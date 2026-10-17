from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / "payload"
ARCHIVE = ROOT.parent / "formation-kit-2026-09-19.zip"


def payload_files():
    return [
        path
        for path in sorted(PAYLOAD.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]


def main():
    files = payload_files()
    entries = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
        for path in files
    ]
    manifest = {"version": "2026-09-19", "files": entries}
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    included = [
        path
        for path in sorted(ROOT.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]
    with ZipFile(ARCHIVE, "w", ZIP_DEFLATED) as bundle:
        for path in included:
            bundle.write(path, Path("formation-kit") / path.relative_to(ROOT))
    print(f"manifest_files={len(entries)} archive={ARCHIVE} bytes={ARCHIVE.stat().st_size}")


if __name__ == "__main__":
    main()
