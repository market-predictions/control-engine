from __future__ import annotations

"""Owner-approved recovery/preparation for one direct V4 Mission supersession.

This adapter deliberately reuses the existing owner-admin GitHub capability and
I/O helpers. It does not create a second runtime authority or generic queue edit
surface. The public command carries only exact private commit SHAs and an opaque
authority key; Mission/gap identities are resolved inside the trusted carrier.
"""

import base64
import json
import os
from typing import Any, Mapping

from control_engine.v4_authority_io import assert_v4_queue_bound_to_authority
from control_engine.v4_contracts import V4ValidationError, validate_queue_v4
from control_engine.v4_mission_convergence import MissionConvergenceError, converge_direct_supersession_v4
from control_engine.v4_runtime_protocol import strict_json_object
from scripts import control_v4_owner_admin as owner_admin


OPERATION = "CONVERGE_MISSION_REVISION"
MODES = {"PREPARE_ADOPTION", "RECOVER_CURRENT"}
COMMAND_KEYS = {
    "operation",
    "mode",
    "previous_authority_sha",
    "next_authority_sha",
    "authority_key",
}


class MissionConvergenceCarrierError(owner_admin.OwnerAdminError):
    pass


def parse_command(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.startswith(owner_admin.PREFIX):
        raise MissionConvergenceCarrierError("owner-admin command prefix invalid")
    try:
        payload = strict_json_object(raw[len(owner_admin.PREFIX):])
    except Exception as exc:
        raise MissionConvergenceCarrierError("mission-convergence JSON invalid") from exc
    if set(payload) != COMMAND_KEYS or payload.get("operation") != OPERATION:
        raise MissionConvergenceCarrierError("mission-convergence command fields invalid")
    if payload.get("mode") not in MODES:
        raise MissionConvergenceCarrierError("mission-convergence mode invalid")
    payload["previous_authority_sha"] = owner_admin._sha(payload["previous_authority_sha"])
    payload["next_authority_sha"] = owner_admin._sha(payload["next_authority_sha"])
    if payload["previous_authority_sha"] == payload["next_authority_sha"]:
        raise MissionConvergenceCarrierError("authority revision did not advance")
    payload["authority_key"] = owner_admin._opaque_key(payload["authority_key"], label="authority key")
    return payload


def _strict_descendant(previous_sha: str, next_sha: str) -> None:
    comparison = owner_admin._private_get(
        f"repos/{owner_admin.PRIVATE_REPOSITORY}/compare/{previous_sha}...{next_sha}"
    )
    merge_base = ((comparison.get("merge_base_commit") or {}).get("sha")) if isinstance(comparison, Mapping) else None
    if (
        not isinstance(comparison, Mapping)
        or comparison.get("status") != "ahead"
        or comparison.get("behind_by") != 0
        or not isinstance(comparison.get("ahead_by"), int)
        or comparison.get("ahead_by") < 1
        or merge_base != previous_sha
    ):
        raise MissionConvergenceCarrierError("next authority is not a strict descendant of previous authority")


def _mission_id_for_authority_key(bundle, authority_key: str) -> str:
    matches = [
        mission
        for mission in bundle.missions
        if owner_admin.authority_key_v4(mission, bundle) == authority_key
    ]
    if len(matches) != 1:
        raise MissionConvergenceCarrierError("opaque authority key does not resolve exactly")
    mission_id = matches[0].get("mission_id")
    if not isinstance(mission_id, str) or not mission_id:
        raise MissionConvergenceCarrierError("resolved Mission identity invalid")
    return mission_id


def _load_state(command: Mapping[str, Any]) -> dict[str, Any]:
    repository = owner_admin._private_get(f"repos/{owner_admin.PRIVATE_REPOSITORY}")
    node_id = repository.get("node_id") if isinstance(repository, Mapping) else None
    if (
        not isinstance(repository, Mapping)
        or repository.get("full_name") != owner_admin.PRIVATE_REPOSITORY
        or repository.get("private") is not True
        or not isinstance(node_id, str)
        or not node_id
    ):
        raise MissionConvergenceCarrierError("private repository identity invalid")

    previous_sha = command["previous_authority_sha"]
    next_sha = command["next_authority_sha"]
    _strict_descendant(previous_sha, next_sha)

    live_main = owner_admin._branch_head(owner_admin.PRIVATE_REPOSITORY, "main", private=True)
    expected_live_main = previous_sha if command["mode"] == "PREPARE_ADOPTION" else next_sha
    if live_main != expected_live_main:
        raise MissionConvergenceCarrierError("private main does not match mission-convergence mode")

    runtime_sha = owner_admin._branch_head(
        owner_admin.PRIVATE_REPOSITORY, owner_admin.RUNTIME_BRANCH, private=True
    )
    queue, queue_blob = owner_admin._private_json(owner_admin.QUEUE_PATH, runtime_sha)
    validate_queue_v4(queue)
    previous_bundle = owner_admin._load_bundle(previous_sha)
    next_bundle = owner_admin._load_bundle(next_sha)
    mission_id = _mission_id_for_authority_key(next_bundle, command["authority_key"])

    # The incident/preparation source must still be coherent with the immediately
    # previous trusted authority. This prevents the recovery tool from becoming a
    # generic stale-queue cleaner.
    assert_v4_queue_bound_to_authority(queue, previous_bundle)

    return {
        "repository_node_id": node_id,
        "live_main": live_main,
        "runtime_sha": runtime_sha,
        "queue_blob": queue_blob,
        "queue": queue,
        "previous_bundle": previous_bundle,
        "next_bundle": next_bundle,
        "mission_id": mission_id,
    }


def _write_queue_exact(state: Mapping[str, Any], queue: Mapping[str, Any], command: Mapping[str, Any]) -> str:
    validate_queue_v4(queue)
    assert_v4_queue_bound_to_authority(queue, state["previous_bundle"])
    assert_v4_queue_bound_to_authority(queue, state["next_bundle"])

    live_main = state["live_main"]
    runtime_sha = state["runtime_sha"]
    if owner_admin._branch_head(owner_admin.PRIVATE_REPOSITORY, "main", private=True) != live_main:
        raise owner_admin.StaleWriteError("private main moved before mission-convergence write")
    if (
        owner_admin._branch_head(owner_admin.PRIVATE_REPOSITORY, owner_admin.RUNTIME_BRANCH, private=True)
        != runtime_sha
    ):
        raise owner_admin.StaleWriteError("private runtime ref moved before mission-convergence write")

    text = json.dumps(queue, separators=(",", ":"), ensure_ascii=False)
    blob = owner_admin._private_post(
        f"repos/{owner_admin.PRIVATE_REPOSITORY}/git/blobs",
        {"content": base64.b64encode(text.encode("utf-8")).decode("ascii"), "encoding": "base64"},
    )
    new_blob = owner_admin._sha(blob.get("sha") if isinstance(blob, Mapping) else None)
    parent = owner_admin._private_get(
        f"repos/{owner_admin.PRIVATE_REPOSITORY}/git/commits/{runtime_sha}"
    )
    parent_tree = owner_admin._sha(
        ((parent.get("tree") or {}).get("sha")) if isinstance(parent, Mapping) else None
    )
    tree = owner_admin._private_post(
        f"repos/{owner_admin.PRIVATE_REPOSITORY}/git/trees",
        {
            "base_tree": parent_tree,
            "tree": [
                {
                    "path": owner_admin.QUEUE_PATH,
                    "mode": "100644",
                    "type": "blob",
                    "sha": new_blob,
                }
            ],
        },
    )
    new_tree = owner_admin._sha(tree.get("sha") if isinstance(tree, Mapping) else None)
    commit = owner_admin._private_post(
        f"repos/{owner_admin.PRIVATE_REPOSITORY}/git/commits",
        {
            "message": f"Control V4 mission revision convergence: {command['mode']}",
            "tree": new_tree,
            "parents": [runtime_sha],
        },
    )
    new_commit = owner_admin._sha(commit.get("sha") if isinstance(commit, Mapping) else None)

    # Revalidate both immutable refs immediately before the one atomic ref CAS.
    if owner_admin._branch_head(owner_admin.PRIVATE_REPOSITORY, "main", private=True) != live_main:
        raise owner_admin.StaleWriteError("private main moved before mission-convergence CAS")
    if (
        owner_admin._branch_head(owner_admin.PRIVATE_REPOSITORY, owner_admin.RUNTIME_BRANCH, private=True)
        != runtime_sha
    ):
        raise owner_admin.StaleWriteError("private runtime ref moved before mission-convergence CAS")

    mutation = """
    mutation UpdateRefs($input: UpdateRefsInput!) {
      updateRefs(input: $input) { clientMutationId }
    }
    """
    payload = {
        "query": mutation,
        "variables": {
            "input": {
                "repositoryId": state["repository_node_id"],
                "clientMutationId": (
                    f"control-v4-mission-convergence-{os.environ.get('GITHUB_RUN_ID', 'unknown')}-"
                    f"{command['mode'].lower()}"
                ),
                "refUpdates": [
                    {
                        "name": "refs/heads/main",
                        "beforeOid": live_main,
                        "afterOid": live_main,
                        "force": False,
                    },
                    {
                        "name": f"refs/heads/{owner_admin.RUNTIME_BRANCH}",
                        "beforeOid": runtime_sha,
                        "afterOid": new_commit,
                        "force": False,
                    },
                ],
            }
        },
    }
    result = owner_admin._request_json(
        owner_admin.GRAPHQL,
        headers={**owner_admin._private_headers(), "Content-Type": "application/json"},
        method="POST",
        payload=payload,
    )
    if (
        not isinstance(result, Mapping)
        or result.get("errors")
        or not isinstance((result.get("data") or {}).get("updateRefs"), Mapping)
    ):
        raise owner_admin.StaleWriteError("mission-convergence atomic updateRefs rejected")
    return new_commit


def main() -> int:
    try:
        command = parse_command(os.environ.get("CONTROL_V4_OWNER_COMMAND", ""))
        state = _load_state(command)
        next_queue = converge_direct_supersession_v4(
            state["queue"],
            state["previous_bundle"],
            state["next_bundle"],
            state["mission_id"],
        )
        removed_count = len(state["queue"]["tasks"]) - len(next_queue["tasks"])
        runtime_commit = _write_queue_exact(state, next_queue, command)
        print(f"CONTROL_V4_OWNER_ADMIN={OPERATION}:PASS")
        print(f"MODE={command['mode']}")
        print(f"REMOVED_NON_DONE_TASK_COUNT={removed_count}")
        print(f"RUNTIME_COMMIT={runtime_commit}")
        return 0
    except (owner_admin.OwnerAdminError, MissionConvergenceError, V4ValidationError) as exc:
        print(f"CONTROL_V4_OWNER_ADMIN={OPERATION}:REJECTED:{type(exc).__name__}:{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
