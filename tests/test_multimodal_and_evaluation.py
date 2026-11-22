"""Tests for TCGA/cBioPortal ingestion, real medical attachments (PNG/DICOM), and library evaluation."""

import json
import struct
import zlib

from fastapi.testclient import TestClient
import pytest

from mdt_demo.api import create_app


def _make_png(width: int = 16, height: int = 12) -> bytes:
    """Build a minimal valid grayscale PNG binary in pure Python."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw_scanlines = b"".join(b"\x00" + b"\x80" * width for _ in range(height))
    idat = zlib.compress(raw_scanlines)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _make_dicom(*, include_pii: bool = True) -> bytes:
    """Build a minimal valid DICOM Part 10 binary with explicit VR tags."""
    def elem_str(group: int, element: int, vr: bytes, text: str) -> bytes:
        data = text.encode("ascii")
        if len(data) % 2:
            data += b" "
        return struct.pack("<HH", group, element) + vr + struct.pack("<H", len(data)) + data

    def elem_us(group: int, element: int, value: int) -> bytes:
        return struct.pack("<HH", group, element) + b"US" + struct.pack("<HH", 2, value)

    body = bytearray(b"\x00" * 128 + b"DICM")
    body += elem_str(0x0008, 0x0060, b"CS", "CT")
    body += elem_str(0x0008, 0x0020, b"DA", "20240310")
    if include_pii:
        body += elem_str(0x0010, 0x0010, b"PN", "SECRET_PATIENT_NAME")
    body += elem_str(0x0018, 0x0015, b"CS", "CHEST")
    body += elem_str(0x0018, 0x0050, b"DS", "1.25")
    body += elem_us(0x0028, 0x0010, 512)
    body += elem_us(0x0028, 0x0011, 512)
    body += elem_str(0x0028, 0x1050, b"DS", "-600")
    body += elem_str(0x0028, 0x1051, b"DS", "1500")
    return bytes(body)


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, event_delay=0)) as client:
        yield client


def test_tcga_cbioportal_tsv_template_import_and_unplaced_isolation(client):
    cap_res = client.get("/api/v2/datasets/capabilities")
    assert cap_res.status_code == 200
    assert len(cap_res.json()["data"]) == 5

    tpl_res = client.get("/api/v2/datasets/template?source=tcga_cbioportal_tsv")
    assert tpl_res.status_code == 200
    assert b"TCGA-LUAD-DEMO-01" in tpl_res.content

    prev_res = client.post("/api/v2/datasets/preview?source=tcga_cbioportal_tsv&max_cases=10", content=tpl_res.content)
    assert prev_res.status_code == 200, prev_res.text
    preview = prev_res.json()["data"]
    assert preview["case_count"] == 2
    assert preview["unplaced_count"] >= 4

    commit_res = client.post(f"/api/v2/datasets/import/{preview['preview_id']}")
    assert commit_res.status_code == 200
    case_id = commit_res.json()["data"]["imported_case_ids"][0]
    case = client.get(f"/api/v2/cases/{case_id}").json()["data"]
    assert case["case_kind"] == "public_research"
    # Undated staging/molecular/outcome fields stay isolated in unplaced_records
    assert len(case["unplaced_records"]) == 3
    # Dated pathology event enables traceable dated_pathology_histology_v1 semantic check
    path_event = next(ev for ev in case["timeline"] if ev["event_type"] == "pathology")
    wf = client.get(f"/api/v2/cases/{case_id}/workflow-plan?trigger_event_id={path_event['event_id']}").json()["data"]
    assert wf["completeness"]["can_auto_enrich"] is True
    assert wf["completeness"]["semantic_inferred"][0]["fact_key"] == "pathology_confirmed"


def test_real_png_and_dicom_attachment_upload_deidentification_and_serving(client):
    # 1. Valid PNG upload
    png_bytes = _make_png(32, 24)
    up_png = client.post(
        "/api/v2/cases/LUNG-SYN-001/events/E002/attachments?filename=chest_ct_slice.png",
        content=png_bytes,
    )
    assert up_png.status_code == 201, up_png.text
    att_png = up_png.json()["data"]
    assert att_png["kind"] == "image"
    assert att_png["metadata"]["width"] == 32
    assert att_png["metadata"]["height"] == 24
    assert att_png["metadata"]["previewable"] is True

    # Serve PNG inline with nosniff
    content_res = client.get(f"/api/v2/cases/LUNG-SYN-001/attachments/{att_png['attachment_id']}/content")
    assert content_res.status_code == 200
    assert content_res.content == png_bytes
    assert content_res.headers["x-content-type-options"] == "nosniff"

    # 2. Valid DICOM Part 10 upload with PII stripping
    dcm_bytes = _make_dicom(include_pii=True)
    up_dcm = client.post(
        "/api/v2/cases/LUNG-SYN-001/events/E002/attachments?filename=series_01.dcm",
        content=dcm_bytes,
    )
    assert up_dcm.status_code == 201, up_dcm.text
    att_dcm = up_dcm.json()["data"]
    assert att_dcm["kind"] == "dicom"
    assert att_dcm["metadata"]["pii_group_0010_skipped"] == 1
    assert att_dcm["metadata"]["dicom_tags"]["modality"] == "CT"
    assert att_dcm["metadata"]["dicom_tags"]["rows"] == 512
    assert att_dcm["metadata"]["dicom_tags"]["columns"] == 512
    assert att_dcm["metadata"]["dicom_tags"]["slice_thickness_mm"] == 1.25
    assert "SECRET_PATIENT_NAME" not in json.dumps(att_dcm)

    # 3. Listing & deletion
    listed = client.get("/api/v2/cases/LUNG-SYN-001/attachments?event_id=E002").json()["data"]
    assert len(listed) == 2
    del_res = client.delete(f"/api/v2/cases/LUNG-SYN-001/attachments/{att_png['attachment_id']}")
    assert del_res.status_code == 200
    assert len(client.get("/api/v2/cases/LUNG-SYN-001/attachments?event_id=E002").json()["data"]) == 1

    # 4. Reject spoofed image magic & unsupported extension
    assert client.post(
        "/api/v2/cases/LUNG-SYN-001/events/E002/attachments?filename=fake.png",
        content=b"not a real png file at all",
    ).status_code == 422
    assert client.post(
        "/api/v2/cases/LUNG-SYN-001/events/E002/attachments?filename=malware.exe",
        content=b"MZ...",
    ).status_code == 422


def test_library_evaluation_blind_annotations_and_thesis_exports(client):
    # Evaluate all seed cases before annotation
    eval_res = client.post("/api/v2/experiments/evaluate", json={"trigger_scope": "all"})
    assert eval_res.status_code == 200, eval_res.text
    data = eval_res.json()["data"]
    assert data["family_count"] == 3
    assert data["scenario_count"] == 13  # 6 + 3 + 4 events across LUNG-SYN-001/002/003
    assert len(data["methods"]) == 8
    assert "\\begin{table}" in data["latex_table"]
    assert "scenario_id,case_family_id" in data["scores_csv"]

    # Add blind reference annotations for two scenarios
    ann1 = client.put(
        "/api/v2/annotations/LUNG-SYN-001:v1:E002",
        json={
            "case_id": "LUNG-SYN-001", "case_version": 1, "trigger_event_id": "E002",
            "annotator_id": "clinician_a", "required_agents": ["oncology", "radiology"],
            "expected_decision": "NEED_MORE_INFORMATION",
            "missing_fields": ["pathology_confirmed"], "rationale": "仅有影像，尚未病理确诊。",
        },
    )
    assert ann1.status_code == 200
    ann2 = client.put(
        "/api/v2/annotations/LUNG-SYN-003:v1:E004",
        json={
            "case_id": "LUNG-SYN-003", "case_version": 1, "trigger_event_id": "E004",
            "annotator_id": "clinician_a", "required_agents": ["oncology", "radiology", "surgery", "pathology"],
            "expected_decision": "DEFER_DECISION",
            "missing_fields": [], "rationale": "同日存在相反进展记录，应暂缓判断。",
        },
    )
    assert ann2.status_code == 200
    assert len(client.get("/api/v2/annotations").json()["data"]) == 2

    # Re-evaluate and verify gold-standard thesis metrics + family-clustered bootstrap CI
    eval2 = client.post("/api/v2/experiments/evaluate", json={"trigger_scope": "all"}).json()["data"]
    assert eval2["annotated_scenario_count"] == 2
    b3 = next(m for m in eval2["methods"] if m["method_id"] == "B3")
    assert b3["specialist_recall"] == 1.0
    assert b3["false_pass_rate"] == 0.0
    assert b3["accuracy"] == 1.0

    stats = eval2["paired_statistics"]
    assert stats["bootstrap_resamples"] == 1000
    assert stats["bootstrap_seed"] == 2026
    assert stats["cluster_unit"] == "case_family_id"
    assert stats["family_count"] == 3
    contrasts = {c["contrast_id"]: c for c in stats["contrasts"]}
    assert set(contrasts.keys()) == {"B3_vs_A3", "B3_vs_A2", "B3_vs_A1", "B3_vs_B0"}
    assert contrasts["B3_vs_A3"]["ci_low"] <= contrasts["B3_vs_A3"]["point_estimate"] <= contrasts["B3_vs_A3"]["ci_high"]
    assert contrasts["B3_vs_A3"]["point_estimate"] > 0

    # Delete annotation cleanly
    assert client.delete("/api/v2/annotations/LUNG-SYN-001:v1:E002").status_code == 200
    assert len(client.get("/api/v2/annotations").json()["data"]) == 1


def test_cli_runner_supports_tcga_and_exports_paper_artifacts(client, tmp_path, project_root):
    import subprocess
    import sys

    tpl = client.get("/api/v2/datasets/template?source=tcga_cbioportal_tsv")
    assert tpl.status_code == 200
    tsv_file = tmp_path / "tcga_nsclc.tsv"
    tsv_file.write_bytes(tpl.content)

    from mdt_demo.research.datasets import prepare_import
    prepared = prepare_import("tcga_cbioportal_tsv", tpl.content, 10)
    first_case = prepared.cases[0]
    first_ev = first_case["timeline"][0]["event_id"]
    first_sid = f"{first_case['case_id']}:v{first_case['version']}:{first_ev}"

    ann_file = tmp_path / "annotations.json"
    ann_file.write_text(json.dumps({
        first_sid: {
            "scenario_id": first_sid,
            "case_id": first_case["case_id"],
            "case_version": first_case["version"],
            "trigger_event_id": first_ev,
            "annotator_id": "reviewer_cli",
            "required_agents": ["oncology"],
            "expected_decision": "NEED_MORE_INFORMATION",
            "missing_fields": ["imaging_complete"],
            "rationale": "仅有诊断日记录，缺影像确认。",
        }
    }), encoding="utf-8")

    out_dir = tmp_path / "tcga_batch"
    cmd = [
        sys.executable, str(project_root / "scripts/run_mock_experiments.py"),
        "--source", "tcga_cbioportal_tsv",
        "--input", str(tsv_file),
        "--annotations", str(ann_file),
        "--export-paper",
        "--output-dir", str(out_dir),
    ]
    res = subprocess.run(cmd, check=True, capture_output=True, text=True)
    assert "论文产物已导出" in res.stdout
    assert (out_dir / "results.json").exists()
    assert (out_dir / "scores.csv").exists()
    assert (out_dir / "ablation_table.tex").exists()
    stats_json = json.loads((out_dir / "statistics_summary.json").read_text(encoding="utf-8"))
    assert stats_json["family_count"] == 2
    assert stats_json["annotated_scenario_count"] == 1
    assert stats_json["paired_statistics"]["bootstrap_seed"] == 2026
    assert "\\begin{table}" in (out_dir / "ablation_table.tex").read_text(encoding="utf-8")
