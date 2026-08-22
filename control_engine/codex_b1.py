from __future__ import annotations

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
    reviews: list[dict[str, Any]],
    review_comments: list[dict[str, Any]],
    trigger_reactions: list[dict[str, Any]],
    issue_comments: list[dict[str, Any]] | None = None,
) -> CodexReviewDecision:
    if not _valid_sha(candidate_sha):
        raise CodexB1Error("candidate_sha is invalid")
    for collection in (reviews, review_comments, trigger_reactions):
        if not isinstance(collection, list) or any(not isinstance(item, dict) for item in collection):
            raise CodexB1Error("Codex snapshot collections must contain objects")
    if issue_comments is None:
        issue_comments = []
    if not isinstance(issue_comments, list) or any(not isinstance(item, dict) for item in issue_comments):
        raise CodexB1Error("issue_comments must contain objects")

    codex_reviews = [item for item in reviews if _is_codex(item)]
    exact_reviews = [item for item in codex_reviews if _commit(item) == candidate_sha]
    stale_reviews = [item for item in codex_reviews if _commit(item) not in (None, candidate_sha)]

    exact_review_ids = {item.get("id") for item in exact_reviews if item.get("id") is not None}
    finding_records: list[tuple[str, bool]] = []
    for item in review_comments:
        if not _is_codex(item):
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
    # issue comments cannot satisfy a later request for a different lineage.
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
            summary="Only stale Codex review evidence is present.",
            findings=(),
            reviewed_commit=_commit(stale_reviews[-1]),
        )

    return CodexReviewDecision(
        status="PENDING",
        verdict=None,
        summary="No terminal Codex review evidence is present yet.",
        findings=(),
        reviewed_commit=candidate_sha if exact_reviews else None,
    )
