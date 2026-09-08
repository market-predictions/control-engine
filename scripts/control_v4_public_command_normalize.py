from __future__ import annotations

"""Normalize the two reviewed Control V4 public command wire framings.

The Scheduled Runner emits the command token followed by JSON on the next line,
while the strict protocol parser's internal framing uses one space. This adapter
changes only that separator and runs before any private capability is created.
"""

import os
from pathlib import Path


COMMAND_TOKENS = ("CONTROL_V4_RUNTIME_TICK", "CONTROL_V4_RUNTIME_EVENT")


class PublicCommandEnvelopeError(ValueError):
    pass


def normalize_public_command_envelope(body: str) -> str:
    if not isinstance(body, str):
        raise PublicCommandEnvelopeError("public command body invalid")

    for token in COMMAND_TOKENS:
        for separator in (" ", "\n"):
            prefix = token + separator
            if body.startswith(prefix):
                payload = body[len(prefix):]
                if not payload.startswith("{"):
                    raise PublicCommandEnvelopeError("public command payload framing invalid")
                return token + " " + payload

    raise PublicCommandEnvelopeError("unsupported public command envelope")


def main() -> int:
    raw = os.environ.get("CONTROL_V4_PUBLIC_COMMAND_RAW", "")
    output_path = os.environ.get("CONTROL_V4_NORMALIZED_COMMAND_PATH", "")
    if not output_path:
        raise SystemExit("normalized command path missing")
    try:
        normalized = normalize_public_command_envelope(raw)
    except PublicCommandEnvelopeError as exc:
        raise SystemExit("public command envelope invalid") from exc
    Path(output_path).write_text(normalized, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
