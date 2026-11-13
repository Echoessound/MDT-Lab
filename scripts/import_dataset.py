"""Preview an external file; --commit explicitly writes the validated batch."""
import argparse
import json
from pathlib import Path

from mdt_demo.research.datasets import CATALOG, prepare_import
from dotenv import load_dotenv
from mdt_demo.research.persistence.config import StorageConfig, create_repository

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", choices=CATALOG)
parser.add_argument("file", type=Path)
parser.add_argument("--max-cases", type=int, default=10)
parser.add_argument("--commit", action="store_true")
parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
args = parser.parse_args()
prepared = prepare_import(args.source, args.file.read_bytes(), args.max_cases)
result = prepared.summary
if args.commit:
    if not prepared.cases:
        raise SystemExit("没有可导入病例；未写入数据库。")
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    store = create_repository(StorageConfig.from_env(), args.output_dir)
    try:
        result = store.import_cases(prepared.cases, prepared.summary)
    finally:
        store.close()
print(json.dumps(result, ensure_ascii=False, indent=2))
