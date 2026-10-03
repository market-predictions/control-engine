from __future__ import annotations

"""Bounded exact-candidate materialization behind an admitted TICK.

This is not a planner. It may materialize at most one current Mission OPEN gap
per admitted TICK, and only when private main explicitly carries the reviewed
auto-materialization policy and the gap already has exactly one public, open,
mergeable same-repository owner-authored PR bound to the exact current Mission
revision + gap.

A published terminal NO_WORK remains mutation-free. If an exact candidate is
materialized, materialization and acquisition land in one existing private CAS
and the same admitted TICK publishes WORK instead of NO_WORK.
"""

from datetime import datetime, timezone
import os
from typing import Any, Mapping

from control_engine.v4_contracts import V4ValidationError
from control_engine.v4_runtime_protocol import (
    RESULT_PROTOCOL_ID,
    RuntimeProtocolError,
    assert_public_safe,
    parse_public_command,
    strict_json_object,
)
from scripts import control_v4_owner_admin as owner_admin
from scripts import control_v4_replenishment_snapshot as snapshot
from scripts import control_v4_runtime_carrier as runtime_carrier


POLICY_PATH = "control/CONTROL_V4_REPLENISHMENT_DISCOVERY.md"
AUTO_MATERIALIZATION_POLICY = "auto_materialization_policy=MISSION_OPEN_EXACT_CANDIDATE_V1"
PRINCIPAL_LOGIN = "market-predictions"


class AutoReplenishError(RuntimeError):
    pass


def _auto_materialization_policy_enabled(state: Mapping[str, Any]) -> bool:
    text, _blob_sha = runtime_carrier._text_file(POLICY_PATH, state["main_sha"])
    return AUTO_MATERIALIZATION_POLICY in text.splitlines()


def _exact_public_repository(repository: str) -> None:
    value = owner_admin._public_get(f"repos/{repository}")
    if not isinstance(value, Mapping) or value.get("full_name") != repository or value.get("private") is not False:
        raise AutoReplenishError("replenishment target repository is not exact public repository")


def _candidate_is_trusted_source(item: Mapping[str, Any], repository: str) -> bool:
    head = item.get("head") or {}
    head_repo = head.get("repo") or {}
    user = item.get("user") or {}
    return (
        isinstance(head, Mapping)
        and isinstance(head_repo, Mapping)
        and isinstance(user, Mapping)
        and head_repo.get("full_name") == repository
        and head_repo.get("private") is False
        and user.get("login") == PRINCIPAL_LOGIN
    )


def _candidate_command(
    mission: Mapping[str, Any],
    gap: Mapping[str, Any],
    bundle: Any,
) -> dict[str, Any] | None:
    repository = gap["repository"]
    _exact_public_repository(repository)
    pulls = owner_admin._public_get(
        f"repos/{repository}/pulls?state=open&base=main&per_page=100&sort=updated&direction=desc"
    )
    if not isinstance(pulls, list):
        raise AutoReplenishError("replenishment candidate listing invalid")
    if len(pulls) >= 100:
        raise AutoReplenishError("replenishment candidate listing exceeds bounded read")

    mission_marker = f"Mission: `{mission['mission_id']}` revision `{mission['mission_revision']}`"
    gap_marker = f"Gap: `{gap['gap_id']}`"
    exact_claims = []
    trusted_matches = []
    for item in pulls:
        if not isinstance(item, Mapping):
            continue
        body = item.get("body")
        if isinstance(body, str) and mission_marker in body and gap_marker in body:
            exact_claims.append(item)
            if _candidate_is_trusted_source(item, repository):
                trusted_matches.append(item)
    if len(exact_claims) > 1:
        raise AutoReplenishError("multiple exact replenishment candidates claim the same governed gap")
    if exact_claims and not trusted_matches:
        raise AutoReplenishError("exact replenishment candidate is not same-repository owner-authored")
    if not trusted_matches:
        return None

    pr_number = trusted_matches[0].get("number")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number < 1:
        raise AutoReplenishError("replenishment candidate PR identity invalid")
    pr = owner_admin._public_get(f"repos/{repository}/pulls/{pr_number}")
    if not isinstance(pr, Mapping) or not _candidate_is_trusted_source(pr, repository):
        raise AutoReplenishError("replenishment candidate source identity drifted")
    head = pr.get("head") or {}
    base = pr.get("base") or {}
    if base.get("ref") != "main":
        raise AutoReplenishError("replenishment candidate must target main")
    command = {
        "operation": "ACTIVATE_ROOT_CANDIDATE",
        "activation_key": owner_admin.activation_key_v4(mission, gap, bundle),
        "repository": repository,
        "candidate_pr_number": pr_number,
        "candidate_sha": head.get("sha"),
        "candidate_head_branch": head.get("ref"),
        "expected_base_branch": base.get("ref"),
        "expected_base_sha": base.get("sha"),
    }
    owner_admin.validate_public_target(command, owner_admin._public_target(command))
    return command


def _plan_materialize_and_acquire_one(
    state: Mapping[str, Any],
    bundle: Any,
    tick_command: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    if state.get("runtime_enabled") is not True:
        return None
    if state.get("integration_enabled") is True:
        raise AutoReplenishError("auto replenishment requires integration disabled")
    if tick_command.get("kind") != "TICK" or not isinstance(tick_command.get("run_id"), str):
        raise AutoReplenishError("auto replenishment requires exact admitted TICK")

    queue = state["queue"]
    repositories = sorted(
        {
            mission.get("repository")
            for mission in bundle.missions
            if isinstance(mission, Mapping) and isinstance(mission.get("repository"), str)
        }
    )
    for repository in repositories:
        eligible = owner_admin.eligible_unmaterialized_gaps_v4(queue, bundle, repository)
        for mission, gap in eligible:
            command = _candidate_command(mission, gap, bundle)
            if command is None:
                continue

            approval = owner_admin.replenishment_approval_payload_v4(queue, bundle, repository)
            now = datetime.now(timezone.utc)
            materialized = owner_admin.activate_root_candidate_v4(
                queue,
                bundle,
                command,
                approval,
                now=now,
            )
            before_ids = {task["task_id"] for task in queue["tasks"]}
            new_ids = [task["task_id"] for task in materialized["tasks"] if task["task_id"] not in before_ids]
            if len(new_ids) != 1:
                raise AutoReplenishError("auto replenishment did not create exactly one root task")
            task_id = new_ids[0]

            acquired = runtime_carrier.acquire_task_v4(
                materialized,
                task_id=task_id,
                run_id=tick_command["run_id"],
                now=now,
                control_runtime_enabled=True,
                integration_enabled=False,
            )
            work_result = runtime_carrier.safe_work_capsule(
                acquired,
                task_id=task_id,
                run_id=tick_command["run_id"],
            )
            if work_result.get("result") != "WORK":
                raise AutoReplenishError("auto replenishment acquisition did not produce WORK")
            return acquired, command, work_result
    return None


def _revalidate_candidate_command(
    state: Mapping[str, Any],
    bundle: Any,
    command: Mapping[str, Any],
) -> None:
    repository = command.get("repository")
    activation_key = command.get("activation_key")
    if not isinstance(repository, str) or not repository or not isinstance(activation_key, str) or not activation_key:
        raise AutoReplenishError("replenishment candidate binding invalid before runtime write")

    eligible = owner_admin.eligible_unmaterialized_gaps_v4(state["queue"], bundle, repository)
    matches = [
        (mission, gap)
        for mission, gap in eligible
        if owner_admin.activation_key_v4(mission, gap, bundle) == activation_key
    ]
    if len(matches) != 1:
        raise AutoReplenishError("replenishment authority eligibility changed before runtime write")

    mission, gap = matches[0]
    fresh_command = _candidate_command(mission, gap, bundle)
    if fresh_command is None or fresh_command != dict(command):
        raise AutoReplenishError("replenishment candidate binding changed before runtime write")


def _assert_proposal_targets_public(result: Mapping[str, Any]) -> None:
    proposals = result.get("replenishment_proposals", [])
    if not isinstance(proposals, list):
        raise AutoReplenishError("replenishment proposal envelope invalid")
    for proposal in proposals:
        if not isinstance(proposal, Mapping):
            raise AutoReplenishError("replenishment proposal invalid")
        repository = proposal.get("repository")
        if not isinstance(repository, str) or not repository:
            raise AutoReplenishError("replenishment repository identity invalid")
        _exact_public_repository(repository)


def _set_output(result: Mapping[str, Any]) -> None:
    snapshot._set_output(result)


def _proposal_fallback(result: Mapping[str, Any], state: Mapping[str, Any], bundle: Any) -> dict[str, Any]:
    enriched = snapshot.enrich_no_work_result_v4(result, state["queue"], bundle)
    _assert_proposal_targets_public(enriched)
    return enriched


def _mutation_path_error(run_id: object) -> dict[str, Any]:
    value = run_id if isinstance(run_id, str) else "unknown"
    return {
        "protocol": RESULT_PROTOCOL_ID,
        "result": "ERROR",
        "code": "AUTO_REPLENISH_FAIL_CLOSED",
        "run_id": value,
    }


def main() -> int:
    try:
        result = strict_json_object(os.environ.get("CONTROL_V4_CARRIER_RESULT", ""))
        assert_public_safe(result)
        if result.get("protocol") != RESULT_PROTOCOL_ID:
            raise RuntimeProtocolError("carrier result protocol invalid")
        if result.get("result") != "NO_WORK":
            _set_output(result)
            return 0

        state = runtime_carrier._load_current()
        bundle = runtime_carrier._load_authority_bundle(state["main_sha"])
        if not _auto_materialization_policy_enabled(state):
            _set_output(_proposal_fallback(result, state, bundle))
            return 0

        public_command = parse_public_command(os.environ.get("CONTROL_V4_PUBLIC_COMMAND", ""))
        if public_command.get("kind") != "TICK" or public_command.get("run_id") != result.get("run_id"):
            raise AutoReplenishError("carrier NO_WORK does not bind exact admitted TICK")

        planned = _plan_materialize_and_acquire_one(state, bundle, public_command)
        if planned is None:
            _set_output(_proposal_fallback(result, state, bundle))
            return 0

        acquired_queue, command, work_result = planned

        # From here a durable write is possible. Pre-seed a public-safe error so
        # an ambiguous transport failure can never make publication fall back to
        # the carrier's original terminal NO_WORK.
        _set_output(_mutation_path_error(result.get("run_id")))

        runtime_carrier._assert_tick_not_superseded(public_command)
        runtime_carrier._assert_tick_fresh(now=datetime.now(timezone.utc))
        _revalidate_candidate_command(state, bundle, command)
        runtime_carrier._write_queue_exact(
            state,
            acquired_queue,
            reason="auto-replenish-acquire",
        )
        print(
            "CONTROL_V4_AUTO_REPLENISH=ACQUIRED "
            f"{command['repository']}#{command['candidate_pr_number']}@{command['candidate_sha']}"
        )
        _set_output(work_result)
        return 0
    except (
        AutoReplenishError,
        RuntimeProtocolError,
        V4ValidationError,
        owner_admin.OwnerAdminError,
        runtime_carrier.CarrierError,
    ):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
