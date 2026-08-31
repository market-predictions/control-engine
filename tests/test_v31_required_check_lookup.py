from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "control_kernel_v31.py"
spec = importlib.util.spec_from_file_location("control_kernel_v31_required_checks", SCRIPT)
bridge = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(bridge)


def test_required_checks_are_not_limited_by_unrelated_first_100_runs(monkeypatch):
    calls: list[str] = []

    def fake_api(_token, method, path, body=None):
        assert method == "GET"
        assert body is None
        calls.append(path)
        if "check_name=ci%2Frequired" in path:
            return {
                "total_count": 1,
                "check_runs": [
                    {
                        "name": "ci/required",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ],
            }
        raise AssertionError(path)

    monkeypatch.setattr(bridge, "_api", fake_api)

    assert bridge._required_checks_green("token", "o/r", "a" * 40, ["ci/required"]) is True
    assert calls == [
        "repos/o/r/commits/" + "a" * 40 + "/check-runs?check_name=ci%2Frequired&filter=latest&per_page=1"
    ]


def test_required_check_lookup_remains_fail_closed(monkeypatch):
    monkeypatch.setattr(
        bridge,
        "_api",
        lambda *_args, **_kwargs: {
            "total_count": 1,
            "check_runs": [
                {
                    "name": "ci/required",
                    "status": "completed",
                    "conclusion": "failure",
                }
            ],
        },
    )

    assert bridge._required_checks_green("token", "o/r", "b" * 40, ["ci/required"]) is False


def test_missing_required_check_lookup_remains_fail_closed(monkeypatch):
    monkeypatch.setattr(
        bridge,
        "_api",
        lambda *_args, **_kwargs: {"total_count": 0, "check_runs": []},
    )

    assert bridge._required_checks_green("token", "o/r", "c" * 40, ["ci/required"]) is False
