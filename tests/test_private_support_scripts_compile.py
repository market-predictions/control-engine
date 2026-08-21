from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_private_support_scripts_compile() -> None:
    for relative in (
        "scripts/private_intake_diagnostic.py",
        "scripts/quarantine_zta_legacy_repair.py",
    ):
        path = ROOT / relative
        compile(path.read_text(encoding="utf-8"), relative, "exec")
