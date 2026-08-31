#!/usr/bin/env python3
"""Trusted static validator for an exact private Control V3.1 candidate.

Private Control is treated strictly as committed Git data. Candidate-controlled
code is never imported or executed. Public logs expose only fixed PASS/FAIL
markers; candidate-derived values are never included in process output.
"""
from __future__ import annotations

from datetime import date
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
OWNER_RE = re.compile(r"^(?!.*--)[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
REVISION_RE = re.compile(r"^(?P<day>\d{4}-\d{2}-\d{2})-r(?P<sequence>[1-9]\d*)$")


class ValidationError(ValueError):
    pass


class DuplicateKeyError(ValueError):
    pass


def zero(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def require_zero_relay_count(document: Mapping[str, Any]) -> None:
    if not zero(document.get("principal_manual_relay_count")):
        raise ValidationError("principal manual relay count must be exact integer zero")


def explicit_bool(value: object) -> bool:
    return isinstance(value, bool)


def revision_key(value: object) -> tuple[int, date]:
    if not isinstance(value, str):
        raise ValidationError("Mission revision invalid")
    match = REVISION_RE.fullmatch(value)
    if match is None:
        raise ValidationError("Mission revision invalid")
    try:
        day = date.fromisoformat(match.group("day"))
    except ValueError as exc:
        raise ValidationError("Mission revision invalid") from exc
    return int(match.group("sequence")), day


def canonical_repository(value: object) -> str | None:
    if not isinstance(value, str) or value.count("/") != 1:
        return None
    owner, repo = value.split("/", 1)
    if not OWNER_RE.fullmatch(owner) or not REPO_RE.fullmatch(repo) or repo in {".", ".."}:
        return None
    return f"{owner.lower()}/{repo.lower()}"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError("duplicate JSON object key")
        result[key] = value
    return result


def strict_json(raw: str) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, DuplicateKeyError, TypeError, ValueError) as exc:
        raise ValidationError("private JSON invalid or ambiguous") from exc


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Compare JSON contracts with JSON type semantics, not Python numeric coercion."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


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
        raise ValidationError("trusted Git read failed") from exc
    return result.stdout


def committed_tree(root: Path) -> dict[str, tuple[str, str, str]]:
    raw = git_bytes(root, "ls-tree", "-rz", "-r", "--full-tree", "HEAD")
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
            raise ValidationError("private Git tree contains unsupported record") from exc
        if path in entries:
            raise ValidationError("duplicate committed path")
        entries[path] = (mode, obj_type, oid)
    return entries


def blob_bytes(root: Path, entries: Mapping[str, tuple[str, str, str]], rel: str) -> bytes:
    entry = entries.get(rel)
    if entry is None:
        raise ValidationError("required committed file missing")
    mode, obj_type, oid = entry
    if mode != "100644" or obj_type != "blob":
        raise ValidationError("committed path is not inert regular data")
    return git_bytes(root, "cat-file", "blob", oid)


def text(root: Path, entries: Mapping[str, tuple[str, str, str]], rel: str) -> str:
    try:
        return blob_bytes(root, entries, rel).decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ValidationError("committed file is not UTF-8") from exc


def load(root: Path, entries: Mapping[str, tuple[str, str, str]], rel: str) -> dict[str, Any]:
    value = strict_json(text(root, entries, rel))
    if not isinstance(value, dict):
        raise ValidationError("JSON root must be an object")
    return value


def trusted_schema(rel: str) -> dict[str, Any]:
    path = PUBLIC_ROOT / rel
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValidationError("trusted public schema unavailable") from exc
    if not isinstance(value, dict):
        raise ValidationError("trusted public schema root invalid")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ValidationError("trusted public schema invalid") from exc
    return value


def validate_instance(instance: Mapping[str, Any], schema: Mapping[str, Any], *, label: str = "instance") -> None:
    del label
    try:
        Draft202012Validator(schema).validate(instance)
    except JsonSchemaValidationError as exc:
        raise ValidationError("instance violates trusted schema") from exc


def require_exact_schema_bytes(candidate: bytes, trusted: bytes, *, label: str = "schema") -> None:
    del label
    if candidate != trusted:
        raise ValidationError("private schema differs byte-for-byte from trusted public contract")


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
            raise ValidationError("private candidate contains executable, symlink, submodule, or non-blob object")
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
        raise ValidationError("private candidate contains non-V3.1 active surface")

    if fixed.difference(entries):
        raise ValidationError("private V3.1 fixed surface missing")
    if not mission_paths:
        raise ValidationError("Mission registry is empty")
    if not authority_paths:
        raise ValidationError("repository authority registry is empty")
    return sorted(mission_paths), sorted(authority_paths)


def validate_trusted_schema_mirrors(root: Path, entries: Mapping[str, tuple[str, str, str]]) -> tuple[dict[str, Any], dict[str, Any]]:
    trusted_mission_bytes = (PUBLIC_ROOT / MISSION_SCHEMA_REL).read_bytes()
    trusted_repository_bytes = (PUBLIC_ROOT / REPOSITORY_SCHEMA_REL).read_bytes()
    require_exact_schema_bytes(blob_bytes(root, entries, MISSION_SCHEMA_REL), trusted_mission_bytes)
    require_exact_schema_bytes(blob_bytes(root, entries, REPOSITORY_SCHEMA_REL), trusted_repository_bytes)
    return trusted_schema(MISSION_SCHEMA_REL), trusted_schema(REPOSITORY_SCHEMA_REL)


def assert_acyclic_dependencies(gaps: list[dict[str, Any]], *, mission_name: str = "Mission") -> None:
    del mission_name
    graph = {gap["gap_id"]: list(gap.get("depends_on", [])) for gap in gaps}
    state: dict[str, int] = {}
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
                raise ValidationError("unknown gap dependency")
            dependency_state = state.get(dependency, 0)
            if dependency_state == 1:
                raise ValidationError("cyclic gap dependency")
            if dependency_state == 0:
                state[dependency] = 1
                stack.append((dependency, iter(graph[dependency])))


def assert_gap_integration_authorized(
    gap_policy: str,
    repository_authority: Mapping[str, Any],
    *,
    global_runtime_enabled: bool,
    global_integration_enabled: bool,
    label: str = "gap",
) -> None:
    del label
    if gap_policy == "HOLD_AFTER_PASS":
        return
    if gap_policy != "AUTO_AFTER_PASS":
        raise ValidationError("gap integration policy invalid")
    if not (
        global_runtime_enabled is True
        and global_integration_enabled is True
        and repository_authority.get("integration_policy") == "AUTO_AFTER_PASS"
        and repository_authority.get("integration_enabled") is True
        and repository_authority.get("control_auto_profile") == "CONTROL_AUTO_V1"
    ):
        raise ValidationError("gap integration policy exceeds Control authority")


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
    if global_auth.get("protocol_id") != "CONTROL_RUNTIME_AUTHORITY_V3_1":
        raise ValidationError("global V3.1 authority invalid")
    require_zero_relay_count(global_auth)
    if global_auth.get("semantic_claim_lease_seconds") != 5400:
        raise ValidationError("V3.1 semantic claim lease invalid")
    if not explicit_bool(global_auth.get("control_runtime_enabled")) or not explicit_bool(global_auth.get("integration_enabled")):
        raise ValidationError("break-glass authority must be explicit booleans")

    repository_authority: dict[str, dict[str, Any]] = {}
    for path in authority_paths:
        doc = load(root, entries, path)
        validate_instance(doc, repository_schema)
        require_zero_relay_count(doc)
        canonical = canonical_repository(doc.get("repository"))
        if canonical is None or canonical in repository_authority:
            raise ValidationError("repository authority identity invalid or duplicated")
        repository_authority[canonical] = doc

    seen_missions: set[str] = set()
    for path in mission_paths:
        mission = load(root, entries, path)
        validate_instance(mission, mission_schema)
        require_zero_relay_count(mission)
        mission_id = mission["mission_id"]
        revision = mission["mission_revision"]
        revision_key(revision)
        canonical_repo = canonical_repository(mission["repository"])
        if mission_id in seen_missions or canonical_repo is None or canonical_repo not in repository_authority:
            raise ValidationError("Mission identity or repository authority invalid")
        seen_missions.add(mission_id)
        repo_authority = repository_authority[canonical_repo]
        gaps = mission["gaps"]
        ids = [gap["gap_id"] for gap in gaps]
        if len(ids) != len(set(ids)):
            raise ValidationError("Mission gap identity duplicated")
        idset = set(ids)
        for gap in gaps:
            if canonical_repository(gap["repository"]) != canonical_repo:
                raise ValidationError("gap repository differs from Mission repository")
            if any(dependency not in idset for dependency in gap["depends_on"]):
                raise ValidationError("gap dependency invalid")
            assert_gap_integration_authorized(
                gap["integration_policy"],
                repo_authority,
                global_runtime_enabled=global_auth["control_runtime_enabled"],
                global_integration_enabled=global_auth["integration_enabled"],
            )
        assert_acyclic_dependencies(gaps)

    index = text(root, entries, "control/SYSTEM_INDEX.md")
    for marker in (
        "CONTROL_AUTONOMY_ARCHITECTURE_V3_1.md",
        "MISSION DEFINES INTENT",
        "REPOSITORY PROVIDES FACTS",
        "no A2 baseline",
        "no normal provider fallback",
    ):
        if marker not in index:
            raise ValidationError("canonical SYSTEM_INDEX missing required V3.1 marker")


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
            raise ValidationError("V3.1 Mission identity missing or duplicated")
        revision_key(doc.get("mission_revision"))
        documents[mission_id] = doc
    return documents


def enforce_revision_discipline(candidate_docs: Mapping[str, dict[str, Any]], base_docs: Mapping[str, dict[str, Any]]) -> None:
    for mission_id, base_doc in base_docs.items():
        candidate_doc = candidate_docs.get(mission_id)
        if candidate_doc is None:
            raise ValidationError("existing V3.1 Mission removed instead of being revised/retired")
        if canonical_json_bytes(candidate_doc) == canonical_json_bytes(base_doc):
            continue
        base_revision = base_doc.get("mission_revision")
        candidate_revision = candidate_doc.get("mission_revision")
        if candidate_revision == base_revision:
            raise ValidationError("execution-relevant Mission changed without new mission_revision")
        base_sequence, base_day = revision_key(base_revision)
        candidate_sequence, candidate_day = revision_key(candidate_revision)
        if candidate_sequence <= base_sequence or candidate_day < base_day:
            raise ValidationError("Mission revision must move forward monotonically")
        if candidate_doc.get("supersedes_revision") != base_revision:
            raise ValidationError("new Mission revision must explicitly supersede current revision")


def validate_revision_discipline(candidate: Path, base: Path) -> None:
    candidate_entries = committed_tree(candidate)
    base_entries = committed_tree(base)
    candidate_docs = mission_documents_by_identity(candidate, candidate_entries)
    base_docs = mission_documents_by_identity(base, base_entries)
    enforce_revision_discipline(candidate_docs, base_docs)


def main() -> int:
    if len(sys.argv) != 3:
        raise ValidationError("validator invocation invalid")
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
    except ValidationError:
        print("CONTROL_PRIVATE_V3_1_STATIC_VALIDATION=FAIL", file=sys.stderr)
        raise SystemExit(2)
    except Exception:
        print("CONTROL_PRIVATE_V3_1_STATIC_VALIDATION=FAIL_INTERNAL", file=sys.stderr)
        raise SystemExit(3)
