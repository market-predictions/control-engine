#!/usr/bin/env python3
"""Trusted static validator for an exact private Control V3.1 candidate.

The private candidate is treated strictly as Git data. This validator never
imports, executes, sources, checks out, or follows candidate-controlled code,
workflows, hooks, symlinks, or filesystem paths.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

REPOSITORY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+$")
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"


class ValidationError(ValueError):
    pass


def zero(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def explicit_bool(value: object) -> bool:
    return isinstance(value, bool)


def valid_repository(value: object) -> bool:
    return isinstance(value, str) and bool(REPOSITORY_RE.fullmatch(value))


def git_bytes(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", *args],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValidationError(f"trusted Git read failed: {' '.join(args)}") from exc
    return result.stdout


def committed_tree(root: Path) -> dict[str, tuple[str, str, str]]:
    raw = git_bytes(root, "ls-tree", "-rz", "--full-tree", "HEAD")
    entries: dict[str, tuple[str, str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode_b, type_b, oid_b = metadata.split(b" ", 2)
            path = raw_path.decode("utf-8", "strict")
            mode = mode_b.decode("ascii")
            obj_type = type_b.decode("ascii")
            oid = oid_b.decode("ascii")
        except Exception as exc:
            raise ValidationError("private Git tree contains an unsupported path/object record") from exc
        if path in entries:
            raise ValidationError(f"duplicate committed path: {path}")
        entries[path] = (mode, obj_type, oid)
    return entries


def blob_bytes(root: Path, entries: dict[str, tuple[str, str, str]], rel: str) -> bytes:
    entry = entries.get(rel)
    if entry is None:
        raise ValidationError(f"required committed file missing: {rel}")
    mode, obj_type, oid = entry
    if mode != "100644" or obj_type != "blob":
        raise ValidationError(f"committed path is not inert regular data: {rel}")
    return git_bytes(root, "cat-file", "blob", oid)


def text(root: Path, entries: dict[str, tuple[str, str, str]], rel: str) -> str:
    try:
        return blob_bytes(root, entries, rel).decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"committed file is not UTF-8: {rel}") from exc


def load(root: Path, entries: dict[str, tuple[str, str, str]], rel: str) -> dict[str, Any]:
    try:
        value = json.loads(text(root, entries, rel))
    except Exception as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError(f"invalid JSON: {rel}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"JSON root must be an object: {rel}")
    return value


def _single_child(path: str, prefix: str) -> str | None:
    if not path.startswith(prefix):
        return None
    tail = path[len(prefix):]
    if not tail or "/" in tail:
        return None
    return tail


def validate_surface(entries: dict[str, tuple[str, str, str]]) -> tuple[list[str], list[str]]:
    fixed = {
        "README.md",
        "control/CHANGELOG.md",
        "control/CONTROL_AUTONOMY_ARCHITECTURE_V3_1.md",
        "control/CONTROL_RUNTIME_AUTHORITY_V3_1.json",
        "control/SYSTEM_INDEX.md",
        "control/missions/README.md",
        "schemas/mission_contract_v31.schema.json",
        "schemas/repository_authority_v31.schema.json",
    }
    mission_paths: list[str] = []
    authority_paths: list[str] = []

    for path, (mode, obj_type, _oid) in entries.items():
        if mode != "100644" or obj_type != "blob":
            raise ValidationError(f"private candidate contains executable, symlink, submodule, or non-blob object: {path}")
        if path in fixed:
            continue
        mission_name = _single_child(path, "control/missions/")
        if mission_name and mission_name.endswith(".mission.json"):
            mission_paths.append(path)
            continue
        authority_name = _single_child(path, "control/repository-authority/")
        if authority_name and authority_name.endswith(".json"):
            authority_paths.append(path)
            continue
        raise ValidationError(f"private candidate contains non-V3.1 active surface: {path}")

    missing = fixed.difference(entries)
    if missing:
        raise ValidationError(f"private V3.1 fixed surface missing: {sorted(missing)}")
    if not mission_paths:
        raise ValidationError("Mission registry is empty")
    if not authority_paths:
        raise ValidationError("repository authority registry is empty")
    return sorted(mission_paths), sorted(authority_paths)


def validate_schema_document(schema: dict[str, Any], *, title: str, required: set[str], protocol_const: str) -> None:
    if schema.get("$schema") != DRAFT_2020_12 or schema.get("title") != title:
        raise ValidationError(f"schema identity invalid: {title}")
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ValidationError(f"schema root contract invalid: {title}")
    schema_required = schema.get("required")
    properties = schema.get("properties")
    if not isinstance(schema_required, list) or set(schema_required) != required or not isinstance(properties, dict):
        raise ValidationError(f"schema required/properties contract invalid: {title}")
    protocol = properties.get("protocol_id")
    if not isinstance(protocol, dict) or protocol.get("const") != protocol_const:
        raise ValidationError(f"schema protocol contract invalid: {title}")
    repository = properties.get("repository")
    if not isinstance(repository, dict) or repository.get("type") != "string" or not isinstance(repository.get("pattern"), str):
        raise ValidationError(f"schema repository contract invalid: {title}")


def validate_schemas(root: Path, entries: dict[str, tuple[str, str, str]]) -> None:
    mission_schema = load(root, entries, "schemas/mission_contract_v31.schema.json")
    validate_schema_document(
        mission_schema,
        title="MISSION_CONTRACT_V3_1",
        required={
            "protocol_id", "mission_id", "mission_revision", "repository",
            "desired_outcome", "gaps", "authority_boundaries", "principal_manual_relay_count",
        },
        protocol_const="MISSION_CONTRACT_V3_1",
    )
    gap_schema = mission_schema.get("properties", {}).get("gaps", {}).get("items")
    if not isinstance(gap_schema, dict) or gap_schema.get("type") != "object" or gap_schema.get("additionalProperties") is not False:
        raise ValidationError("Mission gap schema contract invalid")
    gap_required = gap_schema.get("required")
    gap_properties = gap_schema.get("properties")
    expected_gap = {"gap_id", "gap_state", "depends_on", "repository", "operation", "acceptance", "integration_policy"}
    if not isinstance(gap_required, list) or set(gap_required) != expected_gap or not isinstance(gap_properties, dict):
        raise ValidationError("Mission gap required/properties contract invalid")
    if gap_properties.get("operation", {}).get("const") != "IMPLEMENTATION":
        raise ValidationError("Mission gap operation schema contract invalid")

    authority_schema = load(root, entries, "schemas/repository_authority_v31.schema.json")
    validate_schema_document(
        authority_schema,
        title="CONTROL_REPOSITORY_AUTHORITY_V3_1",
        required={
            "protocol_id", "repository", "integration_policy", "control_auto_profile",
            "integration_enabled", "required_check_runs", "principal_manual_relay_count",
        },
        protocol_const="CONTROL_REPOSITORY_AUTHORITY_V3_1",
    )
    if authority_schema.get("properties", {}).get("integration_enabled", {}).get("type") != "boolean":
        raise ValidationError("repository authority boolean schema contract invalid")


def assert_acyclic_dependencies(gaps: list[dict[str, Any]], *, mission_name: str) -> None:
    graph = {gap["gap_id"]: list(gap.get("depends_on", [])) for gap in gaps}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(gap_id: str) -> None:
        if gap_id in visited:
            return
        if gap_id in visiting:
            raise ValidationError(f"cyclic gap dependency: {mission_name}:{gap_id}")
        visiting.add(gap_id)
        for dependency in graph[gap_id]:
            visit(dependency)
        visiting.remove(gap_id)
        visited.add(gap_id)

    for gap_id in graph:
        visit(gap_id)


def validate_candidate(root: Path) -> None:
    entries = committed_tree(root)
    mission_paths, authority_paths = validate_surface(entries)
    validate_schemas(root, entries)

    global_auth = load(root, entries, "control/CONTROL_RUNTIME_AUTHORITY_V3_1.json")
    if global_auth.get("protocol_id") != "CONTROL_RUNTIME_AUTHORITY_V3_1" or not zero(global_auth.get("principal_manual_relay_count")):
        raise ValidationError("global V3.1 authority invalid")
    if global_auth.get("semantic_claim_lease_seconds") != 5400:
        raise ValidationError("V3.1 semantic claim lease must be exactly 5400 seconds")
    if not explicit_bool(global_auth.get("control_runtime_enabled")) or not explicit_bool(global_auth.get("integration_enabled")):
        raise ValidationError("break-glass authority must be explicit booleans")

    repository_authority: dict[str, dict[str, Any]] = {}
    for path in authority_paths:
        doc = load(root, entries, path)
        name = path.rsplit("/", 1)[-1]
        if doc.get("protocol_id") != "CONTROL_REPOSITORY_AUTHORITY_V3_1" or not zero(doc.get("principal_manual_relay_count")):
            raise ValidationError(f"repository authority invalid: {name}")
        repository = doc.get("repository")
        if not valid_repository(repository) or repository in repository_authority:
            raise ValidationError(f"repository authority identity invalid: {name}")
        if doc.get("integration_policy") not in {"AUTO_AFTER_PASS", "HOLD_AFTER_PASS"}:
            raise ValidationError(f"repository integration policy invalid: {name}")
        if doc.get("control_auto_profile") not in {"CONTROL_AUTO_V1", "NONE"}:
            raise ValidationError(f"repository AUTO profile invalid: {name}")
        if not explicit_bool(doc.get("integration_enabled")):
            raise ValidationError(f"repository integration_enabled must be an explicit boolean: {name}")
        checks = doc.get("required_check_runs")
        if not isinstance(checks, list) or len(checks) != len(set(checks)) or any(not isinstance(x, str) or not x for x in checks):
            raise ValidationError(f"required_check_runs invalid: {name}")
        repository_authority[repository] = doc

    seen_missions: set[str] = set()
    for path in mission_paths:
        mission = load(root, entries, path)
        name = path.rsplit("/", 1)[-1]
        if mission.get("protocol_id") != "MISSION_CONTRACT_V3_1" or not zero(mission.get("principal_manual_relay_count")):
            raise ValidationError(f"Mission protocol/relay invalid: {name}")
        mission_id = mission.get("mission_id")
        revision = mission.get("mission_revision")
        repository = mission.get("repository")
        if not isinstance(mission_id, str) or not mission_id or mission_id in seen_missions or not isinstance(revision, str) or not revision:
            raise ValidationError(f"Mission identity invalid: {name}")
        seen_missions.add(mission_id)
        if not valid_repository(repository) or repository not in repository_authority:
            raise ValidationError(f"Mission repository has no valid authority: {name}")
        if any(key in mission for key in ("state", "priority", "next_action", "worker", "provider", "schedule")):
            raise ValidationError(f"Mission contains mutable/routing state: {name}")
        gaps = mission.get("gaps")
        if not isinstance(gaps, list) or not gaps:
            raise ValidationError(f"Mission gaps invalid: {name}")
        ids = [g.get("gap_id") for g in gaps if isinstance(g, dict)]
        if len(ids) != len(gaps) or any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
            raise ValidationError(f"Mission gap identity invalid: {name}")
        idset = set(ids)
        for gap in gaps:
            gid = gap.get("gap_id")
            if gap.get("gap_state") not in {"OPEN", "RETIRED"}:
                raise ValidationError(f"gap_state invalid: {name}:{gid}")
            if gap.get("repository") != repository or gap.get("operation") != "IMPLEMENTATION":
                raise ValidationError(f"gap execution identity invalid: {name}:{gid}")
            if gap.get("integration_policy") not in {"AUTO_AFTER_PASS", "HOLD_AFTER_PASS"}:
                raise ValidationError(f"gap integration policy invalid: {name}:{gid}")
            deps = gap.get("depends_on")
            if not isinstance(deps, list) or len(deps) != len(set(deps)) or any(dep not in idset for dep in deps):
                raise ValidationError(f"gap dependency invalid: {name}:{gid}")
            acceptance = gap.get("acceptance")
            if not isinstance(acceptance, list) or not acceptance or any(not isinstance(x, str) or not x for x in acceptance):
                raise ValidationError(f"gap acceptance invalid: {name}:{gid}")
            forbidden = {"state", "satisfied", "status", "priority", "instruction", "worker", "provider", "retry", "schedule"}
            if forbidden.intersection(gap):
                raise ValidationError(f"gap contains planning/execution state: {name}:{gid}")
        assert_acyclic_dependencies(gaps, mission_name=name)

    index = text(root, entries, "control/SYSTEM_INDEX.md")
    for marker in (
        "CONTROL_AUTONOMY_ARCHITECTURE_V3_1.md",
        "MISSION DEFINES INTENT",
        "REPOSITORY PROVIDES FACTS",
        "no A2 baseline",
        "no normal provider fallback",
    ):
        if marker not in index:
            raise ValidationError(f"canonical SYSTEM_INDEX missing {marker}")


def mission_documents_by_identity(root: Path, entries: dict[str, tuple[str, str, str]]) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for path in sorted(entries):
        name = _single_child(path, "control/missions/")
        if not name or not name.endswith(".mission.json"):
            continue
        doc = load(root, entries, path)
        if doc.get("protocol_id") != "MISSION_CONTRACT_V3_1":
            continue
        mission_id = doc.get("mission_id")
        if not isinstance(mission_id, str) or not mission_id or mission_id in documents:
            raise ValidationError("V3.1 Mission identity is missing or duplicated")
        documents[mission_id] = doc
    return documents


def enforce_revision_discipline(candidate_docs: dict[str, dict[str, Any]], base_docs: dict[str, dict[str, Any]]) -> None:
    for mission_id, base_doc in base_docs.items():
        candidate_doc = candidate_docs.get(mission_id)
        if candidate_doc is None:
            raise ValidationError(f"existing V3.1 Mission removed instead of being revised/retired: {mission_id}")
        if candidate_doc != base_doc and candidate_doc.get("mission_revision") == base_doc.get("mission_revision"):
            raise ValidationError(f"execution-relevant Mission changed without new mission_revision: {mission_id}")


def validate_revision_discipline(candidate: Path, base: Path) -> None:
    candidate_entries = committed_tree(candidate)
    base_entries = committed_tree(base)
    candidate_docs = mission_documents_by_identity(candidate, candidate_entries)
    base_docs = mission_documents_by_identity(base, base_entries)
    enforce_revision_discipline(candidate_docs, base_docs)


def main() -> int:
    if len(sys.argv) != 3:
        raise ValidationError("usage: validate_private_control_v31.py CANDIDATE_GIT_REPO BASE_GIT_REPO")
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
