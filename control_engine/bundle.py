from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class BundleContractError(ValueError):
    pass


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def validate_bundle(bundle: dict[str, Any], root: Path) -> dict[str, Any]:
    if bundle.get("schema_version") != "1.0" or bundle.get("bundle_id") != "CONTROL_ENGINE_BUNDLE_V1":
        raise BundleContractError("unsupported bundle contract")
    if bundle.get("engine_repository") != "market-predictions/control-engine":
        raise BundleContractError("unexpected engine repository")
    if bundle.get("private_data_policy") != "NO_PRIVATE_RUNTIME_STATE":
        raise BundleContractError("private data policy weakened")
    if bundle.get("consumer_ref_policy") != "EXACT_COMMIT_SHA_ONLY":
        raise BundleContractError("floating consumer ref policy forbidden")
    files = bundle.get("files")
    if not isinstance(files, list) or not files:
        raise BundleContractError("bundle files required")
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise BundleContractError("bundle entry must be object")
        path = entry.get("path")
        expected = entry.get("git_blob_sha")
        if not isinstance(path, str) or not path or path.startswith("/") or ".." in Path(path).parts:
            raise BundleContractError("invalid bundle path")
        if path in seen:
            raise BundleContractError(f"duplicate bundle path: {path}")
        seen.add(path)
        if not isinstance(expected, str) or len(expected) != 40 or any(ch not in "0123456789abcdef" for ch in expected):
            raise BundleContractError(f"invalid git blob sha: {path}")
        target = root / path
        if not target.is_file():
            raise BundleContractError(f"missing bundle file: {path}")
        actual = git_blob_sha(target.read_bytes())
        if actual != expected:
            raise BundleContractError(f"bundle blob mismatch: {path}")
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", nargs="?", default="ENGINE_BUNDLE_V1.json")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    validate_bundle(bundle, Path(args.root))
    print("CONTROL_ENGINE_BUNDLE_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
