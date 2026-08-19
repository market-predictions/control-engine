import json
from pathlib import Path

import pytest

from control_engine.bundle import BundleContractError, git_blob_sha, validate_bundle

ROOT = Path(__file__).parents[1]


def test_repository_bundle_matches_exact_checked_out_bytes():
    bundle = json.loads((ROOT / "ENGINE_BUNDLE_V1.json").read_text(encoding="utf-8"))
    validated = validate_bundle(bundle, ROOT)
    assert validated["consumer_ref_policy"] == "EXACT_COMMIT_SHA_ONLY"


def test_changed_bytes_fail_blob_binding(tmp_path):
    target = tmp_path / "module.py"
    target.write_text("print('changed')\n", encoding="utf-8")
    bundle = {
        "schema_version": "1.0",
        "bundle_id": "CONTROL_ENGINE_BUNDLE_V1",
        "engine_repository": "market-predictions/control-engine",
        "private_data_policy": "NO_PRIVATE_RUNTIME_STATE",
        "consumer_ref_policy": "EXACT_COMMIT_SHA_ONLY",
        "files": [{"module_id":"x","role":"implementation","path":"module.py","git_blob_sha":"0" * 40}],
    }
    with pytest.raises(BundleContractError, match="bundle blob mismatch"):
        validate_bundle(bundle, tmp_path)


def test_git_blob_hash_is_content_and_length_bound():
    assert git_blob_sha(b"abc") != git_blob_sha(b"abc\n")
    assert len(git_blob_sha(b"abc")) == 40


def test_path_traversal_fails_closed(tmp_path):
    bundle = {
        "schema_version": "1.0",
        "bundle_id": "CONTROL_ENGINE_BUNDLE_V1",
        "engine_repository": "market-predictions/control-engine",
        "private_data_policy": "NO_PRIVATE_RUNTIME_STATE",
        "consumer_ref_policy": "EXACT_COMMIT_SHA_ONLY",
        "files": [{"module_id":"x","role":"implementation","path":"../private.json","git_blob_sha":"0" * 40}],
    }
    with pytest.raises(BundleContractError, match="invalid bundle path"):
        validate_bundle(bundle, tmp_path)


def test_weakened_or_floating_policy_fails_closed(tmp_path):
    bundle = json.loads((ROOT / "ENGINE_BUNDLE_V1.json").read_text(encoding="utf-8"))
    bundle["consumer_ref_policy"] = "MAIN_ALLOWED"
    with pytest.raises(BundleContractError, match="floating consumer ref policy forbidden"):
        validate_bundle(bundle, ROOT)

    bundle = json.loads((ROOT / "ENGINE_BUNDLE_V1.json").read_text(encoding="utf-8"))
    bundle["private_data_policy"] = "ALLOW_PRIVATE"
    with pytest.raises(BundleContractError, match="private data policy weakened"):
        validate_bundle(bundle, ROOT)
