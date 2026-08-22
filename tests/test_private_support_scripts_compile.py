from pathlib import Path
import os
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_private_support_scripts_compile() -> None:
    for relative in (
        "scripts/private_intake_diagnostic.py",
        "scripts/private_reconcile_readonly_probe.py",
        "scripts/quarantine_zta_legacy_repair.py",
    ):
        path = ROOT / relative
        compile(path.read_text(encoding="utf-8"), relative, "exec")


def test_readonly_reconcile_probe_runs_directly_without_package_import_failure() -> None:
    env = os.environ.copy()
    env.pop("CONTROL_GITHUB_WRITE_TOKEN", None)
    completed = subprocess.run(
        [sys.executable, "scripts/private_reconcile_readonly_probe.py"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 78
    assert completed.stdout.strip() == "PRIVATE_RECONCILE_PROBE=NO_TOKEN"
    assert "ModuleNotFoundError" not in completed.stderr
