"""Preview SQLite → MongoDB migration; --commit writes and verifies atomically."""
import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
from mdt_demo.api_schemas import APIError
from mdt_demo.research.persistence.config import StorageConfig
from mdt_demo.research.persistence.migration import migrate_sqlite
from mdt_demo.research.persistence.mongo import MongoResearchStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?", default=Path("outputs/research.sqlite3"))
    parser.add_argument("--database", help="Destination database; defaults to MDT_MONGODB_DATABASE")
    parser.add_argument("--commit", action="store_true", help="Stop application workers before committing")
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    config = StorageConfig.from_env()
    store = None
    try:
        store = MongoResearchStore(config.uri, args.database or config.database)
        result = migrate_sqlite(args.source, store, dry_run=not args.commit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except APIError as error:
        raise SystemExit(f"{error.code}: {error.message}") from None
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    main()
