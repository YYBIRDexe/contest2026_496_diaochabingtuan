from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    recorded = {item["path"]: item for item in manifest["files"]}
    current = {
        path.relative_to(ROOT).as_posix(): path
        for path in sorted((ROOT / "payload").rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    if set(recorded) != set(current):
        missing = sorted(set(recorded) - set(current))
        extra = sorted(set(current) - set(recorded))
        raise RuntimeError(f"manifest path mismatch: missing={missing}, extra={extra}")
    for name, path in current.items():
        item = recorded[name]
        digest = sha256(path.read_bytes()).hexdigest()
        if digest != item["sha256"] or path.stat().st_size != item["bytes"]:
            raise RuntimeError(f"manifest content mismatch: {name}")
    print(f"MANIFEST_OK version={manifest['version']} files={len(current)}")


if __name__ == "__main__":
    main()
