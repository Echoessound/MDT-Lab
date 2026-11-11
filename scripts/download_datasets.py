"""Download two small, public sample files with reproducible checksum manifests."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from mdt_demo.research.datasets import CATALOG
from mdt_demo.research.downloads import download_dataset

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", choices=[key for key, value in CATALOG.items() if value["download_url"]])
parser.add_argument("--directory", type=Path, default=Path("data/raw/external"))
args = parser.parse_args()
metadata = CATALOG[args.source]
args.directory.mkdir(parents=True, exist_ok=True)
raw = download_dataset(args.source)
digest = hashlib.sha256(raw).hexdigest()
target = args.directory / metadata["filename"]
if target.exists() and target.read_bytes() != raw:
    raise SystemExit("目标文件已存在且内容不同，请指定新目录保留旧版本。")
target.write_bytes(raw)
manifest = {**metadata, "artifact_sha256": digest, "byte_count": len(raw),
            "downloaded_at": datetime.now(timezone.utc).isoformat()}
target.with_suffix(target.suffix + ".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"file": str(target.resolve()), "bytes": len(raw), "sha256": digest}, ensure_ascii=False))
