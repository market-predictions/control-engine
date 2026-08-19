from pathlib import Path
import re

ROOT = Path(__file__).parents[1]

FORBIDDEN_PATH_MARKERS = {
    "control-runtime-state", "dispatch_queue", "dispatch_runs", "work_claims",
    "worker-results", "handovers", "project-intake", "runtime-ops",
}
SECRET_PATTERNS = [
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)(?:cloudflare_api_token|groq_api_key|openai_api_key)\s*=\s*['\"]?[A-Za-z0-9_\-]{20,}"),
]
TEXT_SUFFIXES = {".py", ".json", ".md", ".yml", ".yaml", ".txt", ".toml"}


def source_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or ".pytest_cache" in path.parts or "__pycache__" in path.parts:
            continue
        yield path


def test_no_private_runtime_paths_are_published():
    offenders = []
    for path in source_files():
        lowered = "/".join(part.casefold() for part in path.relative_to(ROOT).parts)
        if any(marker in lowered for marker in FORBIDDEN_PATH_MARKERS):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"private-runtime path markers found: {offenders}"


def test_no_obvious_secret_values_are_published():
    offenders = []
    for path in source_files():
        if path.suffix.casefold() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                offenders.append(str(path.relative_to(ROOT)))
                break
    assert offenders == [], f"possible secret values found: {offenders}"
