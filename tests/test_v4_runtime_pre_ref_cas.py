from pathlib import Path

from scripts import control_v4_runtime_carrier as carrier


def test_writer_defers_optional_authority_fence_until_after_git_object_construction():
    text = Path("scripts/control_v4_runtime_carrier.py").read_text(encoding="utf-8")
    writer = text.split("def _write_queue_exact(", 1)[1].split("def _assert_public_target_repository", 1)[0]

    assert writer.index('f"repos/{PRIVATE_REPOSITORY}/git/blobs"') < writer.index(
        'f"repos/{PRIVATE_REPOSITORY}/git/commits"'
    )
    assert writer.index('f"repos/{PRIVATE_REPOSITORY}/git/commits"') < writer.index("_update_refs_exact(")
    assert "pre_ref_cas=pre_ref_cas" in writer


def test_pre_ref_cas_hook_runs_immediately_before_command_freshness_and_graphql(monkeypatch):
    order = []
    monkeypatch.setenv("CONTROL_PLANE_TOKEN", "inert-test-token")

    monkeypatch.setattr(
        carrier,
        "_assert_current_command_fresh_at_ref_cas",
        lambda _queue: order.append("command-fresh"),
    )

    def fake_request(url, **kwargs):
        assert url == carrier.GRAPHQL
        assert kwargs["method"] == "POST"
        order.append("graphql-updateRefs")
        return {"data": {"updateRefs": {"clientMutationId": "test"}}}

    monkeypatch.setattr(carrier, "_request_json", fake_request)

    carrier._update_refs_exact(
        repository_node_id="repo-node",
        main_oid="a" * 40,
        runtime_before_oid="b" * 40,
        runtime_after_oid="c" * 40,
        client_id="test",
        source_queue={"tasks": []},
        pre_ref_cas=lambda: order.append("authority-fence"),
    )

    assert order == ["authority-fence", "command-fresh", "graphql-updateRefs"]
