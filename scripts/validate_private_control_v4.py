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
from control_engine.v4_contracts import V4ValidationError, revision_strictly_precedes
from control_engine.v4_runtime_protocol import CANONICAL_RUNNER_PROMPT_BLOB_SHA

RUNTIME_PATH = "control/CONTROL_RUNTIME_AUTHORITY_V4.json"
INDEX_PATH = "control/SYSTEM_INDEX.md"
RUNNER_CONFIG_PATH = "control/CONTROL_RUNNER_V4.json"
RUNNER_PROMPT_PATH = "control/CONTROL_RUNNER_V4_PROMPT.md"
MISSION_README_PATH = "control/missions/README.md"
CHANGELOG_PATH = "control/CHANGELOG.md"
COHERENCE_REPAIR_PATH = "control/CONTROL_V4_COHERENCE_REPAIR_2026_09_05.md"
REPLENISHMENT_POLICY_PATH = "control/CONTROL_V4_REPLENISHMENT_DISCOVERY.md"
AUTO_MATERIALIZATION_POLICY = "auto_materialization_policy=MISSION_OPEN_EXACT_CANDIDATE_V1"
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
    REPLENISHMENT_POLICY_PATH,
    MISSION_README_PATH,
    CHANGELOG_PATH,
}
HISTORICAL_AUDIT_PATHS = {COHERENCE_REPAIR_PATH}
CURRENT_SURFACE_PATHS = NORMATIVE_DOCTRINE_PATHS | HISTORICAL_AUDIT_PATHS
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
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
        "04e7dbb577e1dbe630a1422d7b38dff2fd337e3c",
        "e100b7655dd1596f0562820e55a8da2a3358a6a8",
        "2cc54e0fbf21b93609d3c4e093bcdacfb566fcb0",
        "3e577ae37c46d39b07e8b1bb9a19d59d4bddd242",
        "419afc91bc4b1f3fa7f1d624d713077452a3d7ee",
        "2d686b2271a9ff5cde931109d7a8078c8a2154d5",
        "fe3179cb9dd595999c45a0f9233ef5dc397d9fa0",
        "6cd83f6c687ae2b8cf437add85c798bfb95f28f3",
        "6628a9e4c47234bd1e58611225c6fa3f236051f4",
        "2e31c866e7484c5ff6346c50603bb76a2029c331",
        "b3d671767231ec534c6e22eb7a0c6c4c2875605f",
        "05f15520228cc659b6668e4eb39f194047d15900",
    }
)
REVIEWED_SYSTEM_INDEX_BLOB_SHA = "f65c05a566539cbda7d9e75993fce8be7b5842c6"

STATELESS_TRANSPORT_PROMPT_REQUIRED_MARKERS = (
    "execution_surface=GITHUB_ACTIONS_NATIVE",
    "The one canonical Control V4 Runner is the trusted-main GitHub Actions workflow",
    ".github/workflows/control-v4-native-runner.yml",
    "It is not an LLM prompt and grants no authority by itself.",
    "control-runtime-state:control/DISPATCH_QUEUE.json",
    "principal_manual_relay_count=0",
    "integration_enabled=false",
    "No ChatGPT Scheduled Task, Work task, Codex automation, Guardian, second queue,",
)
COMMAND_BINDING_PROMPT_REQUIRED_MARKERS = (
    "runner_command_generation=9c7e1a4b2d6f8053",
    "execution_surface=GITHUB_ACTIONS_NATIVE",
    "checks out exact trusted `control-engine@main`",
    "creates one fresh generation-bound run id",
    "creates an exact private `control-plane` capability",
    "performs one ordinary V4 acquisition using the existing lease/CAS primitives",
)
LIVE_TICK_RESPONSIBILITY_PROMPT_REQUIRED_MARKERS = (
    "The workflow wakes hourly at minute 30 using GitHub's native cron",
    "`30 * * * *`",
    "A failed GitHub Actions run does not disable future cron wakes.",
    "Expired-holder recovery remains the existing canonical lease mechanism.",
)
LIVENESS_PROMPT_REQUIRED_MARKERS = (
    "processes at most one newly acquired WORK item",
    "There is no same-invocation multi-task continuation requirement.",
    "One WORK per wake is the deliberate liveness/simplicity cap.",
    "The next hourly wake re-reads current truth.",
)
TARGET_EFFECT_PROMPT_REQUIRED_MARKERS = (
    "A target-repository mutation is permitted only for the exact currently held",
    "installation token scoped to that exact repository",
    "revalidates the target immediately before the effect",
    "requires exact readback",
    "perform no target effect and close the holder with YIELD",
)
CANONICAL_EVENT_PROMPT_REQUIRED_MARKERS = (
    "closes any holder with one accepted EVENT or fail-closed YIELD",
    "candidate-less BUILD: YIELD.",
    "CANDIDATE_READY",
    "INTERNAL_REPAIR",
    "INTERNAL_PASS",
    "EXTERNAL_REQUESTED",
    "EXTERNAL_FINDING",
    "EXTERNAL_PASS",
    "REVIEW_UNAVAILABLE",
)
HOLDER_CLOSEOUT_PROMPT_REQUIRED_MARKERS = (
    "closes any holder with one accepted EVENT or fail-closed YIELD",
    "Runtime queue mutation remains the existing exact private-main no-op +",
    "runtime-ref atomic CAS",
    "No blind retries occur after ambiguous writes.",
)
COMPLEXITY_BRAKE_PROMPT_REQUIRED_MARKERS = (
    "Routine NO_WORK/BUSY wakes perform no",
    "model call.",
    "Codex is not the routine executor.",
    "smallest authorized change",
    "No ChatGPT Scheduled Task, Work task, Codex automation, Guardian, second queue,",
    "retry ledger, heartbeat ledger or recovery database",
)
OBSOLETE_TRANSPORT_RECOVERY_MARKERS = (
    "one canonical ChatGPT Scheduled Control V4 Runner",
    "Mandatory continuation with one runaway cap",
    "at most **8 new-holder acquisitions per Scheduled invocation**",
    "post a **second same-`run_id` TICK**",
    "Control V4 Liveness Guardian A",
    "Control V4 Liveness Guardian B",
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


def validate_authority_evolution(candidate_bundle, base_bundle) -> None:
    base_missions = {mission["mission_id"]: mission for mission in base_bundle.missions}
    candidate_missions = {mission["mission_id"]: mission for mission in candidate_bundle.missions}

    missing_missions = sorted(set(base_missions) - set(candidate_missions))
    if missing_missions:
        raise ValidationError("current V4 Mission authority may not be deleted")

    missing_authorities = sorted(set(base_bundle.authority_blob_shas) - set(candidate_bundle.authority_blob_shas))
    if missing_authorities:
        raise ValidationError("current V4 repository authority may not be deleted")

    for mission_id, base_mission in base_missions.items():
        if candidate_bundle.mission_blob_shas[mission_id] == base_bundle.mission_blob_shas[mission_id]:
            continue
        candidate_mission = candidate_missions[mission_id]
        base_revision = base_mission["mission_revision"]
        candidate_revision = candidate_mission["mission_revision"]
        try:
            advances = revision_strictly_precedes(base_revision, candidate_revision)
        except V4ValidationError as exc:
            raise ValidationError("changed V4 Mission revision is invalid") from exc
        if not advances:
            raise ValidationError("changed V4 Mission must advance mission_revision")
        if candidate_mission.get("supersedes_revision") != base_revision:
            raise ValidationError("changed V4 Mission must supersede exact current revision")


def validate_current_surface(root: Path, entries) -> None:
    stale = sorted(path for path in LEGACY_CURRENT_PATHS if path in entries)
    if stale:
        raise ValidationError("private main retains competing V3.1 current authority")

    for path in sorted(CURRENT_SURFACE_PATHS):
        _regular_blob(entries, path)

    replenishment_policy = _text(root, entries, REPLENISHMENT_POLICY_PATH)
    if AUTO_MATERIALIZATION_POLICY not in replenishment_policy.splitlines():
        raise ValidationError("private replenishment policy lacks exact auto-materialization authority marker")

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
        raise ValidationError("obsolete Runner contract is not trusted by the current native workflow contract")
    if prompt_oid != REVIEWED_RUNNER_PROMPT_BLOB_SHA:
        raise ValidationError("Runner prompt blob differs from exact trusted reviewed V4 prompt contract")
    if any(marker not in prompt_text for marker in STATELESS_TRANSPORT_PROMPT_REQUIRED_MARKERS):
        raise ValidationError("current Runner contract lacks required native authority markers")
    if any(marker not in prompt_text for marker in COMMAND_BINDING_PROMPT_REQUIRED_MARKERS):
        raise ValidationError("current Runner contract lacks required native binding markers")
    if any(marker not in prompt_text for marker in LIVE_TICK_RESPONSIBILITY_PROMPT_REQUIRED_MARKERS):
        raise ValidationError("current Runner contract lacks required native wake/liveness markers")
    if any(marker not in prompt_text for marker in LIVENESS_PROMPT_REQUIRED_MARKERS):
        raise ValidationError("current Runner contract lacks one-WORK invocation-liveness markers")
    if any(marker not in prompt_text for marker in TARGET_EFFECT_PROMPT_REQUIRED_MARKERS):
        raise ValidationError("current Runner contract lacks exact target-effect markers")
    if any(marker not in prompt_text for marker in CANONICAL_EVENT_PROMPT_REQUIRED_MARKERS):
        raise ValidationError("current Runner contract lacks event semantics markers")
    if any(marker not in prompt_text for marker in HOLDER_CLOSEOUT_PROMPT_REQUIRED_MARKERS):
        raise ValidationError("current Runner contract lacks holder-closeout markers")
    if any(marker not in prompt_text for marker in COMPLEXITY_BRAKE_PROMPT_REQUIRED_MARKERS):
        raise ValidationError("current Runner contract lacks simplicity/cost-boundary markers")
    if any(marker in prompt_text for marker in OBSOLETE_TRANSPORT_RECOVERY_MARKERS):
        raise ValidationError("current Runner contract retains obsolete ChatGPT-scheduled semantics")


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
    if config.get("execution_surface") != "GITHUB_ACTIONS_NATIVE" or config.get("prompt_path") != RUNNER_PROMPT_PATH:
        raise ValidationError("Runner execution/prompt identity invalid")
    if config.get("workflow_path") != ".github/workflows/control-v4-native-runner.yml":
        raise ValidationError("Runner native workflow path invalid")
    if config.get("workflow_repository") != "market-predictions/control-engine" or config.get("workflow_ref") != "main":
        raise ValidationError("Runner native workflow binding invalid")
    if config.get("runner_command_generation") != "9c7e1a4b2d6f8053":
        raise ValidationError("Runner generation invalid")

    prompt_text = _text(root, entries, RUNNER_PROMPT_PATH)
    _, prompt_oid = _blob(root, entries, RUNNER_PROMPT_PATH)
    _validate_prompt_trust(prompt_text, prompt_oid)
    if config.get("prompt_blob_sha") != prompt_oid:
        raise ValidationError("Runner config does not bind the exact trusted reviewed prompt blob")
    if "status=CANDIDATE_INERT" in prompt_text or "status=CANDIDATE" in prompt_text:
        raise ValidationError("active Runner contract retains candidate/inert lifecycle metadata")

    if config.get("schedule") != {
        "timing_mode": "GITHUB_CRON",
        "timezone_display": "Europe/Amsterdam",
        "cron_utc": "30 * * * *",
    }:
        raise ValidationError("Runner schedule differs from reviewed native V4 binding")
    if config.get("automation_object_binding_status") != "NATIVE_WORKFLOW_BOUND":
        raise ValidationError("Runner native workflow binding status invalid")
    if config.get("scheduled_credential_binding_status") != "CONTROL_GITHUB_APP_EXACT_REPOSITORY_TOKENS":
        raise ValidationError("Runner native credential binding status invalid")
    if config.get("effective_capability_binding_status") != "TRUSTED_MAIN_WORKFLOW_PLUS_EXACT_REPOSITORY_CAPABILITIES":
        raise ValidationError("Runner native capability binding invalid")
    worker = config.get("semantic_worker")
    if worker != {
        "routine_heartbeat_model_calls": 0,
        "provider_boundary": "FREELLMAPI",
        "worker_source_repository": "market-predictions/agent",
        "worker_mode": "EPHEMERAL_ON_DEMAND_PUBLIC_TARGET_FACTS_ONLY",
    }:
        raise ValidationError("Runner semantic worker binding invalid")
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
        "replenishment_policy=control/CONTROL_V4_REPLENISHMENT_DISCOVERY.md",
        "fresh live projection",
        "STATUS_OBSERVABILITY_INCOMPLETE",
        "### Canonical status dashboard presentation contract",
        "Workstream | State | Current truth | Complexity risk | Autonomous? | Autonomous ETA | Waiting on | Approval needed | Stalled since | Next action",
        "`State` and `Complexity risk` are independent dimensions.",
        "`Approval needed` is `—` unless further useful progress on that workstream requires a principal authority decision.",
        "### Principal approval handshake",
        "Control works autonomously inside already-governed authority.",
        "APPROVAL NEEDED — A1 — <workstream>",
        "Approval is one-shot and action-scoped.",
        "The conversation is an approval interaction surface, not persistent semantic authority.",
        "Queue replenishment candidate missing",
        "## Automatic candidate materialize+acquire",
        AUTO_MATERIALIZATION_POLICY,
        "auto_materialization_requires_runtime_enabled=true",
        "auto_materialization_requires_exact_existing_candidate=true",
        "auto_materialization_max_per_tick=1",
        "auto_materialization_and_acquisition_one_cas=true",
        "terminal_no_work_requires_no_auto_mutation=true",
        "candidate_less_build_for_replenishment=false",
        "no material progress for more than 24 hours MUST be shown as stalled",
        "The 24-hour stall threshold overrides any longer `Autonomous ETA` band.",
        "More than 48 hours without a legitimate external dependency MUST escalate the workstream to at least 🟠 ORANGE",
        "status_dashboard_contract=CANONICAL_V2",
        "status_dashboard_requires_complexity_risk=true",
        "status_dashboard_requires_autonomous_eta=true",
        "status_dashboard_requires_waiting_on=true",
        "status_dashboard_requires_approval_needed=true",
        "status_dashboard_requires_stalled_since=true",
        "status_dashboard_preserves_active_green_workstreams=true",
        "status_dashboard_owner_approval_handshake=CONTROL_INITIATED",
        "owner_approval_is_action_scoped=true",
        "owner_approval_is_persistent_semantic_authority=false",
    }
    if any(marker not in text for marker in required):
        raise ValidationError("SYSTEM_INDEX lacks current V4 live-first/status-dashboard/replenishment authority markers")

    for stale in (
        "# Control — Canonical System Index V3.1",
        "Control Autonomy V3.1 supersedes conflicting",
        "Until cutover, V3.1 above is current truth.",
        "project_replenishment_approval_scope=",
        "project_replenishment_task_by_task_approval=",
        "project_replenishment_future_authority=",
    ):
        if stale in text:
            raise ValidationError("SYSTEM_INDEX retains stale V3.1 or approval-gated replenishment authority")


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
        base_bundle = load_v4_authority_from_git(base_root)
    except V4ValidationError as exc:
        raise ValidationError("trusted public V4 authority validation failed") from exc

    validate_authority_evolution(candidate_bundle, base_bundle)
    validate_current_surface(candidate_root, candidate_entries)
    runtime = validate_runtime_and_runner(candidate_root, candidate_entries)
    index_raw, index_oid = _blob(candidate_root, candidate_entries, INDEX_PATH)
    validate_system_index(index_raw, runtime, index_oid=index_oid)

    print("CONTROL_PRIVATE_V4_VALIDATION=PASS")
    print("CONTROL_PRIVATE_CANDIDATE_EXECUTION=false")
    print("CONTROL_PRIVATE_RUNTIME_MUTATION=false")
    print("CONTROL_PRIVATE_V4_CURRENT_SURFACE_CLEAN=true")
    print("CONTROL_PRIVATE_V4_AUTHORITY_EVOLUTION_VALID=true")
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
