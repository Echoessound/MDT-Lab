import { describe, expect, it } from 'vitest';
import { ablationMatrixSchema, imagingPipelineSchema, workflowPlanSchema } from './schemas';
import { computeSlideDirection } from './workspace-controls';
import {
  conflictDimensionLabel,
  errorCodeLabel,
  factKeyLabel,
  formatFactValue,
  modeNameZh,
  nodeNameLabel,
  providerLabelZh,
  ruleIdLabel,
  safetyCheckLabel,
  sourceNameLabel,
  toolNameLabel,
} from './zh-dict';

describe('Chinese localization dictionary (zh-dict)', () => {
  it('translates clinical fact keys, missing reason suffixes, and common dataset values', () => {
    expect(factKeyLabel('imaging_complete')).toBe('影像资料齐备');
    expect(factKeyLabel('pathology_confirmed')).toBe('病理学已确诊');
    expect(factKeyLabel('egfr_status_missing_reason')).toBe('EGFR 基因突变状态（缺失原因）');
    expect(formatFactValue(true)).toBe('是（已确认）');
    expect(formatFactValue(false)).toBe('否（待补齐）');
    expect(formatFactValue(null)).toBe('未记录');
    expect(formatFactValue('Adenocarcinoma')).toBe('肺腺癌');
    expect(formatFactValue('Wildtype')).toBe('野生型（未见突变）');
    expect(formatFactValue('CT')).toBe('胸部 CT 断层扫描');
  });

  it('translates provenance sources, checks, conflicts, nodes, tools, rules, errors and providers', () => {
    expect(sourceNameLabel('tcia_nsclc_radiogenomics')).toBe('TCIA 肺癌影像基因组公开队列');
    expect(safetyCheckLabel('temporal_boundary')).toBe('纵向时间截点防泄漏核验');
    expect(conflictDimensionLabel('source_fact_conflict')).toBe('同日多源记录矛盾');
    expect(nodeNameLabel('targeted_discussion')).toBe('定向协同协商');
    expect(toolNameLabel('evidence_lookup')).toBe('冻结证据注册表检索');
    expect(ruleIdLabel('event_imaging')).toBe('影像复核调度规则');
    expect(errorCodeLabel('invalid_evidence')).toBe('证据引用未通过冻结注册表核验');
    expect(modeNameZh('mock')).toBe('本地规则仿真');
    expect(modeNameZh('llm')).toBe('大模型推演');
    expect(providerLabelZh('mock', 'deterministic-research-v1')).toContain('内置确定性规则引擎');
  });
});

describe('directional tab transition helper', () => {
  const tabs = [
    { key: 'timeline' as const },
    { key: 'workflow' as const },
    { key: 'routing' as const },
    { key: 'sources' as const },
  ];

  it('computes slide direction accurately when navigating tabs', () => {
    expect(computeSlideDirection(tabs, 'timeline', 'workflow')).toBe('right');
    expect(computeSlideDirection(tabs, 'sources', 'timeline')).toBe('left');
    expect(computeSlideDirection(tabs, 'routing', 'routing')).toBe('none');
  });
});

describe('workflow designer, imaging pipeline, and ablation schemas', () => {
  it('validates backend workflow plan, imaging pipeline, and ablation matrix payloads', () => {
    const plan = workflowPlanSchema.parse({
      workflow_id: 'wf_LUNG-SYN-001_v1_E002',
      case_id: 'LUNG-SYN-001',
      case_version: 1,
      trigger_event_id: 'E002',
      trigger_event_title: '影像报告与附件归档（合成）',
      trigger_event_type: 'imaging',
      strategy_version: 'case-adaptive-workflow-v2',
      clinical_phase: '多模态医学影像与病灶特征复核',
      complexity_level: 'elevated',
      complexity_label: '资料待补核查态',
      visible_event_count: 2,
      excluded_future_event_count: 4,
      unplaced_record_count: 0,
      source_conflict_count: 0,
      selected_agents: ['oncology', 'radiology'],
      specialist_plan: [
        {
          agent_id: 'oncology',
          agent_label: '肿瘤内科',
          selected: true,
          routing_type: '基础事件命中',
          focus: '统筹全病程诊疗时间线',
          clinical_tasks: ['核对截至 E002 的 2 条事件'],
        },
      ],
      workflow_stages: [
        {
          stage_id: 'stage_intake_freeze',
          step_number: 1,
          title: '纵向病程冻结与防泄漏截断',
          category: 'ingestion',
          status: 'active',
          automated_operator: 'freeze_context',
          description: '锁定截至 E002 的事件。',
        },
      ],
      completeness: {
        trigger_event_id: 'E002',
        trigger_event_type: 'imaging',
        required_fields: [
          { fact_key: 'imaging_complete', fact_label: '影像资料齐备', strict_satisfied: true, semantic_satisfied: true },
        ],
        strict_missing: ['pathology_confirmed'],
        strict_missing_labels: ['病理学已确诊'],
        semantic_inferred: [],
        post_inference_missing: ['pathology_confirmed'],
        post_inference_missing_labels: ['病理学已确诊'],
        strict_completeness_score: 50,
        semantic_completeness_score: 50,
        can_auto_enrich: false,
        recommended_facts: {},
      },
      imaging_summary: { study_count: 1, overall_qc_status: 'passed' },
      predicted_decisions: {
        strict_rule_decision: 'NEED_MORE_INFORMATION',
        semantic_enriched_decision: 'NEED_MORE_INFORMATION',
      },
    });
    expect(plan.selected_agents).toEqual(['oncology', 'radiology']);

    const imaging = imagingPipelineSchema.parse({
      case_id: 'LUNG-SYN-001',
      case_version: 1,
      trigger_event_id: 'E002',
      pipeline_version: 'medical-imaging-pipeline-v1',
      study_count: 1,
      overall_qc_status: 'passed',
      studies: [
        {
          study_id: 'IMG_E002',
          event_id: 'E002',
          occurred_at: '2026-01-12',
          title: '影像报告与附件归档',
          modality: 'CT',
          modality_label: '高分辨胸部增强 CT (HRCT)',
          anatomical_site: '右肺上叶尖后段 (RUL)',
          qc_status: 'passed',
          qc_score: 94,
          qc_message: '通过自动化影像质控',
          dicom_metadata: {
            series_uid: '1.2.840.113619.2.55.1234.1',
            slice_thickness_mm: 1.25,
            matrix_size: '512 × 512',
            window_presets: {
              lung: { label: '肺窗 (W:1500 / L:-600)', width: 1500, level: -600 },
            },
          },
          radiomics: {
            lesion_diameter_mm: 22.4,
            hu_mean: -15,
            suvmax: 4.6,
            glcm_entropy: 4.32,
            sphericity: 0.74,
            lymph_node_mm: 9.5,
            morphology_tags: ['分叶征', '短毛刺征'],
          },
          svg_slice: {
            lesion_cx: 88,
            lesion_cy: 104,
            lesion_radius: 13,
            contour_polygon: '100,104 95,112 88,118',
            is_left_lung: false,
            has_artifact_or_missing: false,
            has_conflict_marker: false,
          },
          pipeline_steps: [
            { step_id: 'dicom_normalization', title: 'DICOM 序列校验', status: 'passed', detail: '层厚 1.25mm' },
          ],
        },
      ],
    });
    expect(imaging.studies[0].radiomics.lesion_diameter_mm).toBe(22.4);

    const ablation = ablationMatrixSchema.parse({
      case_id: 'LUNG-SYN-001',
      case_version: 1,
      trigger_event_id: 'E003',
      visible_events: 3,
      call_saving_pct: 50,
      fixed_total_calls: 4,
      routed_total_calls: 2,
      methods: [
        {
          method_id: 'B3',
          name: 'B3 · 完整门控工作流（本系统）',
          category: '核心机制',
          routing_strategy: '事件路由 + 安全门控',
          selected_agents: ['oncology', 'pathology'],
          agent_calls: 2,
          discussion_rounds: 0,
          pre_gate_decision: 'READY_FOR_REVIEW',
          final_decision: 'READY_FOR_REVIEW',
          missing_count: 0,
          unresolved_conflicts: 0,
          key_finding: '节省 50% 调用',
        },
      ],
    });
    expect(ablation.call_saving_pct).toBe(50);
  });
});
