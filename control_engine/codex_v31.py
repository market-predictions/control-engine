from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Mapping, Sequence


REQUEST_MARKER = "CONTROL_V3_1_CODEX_B1_REQUEST_V1"
INDETERMINATE_MARKER = "CONTROL_B1_INDETERMINATE:"
TRUSTED_CODEX_LOGINS = frozenset({"chatgpt-codex-connector", "chatgpt-codex-connector[bot]"})
CLEAN_PREFIX = "Codex Review: Didn't find any major issues."
TERMINAL_REVIEW_STATES = frozenset({"COMMENTED", "APPROVED", "CHANGES_REQUESTED"})
MAX_ACCEPTANCE = 40
MAX_REQUEST_BYTES = 12_000
MAX_FINDINGS = 40
MAX_FINDING_BYTES = 4_000
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CLEAN_SHA_RE = re.compile(r"Reviewed commit:\*\*\s*`([0-9a-f]{10,40})`", re.IGNORECASE)


class CodexEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class CodexDecision:
    status: str
    verdict: str | None
    summary: str
    findings: tuple[str, ...] = ()


def _sha(value: object) -> bool:
    return isinstance(value, str) and bool(SHA_RE.fullmatch(value))


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _login(item: Mapping[str, Any]) -> str:
    user = item.get("user")
    if isinstance(user, Mapping) and isinstance(user.get("login"), str):
        return user["login"]
    value = item.get("user_login")
    return value if isinstance(value, str) else ""


def _trusted(item: Mapping[str, Any]) -> bool:
    return _login(item) in TRUSTED_CODEX_LOGINS


def _after(item: Mapping[str, Any], start: datetime) -> bool:
    for key in ("submitted_at", "created_at"):
        value = _timestamp(item.get(key))
        if value is not None:
            return value >= start
    return False


def request_id(*, task_id: str, run_id: str, candidate_sha: str) -> str:
    if not isinstance(task_id, str) or not task_id or not isinstance(run_id, str) or not run_id or not _sha(candidate_sha):
        raise CodexEvidenceError("Codex request identity is invalid")
    material = f"{task_id}\n{run_id}\n{candidate_sha}\n".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def build_request(*, task_id: str, run_id: str, candidate_sha: str, acceptance: Sequence[str]) -> str:
    rid = request_id(task_id=task_id, run_id=run_id, candidate_sha=candidate_sha)
    if not isinstance(acceptance, (list, tuple)) or not acceptance or len(acceptance) > MAX_ACCEPTANCE:
        raise CodexEvidenceError("Codex acceptance is missing or unbounded")
    normalized: list[str] = []
    for item in acceptance:
        if not isinstance(item, str) or not item or item != item.strip() or len(item.splitlines()) != 1:
            raise CodexEvidenceError("Codex acceptance item must be one trimmed line")
        normalized.append(item)
    criteria = "\n".join(f"- {item}" for item in normalized)
    body = (
        "@codex review\n\n"
        "Act only as an independent read-only B1 reviewer for the exact current PR head. "
        "Do not modify code, PR metadata, branches, Control runtime, or integration state. "
        "Review the candidate fresh against only the bounded acceptance criteria below. "
        f"If required evidence is genuinely missing or conflicting, prefix that finding exactly with `{INDETERMINATE_MARKER}`. "
        "Otherwise report each material defect as a normal review finding. No material finding means the criteria are supported.\n\n"
        f"{REQUEST_MARKER}\n"
        f"request_id={rid}\n"
        f"task_id={task_id}\n"
        f"run_id={run_id}\n"
        f"candidate_sha={candidate_sha}\n\n"
        "Acceptance criteria:\n"
        f"{criteria}\n"
    )
    if len(body.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise CodexEvidenceError("Codex request exceeds bounded size")
    return body


def parse_request(body: object) -> tuple[str, str, str, str] | None:
    if not isinstance(body, str) or not body:
        return None
    raw_lines = body.splitlines()
    if not raw_lines or raw_lines[0] != "@codex review":
        return None
    lines = [line.strip() for line in raw_lines]
    if REQUEST_MARKER not in lines or "Acceptance criteria:" not in lines:
        return None
    values: dict[str, str] = {}
    for key in ("request_id", "task_id", "run_id", "candidate_sha"):
        matches = [line.split("=", 1)[1] for line in lines if line.startswith(f"{key}=")]
        if len(matches) != 1 or not matches[0]:
            return None
        values[key] = matches[0]
    if not _sha(values["candidate_sha"]) or not re.fullmatch(r"[0-9a-f]{64}", values["request_id"]):
        return None
    expected = request_id(task_id=values["task_id"], run_id=values["run_id"], candidate_sha=values["candidate_sha"])
    if values["request_id"] != expected:
        return None
    marker_index = lines.index("Acceptance criteria:")
    if marker_index == len(lines) - 1 or not any(line.startswith("- ") and line[2:] for line in lines[marker_index + 1 :]):
        return None
    return values["request_id"], values["task_id"], values["run_id"], values["candidate_sha"]


def _request_start(request: Mapping[str, Any], *, task_id: str, run_id: str, candidate_sha: str) -> datetime:
    expected = (request_id(task_id=task_id, run_id=run_id, candidate_sha=candidate_sha), task_id, run_id, candidate_sha)
    if parse_request(request.get("body")) != expected:
        raise CodexEvidenceError("Codex request does not match exact task/run/candidate")
    created = _timestamp(request.get("created_at"))
    updated = _timestamp(request.get("updated_at"))
    if created is None:
        raise CodexEvidenceError("Codex request has no valid creation timestamp")
    if updated is not None and updated != created:
        raise CodexEvidenceError("Codex request was edited")
    return created


def _review_commit(item: Mapping[str, Any]) -> str | None:
    values: list[str] = []
    for key in ("commit_id", "original_commit_id", "reviewed_commit"):
        if key not in item:
            continue
        value = item.get(key)
        if not _sha(value):
            return ""
        values.append(value)
    if not values:
        return None
    return values[0] if len(set(values)) == 1 else ""


def _bounded_finding(item: Mapping[str, Any]) -> str | None:
    body = item.get("body")
    if not isinstance(body, str) or not body.strip():
        return None
    raw = body.strip()
    encoded = raw.encode("utf-8")
    if len(encoded) > MAX_FINDING_BYTES:
        raw = encoded[:MAX_FINDING_BYTES].decode("utf-8", errors="ignore").rstrip() + "…"
    path = item.get("path")
    line = item.get("line") or item.get("original_line")
    prefix = ""
    if isinstance(path, str) and path:
        prefix = path + (f":{line}" if isinstance(line, int) else "") + ": "
    return prefix + raw


def _clean_commit(body: object) -> str | None:
    if not isinstance(body, str) or not body.startswith(CLEAN_PREFIX):
        return None
    match = CLEAN_SHA_RE.search(body)
    return match.group(1) if match else None


def classify(
    *,
    task_id: str,
    run_id: str,
    candidate_sha: str,
    request: Mapping[str, Any],
    issue_comments: Sequence[Mapping[str, Any]],
    reviews: Sequence[Mapping[str, Any]],
    review_comments: Sequence[Mapping[str, Any]],
) -> CodexDecision:
    if not _sha(candidate_sha):
        raise CodexEvidenceError("candidate_sha is invalid")
    start = _request_start(request, task_id=task_id, run_id=run_id, candidate_sha=candidate_sha)

    trusted_reviews = [item for item in reviews if _trusted(item) and _after(item, start)]
    terminal = [item for item in trusted_reviews if item.get("state") in TERMINAL_REVIEW_STATES and _timestamp(item.get("submitted_at")) is not None]
    stale_terminal = [item for item in terminal if _review_commit(item) not in (None, candidate_sha)]
    malformed_terminal = [item for item in terminal if _review_commit(item) == ""]
    if stale_terminal or malformed_terminal:
        return CodexDecision("EXECUTION_UNAVAILABLE", None, "Codex terminal review evidence is stale or malformed.")

    exact_review_ids = {
        item.get("id")
        for item in terminal
        if _review_commit(item) == candidate_sha and item.get("id") is not None
    }
    records: list[tuple[str, bool]] = []
    for item in review_comments:
        if not _trusted(item) or not _after(item, start):
            continue
        commit = _review_commit(item)
        review_id = item.get("pull_request_review_id")
        if commit == "" or (commit is not None and commit != candidate_sha):
            return CodexDecision("EXECUTION_UNAVAILABLE", None, "Codex review finding is stale or malformed.")
        if review_id not in exact_review_ids:
            continue
        finding = _bounded_finding(item)
        if finding is None:
            continue
        body = item.get("body")
        tagged = isinstance(body, str) and body.startswith(INDETERMINATE_MARKER)
        records.append((finding, tagged))

    changes_requested = [item for item in terminal if item.get("state") == "CHANGES_REQUESTED" and _review_commit(item) == candidate_sha]
    definite = [finding for finding, tagged in records if not tagged]
    indeterminate = [finding for finding, tagged in records if tagged]
    if definite or changes_requested:
        findings = list(definite[:MAX_FINDINGS])
        if changes_requested and len(findings) < MAX_FINDINGS:
            findings.append("Codex exact-head review state is CHANGES_REQUESTED.")
        return CodexDecision("COMPLETE", "FAIL", "Codex found material exact-head defect(s).", tuple(findings))
    if indeterminate:
        return CodexDecision(
            "COMPLETE",
            "INDETERMINATE",
            "Codex reported missing or conflicting required evidence.",
            tuple(indeterminate[:MAX_FINDINGS]),
        )

    clean: list[Mapping[str, Any]] = []
    for item in issue_comments:
        if not _trusted(item) or not _after(item, start):
            continue
        prefix = _clean_commit(item.get("body"))
        if prefix is not None and candidate_sha.startswith(prefix):
            clean.append(item)
        elif isinstance(item.get("body"), str) and item["body"].startswith(CLEAN_PREFIX):
            return CodexDecision("EXECUTION_UNAVAILABLE", None, "Codex clean-review evidence is bound to the wrong or missing head.")
    if len(clean) > 1:
        return CodexDecision("EXECUTION_UNAVAILABLE", None, "Multiple Codex clean-review signals are ambiguous.")
    if len(clean) == 1:
        return CodexDecision("COMPLETE", "PASS", "Codex found no material issues on the exact candidate.")
    return CodexDecision("PENDING", None, "No terminal trusted Codex verdict evidence is available yet.")
