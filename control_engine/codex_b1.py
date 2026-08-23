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


def _request_candidate(item: dict[str, Any]) -> str | None:
    body = item.get("body")
    if not isinstance(body, str) or not body:
        return None
    lines = [line.strip() for line in body.splitlines()]
    if REQUEST_MARKER not in lines:
        return None
    for line in lines:
        if line.startswith("candidate_sha="):
            candidate = line.split("=", 1)[1].strip()
            return candidate if _valid_sha(candidate) else None
    return None


def _request_window(
    *,
    request_comment_id: int,
    candidate_sha: str,
    issue_comments: list[dict[str, Any]],
) -> tuple[datetime, datetime | None, bool]:
    if not isinstance(request_comment_id, int) or isinstance(request_comment_id, bool) or request_comment_id <= 0:
        raise CodexB1Error("request_comment_id must be a positive integer")

    current = next((item for item in issue_comments if item.get("id") == request_comment_id), None)
    if current is None:
        raise CodexB1Error("exact Codex request comment is absent from issue_comments")
    if _request_candidate(current) != candidate_sha:
        raise CodexB1Error("exact Codex request comment is not bound to candidate_sha")
    request_start = _parse_timestamp(current.get("created_at"))
    if request_start is None:
        raise CodexB1Error("exact Codex request comment has no valid created_at timestamp")

    later_requests: list[tuple[datetime, int]] = []
    for item in issue_comments:
        other_id = item.get("id")
        if other_id == request_comment_id or _request_candidate(item) != candidate_sha:
            continue
        if not isinstance(other_id, int) or isinstance(other_id, bool) or other_id <= 0:
            raise CodexB1Error("Codex request comment has an invalid id")
        other_time = _parse_timestamp(item.get("created_at"))
        if other_time is None:
            raise CodexB1Error("Codex request comment has no valid created_at timestamp")
        if other_id > request_comment_id:
            if other_time < request_start:
                raise CodexB1Error("Codex request comment chronology is inconsistent")
            later_requests.append((other_time, other_id))
        elif other_time > request_start:
            raise CodexB1Error("Codex request comment chronology is inconsistent")

    if not later_requests:
        return request_start, None, False
    request_end, _ = min(later_requests, key=lambda value: (value[0], value[1]))
    return request_start, request_end, request_end == request_start


def request_id(*, task_id: str, handover_id: str, candidate_sha: str) -> str:
    if not task_id or not handover_id or not _valid_sha(candidate_sha):
        raise CodexB1Error("Codex request identity is incomplete or invalid")
    raw = f"{task_id}\n{handover_id}\n{candidate_sha}\n".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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
    if any(not isinstance(item, str) or not item.strip() for item in acceptance_criteria):
        raise CodexB1Error("acceptance_criteria contains an invalid item")

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


def _commit(item: dict[str, Any]) -> str | None:
    for key in ("commit_id", "original_commit_id", "reviewed_commit"):
        value = item.get(key)
        if isinstance(value, str) and _valid_sha(value):
            return value
    return None


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


def classify_review_snapshot(
    *,
    candidate_sha: str,
    request_comment_id: int,
    reviews: list[dict[str, Any]],
    review_comments: list[dict[str, Any]],
    trigger_reactions: list[dict[str, Any]],
    issue_comments: list[dict[str, Any]],
) -> CodexReviewDecision:
    if not _valid_sha(candidate_sha):
        raise CodexB1Error("candidate_sha is invalid")
    for collection in (reviews, review_comments, trigger_reactions, issue_comments):
        if not isinstance(collection, list) or any(not isinstance(item, dict) for item in collection):
            raise CodexB1Error("Codex snapshot collections must contain objects")

    # Bind the review evidence to the exact GitHub request comment, not to a
    # caller-supplied lower timestamp. The next request for the same candidate
    # is an exclusive upper bound, preventing later same-head handshakes from
    # poisoning this request. Same-timestamp adjacent requests are ambiguous and
    # therefore fail closed instead of guessing ownership of review evidence.
    request_start, request_end, ambiguous_window = _request_window(
        request_comment_id=request_comment_id,
        candidate_sha=candidate_sha,
        issue_comments=issue_comments,
    )
    if ambiguous_window:
        return CodexReviewDecision(
            status="EXECUTION_UNAVAILABLE",
            verdict=None,
            summary="Adjacent Codex requests share a timestamp, so review ownership is ambiguous.",
            findings=(),
            reviewed_commit=None,
        )

    codex_reviews = [
        item
        for item in reviews
        if _is_codex(item) and _belongs_to_request(item, request_start, request_end)
    ]
    exact_reviews = [item for item in codex_reviews if _commit(item) == candidate_sha]
    stale_reviews = [item for item in codex_reviews if _commit(item) not in (None, candidate_sha)]

    exact_review_ids = {item.get("id") for item in exact_reviews if item.get("id") is not None}
    finding_records: list[tuple[str, bool]] = []
    for item in review_comments:
        if not _is_codex(item) or not _belongs_to_request(item, request_start, request_end):
            continue
        item_commit = _commit(item)
        review_id = item.get("pull_request_review_id")
        exact_commit_binding = item_commit == candidate_sha
        exact_review_binding = review_id in exact_review_ids if review_id is not None else False
        if not exact_commit_binding and not exact_review_binding:
            continue
        body = item.get("body")
        tagged_indeterminate = isinstance(body, str) and body.strip().startswith(INDETERMINATE_MARKER)
        finding = _bounded_finding(item)
        if finding:
            finding_records.append((finding, tagged_indeterminate))

    findings = [finding for finding, _ in finding_records]
    if len(findings) > MAX_FINDINGS:
        return CodexReviewDecision(
            status="EXECUTION_UNAVAILABLE",
            verdict=None,
            summary="Codex returned more findings than the bounded contract permits.",
            findings=(),
            reviewed_commit=candidate_sha if exact_reviews else None,
        )

    indeterminate = [finding for finding, tagged in finding_records if tagged]
    definite = [finding for finding, tagged in finding_records if not tagged]
    if definite:
        return CodexReviewDecision(
            status="COMPLETE",
            verdict="FAIL",
            summary=f"Codex deep review found {len(definite)} blocking finding(s).",
            findings=tuple(findings),
            reviewed_commit=candidate_sha,
        )
    if indeterminate:
        return CodexReviewDecision(
            status="COMPLETE",
            verdict="INDETERMINATE",
            summary="Codex deep review reported missing or conflicting required evidence.",
            findings=tuple(findings),
            reviewed_commit=candidate_sha,
        )

    # A clean PASS is accepted only from the Codex reaction on the exact trigger
    # comment. The caller fetches reactions for that comment ID, so historical
    # or later requests on the same candidate cannot satisfy this request.
    clean_reaction = any(
        _is_codex(item) and item.get("content") in {"+1", "thumbs_up"}
        for item in trigger_reactions
    )
    if clean_reaction:
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

    return CodexReviewDecision(
        status="PENDING",
        verdict=None,
        summary="No terminal Codex review evidence is present yet for the current request.",
        findings=(),
        reviewed_commit=candidate_sha if exact_reviews else None,
    )
