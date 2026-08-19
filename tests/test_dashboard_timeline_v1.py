import pytest

from control_engine.timeline import TimelineContractError, build_render_model


def registry():
    return {"version":"1.0.0","projects":[
        {"project_id":"alpha","display_name":"Alpha","repository":"example/alpha","aliases":["a"],"color":"#112233"},
        {"project_id":"beta","display_name":"Beta","repository":"example/beta","aliases":["b"],"color":"#445566"},
    ]}


def event(event_id, project="alpha", at="2026-08-01T10:00:00Z", event_class="PROCESS", event_type="REPAIR", value_class=None, points=0, lineage="cap-1", scope=None, supersedes=None, restores=None, sources=None):
    return {
        "version":"1.1","event_id":event_id,"project_id":project,"occurred_at":at,
        "event_class":event_class,"event_type":event_type,"value_class":value_class,
        "points_delta":points,"capability_lineage_id":lineage,"value_scope_ref":scope,
        "summary":"synthetic event","mapping_rationale":"synthetic contract regression",
        "sources":sources or ["github:example/repo#1"],
        "supersedes_event_id":supersedes,"restores_event_id":restores,
    }


def retained(event_id, at, value_class="CAPABILITY_VALIDATED", points=2, lineage="cap-1", scope="SYNTHETIC::SCOPE", event_type="VALIDATION_PASS", restores=None):
    return event(event_id, at=at, event_class="RETAINED_VALUE", event_type=event_type, value_class=value_class, points=points, lineage=lineage, scope=scope, restores=restores)


def correction(event_id, at, target, value_class="CAPABILITY_VALIDATED", points=-2, lineage="cap-1", scope="SYNTHETIC::SCOPE"):
    return event(event_id, at=at, event_class="CORRECTION", event_type="CORRECTION", value_class=value_class, points=points, lineage=lineage, scope=scope, supersedes=target)


def series(model, project="alpha"):
    return {item["project_id"]: item for item in model["series"]}[project]


def test_portfolio_is_cumulative_unormalized_and_stable_color():
    model = build_render_model(registry(), [
        retained("foundation", "2026-08-01T10:00:00Z", "FOUNDATION", 2, scope="SYNTHETIC::FOUNDATION", event_type="CONTROL_ADOPTION"),
        event("repair", at="2026-08-02T10:00:00Z"),
        retained("beta-int", "2026-08-03T10:00:00Z", "INTEGRATED_CAPABILITY", 3, lineage="beta-cap", scope="SYNTHETIC::BETA", event_type="INTEGRATED" ) | {"project_id":"beta"},
    ])
    assert model["view"] == "portfolio"
    assert model["y_axis"] == "Cumulative Retained Progress points"
    assert model["normalization"] == "none"
    assert series(model)["display_color"] == "#112233"
    assert [p["cumulative_retained_progress"] for p in series(model)["points"]] == [2, 2]


def test_focused_view_uses_same_model_and_grays_context():
    model = build_render_model(registry(), [retained("foundation", "2026-08-01T10:00:00Z", "FOUNDATION", 2, scope="SYNTHETIC::FOUNDATION", event_type="CONTROL_ADOPTION")], "alpha")
    assert series(model)["display_color"] == "#112233"
    assert series(model)["line_weight"] == 3.0
    assert series(model, "beta")["display_color"] == "#D1D5DB"


def test_ten_process_events_make_ten_dots_and_zero_progress():
    events = [event(f"p{i}", at=f"2026-08-{i+1:02d}T10:00:00Z") for i in range(10)]
    points = series(build_render_model(registry(), events))["points"]
    assert len(points) == 10
    assert all(p["points_delta"] == 0 and p["cumulative_retained_progress"] == 0 for p in points)


def test_process_cannot_mint_progress():
    with pytest.raises(TimelineContractError, match="PROCESS event must have zero points"):
        build_render_model(registry(), [event("bad", points=2)])


def test_fixed_weight_is_enforced():
    with pytest.raises(TimelineContractError, match="wrong point weight"):
        build_render_model(registry(), [retained("bad", "2026-08-01T10:00:00Z", "INTEGRATED_CAPABILITY", 2)])


def test_same_lineage_class_cannot_double_credit():
    with pytest.raises(TimelineContractError, match="duplicate active retained credit"):
        build_render_model(registry(), [retained("one", "2026-08-01T10:00:00Z"), retained("two", "2026-08-02T10:00:00Z")])


def test_same_scope_cannot_mint_again_under_renamed_lineage():
    with pytest.raises(TimelineContractError, match="duplicate active value-scope credit"):
        build_render_model(registry(), [retained("one", "2026-08-01T10:00:00Z", lineage="v1"), retained("two", "2026-08-02T10:00:00Z", lineage="v2")])


def test_correction_and_exact_restoration_do_not_double_count():
    events = [
        retained("foundation", "2026-08-01T10:00:00Z", "FOUNDATION", 2, scope="SYNTHETIC::FOUNDATION", event_type="CONTROL_ADOPTION"),
        retained("credit", "2026-08-02T10:00:00Z"),
        correction("revoke", "2026-08-03T10:00:00Z", "credit"),
        event("repair", at="2026-08-04T10:00:00Z"),
        retained("restore", "2026-08-05T10:00:00Z", restores="revoke"),
    ]
    assert [p["cumulative_retained_progress"] for p in series(build_render_model(registry(), events))["points"]] == [2, 4, 2, 2, 4]


def test_restoration_requires_latest_correction():
    with pytest.raises(TimelineContractError, match="restoration must reference latest correction"):
        build_render_model(registry(), [retained("credit", "2026-08-01T10:00:00Z"), correction("revoke", "2026-08-02T10:00:00Z", "credit"), retained("restore", "2026-08-03T10:00:00Z")])


def test_lineage_rename_cannot_evade_correction_history():
    events = [retained("credit", "2026-08-01T10:00:00Z", lineage="v1"), correction("revoke", "2026-08-02T10:00:00Z", "credit", lineage="v1"), retained("repair", "2026-08-03T10:00:00Z", lineage="v2", restores="revoke")]
    with pytest.raises(TimelineContractError, match="correction lineage/scope history divergence"):
        build_render_model(registry(), events)


def test_untrusted_source_and_unknown_project_fail_closed():
    with pytest.raises(TimelineContractError, match="non-authoritative source"):
        build_render_model(registry(), [event("bad", sources=["chat:memory"])])
    with pytest.raises(TimelineContractError, match="unknown project_id"):
        build_render_model(registry(), [event("bad-project", project="unknown")])


def test_duplicate_alias_across_projects_fails_closed():
    bad = registry(); bad["projects"][1]["aliases"] = ["alpha"]
    with pytest.raises(TimelineContractError, match="duplicate project alias across projects"):
        build_render_model(bad, [])
