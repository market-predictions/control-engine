#!/usr/bin/env python3
"""Trusted static validator for an exact private Control V3.1 candidate.

The candidate repository is data only. This validator never imports or executes
candidate-controlled Python, shell, workflows, actions, or hooks.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ValidationError(ValueError):
    pass


def load(root: Path, rel: str):
    path = root / rel
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValidationError(f"invalid JSON: {rel}") from exc


def zero(value):
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def files(directory: Path) -> set[str]:
    return {p.name for p in directory.iterdir() if p.is_file()}


def dirs(directory: Path) -> set[str]:
    return {p.name for p in directory.iterdir() if p.is_dir()}


def validate_candidate(root: Path) -> None:
    if files(root) != {"README.md"}:
        raise ValidationError("private root must contain only README.md as a non-dot file")
    if dirs(root) != {".github", "control", "schemas", "tools"}:
        raise ValidationError("private root directory surface is not V3.1-minimal")
    if files(root / ".github" / "workflows") != {"validate-control-v3-1.yml"}:
        raise ValidationError("private workflow surface is not read-only V3.1 validation only")
    if files(root / "tools") != {"validate_control_v31.py"}:
        raise ValidationError("private executable tool surface is not V3.1-minimal")
    if files(root / "schemas") != {"mission_contract_v31.schema.json", "repository_authority_v31.schema.json"}:
        raise ValidationError("private schema surface contains legacy contracts")
    if files(root / "control") != {
        "CHANGELOG.md",
        "CONTROL_AUTONOMY_ARCHITECTURE_V3_1.md",
        "CONTROL_RUNTIME_AUTHORITY_V3_1.json",
        "SYSTEM_INDEX.md",
    }:
        raise ValidationError("private Control authority surface contains legacy doctrine/state")
    if dirs(root / "control") != {"missions", "repository-authority"}:
        raise ValidationError("private Control directory surface contains legacy projections/state")

    workflow = (root / ".github" / "workflows" / "validate-control-v3-1.yml").read_text(encoding="utf-8")
    forbidden_workflow = ("control-runtime-state", "DISPATCH_QUEUE.json", "worker-results/", "contents: write", "pull-requests: write")
    if any(token in workflow for token in forbidden_workflow):
        raise ValidationError("private validation workflow has runtime/write authority")

    global_auth = load(root, "control/CONTROL_RUNTIME_AUTHORITY_V3_1.json")
    if global_auth.get("protocol_id") != "CONTROL_RUNTIME_AUTHORITY_V3_1" or not zero(global_auth.get("principal_manual_relay_count")):
        raise ValidationError("global V3.1 authority invalid")
    if global_auth.get("semantic_claim_lease_seconds") != 5400:
        raise ValidationError("V3.1 semantic claim lease must be exactly 5400 seconds")
    if global_auth.get("control_runtime_enabled") not in {True, False} or global_auth.get("integration_enabled") not in {True, False}:
        raise ValidationError("break-glass authority must be explicit booleans")

    repository_authority: dict[str, dict] = {}
    auth_dir = root / "control" / "repository-authority"
    for path in sorted(auth_dir.glob("*.json")):
        doc = load(root, path.relative_to(root).as_posix())
        if doc.get("protocol_id") != "CONTROL_REPOSITORY_AUTHORITY_V3_1" or not zero(doc.get("principal_manual_relay_count")):
            raise ValidationError(f"repository authority invalid: {path.name}")
        repository = doc.get("repository")
        if not isinstance(repository, str) or repository.count("/") != 1 or repository in repository_authority:
            raise ValidationError(f"repository authority identity invalid: {path.name}")
        if doc.get("integration_policy") not in {"AUTO_AFTER_PASS", "HOLD_AFTER_PASS"}:
            raise ValidationError(f"repository integration policy invalid: {path.name}")
        if doc.get("control_auto_profile") not in {"CONTROL_AUTO_V1", "NONE"}:
            raise ValidationError(f"repository AUTO profile invalid: {path.name}")
        if doc.get("integration_enabled") not in {True, False}:
            raise ValidationError(f"repository integration_enabled invalid: {path.name}")
        checks = doc.get("required_check_runs")
        if not isinstance(checks, list) or len(checks) != len(set(checks)) or any(not isinstance(x, str) or not x for x in checks):
            raise ValidationError(f"required_check_runs invalid: {path.name}")
        repository_authority[repository] = doc
    if not repository_authority:
        raise ValidationError("repository authority registry is empty")

    mission_dir = root / "control" / "missions"
    mission_paths = sorted(mission_dir.glob("*.mission.json"))
    if not mission_paths or files(mission_dir) != {"README.md", *(p.name for p in mission_paths)}:
        raise ValidationError("Mission registry surface invalid")
    seen_missions: set[str] = set()
    for path in mission_paths:
        mission = load(root, path.relative_to(root).as_posix())
        if mission.get("protocol_id") != "MISSION_CONTRACT_V3_1" or not zero(mission.get("principal_manual_relay_count")):
            raise ValidationError(f"Mission protocol/relay invalid: {path.name}")
        mission_id = mission.get("mission_id")
        revision = mission.get("mission_revision")
        repository = mission.get("repository")
        if not isinstance(mission_id, str) or not mission_id or mission_id in seen_missions or not isinstance(revision, str) or not revision:
            raise ValidationError(f"Mission identity invalid: {path.name}")
        seen_missions.add(mission_id)
        if repository not in repository_authority:
            raise ValidationError(f"Mission repository has no authority: {path.name}")
        if any(key in mission for key in ("state", "priority", "next_action", "worker", "provider", "schedule")):
            raise ValidationError(f"Mission contains mutable/routing state: {path.name}")
        gaps = mission.get("gaps")
        if not isinstance(gaps, list) or not gaps:
            raise ValidationError(f"Mission gaps invalid: {path.name}")
        ids = [g.get("gap_id") for g in gaps]
        if any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
            raise ValidationError(f"Mission gap identity invalid: {path.name}")
        idset = set(ids)
        for gap in gaps:
            gid = gap.get("gap_id")
            if gap.get("gap_state") not in {"OPEN", "RETIRED"}:
                raise ValidationError(f"gap_state invalid: {path.name}:{gid}")
            if gap.get("repository") != repository or gap.get("operation") != "IMPLEMENTATION":
                raise ValidationError(f"gap execution identity invalid: {path.name}:{gid}")
            if gap.get("integration_policy") not in {"AUTO_AFTER_PASS", "HOLD_AFTER_PASS"}:
                raise ValidationError(f"gap integration policy invalid: {path.name}:{gid}")
            deps = gap.get("depends_on")
            if not isinstance(deps, list) or len(deps) != len(set(deps)) or any(dep not in idset for dep in deps):
                raise ValidationError(f"gap dependency invalid: {path.name}:{gid}")
            acceptance = gap.get("acceptance")
            if not isinstance(acceptance, list) or not acceptance or any(not isinstance(x, str) or not x for x in acceptance):
                raise ValidationError(f"gap acceptance invalid: {path.name}:{gid}")
            forbidden = {"state", "satisfied", "status", "priority", "instruction", "worker", "provider", "retry", "schedule"}
            if forbidden.intersection(gap):
                raise ValidationError(f"gap contains planning/execution state: {path.name}:{gid}")

    index = (root / "control" / "SYSTEM_INDEX.md").read_text(encoding="utf-8")
    for marker in ("CONTROL_AUTONOMY_ARCHITECTURE_V3_1.md", "MISSION DEFINES INTENT", "REPOSITORY PROVIDES FACTS", "no A2 baseline", "no normal provider fallback"):
        if marker not in index:
            raise ValidationError(f"canonical SYSTEM_INDEX missing {marker}")


def validate_revision_discipline(candidate: Path, base: Path) -> None:
    base_dir = base / "control" / "missions"
    candidate_dir = candidate / "control" / "missions"
    if not base_dir.exists():
        return
    for candidate_path in sorted(candidate_dir.glob("*.mission.json")):
        base_path = base_dir / candidate_path.name
        if not base_path.is_file() or candidate_path.read_bytes() == base_path.read_bytes():
            continue
        candidate_doc = json.loads(candidate_path.read_text(encoding="utf-8"))
        try:
            base_doc = json.loads(base_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if base_doc.get("protocol_id") == "MISSION_CONTRACT_V3_1" and candidate_doc.get("mission_revision") == base_doc.get("mission_revision"):
            raise ValidationError(f"execution-relevant Mission changed without new mission_revision: {candidate_path.name}")


def main() -> int:
    if len(sys.argv) != 3:
        raise ValidationError("usage: validate_private_control_v31.py CANDIDATE_ROOT BASE_ROOT")
    candidate = Path(sys.argv[1]).resolve()
    base = Path(sys.argv[2]).resolve()
    validate_candidate(candidate)
    validate_revision_discipline(candidate, base)
    print("CONTROL_PRIVATE_V3_1_STATIC_VALIDATION=PASS")
    print("PRIVATE_CANDIDATE_EXECUTION=false")
    print("PRIVATE_RUNTIME_MUTATION=false")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as exc:
        print(f"CONTROL_PRIVATE_V3_1_STATIC_VALIDATION=FAIL:{exc}", file=sys.stderr)
        raise SystemExit(2)
