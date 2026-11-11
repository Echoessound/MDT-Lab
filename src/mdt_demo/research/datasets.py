"""Bounded, deterministic adapters for Synthea CSV and TCIA clinical tables.

Parsing never calls a model. Undated retrospective fields are retained separately
and excluded by freeze_context. No completeness flag is inferred from row presence.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
import csv
import hashlib
import io
import json
import math
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from pydantic import ValidationError

from ..api_schemas import APIError
from .schemas import ResearchCase

MAPPING_VERSION = "dataset-mapping-v1"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
CATALOG = {
    "synthea_csv": {
        "source": "synthea_csv", "name": "Synthea 合成病程", "format": "CSV ZIP",
        "filename": "synthea_sample_csv.zip", "synthetic": True,
        "source_name": "synthea", "dataset_version": "synthea-csv-content-addressed",
        "source_url": "https://synthetichealth.github.io/downloads.html",
        "download_url": "https://synthetichealth.github.io/synthea-sample-data/downloads/latest/synthea_sample_data_csv_latest.zip",
        "license": "Synthea 官方下载页允许不受限制的研究等再利用；须引用数据来源。",
        "citation": "Walonoski et al. JAMIA 2018. DOI: 10.1093/jamia/ocx079",
        "description": "导入通用合成病程；通用样本不保证包含肺癌。姓名、地址、证件和费用字段不导入。",
    },
    "tcia_nsclc_csv": {
        "source": "tcia_nsclc_csv", "name": "TCIA NSCLC-Radiogenomics", "format": "临床 CSV",
        "filename": "tcia_nsclc_clinical.csv", "synthetic": False,
        "source_name": "tcia_nsclc_radiogenomics", "dataset_version": "NSCLC-Radiogenomics-v4-clinical-2018-05-22",
        "source_url": "https://www.cancerimagingarchive.net/collection/nsclc-radiogenomics/",
        "download_url": "https://wiki.cancerimagingarchive.net/download/attachments/28672347/NSCLCR01Radiogenomic_DATA_LABELS_2018-05-22_1500-shifted.csv?api=v2&modificationDate=1531967714295&version=1",
        "license": "CC BY 3.0；遵守 TCIA 数据使用条款并保留数据与论文引用。",
        "citation": "Bakr et al. Data for NSCLC Radiogenomics v4. DOI: 10.7937/K9/TCIA.2017.7hs46erv; Scientific Data 2018, 5:180202",
        "description": "仅导入临床表。有日期的检查和随访进入时间线；无可用时间的病理、分子与治疗字段单独展示。",
    },
}
CATALOG["research_json"] = {
    "source": "research_json", "name": "研究病例与相关资料", "format": "JSON",
    "filename": "research_cases.json", "synthetic": None,
    "source_url": None, "download_url": None,
    "license": "由导入文件逐项声明来源、许可与数据版本。",
    "citation": "由导入文件提供引用。",
    "description": "按模板导入结构化病例、带日期的相关事实与无日期资料；所有病例须声明来源。",
}
MISSING = {"", "na", "n/a", "nan", "none", "null", "unknown", "not collected", "not available",
           "not assessed", "not performed", "not tested", "not recorded", "not applicable"}


@dataclass
class PreparedImport:
    cases: list[dict]
    summary: dict


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _rows(raw: bytes, required: set[str], *, limit: int = 120_000) -> list[dict]:
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        names = reader.fieldnames or []
        normalized = [name.strip() for name in names]
        if len(normalized) != len(set(normalized)) or len(names) > 100:
            raise ValueError("列名重复或列数超出限制")
        if not required <= set(normalized):
            missing = ", ".join(sorted(required - set(normalized)))
            raise ValueError(f"缺少必要列：{missing}")
        result = []
        for row in reader:
            if len(result) >= limit or None in row:
                raise ValueError("行数超限或存在列数不一致的记录")
            record = {key.strip(): (value or "").strip() for key, value in row.items()}
            if any(len(value) > 2000 for value in record.values()):
                raise ValueError("单个字段超过2000字符")
            result.append({"row": reader.line_num, "data": record, "columns": dict(zip(normalized, names))})
        return result
    except (UnicodeError, csv.Error, ValueError) as exc:
        raise APIError(422, "INVALID_DATASET_CSV", f"CSV 校验失败：{exc}") from None


def _date(value: str, *, us=False) -> date | None:
    if value.strip().lower() in MISSING:
        return None
    if us:
        return datetime.strptime(value, "%m/%d/%Y").date()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.date()


def _provenance(source, digest):
    item = CATALOG[source]
    return {"source_name": item["source_name"], "source_url": item["source_url"],
            "dataset_version": item["dataset_version"], "license": item["license"],
            "synthetic": item["synthetic"], "artifact_sha256": digest,
            "artifact_name": item["filename"], "mapping_version": MAPPING_VERSION,
            "citation": item["citation"]}


def _event(source, record, table, when, kind, title, facts, fields, timestamp=None):
    return {"event_id": "PENDING", "occurred_at": when.isoformat(), "event_type": kind,
            "title": title, "facts": facts, "source": CATALOG[source]["source_name"],
            "source_record_id": f"{table.removesuffix('.csv')}_{record['row']:07d}",
            "synthetic_extension": False, "confidence": "source_record", "introduced_in_version": 1,
            "source_record_locator": f"{CATALOG[source]['filename']}!{table}:line={record['row']}",
            "source_fields": {key: record["columns"].get(column, column) for key, column in fields.items()},
            "original_timestamp": timestamp,
            "time_note": "仅保留来源记录日期；检查记录存在不代表报告齐备，未推断诊疗结论。"}


def _number_ids(events):
    # Ordinal IDs preserve source timestamp ordering within the existing (date,ID)
    # contract. Date-only rows sort before timed rows; this is not causal ordering.
    events.sort(key=lambda event: (event["occurred_at"], event["original_timestamp"] or "", event["source_record_id"]))
    for index, event in enumerate(events, 1):
        identity = json.dumps(event, ensure_ascii=False, sort_keys=True).encode()
        event["event_id"] = f"E{index:05d}_{_hash(identity)[:10]}"
    return events


def _case(case_id, title, patient, events, provenance, notes, *, unplaced=None, disease=None):
    return ResearchCase.model_validate({"case_id": case_id, "title": title,
        "disease": disease or "通用合成病程，未限定疾病", "case_kind": "synthetic" if provenance["synthetic"] else "public_research",
        "version": 1, "patient": patient,
        "current_question": "截至所选来源事件，已提供记录是否充分且一致，仍需补充哪些资料？",
        "timeline": _number_ids(events), "provenance": [provenance],
        "unplaced_records": unplaced or [], "data_notes": notes}).model_dump(mode="json")


def _synthea(raw, digest, max_cases, warnings, rejected, table_counts):
    specs = {
        "patients.csv": {"Id", "BIRTHDATE", "GENDER"},
        "conditions.csv": {"PATIENT", "START", "CODE", "DESCRIPTION"},
        "encounters.csv": {"PATIENT", "START", "CODE", "DESCRIPTION"},
        "imaging_studies.csv": {"PATIENT", "DATE", "MODALITY_CODE"},
        "procedures.csv": {"PATIENT", "START", "CODE", "DESCRIPTION"},
        "medications.csv": {"PATIENT", "START", "CODE", "DESCRIPTION"},
        "observations.csv": {"PATIENT", "DATE", "CODE", "VALUE", "DESCRIPTION"},
    }
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 100:
                raise ValueError("ZIP 文件条目超过100项")
            chosen, expanded = {}, 0
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in entry.filename or entry.flag_bits & 1:
                    raise ValueError("ZIP 含不允许的路径或加密条目")
                if path.name not in specs or entry.is_dir():
                    continue
                if path.name in chosen:
                    raise ValueError("ZIP 内存在同名数据表")
                expanded += entry.file_size
                if expanded > 120 * 1024 * 1024 or entry.file_size > 60 * 1024 * 1024:
                    raise ValueError("ZIP 解压后的数据超过限制")
                chosen[path.name] = _rows(archive.read(entry), specs[path.name])
            if "patients.csv" not in chosen or "conditions.csv" not in chosen:
                raise ValueError("ZIP 必须包含 patients.csv 和 conditions.csv")
    except (BadZipFile, RuntimeError, OSError, ValueError, NotImplementedError) as exc:
        raise APIError(422, "INVALID_DATASET_ZIP", f"Synthea ZIP 校验失败：{exc}") from None
    for name in specs:
        if name not in chosen:
            warnings[f"缺少可选表 {name}，未生成对应事件。"] += 1
    table_counts.update({name: len(rows) for name, rows in chosen.items()})
    patients = chosen["patients.csv"]
    patient_ids = [record["data"]["Id"] for record in patients]
    if len(patient_ids) != len(set(patient_ids)):
        raise APIError(422, "DUPLICATE_PATIENT_ID", "patients.csv 包含重复患者 ID，未生成导入批次。")
    groups = {key: [] for key in patient_ids}
    seen = set()
    for name, rows in chosen.items():
        if name == "patients.csv":
            continue
        for record in rows:
            row = record["data"]
            patient = row["PATIENT"]
            if patient not in groups:
                warnings["有事件无法关联患者，已排除。"] += 1
                continue
            fingerprint = (name, json.dumps(row, sort_keys=True))
            if fingerprint in seen:
                warnings["已删除完全重复的来源事件。"] += 1
                continue
            seen.add(fingerprint)
            timestamp = row.get("DATE") or row.get("START", "")
            try:
                when = _date(timestamp)
                if when is None:
                    raise ValueError("missing date")
                kind = {"conditions.csv": "diagnosis", "imaging_studies.csv": "imaging", "procedures.csv": "procedure",
                        "medications.csv": "medication"}.get(name, "observation")
                facts, fields = {}, {}
                mapping = {"code": "CODE", "description": "DESCRIPTION", "coding_system": "SYSTEM",
                           "unit": "UNITS", "encounter_id": "ENCOUNTER", "modality": "MODALITY_CODE",
                           "body_site": "BODYSITE_DESCRIPTION", "category": "CATEGORY", "record_type": "ENCOUNTERCLASS"}
                for key, column in mapping.items():
                    if row.get(column):
                        facts[key], fields[key] = row[column], column
                if name == "observations.csv":
                    value = row["VALUE"]
                    if row.get("TYPE", "").lower() == "numeric":
                        value = float(value)
                        if not math.isfinite(value):
                            raise ValueError("nonfinite value")
                    facts["observed_value"], fields["observed_value"] = value, "VALUE"
                title = row.get("DESCRIPTION") or f"{row.get('MODALITY_CODE', '')} 来源检查记录"
                groups[patient].append(_event("synthea_csv", record, name, when, kind, title, facts, fields, timestamp))
            except (ValueError, OverflowError):
                warnings["无法解析时间或数值的 Synthea 事件已排除。"] += 1
    cases = []
    provenance = _provenance("synthea_csv", digest)
    for record in sorted(patients, key=lambda record: record["data"]["Id"]):
        if len(cases) >= max_cases:
            break
        row = record["data"]
        case_id = f"SYNTHEA-{row['Id']}"
        events = groups[row["Id"]]
        try:
            if not events:
                raise ValueError("没有可定位日期的事件")
            if len(events) > 1000:
                raise ValueError("事件超过1000条，未截断；请先按明确的研究窗口筛选")
            birth = _date(row["BIRTHDATE"])
            first = min(date.fromisoformat(event["occurred_at"]) for event in events)
            age = first.year - birth.year - ((first.month, first.day) < (birth.month, birth.day))
            patient = {"age": age, "sex": {"M": "male", "F": "female"}.get(row["GENDER"], "unknown")}
            cases.append(_case(case_id, "Synthea 通用合成病程", patient, events, provenance, [
                "通用合成样本不保证包含肺癌；未导入姓名、地址、证件、保险或费用字段。",
                "年龄以最早导入事件日期计算。原始时间保留；同日序号仅为技术排序，不表示临床因果。",
                "未从诊断、操作或检查记录自动推断资料完整性；当前研究规则可能持续要求补充资料。",
            ]))
        except (ValueError, TypeError, AttributeError, ValidationError):
            rejected.append({"case_id": case_id[:80], "reason": "日期、年龄、标识或事件数量不符合契约；未截断或补造。"})
    return cases


TCIA_GROUPS = {
    "baseline": ("基线和病理字段 时间未定位", {"histology": "Histology", "pathological_t": "Pathological T stage", "pathological_n": "Pathological N stage", "pathological_m": "Pathological M stage", "grade": "Histopathological Grade", "smoking_status": "Smoking status"}),
    "molecular": ("分子字段 时间未定位", {"egfr_status": "EGFR mutation status", "kras_status": "KRAS mutation status", "alk_status": "ALK translocation status"}),
    "treatment": ("治疗和结局汇总 时间未定位", {"adjuvant_treatment": "Adjuvant Treatment", "chemotherapy": "Chemotherapy", "radiation": "Radiation", "recurrence_status": "Recurrence", "survival_status": "Survival Status"}),
}


def _tcia(raw, digest, max_cases, warnings, rejected, table_counts):
    rows = _rows(raw, {"Case ID", "Age at Histological Diagnosis", "Gender", "CT Date", "Histology"}, limit=10_000)
    table_counts["clinical.csv"] = len(rows)
    ids = [r["data"]["Case ID"] for r in rows]
    if len(ids) != len(set(ids)):
        raise APIError(422, "DUPLICATE_PATIENT_ID", "临床表含重复 Case ID，未生成导入批次。")
    cases = []
    provenance = _provenance("tcia_nsclc_csv", digest)
    for record in sorted(rows, key=lambda record: record["data"]["Case ID"]):
        if len(cases) >= max_cases:
            break
        row = record["data"]
        case_id = f"TCIA-NSCLC-RG-{row['Case ID']}"
        try:
            events, unplaced = [], []
            for column, kind, title, facts in [
                ("CT Date", "imaging", "CT 来源检查记录", {"modality": "CT"}),
                ("PET Date", "imaging", "PET 来源检查记录", {"modality": "PET"}),
                ("Date of Recurrence", "recurrence", "来源记录的复发日期", {}),
                ("Date of Last Known Alive", "follow_up", "最后已知存活日期记录", {}),
                ("Date of Death", "follow_up", "死亡日期记录", {}),
            ]:
                value = row.get(column, "")
                try:
                    when = _date(value, us=True)
                except ValueError:
                    warnings["无法解析的 TCIA 日期未进入时间线，已保留在未定位记录中。"] += 1
                    unplaced.append({"record_id": f"invalid_date_{len(unplaced)}", "title": f"{column} 日期无法解析",
                        "facts": {"original_date": value}, "source": provenance["source_name"],
                        "source_record_id": row["Case ID"], "source_record_locator": f"clinical.csv:line={record['row']}",
                        "source_fields": {"original_date": column}})
                    continue
                if when:
                    events.append(_event("tcia_nsclc_csv", record, "clinical.csv", when, kind, title,
                        {**facts, "recorded_date": value, "source_subject_id": row["Case ID"]},
                        {"recorded_date": column, "source_subject_id": "Case ID", **({"modality": column} if facts else {})}, value))
            for key, (title, mapping) in TCIA_GROUPS.items():
                facts, fields = {}, {}
                for field, column in mapping.items():
                    if column not in row:
                        continue
                    raw_value = row[column]
                    missing = raw_value.lower() in MISSING
                    facts[field] = None if missing else raw_value
                    fields[field] = record["columns"][column]
                    if missing:
                        facts[f"{field}_missing_reason"] = raw_value or "empty"
                        fields[f"{field}_missing_reason"] = record["columns"][column]
                        warnings["来源占位值已保留为未知，不转换为阴性或无事件。"] += 1
                if facts:
                    unplaced.append({"record_id": f"{key}_{row['Case ID']}", "title": title, "facts": facts,
                        "source": provenance["source_name"], "source_record_id": row["Case ID"],
                        "source_record_locator": f"{CATALOG['tcia_nsclc_csv']['filename']}!clinical.csv:line={record['row']}",
                        "source_fields": fields})
            patient = {"age": int(row["Age at Histological Diagnosis"]),
                       "sex": {"male": "male", "female": "female"}.get(row["Gender"].lower(), "unknown")}
            cases.append(_case(case_id, f"NSCLC 公开研究病例 {row['Case ID']}", patient, events, provenance, [
                "来源为公开去标识研究临床表；日期按来源 MM/DD/YYYY 转换，保留日期移位语义，不还原身份或真实日历。",
                "年龄为来源的组织学诊断年龄。无时间的病理、分子、治疗与结局汇总不进入历史评议。",
                "只导入日期及表内事实；未下载 DICOM，未推断影像或病理报告齐备，未推导手术日期。",
            ], unplaced=unplaced, disease="非小细胞肺癌公开研究队列"))
        except (ValueError, ValidationError):
            rejected.append({"case_id": case_id[:80], "reason": "年龄、标识或日期事件不符合契约；未补造。"})
    return cases


def _research_json(raw, digest, max_cases, warnings, rejected, table_counts):
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {"cases"} or not isinstance(payload["cases"], list):
            raise ValueError("顶层必须是仅含 cases 数组的对象")
        rows = payload["cases"]
        if not 1 <= len(rows) <= 50:
            raise ValueError("JSON 每份包含1至50个病例")
        cases = [ResearchCase.model_validate(row) for row in rows]
        if len({case.case_id for case in cases}) != len(cases):
            raise ValueError("病例 ID 重复")
        if any(case.version != 1 or any(event.introduced_in_version != 1 for event in case.timeline) for case in cases):
            raise ValueError("新导入病例及事件版本必须为1；后续资料请在病例页追加")
    except (ValueError, UnicodeError, RecursionError):
        # Do not echo a malformed document (which may contain private input).
        raise APIError(422, "INVALID_RESEARCH_JSON", "JSON 不符合研究病例契约；检查模板、必填来源、唯一 ID、日期及初始版本1。") from None
    table_counts["cases"] = len(cases)
    result = []
    for case in sorted(cases, key=lambda item: item.case_id)[:max_cases]:
        data = case.model_dump(mode="json")
        for source in data["provenance"]:
            source.update(artifact_sha256=digest, artifact_name="research_cases.json", mapping_version=MAPPING_VERSION)
        result.append(data)
    if len(cases) > max_cases:
        warnings["本批仅导入所选数量，按病例 ID 排序；其余病例未导入。"] += len(cases) - max_cases
    return result


def prepare_import(source: str, raw: bytes, max_cases: int = 10) -> PreparedImport:
    if source not in CATALOG:
        raise APIError(422, "UNSUPPORTED_DATASET", "当前支持 Synthea CSV ZIP、TCIA 临床 CSV 与研究 JSON。")
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise APIError(413, "DATASET_SIZE_LIMIT", "文件为空或超过20MB限制。")
    if type(max_cases) is not int or not 1 <= max_cases <= 50:
        raise APIError(422, "INVALID_IMPORT_LIMIT", "每批请选择1至50个病例。")
    digest = _hash(raw)
    warnings, rejected, table_counts = Counter(), [], {}
    adapter = {"synthea_csv": _synthea, "tcia_nsclc_csv": _tcia, "research_json": _research_json}[source]
    cases = adapter(raw, digest, max_cases, warnings, rejected, table_counts)
    batch_id = "imp_" + _hash(f"{source}:{digest}:{max_cases}:{MAPPING_VERSION}".encode())[:24]
    summary = {"batch_id": batch_id, "source": source, "source_name": CATALOG[source]["name"],
        "artifact_sha256": digest, "artifact_name": CATALOG[source]["filename"], "byte_count": len(raw),
        "mapping_version": MAPPING_VERSION, "requested_limit": max_cases, "case_count": len(cases),
        "event_count": sum(len(case["timeline"]) for case in cases),
        "unplaced_count": sum(len(case["unplaced_records"]) for case in cases),
        "table_counts": table_counts, "warnings": [{"message": message, "count": count} for message, count in warnings.items()],
        "rejected": rejected[:50], "rejected_count": len(rejected),
        "cases": [{"case_id": case["case_id"], "title": case["title"], "case_kind": case["case_kind"],
                   "event_count": len(case["timeline"]), "unplaced_count": len(case["unplaced_records"])} for case in cases]}
    return PreparedImport(cases, summary)
