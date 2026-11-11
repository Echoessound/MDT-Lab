"""Export actual local v2 API responses for frontend contract tests."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from fastapi.testclient import TestClient
from mdt_demo.api import create_app

with TemporaryDirectory() as temporary:
    with TestClient(create_app(Path(temporary), event_delay=0)) as client:
        cases = client.get('/api/v2/cases').json()['data']
        request = {'case_id': cases[0]['case_id'], 'case_version': 1, 'trigger_event_id': 'E002'}
        initial = client.post('/api/v2/runs', json=request).json()['data']
        run_id = initial['run_id']
        for _ in range(500):
            run = client.get(f'/api/v2/runs/{run_id}').json()['data']
            if run['status'] in {'completed', 'failed', 'incomplete'}:
                break
            time.sleep(.005)
        assert run['report_ready'], run
        result = {'cases': cases, 'initial': initial, 'run': run,
                  'report': client.get(f'/api/v2/runs/{run_id}/report').json()['data'],
                  'events': client.get(f'/api/v2/runs/{run_id}/audit').json()['data']['events'],
                  'model': client.get('/api/v2/settings/llm').json()['data']}
target = Path(__file__).resolve().parents[1] / 'frontend/tests/fixtures/research-contract.json'
target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(target)
