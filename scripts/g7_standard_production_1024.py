from __future__ import annotations

from functools import partial
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g7_standard_production as runner

runner.run_workers_ai_once = partial(runner.run_workers_ai_once, max_tokens=1024)

if __name__ == "__main__":
    raise SystemExit(runner.main())
