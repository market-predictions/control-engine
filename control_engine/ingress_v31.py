from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping


MARKER = "CONTROL_V3_1_A1_COMMAND_V1"
MAX_COMMAND_BYTES = 24_000
ALLOWED_RELEASE_REASONS = frozenset({"EXECUTION_UNAVAILABLE", "EXECUTION_ABORTED"})


class IngressError(ValueError):
    pass


@dataclass(frozen=True)
class A1Command:
    command: str
    task_id: str
    run_id: str | None = None
    result: Mapping[str, Any] | None = None
    reason: str | None = None


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or "\n" in value or "\r" in value:
        raise IngressError(f"{field} must be one non-empty trimmed line")
    return value


def _exact_keys(payload: Mapping[str, Any], expected: set[str]) -> None:
    if set(payload) != expected:
        raise IngressError("A1 command fields are not exact")


def parse_a1_command(body: str) -> A1Command:
    if not isinstance(body, str) or not body:
        raise IngressError("A1 command body is required")
    encoded = body.encode("utf-8")
    if len(encoded) > MAX_COMMAND_BYTES:
        raise IngressError("A1 command exceeds bounded size")

    first, separator, remainder = body.partition("\n")
    if first != MARKER or not separator or not remainder.strip():
        raise IngressError("A1 command marker or JSON payload is invalid")
    try:
        payload = json.loads(remainder)
    except json.JSONDecodeError as exc:
        raise IngressError("A1 command JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise IngressError("A1 command JSON must be an object")

    command = payload.get("command")
    if command == "CLAIM":
        _exact_keys(payload, {"command", "task_id"})
        return A1Command(command=command, task_id=_text(payload.get("task_id"), field="task_id"))

    if command == "RECORD":
        _exact_keys(payload, {"command", "task_id", "run_id", "result"})
        result = payload.get("result")
        if not isinstance(result, dict):
            raise IngressError("result must be an object")
        return A1Command(
            command=command,
            task_id=_text(payload.get("task_id"), field="task_id"),
            run_id=_text(payload.get("run_id"), field="run_id"),
            result=result,
        )

    if command == "RELEASE":
        _exact_keys(payload, {"command", "task_id", "run_id", "reason"})
        reason = _text(payload.get("reason"), field="reason")
        if reason not in ALLOWED_RELEASE_REASONS:
            raise IngressError("release reason is not allowed")
        return A1Command(
            command=command,
            task_id=_text(payload.get("task_id"), field="task_id"),
            run_id=_text(payload.get("run_id"), field="run_id"),
            reason=reason,
        )

    if command == "CODEX_START":
        _exact_keys(payload, {"command", "task_id"})
        return A1Command(command=command, task_id=_text(payload.get("task_id"), field="task_id"))

    raise IngressError("unsupported A1 command")


def command_json(command: A1Command) -> str:
    payload: dict[str, Any] = {"command": command.command, "task_id": command.task_id}
    if command.run_id is not None:
        payload["run_id"] = command.run_id
    if command.result is not None:
        payload["result"] = dict(command.result)
    if command.reason is not None:
        payload["reason"] = command.reason
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)
