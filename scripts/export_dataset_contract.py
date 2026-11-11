"""Generate frontend fixtures from the actual import/run API, with synthetic test rows."""
import json
from pathlib import Path
import tempfile
import time

from fastapi.testclient import TestClient
from mdt_demo.api import create_app
from mdt_demo.research.store import TERMINAL

raw = b'Case ID,Age at Histological Diagnosis,Gender,CT Date,Histology,PET Date,EGFR mutation status\nFIXTURE001,60,Female,01/02/2000,Fixture histology,01/03/2000,Not collected\n'
with tempfile.TemporaryDirectory() as directory, TestClient(create_app(Path(directory), event_delay=0)) as client:
    preview = client.post('/api/v2/datasets/preview?source=tcia_nsclc_csv&max_cases=1', content=raw).json()['data']
    batch = client.post('/api/v2/datasets/import/' + preview['preview_id']).json()['data']
    case = client.get('/api/v2/cases/' + batch['imported_case_ids'][0]).json()['data']
    response = client.post('/api/v2/runs', json={'case_id': case['case_id'], 'case_version': 1, 'trigger_event_id': case['timeline'][0]['event_id']})
    run_id = response.json()['data']['run_id']
    for _ in range(600):
        run = client.get('/api/v2/runs/' + run_id).json()['data']
        if run['status'] in TERMINAL:
            break
        time.sleep(.005)
    assert run['report_ready']
    report = client.get(f'/api/v2/runs/{run_id}/report').json()['data']
    mixed = client.post(f"/api/v2/cases/{case['case_id']}/events", json={'expected_version': 1, 'event': {'occurred_at': '2001-01-01', 'event_type': 'pathology', 'title': 'Fixture synthetic extension', 'facts': {'pathology_confirmed': True}}}).json()['data']
    catalog = client.get('/api/v2/datasets').json()['data']
    fixture = {'catalog': catalog, 'preview': preview, 'batch': batch, 'case': case, 'mixed': mixed, 'run': run, 'report': report}
Path('frontend/tests/fixtures/dataset-contract.json').write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + '\n')
