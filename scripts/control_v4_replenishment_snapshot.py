from __future__ import annotations

"""Read-only replenishment discovery for a successful Control V4 NO_WORK result.

This module does not mutate private authority, runtime state, target repositories,
or the canonical queue. It reuses the existing owner-admin replenishment
calculation and exposes only opaque, public-safe approval material. Canonical
queue tasks still require the existing owner-authored replenishment approval and
ACTIVATE_ROOT_CANDIDATE path.
"""

import json
import os
from typing import Any, Mapping

from control_engine.v4_runtime_protocol import (
    RESULT_PROTOCOL_ID,
    RuntimeProtocolError,
    assert_public_safe,
    strict_json_object,
)
from scripts import control_v4_owner_admin as owner_admin
from scripts import control_v4_runtime_carrier as runtime_carrier


_NO_ELIGIBLE = "project has no currently eligible unmaterialized OPEN gaps"


class ReplenishmentSnapshotError(RuntimeError):
    pass


def replenishment_snapshots_v4(
    queue: Mapping[str, Any],
    bundle: Any,
) -> list[dict[str, Any]]:
    """Return exact opaque project snapshots without changing queue or authority."""
    repositories = sorted(
        {
            mission.get("repository")
            for mission in bundle.missions
            if isinstance(mission, Mapping) and isinstance(mission.get("repository"), str)
        }
    )
    snapshots: list[dict[str, Any]] = []
    for repository in repositories:
        try:
            payload = owner_admin.replenishment_approval_payload_v4(queue, bundle, repository)
        except owner_admin.OwnerAdminError as exc:
            if str(exc) == _NO_ELIGIBLE:
                continue
            raise ReplenishmentSnapshotError("replenishment discovery failed closed") from exc
        snapshot = dict(payload)
        snapshot["approval_command"] = owner_admin.format_replenishment_approval_v4(payload)
        assert_public_safe(snapshot)
        snapshots.append(snapshot)
    return snapshots


def enrich_no_work_result_v4(
    result: Mapping[str, Any],
    queue: Mapping[str, Any],
    bundle: Any,
) -> dict[str, Any]:
    """Attach proposals only to an already-successful canonical NO_WORK result."""
    enriched = dict(result)
    if enriched.get("protocol") != RESULT_PROTOCOL_ID or enriched.get("result") != "NO_WORK":
        assert_public_safe(enriched)
        return enriched
    snapshots = replenishment_snapshots_v4(queue, bundle)
    if snapshots:
        enriched["replenishment_proposals"] = snapshots
    assert_public_safe(enriched)
    return enriched


def _set_output(result: Mapping[str, Any]) -> None:
    text = json.dumps(dict(result), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print(text)
        return
    with open(output_path, "a", encoding="utf-8") as output:
        output.write(f"result_json={text}\n")


def main() -> int:
    raw_result = os.environ.get("CONTROL_V4_CARRIER_RESULT", "")
    try:
        result = strict_json_object(raw_result)
        assert_public_safe(result)
        if result.get("protocol") != RESULT_PROTOCOL_ID:
            raise RuntimeProtocolError("carrier result protocol invalid")
        if result.get("result") != "NO_WORK":
            _set_output(result)
            return 0

        state = runtime_carrier._load_current()
        bundle = runtime_carrier._load_authority_bundle(state["main_sha"])
        enriched = enrich_no_work_result_v4(result, state["queue"], bundle)
        _set_output(enriched)
        return 0
    except (RuntimeProtocolError, ReplenishmentSnapshotError, owner_admin.OwnerAdminError, runtime_carrier.CarrierError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
