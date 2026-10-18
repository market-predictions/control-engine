from __future__ import annotations

"""Deterministically finish one already-requested external review.

Runs only from trusted Engine main. This is not a semantic worker: no claims,
target writes, repair, replenishment, integration, lease renewal or new queue.
The original task must already have an internal PASS and pending review request.
Only its own objectively expired holder may be released in the same READY CAS.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import re
from typing import Any, Mapping

from control_engine.v4_authority_io import assert_v4_queue_bound_to_authority
from control_engine.v4_contracts import validate_queue_v4
from control_engine.v4_runtime_protocol import (
    CORE_EXCLUDED_REPOSITORIES,
    EXTERNAL_REVIEW_BOT_LOGIN,
    EXTERNAL_REVIEW_BOT_USER_ID,
    recover_expired_lock_v4,
    validate_runtime_binding,
)
from scripts import control_v4_owner_admin as admin


class ReviewPending(admin.OwnerAdminError):
    """Evidence is unavailable, unsafe, incomplete, or needs an engineer."""


def _bot(item: Mapping[str, Any]) -> bool:
    user = item.get("user") or {}
    return isinstance(user, Mapping) and (
        user.get("login") == EXTERNAL_REVIEW_BOT_LOGIN
        and user.get("id") == EXTERNAL_REVIEW_BOT_USER_ID
    )


def _bounded_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) >= 100 or any(not isinstance(v, dict) for v in value):
        raise ReviewPending("review evidence is unavailable or exceeds bounded read")
    return value


def eligible(task: Mapping[str, Any]) -> bool:
    external = task.get("external_review")
    return (
        task.get("repository", "").lower() not in CORE_EXCLUDED_REPOSITORIES
        and task.get("status") == "ACTIVE" and task.get("phase") == "REVIEW"
        and task.get("review_policy") == "EXTERNAL"
        and task.get("integration_policy") == "HOLD_AFTER_PASS"
        and task.get("blocker") is None
        and isinstance(task.get("candidate"), Mapping)
        and isinstance(external, Mapping) and external.get("status") == "PENDING"
        and isinstance(external.get("request_ref"), str)
    )


def completion_evidence(state: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    candidate = task["candidate"]
    repository = task["repository"]
    command = {"operation": "RECONCILE_EXTERNAL_REVIEW", "repository": repository, **candidate}
    authority = next(a for a in state["bundle"].authorities if a["repository"].lower() == repository.lower())
    names = authority["required_check_runs"]
    if not names:
        raise ReviewPending("required CI checks are not configured")

    review = task.get("last_review") or {}
    exact_review = {k: candidate[k] for k in ("candidate_sha", "expected_base_branch", "expected_base_sha")}
    if any(review.get(k) != v for k, v in exact_review.items()) or review.get("verdict") != "PASS":
        raise ReviewPending("exact internal PASS is missing")
    external = task["external_review"]
    if any(external.get(k) != v for k, v in exact_review.items()):
        raise ReviewPending("pending review candidate drifted")
    expected_key = f"{task['gap_id']}--{candidate['candidate_sha']}--{candidate['expected_base_branch']}--{candidate['expected_base_sha']}"
    if external.get("request_key") != expected_key:
        raise ReviewPending("pending review request identity drifted")

    repo = admin._public_get(f"repos/{repository}")
    if not isinstance(repo, Mapping) or repo.get("full_name") != repository or repo.get("private") is not False:
        raise ReviewPending("review target must be the exact public repository")
    pr_number = candidate["candidate_pr_number"]
    pr = admin._public_get(f"repos/{repository}/pulls/{pr_number}")
    if not isinstance(pr, Mapping) or pr.get("draft") is not False:
        raise ReviewPending("review target is draft or unavailable")

    request_match = re.fullmatch(
        re.escape(f"https://github.com/{repository}/pull/{pr_number}#issuecomment-") + r"([1-9][0-9]*)",
        external["request_ref"],
    )
    if request_match is None:
        raise ReviewPending("review request is not bound to the exact PR")
    request_id = int(request_match[1])
    request = admin._public_get(f"repos/{repository}/issues/comments/{request_id}")
    requested_at = request.get("created_at") if isinstance(request, Mapping) else None
    if not isinstance(requested_at, str):
        raise ReviewPending("review request timestamp missing")
    try:
        requested_time = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
        internal_time = datetime.fromisoformat(str(review.get("reviewed_at")).replace("Z", "+00:00"))
        if requested_time.tzinfo is None or internal_time.tzinfo is None or requested_time < internal_time:
            raise ValueError("request predates internal review")
    except (ValueError, TypeError) as exc:
        raise ReviewPending("review request does not follow internal PASS") from exc

    comments = _bounded_list(admin._public_get(f"repos/{repository}/issues/{pr_number}/comments?per_page=100"))
    passes = []
    for item in comments:
        if not _bot(item) or not isinstance(item.get("created_at"), str) or item["created_at"] < requested_at:
            continue
        match = re.search(r"(?:\*\*)?Reviewed commit:(?:\*\*)?\s*`([0-9a-f]{10,40})`", str(item.get("body") or ""))
        if match is None or not candidate["candidate_sha"].startswith(match[1]):
            continue
        if "Codex Review: Didn't find any major issues." not in str(item.get("body") or ""):
            raise ReviewPending("review findings need an engineer")
        passes.append(item)
    if len(passes) != 1:
        raise ReviewPending("one unambiguous exact-candidate Codex PASS is required")
    evidence = passes[0]
    command.update(external_review_request_comment_id=request_id, external_review_comment_id=evidence["id"])
    # Existing immutable principal/request and trusted-bot PASS validation.
    external_pass = admin._public_external_review(command, state["queue"])
    for endpoint in (f"pulls/{pr_number}/reviews", f"pulls/{pr_number}/comments"):
        for item in _bounded_list(admin._public_get(f"repos/{repository}/{endpoint}?per_page=100")):
            # GitHub can remap an old inline finding's commit_id after a repair.
            # original_commit_id identifies the candidate that actually had it.
            reviewed_commit = item.get("commit_id")
            if endpoint.endswith("/comments"):
                reviewed_commit = item.get("original_commit_id") or reviewed_commit
            if not _bot(item) or reviewed_commit != candidate["candidate_sha"]:
                continue
            if endpoint.endswith("/comments") or item.get("state") == "CHANGES_REQUESTED":
                raise ReviewPending("current-candidate review findings need an engineer")
            if item.get("body") and "Didn't find any major issues." not in item["body"]:
                raise ReviewPending("ambiguous current-candidate review needs an engineer")

    checks = admin._public_get(f"repos/{repository}/commits/{candidate['candidate_sha']}/check-runs?filter=latest&per_page=100")
    runs = checks.get("check_runs") if isinstance(checks, Mapping) else None
    if not isinstance(runs, list) or checks.get("total_count") != len(runs) or len(runs) >= 100:
        raise ReviewPending("CI evidence is unavailable or truncated")
    checked = []
    for name in names:
        matches = [c for c in runs if isinstance(c, Mapping) and c.get("name") == name]
        if len(matches) != 1:
            raise ReviewPending(f"required CI check missing or ambiguous: {name}")
        check = matches[0]
        app = check.get("app") or {}
        if (check.get("head_sha") != candidate["candidate_sha"]
                or not isinstance(app, Mapping) or app.get("id") != 15368 or app.get("slug") != "github-actions"
                or check.get("status") != "completed" or check.get("conclusion") != "success"):
            raise ReviewPending(f"required exact-candidate CI is not successful: {name}")
        checked.append({k: check.get(k) for k in ("id", "name", "head_sha", "status", "conclusion", "completed_at")})
    # Read current head/base last, including on the final pre-CAS recheck.
    admin.validate_public_target(command, admin._public_target(command))
    return {"command": command, "external_review": external_pass, "checks": checked}


def _unheld_queue(queue: Mapping[str, Any], task: Mapping[str, Any], *, now: datetime) -> Mapping[str, Any]:
    lock = queue.get("execution_lock")
    if lock is None:
        return queue
    if lock.get("task_id") != task["task_id"]:
        raise ReviewPending("another task is held")
    recovered, changed = recover_expired_lock_v4(queue, now=now)
    if not changed:
        raise ReviewPending("task still has a live holder")
    return recovered


def finish_review(state: Mapping[str, Any], task: Mapping[str, Any], evidence: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    queue = state["queue"]
    assert_v4_queue_bound_to_authority(queue, state["bundle"])
    if not eligible(task):
        raise ReviewPending("task is no longer waiting for external review")
    if not any(t == task for t in queue["tasks"]):
        raise ReviewPending("task does not belong to the current queue")
    result = deepcopy(_unheld_queue(queue, task, now=now))
    updated = next(t for t in result["tasks"] if t["task_id"] == task["task_id"])
    updated.update(status="READY", phase=None, external_review=dict(evidence["external_review"]),
                   updated_at=now.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
    validate_queue_v4(result)
    assert_v4_queue_bound_to_authority(result, state["bundle"])
    return result


def _load_state() -> dict[str, Any]:
    state = admin._load_private_state()
    root = "control/"
    authority, _ = admin._private_json(root + "CONTROL_RUNTIME_AUTHORITY_V4.json", state["main_sha"])
    runner, runner_blob = admin._private_json(root + "CONTROL_RUNNER_V4.json", state["main_sha"])
    prompt, prompt_blob = admin._private_file(root + "CONTROL_RUNNER_V4_PROMPT.md", state["main_sha"])
    enabled, integration = validate_runtime_binding(authority, runner, prompt,
        runner_config_blob_sha=runner_blob, prompt_blob_sha=prompt_blob)
    if not enabled or integration:
        raise ReviewPending("runtime disabled or integration hold changed")
    return state


def main() -> int:
    try:
        if (os.environ.get("GITHUB_REPOSITORY") != admin.PUBLIC_REPOSITORY
                or os.environ.get("GITHUB_REF") != "refs/heads/main"
                or os.environ.get("GITHUB_EVENT_NAME") not in {"schedule", "workflow_dispatch"}
                or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"):
            raise admin.OwnerAdminError("review resume requires trusted native Engine main")
        state = _load_state()
        pending = [t for t in state["queue"]["tasks"] if eligible(t)]
        lock = state["queue"].get("execution_lock")
        if lock is not None:
            pending = [t for t in pending if t["task_id"] == lock["task_id"]]
            try:
                if not pending:
                    raise ReviewPending("holder belongs to another scope")
                _unheld_queue(state["queue"], pending[0], now=datetime.now(timezone.utc))
            except ReviewPending:
                print("CONTROL_V4_REVIEW_RESUME=BUSY")
                return 0
        # Rotate bounded reads by the native hourly clock. No persistent cursor;
        # stale early entries cannot indefinitely hide later completed reviews.
        offset = (int(datetime.now(timezone.utc).timestamp()) // 3600 * 8) % len(pending) if pending else 0
        batch = (pending[offset:] + pending[:offset])[:8]
        for task in batch:
            try:
                evidence = completion_evidence(state, task)
                result = finish_review(state, task, evidence, now=datetime.now(timezone.utc))
                def revalidate() -> None:
                    if completion_evidence(state, task) != evidence:
                        raise admin.StaleWriteError("review or CI evidence changed before CAS")
                commit = admin._write_queue_exact(state, result, evidence["command"], pre_ref_cas=revalidate)
            except admin.StaleWriteError:
                raise
            except admin.OwnerAdminError as exc:
                print(f"CONTROL_V4_REVIEW_RESUME=PENDING:{task['repository']}:{exc}")
                continue
            # CAS success is definitive; no fallible post-write readback.
            print("CONTROL_V4_REVIEW_RESUME=READY")
            print("RUNTIME_COMMIT=" + commit)
            print("TARGET=" + json.dumps(evidence["command"], sort_keys=True))
            return 0
        print("CONTROL_V4_REVIEW_RESUME=" + ("PENDING" if pending else "NO_WORK"))
        return 0
    except (admin.OwnerAdminError, ValueError) as exc:
        print(f"CONTROL_V4_REVIEW_RESUME=REJECTED:{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
