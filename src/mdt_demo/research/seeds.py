"""Hand-authored synthetic cases. These are not Synthea, TCIA or clinical data."""

from .schemas import ResearchCase

SOURCE = "research_scenario_generator"
VERSION = "lung-scenarios-v1"


def _event(event_id, when, event_type, title, **facts):
    return {
        "event_id": event_id, "occurred_at": when, "event_type": event_type,
        "title": title, "facts": facts, "source": SOURCE, "source_record_id": None,
        "synthetic_extension": True, "confidence": "synthetic", "introduced_in_version": 1,
    }


def _case(case_id, title, age, sex, events):
    return ResearchCase.model_validate({
        "case_id": case_id, "title": title, "disease": "肺癌（完全虚构的研究场景）",
        "case_kind": "synthetic", "version": 1,
        "patient": {"age": age, "sex": sex},
        "current_question": "截至所选病程事件，相关资料是否充分且一致，是否可以进入人工资料复核？",
        "timeline": events,
        "provenance": [{
            "source_name": SOURCE, "source_url": None, "dataset_version": VERSION,
            "license": "项目自建合成研究场景", "synthetic": True,
        }],
    })


def seed_cases() -> list[ResearchCase]:
    """Return fresh objects, with explicit source and event-level synthetic flags."""
    return [
        _case("LUNG-SYN-001", "资料逐步补齐：影像、病理与分子记录", 58, "female", [
            _event("E001", "2026-01-05", "diagnosis", "初始资料登记（合成）",
                   disease_label="肺部异常待核验", imaging_complete=False, pathology_confirmed=False),
            _event("E002", "2026-01-12", "imaging", "影像报告与附件归档（合成）",
                   imaging_complete=True, imaging_record="合成影像资料已归档，未进行影像模型推理"),
            _event("E003", "2026-01-15", "pathology", "病理记录归档（合成）",
                   pathology_confirmed=True, histology="非小细胞肺癌标签，仅供资料流转模拟"),
            _event("E004", "2026-01-20", "molecular_test", "分子记录待补齐（合成）",
                   molecular_complete=False, molecular_record="报告尚未归档"),
            _event("E005", "2026-01-25", "molecular_test", "补充分子记录（合成）",
                   molecular_complete=True, molecular_record="合成分子资料已归档，无用药或治疗建议"),
            _event("E006", "2026-02-10", "follow_up", "随访资料归档（合成）",
                   follow_up_complete=True, follow_up_record="仅核对资料完整性，不判断疗效"),
        ]),
        _case("LUNG-SYN-002", "资料缺失：等待病理与分子记录", 63, "male", [
            _event("E001", "2026-03-02", "diagnosis", "初始资料尚不完整（合成）",
                   disease_label="肺癌研究任务待复核", pathology_confirmed=False),
            _event("E002", "2026-03-06", "imaging", "影像附件缺失（合成）",
                   imaging_complete=False, imaging_record="合成场景预设：附件尚未提供"),
            _event("E003", "2026-03-09", "molecular_test", "关键记录仍待提供（合成）",
                   molecular_complete=False, molecular_record="合成场景预设：分子报告尚未提供"),
        ]),
        _case("LUNG-SYN-003", "证据冲突：同日记录存在相反标记", 67, "female", [
            _event("E001", "2026-04-01", "diagnosis", "基础资料已登记（合成）",
                   pathology_confirmed=True, disease_label="肺癌研究资料复核任务"),
            _event("E002", "2026-04-03", "imaging", "同日核对记录 A（合成）",
                   imaging_complete=True, progression_confirmed=False,
                   record_note="预设冲突记录 A，不能作为真实病情判断"),
            _event("E003", "2026-04-03", "imaging", "同日核对记录 B（合成）",
                   imaging_complete=True, progression_confirmed=True,
                   record_note="预设冲突记录 B，与记录 A 同日且无替代关系"),
            _event("E004", "2026-04-04", "progression", "触发矛盾资料复核（合成）",
                   progression_event_received=True,
                   review_note="需保留同日相反记录，等待人工核验，不能强制形成共识"),
        ]),
    ]
