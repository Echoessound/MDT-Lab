"""Convert the checksum-pinned TCIA ACRIN 6668 clinical file set 1 to Research JSON."""
import argparse
import csv
from datetime import date, timedelta
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

from mdt_demo.research.datasets import prepare_import


CHECKSUM = "f788dd16488900a3aab35b2c24699e5c2841aa8031e928a8fced9d8edf0ab8ee"
COLLECTION = "https://www.cancerimagingarchive.net/collection/acrin-nsclc-fdg-pet/"
SOURCE = "tcia_acrin_6668"
ORIGIN = date(1960, 1, 1)
DIRECTORY = "ACRIN 6668 NSCLC FDG PET - ACRIN Data TCIA Anonymized"
PROVENANCE = {
    "source_name": SOURCE, "source_url": COLLECTION, "synthetic": False,
    "dataset_version": "ACRIN 6668 v2 / clinical file set 1",
    "license": "CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/)",
    "citation": "Kinahan P, Muzi M, Bialecki B, Herman B, Coombs L. Data from the ACRIN 6668 Trial NSCLC-FDG-PET (Version 2). TCIA, 2019. https://doi.org/10.7937/tcia.2019.30ilqfcl",
}
PROGRESSION = {
    "1": "无疾病证据或无进展证据", "2": "首次报告进展", "3": "既往已报告进展，本次无新部位",
    "4": "既往已报告进展，本次出现新部位",
}
QUALITY = {"1": "充分", "2": "欠佳", "3": "充分", "4": "欠佳", "5": "不足"}


def table(archive, name):
    with archive.open(f"{DIRECTORY}/{name}.csv") as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="latin1", newline=""))
        for row in reader:
            yield reader.line_num, row


def event(form, line, suffix, day_field, row, kind, title, fields):
    day = int(row[day_field])
    source_fields = {"offset_days": day_field}
    facts = {"offset_days": day}
    for key, (column, value) in fields.items():
        if value is not None:
            source_fields[key] = column
            facts[key] = value
    return {
        "event_id": f"{form}_{line:05d}_{suffix}",
        "occurred_at": (ORIGIN + timedelta(days=day)).isoformat(),
        "event_type": kind, "title": title, "facts": facts, "source": SOURCE,
        "source_record_id": f"{form}_{line:05d}", "source_record_locator": f"file-set-1!{form}.csv:line={line}",
        "source_fields": source_fields, "original_timestamp": f"day {day:+d}",
        "time_note": f"{form}.{day_field} 相对 TCIA 去标识基准日的天数，仅精确到日。",
        "synthetic_extension": False, "confidence": "source_record",
    }


def imaging_events(line, row):
    if row["ime1"] == "1" and row["rec"]:
        yield event("IM", line, "receipt", "rec", row, "observation", "收到 PET 未完成记录",
                    {"pet_completed": ("ime1", False)})
    if row["ime1"] != "2":
        return
    phase = {"1": "治疗前", "2": "治疗后"}.get(row["ime5"])
    fields = {"pet_completed": ("ime1", True), "pet_phase": ("ime5", phase)}
    if row["IMe10d"]:
        yield event("IM", line, "1_scan", "IMe10d", row, "imaging", f"{phase or ''} FDG-PET 检查".strip(), fields)
    if row["IMe11d"]:
        if row["IMe10d"] and int(row["IMe11d"]) < int(row["IMe10d"]):
            raise ValueError(f"PET interpretation precedes acquisition at IM.csv:{line}")
        fields["image_quality"] = ("ime12", QUALITY.get(row["ime12"]))
        for column, key in (("ime18", "lung_suv_peak_assessment_1"), ("ime43", "lung_suv_peak_assessment_2")):
            if row[column]:
                fields[key] = (column, float(row[column]))
        yield event("IM", line, "2_read", "IMe11d", row, "imaging", f"{phase or ''} PET 本地判读".strip(), fields)


def radiotherapy_events(line, row):
    if row["t1e1"] == "1" and row["rec"]:
        yield event("T1", line, "receipt", "rec", row, "observation", "收到放疗未开始记录",
                    {"radiotherapy_started": ("t1e1", False)})
    if row["t1e1"] == "2":
        for day, suffix, title in (("T1e2d", "first", "首次放疗"), ("T1e3d", "last", "末次放疗")):
            if row[day]:
                yield event("T1", line, suffix, day, row, "treatment", title, {"radiotherapy_started": ("t1e1", True)})


def follow_up_events(line, row):
    if not row["rec"] or not row["F1e1d"]:
        return
    if int(row["rec"]) < int(row["F1e1d"]):
        raise ValueError(f"Follow-up form received before assessment at F1.csv:{line}")
    fields = {"assessment_offset_days": ("F1e1d", int(row["F1e1d"])),
              "progression_assessment": ("f1e8", PROGRESSION.get(row["f1e8"]))}
    yield event("F1", line, "receipt", "rec", row, "follow_up", "收到临床随访表", fields)


def build(raw):
    if hashlib.sha256(raw).hexdigest() != CHECKSUM:
        raise ValueError("Source ZIP differs from the verified TCIA clinical file set 1 release")
    cases = {}
    with ZipFile(io.BytesIO(raw)) as archive:
        enrollment = sorted(table(archive, "A0"), key=lambda item: int(item[1]["cn"]))
        for line, row in enrollment[:12]:
            subject = row["cn"]
            fields = {
                "pathologically_proven_nsclc": ("a0e34", {"1": False, "2": True}.get(row["a0e34"])),
                "clinical_stage_iib_or_iii": ("a0e36", {"1": False, "2": True}.get(row["a0e36"])),
            }
            cases[subject] = {
                "case_id": f"ACRIN-6668-{int(subject):03d}", "case_kind": "public_research",
                "title": "非小细胞肺癌 · 放化疗前后 PET 研究", "disease": "非小细胞肺癌",
                "patient": {"age": int(row["entryage"]), "sex": {"1": "male", "2": "female"}[row["a0e11"]]},
                "current_question": "截至所选截点，影像判读、放疗和随访有哪些可引用记录，哪些资料仍缺失？",
                "timeline": [event("A0", line, "register", "A0e17d", row, "observation", "试验入组登记", fields)],
                "provenance": [PROVENANCE],
                "data_notes": [
                    "来源日期以 1960-01-01 表示共同基准日，允许负偏移。年龄为登记年龄。",
                    "PET 检查、判读和放疗按来源发生日重放，随访状态仅自研究中心收到该表之日引入。同日按事件编号确定可复现顺序。",
                    f"映射 acrin-6668-v1；原始临床 ZIP SHA-256 {CHECKSUM}。",
                ],
            }
        for name, convert in (("IM", imaging_events), ("T1", radiotherapy_events), ("F1", follow_up_events)):
            for line, row in table(archive, name):
                if row["cn"] in cases:
                    cases[row["cn"]]["timeline"].extend(convert(line, row))
    for case in cases.values():
        case["timeline"].sort(key=lambda item: (item["occurred_at"], item["event_id"]))
    data = (json.dumps({"cases": list(cases.values())}, ensure_ascii=False, indent=2) + "\n").encode()
    prepared = prepare_import("research_json", data, 12)
    if len(prepared.cases) != 12:
        raise ValueError("Expected 12 unique cases")
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_bytes(build(args.archive.read_bytes()))
