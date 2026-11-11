"""Regenerate the browser test fixture from real Pydantic/API output."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from fastapi.testclient import TestClient

from mdt_demo.api import create_app
from mdt_demo.runtime import TERMINAL


def main() -> None:
    with TemporaryDirectory(prefix="mdt-contract-") as temporary:
        with TestClient(create_app(Path(temporary), event_delay=0)) as client:
            initial = client.post("/api/v1/runs", json={"case_id": "SYN-001"}).json()["data"]
            run_id = initial["run_id"]
            for _ in range(500):
                snapshot = client.get(f"/api/v1/runs/{run_id}").json()["data"]
                if snapshot["status"] in TERMINAL:
                    break
                time.sleep(.005)
            else:
                raise RuntimeError("Contract run did not finish")
            fixture = {
                "case": client.get("/api/v1/cases/SYN-001").json()["data"],
                "initial": initial, "run": snapshot,
                "report": client.get(f"/api/v1/runs/{run_id}/report").json()["data"],
                "events": client.get(f"/api/v1/runs/{run_id}/audit").json()["data"]["events"],
            }
    path = Path(__file__).resolve().parents[1] / "frontend/tests/fixtures/contract.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Exported real API contract: {path}")


if __name__ == "__main__":
    main()
