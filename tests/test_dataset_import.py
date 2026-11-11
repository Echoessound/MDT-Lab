import csv
import io
import json
import time
from zipfile import ZipFile

import httpx
import pytest
from fastapi.testclient import TestClient

from mdt_demo.api import create_app
from mdt_demo.api_schemas import APIError
from mdt_demo.research.datasets import prepare_import
from mdt_demo.research.downloads import download_dataset
from mdt_demo.research.import_api import ImportPreviews
from mdt_demo.research.store import ResearchStore, TERMINAL


def tcia_bytes(ids=('T001',), histology='Adenocarcinoma'):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Case ID', 'Age at Histological Diagnosis', 'Gender', 'CT Date', 'Histology', 'PET Date', 'EGFR mutation status', 'Survival Status'])
    for subject in ids:
        writer.writerow([subject, '60', 'Female', '01/02/2000', histology, '01/03/2000', 'Not collected', 'Alive'])
    return output.getvalue().encode()


def synthea_bytes(extra=None):
    out = io.BytesIO()
    with ZipFile(out, 'w') as archive:
        archive.writestr('csv/patients.csv', 'Id,BIRTHDATE,GENDER,FIRST,LAST\nP001,1960-01-01,F,DoNotImport,PrivateName\n')
        archive.writestr('csv/conditions.csv', 'PATIENT,START,CODE,DESCRIPTION\nP001,2000-01-02,123,Synthetic condition\n')
        if extra:
            archive.writestr(*extra)
    return out.getvalue()


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, event_delay=0)) as client:
        yield client


def preview(client, raw, source='tcia_nsclc_csv', limit=10):
    response = client.post(f'/api/v2/datasets/preview?source={source}&max_cases={limit}', content=raw)
    assert response.status_code == 200, response.text
    return response.json()['data']


def commit(client, item):
    return client.post('/api/v2/datasets/import/' + item['preview_id'])


def finish(client, run_id):
    for _ in range(600):
        run = client.get('/api/v2/runs/' + run_id).json()['data']
        if run['status'] in TERMINAL:
            return run
        time.sleep(.005)
    pytest.fail('run did not terminate')


def test_tcia_preview_import_agents_report_and_restart(tmp_path):
    with TestClient(create_app(tmp_path, event_delay=0)) as client:
        before = len(client.get('/api/v2/cases').json()['data'])
        item = preview(client, tcia_bytes())
        assert item['case_count'] == 1 and item['unplaced_count'] == 3
        assert len(client.get('/api/v2/cases').json()['data']) == before
        batch = commit(client, item).json()['data']
        assert commit(client, item).json()['data']['already_imported'] is True
        case_id = batch['imported_case_ids'][0]
        case = client.get('/api/v2/cases/' + case_id).json()['data']
        assert case['case_kind'] == 'public_research'
        assert case['unplaced_records'][1]['facts']['egfr_status'] is None
        trigger = case['timeline'][0]['event_id']
        response = client.post('/api/v2/runs', json={'case_id': case_id, 'case_version': 1, 'trigger_event_id': trigger})
        assert response.status_code == 202
        run_id = response.json()['data']['run_id']
        run = finish(client, run_id)
        assert run['report_ready'] and run['routing']['selected_agents'] == ['oncology', 'radiology']
        report = client.get(f'/api/v2/runs/{run_id}/report').json()['data']
        assert len(report['case_snapshot']['timeline']) == 1
        assert report['case_snapshot']['unplaced_records'] == []
        assert 'Adenocarcinoma' not in json.dumps(report)
        assert report['final_decision'] == 'NEED_MORE_INFORMATION'
        assert all(ref['artifact_sha256'] == item['artifact_sha256'] and ref['source_record_locator'] and ref['source_field'] for ref in report['evidence_registry'])
        events = client.get(f'/api/v2/runs/{run_id}/audit').json()['data']['events']
        stream = client.get(f'/api/v2/runs/{run_id}/events?after_seq=0').text
        assert events[-1]['type'] == 'run.completed' and run_id in stream
    with TestClient(create_app(tmp_path, event_delay=0)) as client:
        assert client.get('/api/v2/datasets').json()['data']['batches'][0]['batch_id'] == batch['batch_id']
        assert client.get(f'/api/v2/runs/{run_id}/report').json()['data'] == report


def test_import_conflict_rolls_back_entire_batch(client):
    commit(client, preview(client, tcia_bytes(('T002',))))
    response = commit(client, preview(client, tcia_bytes(('T001', 'T002'), 'Different')))
    assert response.status_code == 409
    assert client.get('/api/v2/cases/TCIA-NSCLC-RG-T001').status_code == 404
    assert len(client.get('/api/v2/datasets').json()['data']['batches']) == 1


def test_synthea_excludes_identity_and_does_not_invent_completeness():
    prepared = prepare_import('synthea_csv', synthea_bytes())
    case = prepared.cases[0]
    assert case['patient']['age'] == 40
    assert 'PrivateName' not in json.dumps(case) and 'DoNotImport' not in json.dumps(case)
    assert 'pathology_confirmed' not in case['timeline'][0]['facts']
    assert case['provenance'][0]['synthetic'] is True


@pytest.mark.parametrize('raw,source', [(b'not zip', 'synthea_csv'), (synthea_bytes(('../patients.csv', 'bad')), 'synthea_csv'), (b'wrong,columns\na,b\n', 'tcia_nsclc_csv'), (tcia_bytes(('T001', 'T001')), 'tcia_nsclc_csv'), (b'{"cases":[]}', 'research_json'), (b'{"cases":[{"private":"must not echo"}]}', 'research_json')])
def test_malformed_import_is_actionable_and_does_not_write(client, raw, source):
    response = client.post('/api/v2/datasets/preview?source=' + source, content=raw)
    assert response.status_code == 422
    assert 'must not echo' not in response.text
    assert client.get('/api/v2/datasets').json()['data']['batches'] == []


def test_json_template_and_mixed_case_versions(client):
    raw = client.get('/api/v2/datasets/template').content
    item = preview(client, raw, 'research_json')
    assert commit(client, item).status_code == 200
    public = commit(client, preview(client, tcia_bytes())).json()['data']['imported_case_ids'][0]
    response = client.post(f'/api/v2/cases/{public}/events', json={'expected_version': 1, 'event': {
        'occurred_at': '2001-01-01', 'event_type': 'pathology', 'title': 'Synthetic extension', 'facts': {'pathology_confirmed': True}}})
    assert response.status_code == 201 and response.json()['data']['case_kind'] == 'mixed'
    assert client.get(f'/api/v2/cases/{public}?version=1').json()['data']['case_kind'] == 'public_research'


def test_expired_preview_and_limits(client, tmp_path):
    store = ResearchStore(tmp_path / 'other.sqlite3')
    try:
        previews = ImportPreviews(store, ttl_seconds=-1)
        item = previews.preview('tcia_nsclc_csv', tcia_bytes(), 1)
        with pytest.raises(APIError) as error:
            previews.commit(item['preview_id'])
        assert error.value.code == 'IMPORT_PREVIEW_EXPIRED'
    finally:
        store.close()
    assert client.post('/api/v2/datasets/preview?source=tcia_nsclc_csv&max_cases=51', content=tcia_bytes()).status_code == 422
    assert client.post('/api/v2/datasets/preview?source=bad', content=b'x').status_code == 422
    assert client.post('/api/v2/datasets/preview?source=tcia_nsclc_csv', content=b'').status_code == 413
    assert client.post('/api/v2/datasets/import/missing').status_code == 409


def test_connect_uses_same_preview_commit_flow(client, monkeypatch):
    monkeypatch.setattr('mdt_demo.research.import_api.download_dataset', lambda source: tcia_bytes())
    response = client.post('/api/v2/datasets/connect?source=tcia_nsclc_csv&max_cases=1')
    assert response.status_code == 200
    assert commit(client, response.json()['data']).status_code == 200


def test_downloader_bounds_and_rejects_external_redirects(monkeypatch):
    assert download_dataset('tcia_nsclc_csv', transport=httpx.MockTransport(lambda request: httpx.Response(200, content=tcia_bytes()))) == tcia_bytes()
    calls = []
    def redirect(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
    with pytest.raises(APIError) as error:
        download_dataset('tcia_nsclc_csv', transport=httpx.MockTransport(redirect))
    assert error.value.code == 'DATASET_REDIRECT_BLOCKED' and len(calls) == 1
    monkeypatch.setattr('mdt_demo.research.downloads.MAX_UPLOAD_BYTES', 10)
    with pytest.raises(APIError) as error:
        download_dataset('synthea_csv', transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b'x' * 11)))
    assert error.value.code == 'DATASET_SIZE_LIMIT'


def test_cross_origin_cannot_import(client):
    assert client.post('/api/v2/datasets/connect?source=synthea_csv', headers={'Origin': 'https://other.example'}).status_code == 403


def test_transient_upstream_failure_retries_once():
    calls = []
    def upstream(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, content=tcia_bytes())
    assert download_dataset('tcia_nsclc_csv', transport=httpx.MockTransport(upstream)) == tcia_bytes()
    assert len(calls) == 2
    calls.clear()
    def unavailable(request):
        calls.append(request)
        raise httpx.ConnectError('temporary failure')
    with pytest.raises(APIError):
        download_dataset('tcia_nsclc_csv', transport=httpx.MockTransport(unavailable))
    assert len(calls) == 2
