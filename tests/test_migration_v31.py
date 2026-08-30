from datetime import datetime, timezone

from control_engine import migration_v31 as migration

NOW = datetime(2026, 8, 30, 22, 0, tzinfo=timezone.utc)


def wrapped_mission():
    return {
        "mission": {
            "mission_id": "M1",
            "mission_revision": "2026-08-16-r2",
            "repository": "o/r",
            "gaps": [
                {
                    "gap_id": "GAP-10",
                    "gap_state": "OPEN",
                    "depends_on": [],
                    "repository": "o/r",
                    "operation": "IMPLEMENTATION",
                    "acceptance": ["done"],
                    "integration_policy": "HOLD_AFTER_PASS",
                },
                {
                    "gap_id": "GAP-20",
                    "gap_state": "OPEN",
                    "depends_on": ["GAP-10"],
                    "repository": "o/r",
                    "operation": "IMPLEMENTATION",
                    "acceptance": ["next"],
                    "integration_policy": "HOLD_AFTER_PASS",
                },
            ],
        },
        "mission_contract_blob_sha": "1" * 40,
        "repository_authority_blob_sha": "2" * 40,
    }


def legacy_integration(gap="GAP-10", outcome="COMPLETED", status="TERMINAL"):
    root = f"MISSION-M1-2026-08-16-r2-{gap}"
    return {
        "lifecycle_model": "CONTROL_MINIMAL_CORE_V1",
        "task_id": root + "--ASSURE--INTEGRATE",
        "operation": "PROJECT_INTEGRATION",
        "repository": "o/r",
        "status": status,
        "outcome": outcome,
        "result_ref": f"control/worker-results/{root}.json",
        "principal_manual_relay_count": 0,
    }


def legacy_queue(*tasks):
    return {"version": "1.0", "principal_manual_relay_count": 0, "tasks": list(tasks)}


def test_migration_imports_only_completed_integration_for_current_mission_gap():
    q, facts = migration.migrate(
        legacy_queue(
            legacy_integration("GAP-10", "COMPLETED"),
            legacy_integration("GAP-20", "BLOCKED"),
            {"task_id": "MISSION-M1-2026-08-16-r2-GAP-20--ASSURE", "operation": "ASSURANCE", "status": "TERMINAL", "outcome": "PASS"},
        ),
        missions=[wrapped_mission()],
        now=NOW,
    )
    assert q["version"] == "3.1"
    assert q["tasks"] == []
    assert len(facts) == 1
    assert facts[0]["gap_id"] == "GAP-10"
    assert facts[0]["fact"] == migration.MIGRATION_FACT
    assert facts[0]["principal_manual_relay_count"] == 0


def test_blocked_executing_queued_and_assurance_only_never_become_satisfaction_facts():
    q, facts = migration.migrate(
        legacy_queue(
            legacy_integration("GAP-10", "BLOCKED"),
            legacy_integration("GAP-20", None, "EXECUTING"),
            {"task_id": "MISSION-M1-2026-08-16-r2-GAP-10", "operation": "IMPLEMENTATION", "status": "QUEUED", "outcome": None},
            {"task_id": "MISSION-M1-2026-08-16-r2-GAP-10--ASSURE", "operation": "ASSURANCE", "status": "TERMINAL", "outcome": "PASS"},
        ),
        missions=[wrapped_mission()],
        now=NOW,
    )
    assert facts == []
    assert q["tasks"] == []


def test_unmanaged_legacy_success_is_not_imported():
    unmanaged = {
        "lifecycle_model": "CONTROL_MINIMAL_CORE_V1",
        "task_id": "CONTROL-204-PR78--INTEGRATE",
        "operation": "PROJECT_INTEGRATION",
        "status": "TERMINAL",
        "outcome": "COMPLETED",
        "result_ref": "control/worker-results/control-204.json",
    }
    _, facts = migration.migrate(legacy_queue(unmanaged), missions=[wrapped_mission()], now=NOW)
    assert facts == []


def test_migration_is_idempotent_and_never_reintroduces_legacy_tasks():
    first, facts = migration.migrate(legacy_queue(legacy_integration()), missions=[wrapped_mission()], now=NOW)
    second, created = migration.migrate(first, missions=[wrapped_mission()], now=NOW)
    assert second == first
    assert created == []
    assert facts == second["migration_facts"]
    assert all(task.get("lifecycle_model") != "CONTROL_MINIMAL_CORE_V1" for task in second["tasks"])


def test_feed_uses_migration_fact_without_persisting_shadow_or_legacy_task():
    q, _ = migration.migrate(legacy_queue(legacy_integration("GAP-10")), missions=[wrapped_mission()], now=NOW)
    fed, created = migration.feed(q, missions=[wrapped_mission()], now=NOW)
    assert created == ["MISSION-M1-2026-08-16-r2-GAP-20"]
    assert len(fed["tasks"]) == 1
    assert fed["tasks"][0]["operation"] == "IMPLEMENTATION"
    assert all("_migration_shadow" not in task for task in fed["tasks"])
    assert all(task.get("operation") != "PROJECT_INTEGRATION" for task in fed["tasks"])


def test_fact_identity_is_exact_and_duplicate_free():
    q, _ = migration.migrate(legacy_queue(legacy_integration()), missions=[wrapped_mission()], now=NOW)
    assert migration.gap_satisfied_by_fact(q, "M1", "2026-08-16-r2", "GAP-10")
    assert not migration.gap_satisfied_by_fact(q, "M1", "2026-08-16-r2", "GAP-20")
