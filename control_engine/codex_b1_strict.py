from __future__ import annotations

from typing import Any

from control_engine.codex_b1 import (
    CodexB1Error,
    CodexReviewDecision,
    build_review_request,
    classify_review_snapshot,
)


def _login(item: dict[str, Any]) -> str:
    user = item.get("user")
    if isinstance(user, dict) and isinstance(user.get("login"), str):
        return user["login"]
    author = item.get("author")
    if isinstance(author, dict) and isinstance(author.get("login"), str):
        return author["login"]
    value = item.get("user_login")
    return value if isinstance(value, str) else ""


def classify_trusted_review_snapshot(
    *,
    task_id: str,
    handover_id: str,
    candidate_sha: str,
    request_comment_id: int,
    acceptance_criteria: list[str],
    trusted_actuator_login: str,
    reviews: list[dict[str, Any]],
    review_comments: list[dict[str, Any]],
    trigger_reactions: list[dict[str, Any]],
    issue_comments: list[dict[str, Any]],
) -> CodexReviewDecision:
    """Strict production boundary for the non-authoritative Codex handshake.

    The low-level classifier only sees issue comments owned by the configured
    actuator. The exact trigger must also equal the canonical request body
    generated from the expected lineage and acceptance criteria. This keeps
    request ownership explicit and avoids deriving trust from arbitrary PR
    comment history.
    """
    if not isinstance(trusted_actuator_login, str) or not trusted_actuator_login.strip():
        raise CodexB1Error("trusted_actuator_login must be a non-empty GitHub login")
    if not isinstance(issue_comments, list) or any(not isinstance(item, dict) for item in issue_comments):
        raise CodexB1Error("issue_comments must contain objects")

    current = next((item for item in issue_comments if item.get("id") == request_comment_id), None)
    if current is None:
        raise CodexB1Error("exact Codex request comment is absent from issue_comments")
    if _login(current) != trusted_actuator_login:
        raise CodexB1Error("exact Codex request comment is not owned by the trusted actuator")

    expected_body = build_review_request(
        task_id=task_id,
        handover_id=handover_id,
        candidate_sha=candidate_sha,
        acceptance_criteria=acceptance_criteria,
    )
    if current.get("body") != expected_body:
        raise CodexB1Error("exact Codex request comment does not match the canonical request envelope")

    trusted_issue_comments = [
        item for item in issue_comments if _login(item) == trusted_actuator_login
    ]
    return classify_review_snapshot(
        task_id=task_id,
        handover_id=handover_id,
        candidate_sha=candidate_sha,
        request_comment_id=request_comment_id,
        reviews=reviews,
        review_comments=review_comments,
        trigger_reactions=trigger_reactions,
        issue_comments=trusted_issue_comments,
    )
