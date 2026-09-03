from __future__ import annotations

"""Trusted Git-data binding for passive Control V4 transforms.

This module adds no writer, scheduler, network client, or runtime authority. It
loads exact committed authority data from a local Git checkout, computes the
actual Git blob identities, validates the documents with the trusted public
schemas/contracts, and then delegates to the pure V4 transforms.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence

from control_engine.v4_contracts import (
    V4ValidationError,
    derive_rollback_v31,
    forward_transform_v31_to_v4,
    v4_root_task_id,
    validate_authority_set,
    validate_mission_v4,
    validate_queue_v4,
    validate_repository_authority_v4,
)
from scripts import validate_private_control_v31 as v31_private_validator


MISSION_PREFIX = "control/missions/"
AUTHORITY_PREFIX = "control/repository-authority/"
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class V4AuthorityBundle:
    missions: tuple[dict[str, Any], ...]
    authorities: tuple[dict[str, Any], ...]
    mission_blob_shas: Mapping[str, str]
    authority_blob_shas: Mapping[str, str]


class _DuplicateKeyError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError("duplicate JSON object key")
        result[key] = value
    return result


def _strict_json(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8", "strict")
        value = json.loads(text, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKeyError, TypeError, ValueError) as exc:
        raise V4ValidationError("trusted authority JSON invalid or ambiguous") from exc
    if not isinstance(value, dict):
        raise V4ValidationError("trusted authority JSON root must be an object")
    return value


def _git(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null", *args],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise V4ValidationError("trusted Git read failed") from exc
    return result.stdout


def _commit_sha(value: object) -> str:
    if not isinstance(value, str) or COMMIT_SHA_RE.fullmatch(value) is None:
        raise V4ValidationError("frozen authority commit pin must be an exact 40-char lowercase SHA")
    return value


def _head_commit(root: Path) -> str:
    try:
        value = _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode("ascii", "strict").strip()
    except UnicodeDecodeError as exc:
        raise V4ValidationError("trusted Git HEAD identity invalid") from exc
    return _commit_sha(value)


def _committed_tree(root: Path, *, commit_sha: str | None = None) -> dict[str, tuple[str, str, str]]:
    treeish = _commit_sha(commit_sha) if commit_sha is not None else _head_commit(root)
    raw = _git(root, "ls-tree", "-rz", "-r", "--full-tree", treeish)
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
            raise V4ValidationError("trusted Git tree contains unsupported record") from exc
        if path in entries:
            raise V4ValidationError("trusted Git tree contains duplicate path")
        entries[path] = entry
    return entries


def _single_level_json_paths(entries: Mapping[str, tuple[str, str, str]], prefix: str, suffix: str) -> list[str]:
    paths: list[str] = []
    for path in entries:
        if not path.startswith(prefix):
            continue
        tail = path[len(prefix):]
        if tail and "/" not in tail and tail.endswith(suffix):
            paths.append(path)
    return sorted(paths)


def _blob(root: Path, entries: Mapping[str, tuple[str, str, str]], path: str) -> tuple[bytes, str]:
    entry = entries.get(path)
    if entry is None:
        raise V4ValidationError("trusted authority file missing")
    mode, obj_type, oid = entry
    if mode != "100644" or obj_type != "blob":
        raise V4ValidationError("trusted authority path is not an inert regular file")
    return _git(root, "cat-file", "blob", oid), oid


def load_v4_authority_from_git(
    authority_root: Path,
    *,
    commit_sha: str | None = None,
) -> V4AuthorityBundle:
    """Load V4 authority from one exact committed Git object.

    Generic callers may omit `commit_sha` to snapshot the checkout's current HEAD
    once. Rollback frozen authority must pass the immutable V4-40 commit pin.
    """
    root = Path(authority_root)
    entries = _committed_tree(root, commit_sha=commit_sha)
    mission_paths = _single_level_json_paths(entries, MISSION_PREFIX, ".mission.json")
    authority_paths = _single_level_json_paths(entries, AUTHORITY_PREFIX, ".json")
    if not mission_paths or not authority_paths:
        raise V4ValidationError("trusted V4 authority registry is incomplete")

    missions: list[dict[str, Any]] = []
    authorities: list[dict[str, Any]] = []
    mission_shas: dict[str, str] = {}
    authority_shas: dict[str, str] = {}

    for path in mission_paths:
        raw, oid = _blob(root, entries, path)
        mission = _strict_json(raw)
        validate_mission_v4(mission)
        mission_id = mission["mission_id"]
        if mission_id in mission_shas:
            raise V4ValidationError("trusted V4 Mission identity duplicated")
        mission_shas[mission_id] = oid
        missions.append(mission)

    for path in authority_paths:
        raw, oid = _blob(root, entries, path)
        authority = _strict_json(raw)
        validate_repository_authority_v4(authority)
        repository = authority["repository"].lower()
        if repository in authority_shas:
            raise V4ValidationError("trusted V4 repository authority duplicated")
        authority_shas[repository] = oid
        authorities.append(authority)

    validate_authority_set(missions, authorities)
    return V4AuthorityBundle(
        missions=tuple(missions),
        authorities=tuple(authorities),
        mission_blob_shas=dict(mission_shas),
        authority_blob_shas=dict(authority_shas),
    )


def load_v31_missions_from_git(
    authority_root: Path,
    *,
    commit_sha: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Load Missions after validating one exact committed V3.1 authority object."""
    root = Path(authority_root)
    pin = _commit_sha(commit_sha) if commit_sha is not None else None
    try:
        v31_private_validator.validate_candidate(root, commit_sha=pin)
        entries = v31_private_validator.committed_tree(root, commit_sha=pin)
        missions = v31_private_validator.mission_documents_by_identity(root, entries)
    except v31_private_validator.ValidationError as exc:
        raise V4ValidationError("frozen V3.1 authority fails trusted validation") from exc
    if not missions:
        raise V4ValidationError("frozen V3.1 Mission registry is empty")
    return tuple(missions[mission_id] for mission_id in sorted(missions))


def _require_frozen_v4_mission_set(
    frozen_bundle: V4AuthorityBundle,
    current_bundle: V4AuthorityBundle,
) -> None:
    if dict(current_bundle.mission_blob_shas) != dict(frozen_bundle.mission_blob_shas):
        raise V4ValidationError("trusted V4 Mission blob set drifted from frozen cutover Git authority")


def assert_v4_queue_bound_to_authority(
    queue: Mapping[str, Any],
    bundle: V4AuthorityBundle,
) -> None:
    """Prove every Mission-derived runtime field binds exact committed authority."""
    validate_queue_v4(queue)
    mission_by_id = {mission["mission_id"]: mission for mission in bundle.missions}

    for task in queue["tasks"]:
        mission = mission_by_id.get(task["mission_id"])
        if mission is None:
            raise V4ValidationError("V4 task Mission missing from trusted authority")
        if task["mission_revision"] != mission["mission_revision"]:
            raise V4ValidationError("V4 task Mission revision differs from trusted authority")
        if task["mission_contract_blob_sha"] != bundle.mission_blob_shas[task["mission_id"]]:
            raise V4ValidationError("V4 task Mission blob SHA differs from trusted Git authority")

        gap_matches = [gap for gap in mission["gaps"] if gap["gap_id"] == task["gap_id"]]
        if len(gap_matches) != 1:
            raise V4ValidationError("V4 task gap does not resolve exactly in trusted Mission")
        gap = gap_matches[0]
        if gap["gap_state"] != "OPEN":
            raise V4ValidationError("V4 task exists for non-materializable trusted Mission gap")

        expected_task_id = v4_root_task_id(mission["mission_id"], mission["mission_revision"], gap["gap_id"])
        if task["task_id"] != expected_task_id:
            raise V4ValidationError("V4 task identity differs from trusted Mission-derived identity")
        if task["repository"].lower() != gap["repository"].lower():
            raise V4ValidationError("V4 task repository differs from trusted Mission gap")
        if task["acceptance"] != gap["acceptance"]:
            raise V4ValidationError("V4 task acceptance differs from trusted Mission gap")
        if task["integration_policy"] != gap["integration_policy"]:
            raise V4ValidationError("V4 task integration policy differs from trusted Mission gap")
        if task["review_policy"] != gap["review_policy"]:
            raise V4ValidationError("V4 task review policy differs from trusted Mission gap")
        if task["convergence_required"] is not bool(gap.get("convergence_required", False)):
            raise V4ValidationError("V4 task convergence policy differs from trusted Mission gap")

        repository = mission["repository"].lower()
        if task["repository_authority_blob_sha"] != bundle.authority_blob_shas.get(repository):
            raise V4ValidationError("V4 task repository authority SHA differs from trusted Git authority")


def forward_transform_v31_to_v4_from_git(
    v31_queue: Mapping[str, Any],
    *,
    authority_root: Path,
    transformed_at: Any,
) -> dict[str, Any]:
    bundle = load_v4_authority_from_git(authority_root)
    return forward_transform_v31_to_v4(
        v31_queue,
        missions=bundle.missions,
        mission_blob_shas=bundle.mission_blob_shas,
        authorities=bundle.authorities,
        authority_blob_shas=bundle.authority_blob_shas,
        transformed_at=transformed_at,
    )


def derive_rollback_v31_from_git(
    *,
    pre_v31_queue: Mapping[str, Any],
    v4_queue: Mapping[str, Any],
    frozen_v31_authority_root: Path,
    frozen_v31_authority_commit_sha: str,
    frozen_v4_authority_root: Path,
    frozen_v4_authority_commit_sha: str,
    current_v4_authority_root: Path,
    rollback_revisions: Mapping[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, set[str]]]:
    """Run bounded rollback against immutable frozen and current Git authority."""
    frozen_v4_bundle = load_v4_authority_from_git(
        frozen_v4_authority_root,
        commit_sha=_commit_sha(frozen_v4_authority_commit_sha),
    )
    current_v4_bundle = load_v4_authority_from_git(current_v4_authority_root)
    _require_frozen_v4_mission_set(frozen_v4_bundle, current_v4_bundle)
    assert_v4_queue_bound_to_authority(v4_queue, current_v4_bundle)

    pre_cutover_missions: Sequence[Mapping[str, Any]] = load_v31_missions_from_git(
        frozen_v31_authority_root,
        commit_sha=_commit_sha(frozen_v31_authority_commit_sha),
    )
    return derive_rollback_v31(
        pre_v31_queue=pre_v31_queue,
        v4_queue=v4_queue,
        pre_cutover_missions=pre_cutover_missions,
        rollback_revisions=rollback_revisions,
    )
