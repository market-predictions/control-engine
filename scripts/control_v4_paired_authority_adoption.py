from __future__ import annotations

"""One-time, owner-triggered atomic Memory authority + queue rebind.

Trusted code runs only from control-engine/main after the immutable owner
issue-comment gate. It extends the *existing* private GitHub adoption path,
not the runtime owner-admin task protocol. No target source, reviews, mission,
lease, task history, integration policy, or other repository is changed.
"""

import base64
from copy import deepcopy
import json
import os
import re
from typing import Any, Mapping

from control_engine.v4_authority_io import V4AuthorityBundle, assert_v4_queue_bound_to_authority
from control_engine.v4_contracts import V4ValidationError, validate_queue_v4
from scripts import control_v4_owner_admin as admin


COMMAND = "CONTROL_PRIVATE_V4_ADOPT_PAIR"
CONFIRM = "ADOPT_REVIEWED_PRIVATE_MAIN_AND_RUNTIME"
MEMORY = "market-predictions/memory"
MEMORY_TASK = "MISSION--MEMORY_SECOND_BRAIN--2026-10-20-r1--MEM-R0-RECOVER"
MEMORY_HEAD = "ec6c8fabe2f35927e7f6f3e11e3f496e49e26cf6"
MEMORY_BASE = "c407a9c8dfc5617f1a0adc6997a40ddd602ac011"
MEMORY_PATH = "control/repository-authority/market-predictions__memory.json"
EXPECTED_TASK_COUNT = 22


class PairedAdoptionRejected(RuntimeError):
    pass


def parse_command(body: str) -> tuple[str, str, str]:
    if not isinstance(body, str):
        raise PairedAdoptionRejected("paired adoption command absent")
    parts = body.split()
    if len(parts) != 5 or parts[0] != COMMAND or parts[-1] != CONFIRM:
        raise PairedAdoptionRejected("paired adoption command/confirmation invalid")
    old_main, candidate_main, old_runtime = parts[1:4]
    if any(re.fullmatch(r"[0-9a-f]{40}", x) is None for x in (old_main, candidate_main, old_runtime)):
        raise PairedAdoptionRejected("three exact old/new SHAs required")
    if old_main == candidate_main or old_main == old_runtime or candidate_main == old_runtime:
        raise PairedAdoptionRejected("paired SHA identities are not distinct")
    return old_main, candidate_main, old_runtime


def _authority(bundle: V4AuthorityBundle) -> Mapping[str, Any]:
    matches = [a for a in bundle.authorities if a["repository"].lower() == MEMORY]
    if len(matches) != 1:
        raise PairedAdoptionRejected("Memory authority missing/ambiguous")
    return matches[0]


def _assert_minimal_authority_delta(old: V4AuthorityBundle, new: V4AuthorityBundle) -> tuple[str, str]:
    if dict(old.mission_blob_shas) != dict(new.mission_blob_shas):
        raise PairedAdoptionRejected("Mission authority changed")
    old_shas, new_shas = dict(old.authority_blob_shas), dict(new.authority_blob_shas)
    if set(old_shas) != set(new_shas):
        raise PairedAdoptionRejected("repository authority registry changed")
    changed = [name for name in old_shas if old_shas[name] != new_shas[name]]
    if changed != [MEMORY]:
        raise PairedAdoptionRejected("not exactly one Memory authority blob change")
    original, revised = dict(_authority(old)), dict(_authority(new))
    if original.get("required_check_runs") != [] or revised.get("required_check_runs") != ["validate"]:
        raise PairedAdoptionRejected("change is not the exact empty-to-validate check correction")
    original.pop("required_check_runs")
    revised.pop("required_check_runs")
    if original != revised:
        raise PairedAdoptionRejected("Memory authority changed beyond required check")
    return old_shas[MEMORY], new_shas[MEMORY]



def assert_regular_authority_file(commit_sha: str, expected_blob_sha: str) -> None:
    """Inspect committed Git mode, not just REST contents and changed filenames."""
    commit = admin._private_get(f"repos/{admin.PRIVATE_REPOSITORY}/git/commits/{commit_sha}")
    tree_sha = _sha((commit.get("tree") or {}).get("sha") if isinstance(commit, Mapping) else None)
    tree = admin._private_get(f"repos/{admin.PRIVATE_REPOSITORY}/git/trees/{tree_sha}?recursive=1")
    if not isinstance(tree, Mapping) or tree.get("truncated") is not False:
        raise PairedAdoptionRejected("complete exact authority Git tree unavailable")
    matches = [entry for entry in tree.get("tree", []) if isinstance(entry, Mapping)
               and entry.get("path") == MEMORY_PATH]
    if (len(matches) != 1 or matches[0].get("type") != "blob"
            or matches[0].get("mode") != "100644"
            or matches[0].get("sha") != expected_blob_sha):
        raise PairedAdoptionRejected("Memory authority Git mode/type/blob identity mismatch")

def plan_one_binding(queue: Mapping[str, Any], old: V4AuthorityBundle, new: V4AuthorityBundle) -> dict[str, Any]:
    """Pure plan: existing queue under old authority -> identical queue + one new SHA."""
    validate_queue_v4(queue)
    assert_v4_queue_bound_to_authority(queue, old)
    original_sha, candidate_sha = _assert_minimal_authority_delta(old, new)
    if queue.get("execution_lock") is not None or len(queue["tasks"]) != EXPECTED_TASK_COUNT:
        raise PairedAdoptionRejected("queue lock or task count changed")
    indices = [i for i, t in enumerate(queue["tasks"]) if t.get("task_id") == MEMORY_TASK]
    if len(indices) != 1:
        raise PairedAdoptionRejected("existing Memory task is missing/ambiguous")
    task = queue["tasks"][indices[0]]
    if (task.get("repository") != MEMORY
            or task.get("status") != "ACTIVE"
            or task.get("phase") != "REVIEW"
            or task.get("repository_authority_blob_sha") != original_sha
            or (task.get("candidate") or {}).get("candidate_sha") != MEMORY_HEAD
            or (task.get("candidate") or {}).get("expected_base_sha") != MEMORY_BASE
            or task.get("integration_policy") != "HOLD_AFTER_PASS"
            or (task.get("external_review") or {}).get("status") != "PENDING"):
        raise PairedAdoptionRejected("Memory task is no longer the exact guarded R0 review")
    result = deepcopy(queue)
    result["tasks"][indices[0]]["repository_authority_blob_sha"] = candidate_sha
    validate_queue_v4(result)
    assert_v4_queue_bound_to_authority(result, new)
    comparison = deepcopy(result)
    comparison["tasks"][indices[0]]["repository_authority_blob_sha"] = original_sha
    if comparison != queue:
        raise PairedAdoptionRejected("unexpected queue mutation beyond the one task binding")
    return result


def _sha(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise PairedAdoptionRejected("Git SHA unavailable")
    return value


def _current_ref(branch: str) -> str:
    return admin._branch_head(admin.PRIVATE_REPOSITORY, branch, private=True)


def _commit_runtime(queue: Mapping[str, Any], old_runtime: str, current_queue_blob: str) -> str:
    text = json.dumps(queue, ensure_ascii=False, separators=(",", ":"))
    blob = admin._private_post(
        f"repos/{admin.PRIVATE_REPOSITORY}/git/blobs",
        {"content": base64.b64encode(text.encode("utf-8")).decode("ascii"), "encoding": "base64"},
    )
    new_blob = _sha(blob.get("sha") if isinstance(blob, Mapping) else None)
    if new_blob == current_queue_blob:
        raise PairedAdoptionRejected("queue mutation unexpectedly has no effect")
    commit = admin._private_get(f"repos/{admin.PRIVATE_REPOSITORY}/git/commits/{old_runtime}")
    tree_sha = _sha((commit.get("tree") or {}).get("sha") if isinstance(commit, Mapping) else None)
    tree = admin._private_post(
        f"repos/{admin.PRIVATE_REPOSITORY}/git/trees",
        {"base_tree": tree_sha, "tree": [
            {"path": admin.QUEUE_PATH, "mode": "100644", "type": "blob", "sha": new_blob}
        ]},
    )
    new_tree = _sha(tree.get("sha") if isinstance(tree, Mapping) else None)
    new_commit = admin._private_post(
        f"repos/{admin.PRIVATE_REPOSITORY}/git/commits",
        {"message": "Control: atomic Memory validate authority/queue rebind",
         "tree": new_tree, "parents": [old_runtime]},
    )
    return _sha(new_commit.get("sha") if isinstance(new_commit, Mapping) else None)


def adopt_pair(body: str) -> tuple[str, str]:
    expected_main, candidate_main, expected_runtime = parse_command(body)
    repository = admin._private_get(f"repos/{admin.PRIVATE_REPOSITORY}")
    node_id = repository.get("node_id") if isinstance(repository, Mapping) else None
    if (not isinstance(repository, Mapping)
            or repository.get("full_name") != admin.PRIVATE_REPOSITORY
            or repository.get("private") is not True
            or not isinstance(node_id, str) or not node_id):
        raise PairedAdoptionRejected("private repository identity invalid")
    if _current_ref("main") != expected_main or _current_ref(admin.RUNTIME_BRANCH) != expected_runtime:
        raise PairedAdoptionRejected("old main/runtime SHA mismatch")

    comparison = admin._private_get(
        f"repos/{admin.PRIVATE_REPOSITORY}/compare/{expected_main}...{candidate_main}"
    )
    if (not isinstance(comparison, Mapping)
            or comparison.get("status") != "ahead"
            or comparison.get("behind_by") != 0
            or (comparison.get("merge_base_commit") or {}).get("sha") != expected_main
            or not isinstance(comparison.get("ahead_by"), int)
            or comparison["ahead_by"] < 1
            or [x.get("filename") for x in comparison.get("files", [])] != [MEMORY_PATH]):
        raise PairedAdoptionRejected("candidate not an exact one-file descendant")

    old_bundle = admin._load_bundle(expected_main)
    new_bundle = admin._load_bundle(candidate_main)
    old_authority_blob, new_authority_blob = _assert_minimal_authority_delta(old_bundle, new_bundle)
    assert_regular_authority_file(expected_main, old_authority_blob)
    assert_regular_authority_file(candidate_main, new_authority_blob)
    queue, original_blob = admin._private_json(admin.QUEUE_PATH, expected_runtime)
    planned = plan_one_binding(queue, old_bundle, new_bundle)
    new_runtime = _commit_runtime(planned, expected_runtime, original_blob)

    # Final two-reference old-SHA check. Inert Git objects above have no runtime effect.
    if _current_ref("main") != expected_main or _current_ref(admin.RUNTIME_BRANCH) != expected_runtime:
        raise PairedAdoptionRejected("private refs moved before atomic mutation")
    queue_again, blob_again = admin._private_json(admin.QUEUE_PATH, expected_runtime)
    if blob_again != original_blob or queue_again != queue:
        raise PairedAdoptionRejected("canonical queue changed before atomic mutation")

    mutation = """mutation UpdateRefs($input: UpdateRefsInput!) {
      updateRefs(input: $input) { clientMutationId }
    }"""
    payload = {
        "query": mutation,
        "variables": {"input": {
            "repositoryId": node_id,
            "clientMutationId": f"control-v4-memory-paired-{os.environ.get('GITHUB_RUN_ID', 'unknown')}",
            "refUpdates": [
                {"name": "refs/heads/main", "beforeOid": expected_main,
                 "afterOid": candidate_main, "force": False},
                {"name": f"refs/heads/{admin.RUNTIME_BRANCH}", "beforeOid": expected_runtime,
                 "afterOid": new_runtime, "force": False},
            ],
        }},
    }
    response = admin._request_json(
        admin.GRAPHQL, headers={**admin._private_headers(), "Content-Type": "application/json"},
        method="POST", payload=payload,
    )
    if (not isinstance(response, Mapping)
            or response.get("errors")
            or not isinstance((response.get("data") or {}).get("updateRefs"), Mapping)):
        raise PairedAdoptionRejected("atomic GraphQL updateRefs rejected")

    # Do not report PASS if either ref or the new canonical queue fails readback.
    if _current_ref("main") != candidate_main or _current_ref(admin.RUNTIME_BRANCH) != new_runtime:
        raise PairedAdoptionRejected("mandatory paired ref readback failed")
    actual_queue, actual_blob = admin._private_json(admin.QUEUE_PATH, new_runtime)
    if actual_queue != planned:
        raise PairedAdoptionRejected("mandatory canonical queue readback failed")
    assert_v4_queue_bound_to_authority(actual_queue, new_bundle)
    return candidate_main, new_runtime


def main() -> int:
    try:
        adopted_main, adopted_runtime = adopt_pair(os.environ.get("CONTROL_V4_PAIRED_ADOPT_COMMAND", ""))
        print("CONTROL_V4_MEMORY_PAIRED_ADOPTION=PASS")
        print(f"ADOPTED_MAIN={adopted_main}")
        print(f"ADOPTED_RUNTIME={adopted_runtime}")
        return 0
    except (PairedAdoptionRejected, admin.OwnerAdminError, V4ValidationError) as exc:
        print(f"CONTROL_V4_MEMORY_PAIRED_ADOPTION=REJECTED:{type(exc).__name__}:{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
