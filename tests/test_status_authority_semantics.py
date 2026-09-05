import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_public_engine_manifest_cannot_imply_global_control_runtime_state():
    manifest = json.loads((ROOT / "ENGINE_MANIFEST.json").read_text(encoding="utf-8"))
    boundary = (ROOT / "docs" / "PUBLIC_PRIVATE_BOUNDARY_V4.md").read_text(encoding="utf-8")

    assert manifest["repository"] == "market-predictions/control-engine"
    assert manifest["semantic_runtime_authority"] is False
    assert "control_runtime" not in manifest

    assert "component-local manifest" in boundary
    assert "never a source for current **global Control runtime status**" in boundary
    assert "does **not** mean that the canonical Control V4 Runner is inactive" in boundary
    assert "control-plane@control-runtime-state:control/DISPATCH_QUEUE.json" in boundary
