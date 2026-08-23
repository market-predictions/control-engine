from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from dataclasses import dataclass
from typing import Any

PROTOCOL_ID = "CONTROL_CODEX_DEEP_B1_V1"
REQUEST_MARKER = "CONTROL_B1_CODEX_DEEP_REQUEST_V1"
INDETERMINATE_MARKER = "CONTROL_B1_INDETERMINATE:"
CODEX_BOT_LOGINS = frozenset({"chatgpt-codex-connector", "chatgpt-codex-connector[bot]"})
TERMINAL_REVIEW_STATES = frozenset({"COMMENTED", "APPROVED", "CHANGES_REQUESTED", "DISMISSED"})
MAX_ACCEPTANCE_CRITERIA = 40
MAX_REQUEST_BYTES = 12_000
MAX_FINDINGS = 40
MAX_FINDING_BYTES = 4_000


class CodexB1Error(ValueError):
    pass


@dataclass(frozen=True)
class CodexReviewDecision:
    status: str
    verdict: str | None
    summary: str
    findings: tuple[str, ...]
    reviewed_commit: str | None

    @property
    def complete(self) -> bool:
        return self.status == "COMPLETE"


def _valid_sha(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{40}", value or ""))


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _event_timestamp(item: dict[str, Any]) -> datetime | None:
    for key in ("submitted_at", "created_at"):
        parsed = _parse_timestamp(item.get(key))
        if parsed is not None:
            return parsed
    return None


def _belongs_to_request(
    item: dict[str, Any],
    request_start: datetime,
    request_end: datetime | None,
) -> bool:
    timestamp = _event_timestamp(item)
    if timestamp is None or timestamp < request_start:
        return False
    return request_end is None or timestamp < request_end


def request_id(*, task_id: str, handover_id: str, candidate_sha: str) -> str:
    if not task_id or not handover_id or not _valid_sha(candidate_sha):
        raise CodexB1Error("Codex request identity is incomplete or invalid")
    raw = f"{task_id}\n{handover_id}\n{candidate_sha}\n".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _request_candidate(item: dict[str, Any]) -> str | None:
    body = item.get("body")
    if not isinstance(body, str) or not body:
        return None
    raw_lines = body.splitlines()
    if not raw_lines or raw_lines[0] != "@codex review":
        return None
    lines = [line.strip() for line in raw_lines]
    if REQUEST_MARKER not in lines:
        return None
    candidate_lines = [line for line in lines if line.startswith("candidate_sha=")]
    if len(candidate_lines) != 1:
        return None
    candidate = candidate_lines[0].split("=", 1)[1].strip()
    return candidate if _valid_sha(candidate) else None


def _request_identity(item: dict[str, Any]) -> tuple[str, str, str, str] | None:
    body = item.get("body")
    if not isinstance(body, str) or not body:
        return None
    raw_lines = body.splitlines()
    if not raw_lines or raw_lines[0] != "@codex review":
        return None
    lines = [line.strip() for line in raw_lines]
    if REQUEST_MARKER not in lines:
        return None

    values: dict[str, str] = {}
    for key in ("request_id", "task_id", "handover_id", "candidate_sha"):
        matches = [line.split("=", 1)[1].strip() for line in lines if line.startswith(f"{key}=")]
        if len(matches) != 1 or not matches[0]:
            return None
        values[key] = matches[0]

    candidate_sha = values["candidate_sha"]
    if not _valid_sha(candidate_sha) or not re.fullmatch(r"[0-9a-f]{64}", values["request_id"]):
        return None
    expected = request_id(
        task_id=values["task_id"],
        handover_id=values["handover_id"],
        candidate_sha=candidate_sha,
    )
    if values["request_id"] != expected:
        return None
    return values["request_id"], values["task_id"], values["handover_id"], candidate_sha


def _request_window(
    *,
    task_id: str,
    handover_id: str,
    request_comment_id: int,
    candidate_sha: str,
    issue_comments: list[dict[str, Any]],
) -> tuple[datetime, datetime | None, bool, bool]:
    if not isinstance(request_comment_id, int) or isinstance(request_comment_id, bool) or request_comment_id <= 0:
        raise CodexB1Error("request_comment_id must be a positive integer")
    if not task_id or not handover_id:
        raise CodexB1Error("expected Codex request identity is incomplete")

    current = next((item for item in issue_comments if item.get("id") == request_comment_id), None)
    if current is None:
        raise CodexB1Error("exact Codex request comment is absent from issue_comments")
    expected_identity = (
        request_id(task_id=task_id, handover_id=handover_id, candidate_sha=candidate_sha),
        task_id,
        handover_id,
        candidate_sha,
    )
    if _request_identity(current) != expected_identity:
        raise CodexB1Error("exact Codex request comment is not bound to the expected full request identity")
    request_start = _parse_timestamp(current.get("created_at"))
    if request_start is None:
        raise CodexB1Error("exact Codex request comment has no valid created_at timestamp")

    duplicate_same_candidate = False
    has_prior_request = False
    for item in issue_comments:
        other_id = item.get("id")
        if other_id == request_comment_id:
            continue
        other_identity = _request_identity(item)
        if other_identity is None or other_identity[3] != candidate_sha:
            continue
        if not isinstance(other_id, int) or isinstance(other_id, bool) or other_id <= 0:
            raise CodexB1Error("Codex request comment has an invalid id")
        other_time = _parse_timestamp(item.get("created_at"))
        if other_time is None:
            raise CodexB1Error("Codex request comment has no valid created_at timestamp")
        duplicate_same_candidate = True
        if other_id < request_comment_id:
            has_prior_request = True
        if other_id > request_comment_id and other_time < request_start:
            raise CodexB1Error("Codex request comment chronology is inconsistent")
        if other_id < request_comment_id and other_time > request_start:
            raise CodexB1Error("Codex request comment chronology is inconsistent")

    if duplicate_same_candidate:
        return request_start, None, True, has_prior_request
    return request_start, None, False, False


def build_review_request(
    *,
    task_id: str,
    handover_id: str,
    candidate_sha: str,
    acceptance_criteria: list[str],
) -> str:
    rid = request_id(task_id=task_id, handover_id=handover_id, candidate_sha=candidate_sha)
    if not isinstance(acceptance_criteria, list) or not acceptance_criteria:
        raise CodexB1Error("acceptance_criteria must be a non-empty list")
    if len(acceptance_criteria) > MAX_ACCEPTANCE_CRITERIA:
        raise CodexB1Error("too many acceptance criteria for bounded Codex review")
    if any(
        not isinstance(item, str)
        or not item.strip()
        or len(item.splitlines()) != 1
        or item != item.splitlines()[0]
        for item in acceptance_criteria
    ):
        raise CodexB1Error("acceptance_criteria contains an invalid or multiline item")

    criteria = "\n".join(f"- {item.strip()}" for item in acceptance_criteria)
    body = (
        "@codex review\n\n"
        "Act only as an independent read-only deep B1 reviewer for the exact current PR head. "
        "Do not modify code or PR metadata. Review the diff/code against the bounded acceptance criteria below. "
        f"If required evidence is genuinely missing or conflicting, prefix the relevant review finding with `{INDETERMINATE_MARKER}`. "
        "Otherwise report concrete defects as normal review findings. No finding means the bounded criteria are supported by the review.\n\n"
        f"{REQUEST_MARKER}\n"
        f"request_id={rid}\n"
        f"task_id={task_id}\n"
        f"handover_id={handover_id}\n"
        f"candidate_sha={candidate_sha}\n\n"
        "Acceptance criteria:\n"
        f"{criteria}\n"
    )
    if len(body.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise CodexB1Error("Codex review request exceeds bounded budget")
    return body


def _login(item: dict[str, Any]) -> str:
    user = item.get("user")
    if isinstance(user, dict) and isinstance(user.get("login"), str):
        return user["login"]
    value = item.get("user_login")
    return value if isinstance(value, str) else ""


def _is_codex(item: dict[str, Any]) -> bool:
    return _login(item) in CODEX_BOT_LOGINS


def _review_is_terminal(item: dict[str, Any]) -> bool:
    if item.get("state") not in TERMINAL_REVIEW_STATES:
        return False
    return _parse_timestamp(item.get("submitted_at")) is not None


def _commit(item: dict[str, Any]) -> str | None:
    present_values: list[str] = []
    for key in ("commit_id", "original_commit_id", "reviewed_commit"):
        if key not in item:
            continue
        value = item.get(key)
        if not isinstance(value, str) or not _valid_sha(value):
            return ""
        present_values.append(value)
    if not present_values:
        return None
    if len(set(present_values)) != 1:
        return ""
    return present_values[0]


def _bounded_finding(item: dict[str, Any]) -> str | None:
    body = item.get("body")
    if not isinstance(body, str) or not body.strip():
        return None
    raw = body.strip()
    encoded = raw.encode("utf-8")
    if len(encoded) > MAX_FINDING_BYTES:
        raw = encoded[:MAX_FINDING_BYTES].decode("utf-8", errors="ignore").rstrip() + "…"
    path = item.get("path")
    line = item.get("line") or item.get("original_line")
    location = ""
    if isinstance(path, str) and path:
        location = path
        if isinstance(line, int):
            location += f":{line}"
        location += ": "
    return location + raw


def _bounded_records(
    records: list[tuple[str, bool]],
    *,
    preserve_definite: bool,
) -> tuple[str, ...]:
    bounded = list(records[:MAX_FINDINGS])
    if preserve_definite and bounded and not any(not tagged for _, tagged in bounded):
        first_definite = next((record for record in records if not record[1]), None)
        if first_definite is not None:
            bounded[-1] = first_definite
    return tuple(finding for finding, _ in bounded)


def classify_review_snapshot(
    *,
    task_id: str,
    handover_id: str,
    candidate_sha: str,
    request_comment_id: int,
    reviews: list[dict[str, Any]],
    review_comments: list[dict[str, Any]],
    trigger_reactions: list[dict[str, Any]],
    issue_comments: list[dict[str, Any]],
) -> CodexReviewDecision:
    if not _valid_sha(candidate_sha):
        raise CodexB1Error("candidate_sha is invalid")
    if not task_id or not handover_id:
        raise CodexB1Error("expected Codex request identity is incomplete")
    for collection in (reviews, review_comments, trigger_reactions, issue_comments):
        if not isinstance(collection, list) or any(not isinstance(item, dict) for item in collection):
            raise CodexB1Error("Codex snapshot collections must contain objects")

    request_start, request_end, ambiguous_window, has_prior_request = _request_window(
        task_id=task_id,
        handover_id=handover_id,
        request_comment_id=request_comment_id,
        candidate_sha=candidate_sha,
        issue_comments=issue_comments,
    )
    if ambiguous_window:
        return CodexReviewDecision(
            status="EXECUTION_UNAVAILABLE",
            verdict=None,
            summary="Multiple valid Codex requests target the same candidate, so exact review ownership is ambiguous.",
            findings=(),
            reviewed_commit=None,
        )

    codex_reviews = [
        item
        for item in reviews
        if _is_codex(item) and _belongs_to_request(item, request_start, request_end)
    ]
    nonterminal_reviews = [
        item
        for item in reviews
        if _is_codex(item)
        and not _review_is_terminal(item)
        and (
            _event_timestamp(item) is None
            or _belongs_to_request(item, request_start, request_end)
        )
    ]
    nonterminal_review_evidence = bool(nonterminal_reviews)
    terminal_reviews = [item for item in codex_reviews if _review_is_terminal(item)]
    exact_reviews = [item for item in terminal_reviews if _commit(item) == candidate_sha]
    stale_reviews = [item for item in terminal_reviews if _commit(item) not in (None, candidate_sha)]

    exact_review_ids = {item.get("id") for item in exact_reviews if item.get("id") is not None}
    finding_records: list[tuple[str, bool]] = []
    nonterminal_comment_evidence = False
    for item in review_comments:
        if not _is_codex(item) or not _belongs_to_request(item, request_start, request_end):
            continue
        item_commit = _commit(item)
        review_id = item.get("pull_request_review_id")
        if review_id not in exact_review_ids:
            if item_commit in (None, candidate_sha):
                nonterminal_comment_evidence = True
            continue
        if item_commit is not None and item_commit != candidate_sha:
            continue
        body = item.get("body")
        tagged_indeterminate = isinstance(body, str) and body.startswith(INDETERMINATE_MARKER)
        finding = _bounded_finding(item)
        if finding:
            finding_records.append((finding, tagged_indeterminate))

    indeterminate = [finding for finding, tagged in finding_records if tagged]
    definite = [finding for finding, tagged in finding_records if not tagged]
    changes_requested = [item for item in exact_reviews if item.get("state") == "CHANGES_REQUESTED"]
    if definite or changes_requested:
        failure_records = list(finding_records)
        if changes_requested:
            failure_records.append(("Codex terminal exact-head review state is CHANGES_REQUESTED.", False))
        blocking_count = len(definite) + len(changes_requested)
        return CodexReviewDecision(
            status="COMPLETE",
            verdict="FAIL",
            summary=f"Codex deep review found {blocking_count} blocking finding(s).",
            findings=_bounded_records(failure_records, preserve_definite=True),
            reviewed_commit=candidate_sha,
        )
    if indeterminate:
        return CodexReviewDecision(
            status="COMPLETE",
            verdict="INDETERMINATE",
            summary="Codex deep review reported missing or conflicting required evidence.",
            findings=_bounded_records(finding_records, preserve_definite=False),
            reviewed_commit=candidate_sha,
        )
    if nonterminal_review_evidence or nonterminal_comment_evidence:
        return CodexReviewDecision(
            status="PENDING",
            verdict=None,
            summary="Codex review evidence is not yet terminal for the exact current request.",
            findings=(),
            reviewed_commit=None,
        )

    clean_reaction = any(
        _is_codex(item) and item.get("content") in {"+1", "thumbs_up"}
        for item in trigger_reactions
    )
    if clean_reaction and exact_reviews:
        return CodexReviewDecision(
            status="COMPLETE",
            verdict="PASS",
            summary="Codex deep review completed without findings.",
            findings=(),
            reviewed_commit=candidate_sha,
        )

    if stale_reviews and not exact_reviews:
        return CodexReviewDecision(
            status="EXECUTION_UNAVAILABLE",
            verdict=None,
            summary="Only stale Codex review evidence is present for the current request.",
            findings=(),
            reviewed_commit=_commit(stale_reviews[-1]),
        )

    if clean_reaction:
        return CodexReviewDecision(
            status="PENDING",
            verdict=None,
            summary="Clean Codex reaction is present, but no terminal exact-head review is visible yet.",
            findings=(),
            reviewed_commit=None,
        )

    return CodexReviewDecision(
        status="PENDING",
        verdict=None,
        summary="No terminal Codex review evidence is present yet for the current request.",
        findings=(),
        reviewed_commit=candidate_sha if exact_reviews else None,
    )
