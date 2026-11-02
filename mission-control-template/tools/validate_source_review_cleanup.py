from __future__ import annotations
import argparse, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from source_review_turn_chain import validate_cleanup_manifest


def main() -> int:
    p = argparse.ArgumentParser(description="Validate compaction-safe source-review cleanup without deleting anything.")
    p.add_argument("manifest", type=Path)
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--schema", type=Path, default=HERE.parent / "schemas" / "SOURCE_REVIEW_CLEANUP_SCHEMA.json")
    args = p.parse_args()
    root = args.root.resolve()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    errors = validate_cleanup_manifest(manifest, schema, root=root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("source-review cleanup manifest: VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
