from __future__ import annotations

from datetime import datetime
from typing import Any

POINT_WEIGHTS = {
    "FOUNDATION": 2,
    "CAPABILITY_VALIDATED": 2,
    "INDEPENDENT_ACCEPTANCE": 2,
    "INTEGRATED_CAPABILITY": 3,
    "OPERATIONAL_OUTCOME": 4,
}
EVENT_CLASSES = {"PROCESS", "RETAINED_VALUE", "CORRECTION"}
EVENT_TYPES = {
    "CONTROL_ADOPTION", "WORK_EXECUTABLE", "IMPLEMENTATION_STARTED",
    "CANDIDATE_PRODUCED", "VALIDATION_PASS", "ASSURANCE_STARTED",
    "ASSURANCE_PASS", "INTEGRATED", "LIVE_VERIFIED", "OUTCOME_CONFIRMED",
    "BLOCKED", "REPAIR", "RECONCILIATION", "SUPERSEDED", "CORRECTION",
}
SOURCE_PREFIXES = ("github:", "runtime:", "control:")
FOCUS_CONTEXT_COLOR = "#D1D5DB"


class TimelineContractError(ValueError):
    pass


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise TimelineContractError("occurred_at must be a string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise TimelineContractError(f"invalid occurred_at: {value}") from exc
    if parsed.tzinfo is None:
        raise TimelineContractError("occurred_at must include timezone")
    return parsed


def validate_registry(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if registry.get("version") != "1.0.0" or not isinstance(registry.get("projects"), list) or not registry["projects"]:
        raise TimelineContractError("invalid registry")
    indexed: dict[str, dict[str, Any]] = {}
    colors: set[str] = set()
    aliases: dict[str, str] = {}
    for project in registry["projects"]:
        project_id = project.get("project_id")
        name = project.get("display_name")
        color = project.get("color")
        if not _text(project_id) or not _text(name):
            raise TimelineContractError("invalid project identity")
        if project_id in indexed:
            raise TimelineContractError(f"duplicate project_id: {project_id}")
        if not isinstance(color, str) or len(color) != 7 or not color.startswith("#"):
            raise TimelineContractError(f"invalid color for {project_id}")
        try:
            int(color[1:], 16)
        except ValueError as exc:
            raise TimelineContractError(f"invalid color for {project_id}") from exc
        normalized = color.upper()
        if normalized in colors:
            raise TimelineContractError(f"duplicate project color: {color}")
        colors.add(normalized)
        for alias in [project_id, name, *project.get("aliases", [])]:
            if not _text(alias):
                raise TimelineContractError(f"invalid alias for {project_id}")
            key = alias.casefold().strip()
            owner = aliases.get(key)
            if owner is not None and owner != project_id:
                raise TimelineContractError(f"duplicate project alias across projects: {alias}")
            aliases[key] = project_id
        indexed[project_id] = project
    return indexed


def _common(event: dict[str, Any], projects: dict[str, dict[str, Any]], ids: set[str]) -> dict[str, Any]:
    required = {"version", "event_id", "project_id", "occurred_at", "event_class", "event_type", "points_delta", "summary", "mapping_rationale", "sources"}
    missing = required - set(event)
    if missing:
        raise TimelineContractError(f"missing event fields: {sorted(missing)}")
    if event["version"] != "1.1":
        raise TimelineContractError("unsupported event version")
    event_id = event["event_id"]
    if not _text(event_id) or event_id in ids:
        raise TimelineContractError(f"duplicate or invalid event_id: {event_id}")
    ids.add(event_id)
    if event["project_id"] not in projects:
        raise TimelineContractError(f"unknown project_id: {event['project_id']}")
    parsed = _time(event["occurred_at"])
    if event["event_class"] not in EVENT_CLASSES or event["event_type"] not in EVENT_TYPES:
        raise TimelineContractError(f"unsupported event kind: {event_id}")
    delta = event["points_delta"]
    if not isinstance(delta, int) or isinstance(delta, bool) or not -4 <= delta <= 4:
        raise TimelineContractError(f"invalid points_delta for {event_id}")
    sources = event["sources"]
    if not isinstance(sources, list) or not sources or any(not isinstance(s, str) or not s.startswith(SOURCE_PREFIXES) for s in sources):
        raise TimelineContractError(f"non-authoritative source in {event_id}")
    if not _text(event["summary"]) or not _text(event["mapping_rationale"]):
        raise TimelineContractError(f"summary and mapping_rationale required for {event_id}")
    normalized = dict(event)
    normalized["_parsed_at"] = parsed
    return normalized


def validate_events(events: list[dict[str, Any]], projects: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        raise TimelineContractError("events must be list")
    ids: set[str] = set()
    grouped = {project_id: [] for project_id in projects}
    for raw in events:
        if not isinstance(raw, dict):
            raise TimelineContractError("event must be object")
        event = _common(raw, projects, ids)
        grouped[event["project_id"]].append(event)

    ordered: list[dict[str, Any]] = []
    for project_id, items in grouped.items():
        items.sort(key=lambda e: (e["_parsed_at"], e["event_id"]))
        prior: dict[str, dict[str, Any]] = {}
        active_lineage: dict[tuple[str, str], str] = {}
        active_scope: dict[tuple[str, str], str] = {}
        last_lineage_correction: dict[tuple[str, str], str] = {}
        last_scope_correction: dict[tuple[str, str], str] = {}
        cumulative = 0
        for event in items:
            event_id, event_class = event["event_id"], event["event_class"]
            value_class, lineage, scope = event.get("value_class"), event.get("capability_lineage_id"), event.get("value_scope_ref")
            supersedes, restores, delta = event.get("supersedes_event_id"), event.get("restores_event_id"), event["points_delta"]
            if event_class == "PROCESS":
                if delta != 0:
                    raise TimelineContractError(f"PROCESS event must have zero points: {event_id}")
                if value_class is not None or event["event_type"] == "CORRECTION" or supersedes is not None or restores is not None:
                    raise TimelineContractError(f"invalid PROCESS fields: {event_id}")
            elif event_class == "RETAINED_VALUE":
                if value_class not in POINT_WEIGHTS or delta != POINT_WEIGHTS.get(value_class):
                    raise TimelineContractError(f"wrong point weight for {event_id}")
                if not _text(lineage) or not _text(scope) or supersedes is not None or event["event_type"] == "CORRECTION":
                    raise TimelineContractError(f"invalid retained value fields: {event_id}")
                lk, sk = (lineage, value_class), (scope, value_class)
                if lk in active_lineage:
                    raise TimelineContractError(f"duplicate active retained credit in {project_id}: {event_id}")
                if sk in active_scope:
                    raise TimelineContractError(f"duplicate active value-scope credit in {project_id}: {event_id}")
                lc, sc = last_lineage_correction.get(lk), last_scope_correction.get(sk)
                if lc != sc:
                    raise TimelineContractError(f"correction lineage/scope history divergence: {event_id}")
                if lc is None and restores is not None:
                    raise TimelineContractError(f"initial credit cannot restore event: {event_id}")
                if lc is not None and restores != lc:
                    raise TimelineContractError(f"restoration must reference latest correction {lc}: {event_id}")
                active_lineage[lk] = active_scope[sk] = event_id
            else:
                if event["event_type"] != "CORRECTION" or value_class not in POINT_WEIGHTS or not _text(lineage) or not _text(scope) or not _text(supersedes) or restores is not None:
                    raise TimelineContractError(f"invalid correction fields: {event_id}")
                target = prior.get(supersedes)
                if target is None or target["event_class"] != "RETAINED_VALUE":
                    raise TimelineContractError(f"correction target is not prior retained credit: {event_id}")
                if target.get("capability_lineage_id") != lineage or target.get("value_scope_ref") != scope or target.get("value_class") != value_class:
                    raise TimelineContractError(f"correction target mismatch: {event_id}")
                if delta != -target["points_delta"]:
                    raise TimelineContractError(f"correction must exactly revoke prior credit: {event_id}")
                lk, sk = (lineage, value_class), (scope, value_class)
                if active_lineage.get(lk) != supersedes or active_scope.get(sk) != supersedes:
                    raise TimelineContractError(f"correction target is not active credit: {event_id}")
                del active_lineage[lk]; del active_scope[sk]
                last_lineage_correction[lk] = last_scope_correction[sk] = event_id
            cumulative += delta
            if cumulative < 0:
                raise TimelineContractError(f"cumulative retained progress below zero in {project_id}: {event_id}")
            event["cumulative_retained_progress"] = cumulative
            prior[event_id] = event
            ordered.append(event)
    return sorted(ordered, key=lambda e: (e["_parsed_at"], e["project_id"], e["event_id"]))


def build_render_model(registry: dict[str, Any], events: list[dict[str, Any]], focus_project_id: str | None = None) -> dict[str, Any]:
    projects = validate_registry(registry)
    if focus_project_id is not None and focus_project_id not in projects:
        raise TimelineContractError(f"unknown focus project: {focus_project_id}")
    validated = validate_events(events, projects)
    series, max_progress = [], 0
    for project_id, project in projects.items():
        points = []
        for event in validated:
            if event["project_id"] == project_id:
                max_progress = max(max_progress, event["cumulative_retained_progress"])
                points.append({key: event.get(key) for key in ("event_id", "occurred_at", "event_class", "event_type", "value_class", "points_delta", "cumulative_retained_progress", "capability_lineage_id", "value_scope_ref", "summary")})
        focused = focus_project_id == project_id
        canonical = project["color"].upper()
        series.append({"project_id": project_id, "display_name": project["display_name"], "canonical_color": canonical, "display_color": canonical if focus_project_id is None or focused else FOCUS_CONTEXT_COLOR, "focused": focused, "line_weight": 3.0 if focused else (2.0 if focus_project_id is None else 1.0), "points": points})
    return {"contract": "CONTROL_DASHBOARD_TIMELINE_V1", "metric_decision": "DECISION_CUMULATIVE_RETAINED_PROGRESS_2026-08-19", "view": "focused" if focus_project_id else "portfolio", "focus_project_id": focus_project_id, "x_axis": "time", "y_axis": "Cumulative Retained Progress points", "y_min": 0, "suggested_y_max": max(10, ((max_progress + 9) // 10) * 10), "normalization": "none", "dot_semantics": "all canonical events; PROCESS dots do not move the line", "point_weights": dict(POINT_WEIGHTS), "series": series}
