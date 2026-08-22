from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "scripts" / "scheduled_worker_b_v2.sh"
RESILIENT = ROOT / "scripts" / "scheduled_worker_b_v2_resilient.sh"


def _render(tmp_path: Path) -> str:
    wrapper = RESILIENT.read_text(encoding="utf-8")
    match = re.search(
        r"python - \"\$SOURCE\" \"\$PATCHED\" <<'PY'\n(?P<patcher>.*?)\nPY\n",
        wrapper,
        flags=re.DOTALL,
    )
    assert match is not None
    output = tmp_path / "worker-b.sh"
    proc = subprocess.run(
        [sys.executable, "-", str(BASE), str(output)],
        input=match.group("patcher"),
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return output.read_text(encoding="utf-8")


def test_private_tools_direct_execution_needs_code_dir_as_python_package_root(tmp_path: Path) -> None:
    code = tmp_path / "code"
    tools = code / "tools"
    tools.mkdir(parents=True)
    (tools / "__init__.py").write_text("", encoding="utf-8")
    (tools / "base.py").write_text("VALUE = 41\n", encoding="utf-8")
    (tools / "dep.py").write_text("from tools.base import VALUE\n", encoding="utf-8")
    (tools / "entry.py").write_text(
        "try:\n"
        "    from tools.dep import VALUE\n"
        "except ModuleNotFoundError:\n"
        "    from dep import VALUE\n"
        "print(VALUE + 1)\n",
        encoding="utf-8",
    )

    direct = subprocess.run(
        [sys.executable, str(tools / "entry.py")],
        text=True,
        capture_output=True,
        check=False,
    )
    assert direct.returncode != 0
    assert "No module named 'tools'" in direct.stderr

    env = dict(os.environ)
    env["PYTHONPATH"] = str(code)
    repaired = subprocess.run(
        [sys.executable, str(tools / "entry.py")],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert repaired.returncode == 0, repaired.stderr
    assert repaired.stdout.strip() == "42"


def test_rendered_b_worker_sets_private_code_dir_as_connected_runtime_pythonpath(tmp_path: Path) -> None:
    rendered = _render(tmp_path)
    connected = rendered[rendered.index("connected_complete() {") : rendered.index("fetch_code() {")]
    assert 'PYTHONPATH="$CODE_DIR${PYTHONPATH:+:$PYTHONPATH}" \\' in connected
    assert 'python "$CODE_DIR/tools/control_connected_worker_runtime_v1.py" complete "$@"' in connected
