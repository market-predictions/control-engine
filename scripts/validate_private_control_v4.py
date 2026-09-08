from __future__ import annotations

"""Trusted read-only validation of current private Control V4 authority.

The private candidate is data only. This script reads exact committed Git objects,
reuses trusted public V4 contracts, and has no network, queue, runtime, merge,
scheduler, provider, or candidate-execution capability.

Current-surface rule: private ``main`` represents current V4 truth only. Frozen
V3.1 rollback material is read from immutable historical commits by the V4
rollback path; it must not survive on current paths as competing authority.
"""

import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping

from control_engine.v4_authority_io import load_v4_authority_from_git
from control_engine.v4_contracts import V4ValidationError
from control_engine.v4_runtime_protocol import CANONICAL_RUNNER_PROMPT_BLOB_SHA

RUNTIME_PATH = "control/CONTROL_RUNTIME_AUTHORITY_V4.json"
INDEX_PATH = "control/SYSTEM_INDEX.md"
RUNNER_CONFIG_PATH = "control/CONTROL_RUNNER_V4.json"
RUNNER_PROMPT_PATH = "control/CONTROL_RUNNER_V4_PROMPT.md"
MISSION_README_PATH = "control/missions/README.md"
CHANGELOG_PATH = "control/CHANGELOG.md"
COHERENCE_REPAIR_PATH = "control/CONTROL_V4_COHERENCE_REPAIR_2026_09_05.md"
LEGACY_CURRENT_PATHS = {
    "control/CONTROL_AUTONOMY_ARCHITECTURE_V3_1.md",
    "control/CONTROL_RUNTIME_AUTHORITY_V3_1.json",
    "schemas/mission_contract_v31.schema.json",
    "schemas/repository_authority_v31.schema.json",
}
NORMATIVE_DOCTRINE_PATHS = {
    "control/CONTROL_AUTONOMY_ARCHITECTURE_V4.md",
    "control/CONTROL_V4_REALIZATION_RUNBOOK.md",
    "control/CONTROL_V4_ROADMAP.md",
    "control/CONTROL_V4_CONVERGENCE_AND_DEBT_RETIREMENT_PLAN.md",
    "control/CONTROL_V4_SURFACE_INVENTORY.md",
    MISSION_README_PATH,
    CHANGELOG_PATH,
}
HISTORICAL_AUDIT_PATHS = {COHERENCE_REPAIR_PATH}
CURRENT_SURFACE_PATHS = NORMATIVE_DOCTRINE_PATHS | HISTORICAL_AUDIT_PATHS
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
V4_40_FROZEN_AUTHORITY_COMMIT = "3c314362341570349c15de00156dd6f5ab037fbe"
REVIEWED_AUTOMATION_OBJECT_ID = "6a9a7e0b18b08191876c134d83cfbba2"
REVIEWED_RUNNER_PROMPT_BLOB_SHA = CANONICAL_RUNNER_PROMPT_BLOB_SHA
OBSOLETE_RUNNER_PROMPT_BLOB_SHAS = frozenset(
    {
        "4bc8ce5a73e1238427b1ce999be5cd5a6378988c",
        "804c8570141934c5a0b5fa86583c867995ce51f4",
        "fe269bf84744629eca133937854ee284239cbcc9",
        "f9d3b1f1158aa0c84b486120f22b5173417f54e7",
        "0a536651ad3096e2c6de44e6dd25d0cea14ec8e1",
        "f354539a6493bce9269d77fe085300ac4a0c9fa6",
        "74e265ad8d2e84a11e6097feb2e2e27ff5d1b64c",
        "ab005b25b74c3a79ddff2266d90af60e25ddbb77",
        "f984584f7680428db5ecedf414d0bdd518245f1c",
    }
)
REVIEWED_SYSTEM_INDEX_BLOB_SHA = "e8aae3b78782933b51a97f4132580de71893de7f"
STATELESS_TRANSPORT_PROMPT_REQUIRED_MARKERS = (
    "CONTROL_V4_RUNTIME_TICK",
    "CONTROL_V4_RUNTIME_EVENT",
    "market-predictions/control-engine",
    "issue **#106**",
    "MUST NOT depend on direct Scheduled access to private",
    "integration_enabled=false",
    "candidate-less `BUILD` cannot be executed safely from carrier V1 alone; submit `YIELD`",
    "The schedule is a wake-up mechanism, not runtime state.",
    "never reconstruct Control liveness, holder state or recovery state from public comment history",
    "Then create one new unique `run_id` for this invocation in the exact generation-bound format and an empty invocation-local `yielded_task_tokens` set.",
    "Immediately post one fresh initial `CONTROL_V4_RUNTIME_TICK`",
    "Do **not** scan issue #106 history first and do not replay an older TICK or EVENT.",
    "`NO_WORK` or `BUSY` ends this invocation without mutation.",
    "carrier expired-lock recovery are the only cross-invocation holder-recovery mechanism",
    "Do not replay the command and do not derive recovery state from issue history.",
    "The next normal Scheduled invocation starts with a fresh TICK",
)
COMMAND_BINDING_PROMPT_REQUIRED_MARKERS = (
    "runner_command_generation=7c4e91b2d5a83f60",
    "## Pre-acquisition Runner-binding fence",
    "Before creating a `run_id` or posting any acquisition-capable TICK",
    "zero public command writes",
    "6a9a7e0b18b08191876c134d83cfbba2",
    "no second enabled Control V4 Runner object is observed",
    "v4:6a9a7e0b18b08191876c134d83cfbba2:7c4e91b2d5a83f60:<32-lowercase-hex-random>",
    "A stale invocation from an older prompt generation does not satisfy the current generation contract and MUST post no TICK.",
    "requires a new previously unused `runner_command_generation` before adoption.",
    "whose `command_comment_id` equals that exact preserved GitHub command-comment id",
    "no later same-`run_id` Control command",
    "a TICK older than 120 seconds at transition time is rejected before `_tick()` can acquire or mutate private runtime state.",
    "persists no transport cursor or ledger",
)
LIVE_TICK_RESPONSIBILITY_PROMPT_REQUIRED_MARKERS = (
    "### Live-TICK responsibility window",
    "Every acquisition-capable TICK posted by this invocation",
    "do not classify its result as missing, do not end the invocation, and do not abandon responsibility",
    "strictly more than **120 seconds old**",
    "a final exact-command result read performed after that expiry still finds no correlated result",
    "Only case (b) may be treated as a missing TICK result and end the invocation.",
    "Never post a replacement TICK merely because the current one is slow.",
    "persists no timer, cursor, retry record, scheduler state or runtime state",
)
POST_YIELD_CONTINUATION_PROMPT_REQUIRED_MARKERS = (
    "After a correlated `YIELD` or `REVIEW_UNAVAILABLE` result that releases the holder",
    "add that WORK's exact `task_token` to this invocation's `yielded_task_tokens`",
    "continue the same invocation",
    "post one new same-`run_id` acquisition TICK carrying the complete current `yielded_task_tokens` set",
    "This is a new current-state acquisition query, not a replay of an earlier command.",
    "Repeat only after another correlated release/yield",
    "Never carry yielded tokens into another Scheduled invocation.",
    "This bounded yielded-token continuation is what allows candidate-less BUILD, unavailable external review, or another retryable wait to release ownership without starving unrelated eligible work.",
)
TARGET_EFFECT_PROMPT_REQUIRED_MARKERS = (
    "Fresh acquisition of the current holder occurred in this Scheduled invocation under its unique `run_id`",
    "current-holder acquisition TICK",
    "post a **second same-`run_id` TICK**",
    "must be no more than **660 seconds old**",
    "Later revalidation TICKs do not reset or renew this clock.",
    "no more than **15 seconds old**",
    "bounded to **300 seconds or less**",
    "The second same-`run_id` TICK is revalidation only",
)
CANONICAL_EVENT_FAIRNESS_PROMPT_REQUIRED_MARKERS = (
    "### Canonical EVENT wire contract",
    "For every semantic EVENT, copy the correlated trusted `WORK` identity; do not transform it.",
    "`run_id`, `task_token`, `event`, `repository`, `action`",
    "plus `candidate` **iff the correlated WORK contained `candidate`**",
    "copied verbatim from that exact trusted WORK",
    "Never emit public `holder_*` fields.",
    "Never copy `protocol`, `result`, `live_candidate`",
    "Any EVENT that cannot be formed exactly from one correlated trusted WORK fails closed and is not sent.",
    "A prior `REVIEW_UNAVAILABLE`/`INDETERMINATE` external review remains retryable but must not monopolize later selection",
)
OBSOLETE_TRANSPORT_RECOVERY_MARKERS = (
    "read only the bounded issue-#106 history",
    "at least **120 seconds old**",
    "recovery replay",
    "exact same TICK body and same `run_id`",
    "unresolved EVENT",
    "spent for forward scheduling",
    "5400-second unresolved-EVENT retirement clock",
    "earliest TICK for that `run_id` remains the sole initial acquisition TICK",
)
HISTORICAL_COHERENCE_REQUIRED_MARKERS = (
    "status=HISTORICAL_AUDIT_EVIDENCE",
    "documentation_is_current_status_authority=false",
    "runtime_snapshot_semantics=HISTORICAL_OBSERVATION_ONLY",
)


class ValidationError(ValueError):
    pass


class _DuplicateKeyError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError("duplicate JSON object key")
        result[key] = value
    return result


def _strict_json(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKeyError, TypeError, ValueError) as exc:
        raise ValidationError(f"{label} is invalid or ambiguous JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} root must be an object")
    return value


def explicit_bool(value: object) -> bool:
    return isinstance(value, bool)


def require_zero_relay_count(value: Mapping[str, Any]) -> None:
    relay = value.get("principal_manual_relay_count")
    if not isinstance(relay, int) or isinstance(relay, bool) or relay != 0:
        raise ValidationError("principal_manual_relay_count must be exact integer zero")


def require_reviewed_automation_object_id(value: object) -> None:
    if value != REVIEWED_AUTOMATION_OBJECT_ID:
        raise ValidationError("Runner automation object differs from exact reviewed V4-30 object")


def _git(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null", *args],
            cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValidationError("trusted Git read failed") from exc
    return result.stdout


def committed_tree(root: Path) -> dict[str, tuple[str, str, str]]:
    raw = _git(root, "ls-tree", "-rz", "-r", "--full-tree", "HEAD")
    entries: dict[str, tuple[str, str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode_b, type_b, oid_b = metadata.split(b" ", 2)
            path = raw_path.decode("utf-8", "strict")
            entry = (mode_b.decode("ascii"), type_b.decode("ascii"), oid_b.decode("ascii"))
        except Exception as exc:
            raise ValidationError("trusted Git tree contains unsupported record") from exc
        if path in entries:
            raise ValidationError("trusted Git tree contains duplicate path")
        entries[path] = entry
    return entries


def _regular_blob(entries: Mapping[str, tuple[str, str, str]], path: str) -> str:
    entry = entries.get(path)
    if entry is None:
        raise ValidationError(f"required private V4 file missing: {path}")
    mode, obj_type, oid = entry
    if mode != "100644" or obj_type != "blob" or SHA1_RE.fullmatch(oid) is None:
        raise ValidationError(f"private V4 path is not one inert regular Git blob: {path}")
    return oid


def _blob(root: Path, entries: Mapping[str, tuple[str, str, str]], path: str) -> tuple[bytes, str]:
    oid = _regular_blob(entries, path)
    return _git(root, "cat-file", "blob", oid), oid


def _text(root: Path, entries: Mapping[str, tuple[str, str, str]], path: str) -> str:
    raw, _ = _blob(root, entries, path)
    try:
        return raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"{path} is not strict UTF-8") from exc


def validate_changed_surface(candidate_entries, base_entries) -> set[str]:
    changed = {path for path in set(candidate_entries) | set(base_entries) if candidate_entries.get(path) != base_entries.get(path)}

    def allowed(path: str) -> bool:
        if path in {RUNTIME_PATH, INDEX_PATH, RUNNER_CONFIG_PATH, RUNNER_PROMPT_PATH}:
            return True
        if path in LEGACY_CURRENT_PATHS or path in CURRENT_SURFACE_PATHS:
            return True
        if path.startswith("control/missions/") and path.endswith(".mission.json") and "/" not in path[len("control/missions/"):]:
            return True
        if path.startswith("control/repository-authority/") and path.endswith(".json") and "/" not in path[len("control/repository-authority/"):]:
            return True
        return False

    disallowed = sorted(path for path in changed if not allowed(path))
    if disallowed:
        raise ValidationError("private V4 candidate changes non-declarative authority surface")
    return changed


def load_frozen_v4_40_authority(base_root: Path):
    return load_v4_authority_from_git(Path(base_root), commit_sha=V4_40_FROZEN_AUTHORITY_COMMIT)


def validate_current_surface(root: Path, entries) -> None:
    stale = sorted(path for path in LEGACY_CURRENT_PATHS if path in entries)
    if stale:
        raise ValidationError("private main retains competing V3.1 current authority")

    for path in sorted(CURRENT_SURFACE_PATHS):
        _regular_blob(entries, path)

    mission_readme = _text(root, entries, MISSION_README_PATH)
    required = ("Mission Contract Registry — V4", "CONTROL_AUTONOMY_ARCHITECTURE_V4.md", "MISSION_CONTRACT_V4", "review_policy")
    if any(marker not in mission_readme for marker in required):
        raise ValidationError("Mission registry README is not current V4 doctrine")
    for stale_marker in ("Mission Contract Registry — V3.1", "MISSION_CONTRACT_V3_1", "V3.1 FEED"):
        if stale_marker in mission_readme:
            raise ValidationError("Mission registry README retains V3.1 current semantics")

    coherence = _text(root, entries, COHERENCE_REPAIR_PATH)
    if any(marker not in coherence for marker in HISTORICAL_COHERENCE_REQUIRED_MARKERS):
        raise ValidationError(
            "coherence repair record is not explicitly historical audit evidence; current-looking runtime semantics are forbidden"
        )
    for stale_marker in (
        "status=IMPLEMENTATION_CANDIDATE",
        "The current queue remains",
        "Current runtime-carrier invariant",
    ):
        if stale_marker in coherence:
            raise ValidationError("historical coherence record retains current-looking runtime semantics")


def _validate_prompt_trust(prompt_text: str, prompt_oid: str) -> None:
    if prompt_oid in OBSOLETE_RUNNER_PROMPT_BLOB_SHAS:
        raise ValidationError("obsolete Runner prompt is not trusted by the current stateless transport contract")
    if prompt_oid != REVIEWED_RUNNER_PROMPT_BLOB_SHA:
        raise ValidationError("Runner prompt blob differs from exact trusted reviewed V4 prompt contract")
    if any(marker not in prompt_text for marker in STATELESS_TRANSPORT_PROMPT_REQUIRED_MARKERS):
        raise ValidationError("current Runner prompt lacks required state-first transport markers")
    if any(marker not in prompt_text for marker in COMMAND_BINDING_PROMPT_REQUIRED_MARKERS):
        raise ValidationError("current Runner prompt lacks required pre-acquisition command-binding/correlation markers")
    if any(marker not in prompt_text for marker in LIVE_TICK_RESPONSIBILITY_PROMPT_REQUIRED_MARKERS):
        raise ValidationError("current Runner prompt lacks required live-TICK responsibility markers")
    if any(marker not in prompt_text for marker in POST_YIELD_CONTINUATION_PROMPT_REQUIRED_MARKERS):
        raise ValidationError("current Runner prompt lacks required post-yield continuation markers")
    if any(marker not in prompt_text for marker in TARGET_EFFECT_PROMPT_REQUIRED_MARKERS):
        raise ValidationError("current Runner prompt lacks target-effect freshness markers")
    if any(marker not in prompt_text for marker in CANONICAL_EVENT_FAIRNESS_PROMPT_REQUIRED_MARKERS):
        raise ValidationError("current Runner prompt lacks canonical EVENT/fairness markers")
    if any(marker in prompt_text for marker in OBSOLETE_TRANSPORT_RECOVERY_MARKERS):
        raise ValidationError("current Runner prompt retains obsolete public-history recovery semantics")


def validate_runtime_and_runner(root: Path, entries) -> dict[str, Any]:
    runtime_raw, _ = _blob(root, entries, RUNTIME_PATH)
    runtime = _strict_json(runtime_raw, label="CONTROL_RUNTIME_AUTHORITY_V4")
    expected_runtime_keys = {"protocol_id", "control_runtime_enabled", "integration_enabled", "runner_config_path", "runner_config_blob_sha", "principal_manual_relay_count"}
    if set(runtime) != expected_runtime_keys:
        raise ValidationError("CONTROL_RUNTIME_AUTHORITY_V4 key set is not exact")
    if runtime.get("protocol_id") != "CONTROL_RUNTIME_AUTHORITY_V4":
        raise ValidationError("CONTROL_RUNTIME_AUTHORITY_V4 protocol id invalid")
    if not explicit_bool(runtime.get("control_runtime_enabled")) or not explicit_bool(runtime.get("integration_enabled")):
        raise ValidationError("runtime authority switches must be actual JSON booleans")
    if runtime["integration_enabled"] and not runtime["control_runtime_enabled"]:
        raise ValidationError("integration cannot be enabled while Control runtime is disabled")
    require_zero_relay_count(runtime)
    if runtime.get("runner_config_path") != RUNNER_CONFIG_PATH:
        raise ValidationError("runtime authority runner config path is not canonical")

    config_raw, config_oid = _blob(root, entries, RUNNER_CONFIG_PATH)
    if runtime.get("runner_config_blob_sha") != config_oid:
        raise ValidationError("runtime authority does not bind the exact committed Runner config blob")
    config = _strict_json(config_raw, label="CONTROL_RUNNER_V4")
    require_zero_relay_count(config)
    if config.get("protocol_id") != "CONTROL_RUNNER_V4" or config.get("runner_id") != "CONTROL_V4_RUNNER":
        raise ValidationError("Runner config identity invalid")
    if config.get("execution_surface") != "CHATGPT_SCHEDULED" or config.get("prompt_path") != RUNNER_PROMPT_PATH:
        raise ValidationError("Runner execution/prompt identity invalid")

    prompt_text = _text(root, entries, RUNNER_PROMPT_PATH)
    _, prompt_oid = _blob(root, entries, RUNNER_PROMPT_PATH)
    _validate_prompt_trust(prompt_text, prompt_oid)
    if config.get("prompt_blob_sha") != prompt_oid:
        raise ValidationError("Runner config does not bind the exact trusted reviewed prompt blob")
    if "status=CANDIDATE_INERT" in prompt_text or "status=CANDIDATE" in prompt_text:
        raise ValidationError("active Runner prompt retains candidate/inert lifecycle metadata")

    if config.get("schedule") != {"timing_mode": "exact_schedule", "timezone": "Europe/Amsterdam", "rrule": "FREQ=HOURLY;BYMINUTE=30;BYSECOND=0"}:
        raise ValidationError("Runner schedule differs from reviewed V4 binding")
    require_reviewed_automation_object_id(config.get("automation_object_id"))
    if config.get("automation_object_binding_status") != "BOUND":
        raise ValidationError("Runner automation object is not bound")
    if config.get("scheduled_credential_binding_status") != "PLATFORM_MANAGED_NO_STABLE_CREDENTIAL_ID_EXPOSED":
        raise ValidationError("Runner scheduled credential binding status invalid")
    if config.get("effective_capability_binding_status") != "BOUND_TO_EXACT_SCHEDULED_OBJECT_TOOL_SURFACE":
        raise ValidationError("Runner effective capability binding invalid")
    if config.get("scheduled_capability_observation") != {
        "scheduler_automation_admin": "PLATFORM_EXPOSED_ACCEPTED",
        "protection_rules_admin": "UNAVAILABLE_OBSERVED_V4_30",
        "positive_git_cas_proof": "PROVEN_V4_30",
    }:
        raise ValidationError("Runner scheduled capability observation differs from current reviewed V4 binding")
    return runtime


def validate_system_index(raw: bytes, runtime: Mapping[str, Any], *, index_oid: str) -> None:
    del runtime
    if index_oid != REVIEWED_SYSTEM_INDEX_BLOB_SHA:
        raise ValidationError("SYSTEM_INDEX blob differs from exact trusted reviewed V4 live-first contract")
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ValidationError("SYSTEM_INDEX is not strict UTF-8") from exc

    required = {
        "# Control — Canonical System Index V4",
        "architecture=control/CONTROL_AUTONOMY_ARCHITECTURE_V4.md",
        "runtime=control-runtime-state:control/DISPATCH_QUEUE.json",
        "global_safety=control/CONTROL_RUNTIME_AUTHORITY_V4.json",
        "runner_config=control/CONTROL_RUNNER_V4.json",
        "runner_prompt=control/CONTROL_RUNNER_V4_PROMPT.md",
        "fresh live projection",
        "STATUS_OBSERVABILITY_INCOMPLETE",
    }
    if any(marker not in text for marker in required):
        raise ValidationError("SYSTEM_INDEX lacks current V4 live-first authority markers")

    for stale in ("# Control — Canonical System Index V3.1", "Control Autonomy V3.1 supersedes conflicting", "Until cutover, V3.1 above is current truth."):
        if stale in text:
            raise ValidationError("SYSTEM_INDEX retains stale V3.1/current-unadopted routing authority")


def validate_candidate(candidate_root: Path, base_root: Path) -> None:
    candidate_root, base_root = Path(candidate_root), Path(base_root)
    candidate_entries, base_entries = committed_tree(candidate_root), committed_tree(base_root)
    if any(path.startswith(".github/workflows/") for path in candidate_entries):
        raise ValidationError("private main must not contain an executable workflow surface")

    changed = validate_changed_surface(candidate_entries, base_entries)
    if not changed:
        raise ValidationError("private V4 candidate contains no authority change")

    try:
        candidate_bundle = load_v4_authority_from_git(candidate_root)
        load_v4_authority_from_git(base_root)
        frozen_bundle = load_frozen_v4_40_authority(base_root)
    except V4ValidationError as exc:
        raise ValidationError("trusted public V4 authority validation failed") from exc

    if dict(candidate_bundle.mission_blob_shas) != dict(frozen_bundle.mission_blob_shas):
        raise ValidationError("V4-40 adopted Mission blob set drifted during frozen rollback window")
    if dict(candidate_bundle.authority_blob_shas) != dict(frozen_bundle.authority_blob_shas):
        raise ValidationError("V4-40 adopted repository-authority blob set drifted during frozen rollback window")

    validate_current_surface(candidate_root, candidate_entries)
    runtime = validate_runtime_and_runner(candidate_root, candidate_entries)
    index_raw, index_oid = _blob(candidate_root, candidate_entries, INDEX_PATH)
    validate_system_index(index_raw, runtime, index_oid=index_oid)

    print("CONTROL_PRIVATE_V4_VALIDATION=PASS")
    print("CONTROL_PRIVATE_CANDIDATE_EXECUTION=false")
    print("CONTROL_PRIVATE_RUNTIME_MUTATION=false")
    print("CONTROL_PRIVATE_V4_CURRENT_SURFACE_CLEAN=true")
    print("CONTROL_PRIVATE_V4_MISSION_SET_FROZEN=true")
    print("CONTROL_PRIVATE_V4_REPOSITORY_AUTHORITY_SET_FROZEN=true")
    print("CONTROL_PRIVATE_V4_CHANGED_PATHS=" + ",".join(sorted(changed)))


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: validate_private_control_v4.py <private-candidate> <private-base>", file=sys.stderr)
        return 2
    try:
        validate_candidate(Path(argv[1]), Path(argv[2]))
    except ValidationError as exc:
        print(f"CONTROL_PRIVATE_V4_VALIDATION=FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
