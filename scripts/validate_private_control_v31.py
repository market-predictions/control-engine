#!/usr/bin/env python3
"""Trusted static validator for an exact private Control V3.1 candidate.

The private candidate is treated strictly as Git data. This validator never
imports, executes, sources, or follows candidate-controlled code, workflows,
hooks, symlinks, submodules, or filesystem paths.

Contract semantics come from trusted schema copies in public Control main and
are validated with the standard jsonschema Draft 2020-12 implementation.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError as JsonSchemaValidationError

PUBLIC_ROOT = Path(__file__).resolve().parents[1]
MISSION_SCHEMA_REL = "schemas/mission_contract_v31.schema.json"
REPOSITORY_SCHEMA_REL = "schemas/repository_authority_v31.schema.json"
OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


class ValidationError(ValueError):
    pass


def zero(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def explicit_bool(value: object) -> bool:
    return isinstance(value, bool)


def canonical_repository(value: object) -> str | None:
    if not isinstance(value, str) or value.count("/") != 1:
        return None
    owner, repo = value.split("/", 1)
    if not OWNER_RE.fullmatch(owner) or not REPO_RE.fullmatch(repo) or repo in {".", ".."}:
        return None
    return f"{owner.lower()}/{repo.lower()}"


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


def blob_bytes(root: Path, entries: Mapping[str, tuple[str, str, str]], rel: str) -> bytes:
    entry = entries.get(rel)
    if entry is None:
        raise ValidationError(f"required committed file missing: {rel}")
    mode, obj_type, oid = entry
    if mode != "100644" or obj_type != "blob":
        raise ValidationError(f"committed path is not inert regular data: {rel}")
    return git_bytes(root, "cat-file", "blob", oid)


def text(root: Path, entries: Mapping[str, tuple[str, str, str]], rel: str) -> str:
    try:
        return blob_bytes(root, entries, rel).decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"committed file is not UTF-8: {rel}") from exc


def load(root: Path, entries: Mapping[str, tuple[str, str, str]], rel: str) -> dict[str, Any]:
    try:
        value = json.loads(text(root, entries, rel))
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"invalid JSON: {rel}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"JSON root must be an object: {rel}")
    return value


def trusted_schema(rel: str) -> dict[str, Any]:
    path = PUBLIC_ROOT / rel
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValidationError(f"trusted public schema unavailable: {rel}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"trusted public schema root invalid: {rel}")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ValidationError(f"trusted public schema is invalid: {rel}") from exc
    return value


def validate_instance(instance: Mapping[str, Any], schema: Mapping[str, Any], *, label: str) -> None:
    try:
        Draft202012Validator(schema).validate(instance)
    except JsonSchemaValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path)
        suffix = f" at {location}" if location else ""
        raise ValidationError(f"{label} violates trusted schema{suffix}: {exc.message}") from exc


def _single_child(path: str, prefix: str) -> str | None:
    if not path.startswith(prefix):
        return None
    tail = path[len(prefix):]
    if not tail or "/" in tail:
        return None
    return tail


def validate_surface(entries: Mapping[str, tuple[str, str, str]]) -> tuple[list[str], list[str]]:
    fixed = {
        "README.md",
        "control/CHANGELOG.md",
        "control/CONTROL_AUTONOMY_ARCHITECTURE_V3_1.md",
        "control/CONTROL_RUNTIME_AUTHORITY_V3_1.json",
        "control/SYSTEM_INDEX.md",
        "control/missions/README.md",
        MISSION_SCHEMA_REL,
        REPOSITORY_SCHEMA_REL,
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


def validate_trusted_schema_mirrors(root: Path, entries: Mapping[str, tuple[str, str, str]]) -> tuple[dict[str, Any], dict[str, Any]]:
    trusted_mission = trusted_schema(MISSION_SCHEMA_REL)
    trusted_repository = trusted_schema(REPOSITORY_SCHEMA_REL)
    candidate_mission = load(root, entries, MISSION_SCHEMA_REL)
    candidate_repository = load(root, entries, REPOSITORY_SCHEMA_REL)
    if candidate_mission != trusted_mission:
        raise ValidationError("private Mission schema differs from trusted public contract")
    if candidate_repository != trusted_repository:
        raise ValidationError("private repository-authority schema differs from trusted public contract")
    return trusted_mission, trusted_repository


def assert_acyclic_dependencies(gaps: list[dict[str, Any]], *, mission_name: str) -> None:
    """Validate the dependency graph without Python recursion depth coupling."""
    graph = {gap["gap_id"]: list(gap.get("depends_on", [])) for gap in gaps}
    state: dict[str, int] = {}  # 1=visiting, 2=done

    for start in graph:
        if state.get(start) == 2:
            continue
        state[start] = 1
        stack: list[tuple[str, Any]] = [(start, iter(graph[start]))]
        while stack:
            node, dependencies = stack[-1]
            try:
                dependency = next(dependencies)
            except StopIteration:
                state[node] = 2
                stack.pop()
                continue
            if dependency not in graph:
                raise ValidationError(f"unknown gap dependency: {mission_name}:{dependency}")
            dependency_state = state.get(dependency, 0)
            if dependency_state == 1:
                raise ValidationError(f"cyclic gap dependency: {mission_name}:{dependency}")
            if dependency_state == 0:
                state[dependency] = 1
                stack.append((dependency, iter(graph[dependency])))


def assert_gap_integration_authorized(
    gap_policy: str,
    repository_authority: Mapping[str, Any],
    *,
    label: str,
) -> None:
    """Fail closed when a Mission asks for more merge authority than the repo grants."""
    if gap_policy == "HOLD_AFTER_PASS":
        return
    if gap_policy != "AUTO_AFTER_PASS":
        raise ValidationError(f"gap integration policy invalid: {label}")
    if not (
        repository_authority.get("integration_policy") == "AUTO_AFTER_PASS"
        and repository_authority.get("integration_enabled") is True
        and repository_authority.get("control_auto_profile") == "CONTROL_AUTO_V1"
    ):
        raise ValidationError(f"gap integration policy exceeds repository authority: {label}")


def validate_candidate(root: Path) -> None:
    entries = committed_tree(root)
    mission_paths, authority_paths = validate_surface(entries)
    mission_schema, repository_schema = validate_trusted_schema_mirrors(root, entries)

    global_auth = load(root, entries, "control/CONTROL_RUNTIME_AUTHORITY_V3_1.json")
    if set(global_auth) != {
        "protocol_id",
        "control_runtime_enabled",
        "integration_enabled",
        "semantic_claim_lease_seconds",
        "principal_manual_relay_count",
    }:
        raise ValidationError("global V3.1 authority fields are not exact")
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
        validate_instance(doc, repository_schema, label=f"repository authority {name}")
        canonical = canonical_repository(doc.get("repository"))
        if canonical is None or canonical in repository_authority:
            raise ValidationError(f"repository authority identity invalid or duplicated: {name}")
        repository_authority[canonical] = doc

    seen_missions: set[str] = set()
    for path in mission_paths:
        mission = load(root, entries, path)
        name = path.rsplit("/", 1)[-1]
        validate_instance(mission, mission_schema, label=f"Mission {name}")
        mission_id = mission["mission_id"]
        revision = mission["mission_revision"]
        canonical_repo = canonical_repository(mission["repository"])
        if mission_id in seen_missions or canonical_repo is None or canonical_repo not in repository_authority:
            raise ValidationError(f"Mission identity/repository authority invalid: {name}")
        seen_missions.add(mission_id)
        repo_authority = repository_authority[canonical_repo]
        gaps = mission["gaps"]
        ids = [gap["gap_id"] for gap in gaps]
        if len(ids) != len(set(ids)):
            raise ValidationError(f"Mission gap identity duplicated: {name}")
        idset = set(ids)
        for gap in gaps:
            gid = gap["gap_id"]
            if canonical_repository(gap["repository"]) != canonical_repo:
                raise ValidationError(f"gap repository differs from Mission repository: {name}:{gid}")
            if any(dependency not in idset for dependency in gap["depends_on"]):
                raise ValidationError(f"gap dependency invalid: {name}:{gid}")
            assert_gap_integration_authorized(
                gap["integration_policy"],
                repo_authority,
                label=f"{name}:{gid}",
            )
        assert_acyclic_dependencies(gaps, mission_name=name)
        if not isinstance(revision, str) or not revision:
            raise ValidationError(f"Mission revision invalid: {name}")

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


def mission_documents_by_identity(root: Path, entries: Mapping[str, tuple[str, str, str]]) -> dict[str, dict[str, Any]]:
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


def enforce_revision_discipline(candidate_docs: Mapping[str, dict[str, Any]], base_docs: Mapping[str, dict[str, Any]]) -> None:
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
