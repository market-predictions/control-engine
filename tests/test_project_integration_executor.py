import pytest

from scripts import project_integration_executor as integration


REPO = "market-predictions/weekly-etf-eu"
CANDIDATE = "c76ae6444866d00ff9ed8eece71acf5578eae430"
BASE = "5cc712582f86a51951cf57c55992f0ddc49a6ff1"


def _handover() -> dict:
    return {
        "context_refs": [
            {
                "kind": "source",
                "locator": f"https://github.com/{REPO}/commit/{BASE}",
                "immutable_ref": BASE,
            },
            {
                "kind": "source",
                "locator": "pricing/ucits_price_qualification_policy.py",
                "immutable_ref": BASE,
            },
            {
                "kind": "raw_ci",
                "locator": f"https://github.com/{REPO}/actions/runs/32226243055",
                "immutable_ref": CANDIDATE,
            },
            {
                "kind": "raw_ci",
                "locator": f"https://github.com/{REPO}/actions/runs/32226242977",
                "immutable_ref": CANDIDATE,
            },
        ]
    }


def test_trusted_base_sha_requires_exact_repository_commit_binding() -> None:
    assert integration._trusted_base_sha(REPO, _handover()) == BASE

    malformed = _handover()
    malformed["context_refs"][0]["locator"] = "https://github.com/other/repo/commit/" + BASE
    with pytest.raises(integration.IntegrationBlocked):
        integration._trusted_base_sha(REPO, malformed)


def test_trusted_base_sha_rejects_ambiguous_base_identity() -> None:
    handover = _handover()
    other = "a" * 40
    handover["context_refs"].append(
        {
            "kind": "source",
            "locator": f"https://github.com/{REPO}/commit/{other}",
            "immutable_ref": other,
        }
    )
    with pytest.raises(integration.IntegrationBlocked):
        integration._trusted_base_sha(REPO, handover)


def test_ci_run_ids_are_exact_candidate_and_repository_bound() -> None:
    assert integration._ci_run_ids(REPO, CANDIDATE, _handover()) == [32226242977, 32226243055]

    wrong_candidate = _handover()
    wrong_candidate["context_refs"][2]["immutable_ref"] = BASE
    with pytest.raises(integration.IntegrationBlocked):
        integration._ci_run_ids(REPO, CANDIDATE, wrong_candidate)

    wrong_repo = _handover()
    wrong_repo["context_refs"][2]["locator"] = "https://github.com/other/repo/actions/runs/32226243055"
    with pytest.raises(integration.IntegrationBlocked):
        integration._ci_run_ids(REPO, CANDIDATE, wrong_repo)


def test_reconcile_write_scope_admits_only_flat_project_intake_json() -> None:
    allowed = {"control/DISPATCH_QUEUE.json", "control/DISPATCH_RUNS.json"}
    changed = {
        "control/project-intake/CONTROL_193_PR194_ASSURE_R3.json",
        "control/project-intake/nested/escape.json",
        "control/project-intake/not-json.txt",
        "control/worker-results/forbidden.json",
    }
    extended = integration._extend_reconcile_write_scope(allowed, changed)
    assert extended == {
        "control/DISPATCH_QUEUE.json",
        "control/DISPATCH_RUNS.json",
        "control/project-intake/CONTROL_193_PR194_ASSURE_R3.json",
    }


def test_executor_is_pinned_and_never_contains_paid_or_model_provider_path() -> None:
    source = integration.Path(integration.__file__).read_text(encoding="utf-8")
    assert integration.CONTROL_CODE_SHA == "265c6e607c3735f6e98bb74d1f1ba6162e5e9b79"
    assert "CONTROL_CLOUDFLARE" not in source
    assert "merge_method\": \"merge" in source
    assert '"sha": candidate_sha' in source
    assert "evaluate_claimed_project_integration" in source
    assert "--force" not in source
