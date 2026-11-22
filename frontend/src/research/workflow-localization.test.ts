import { describe, expect, it } from 'vitest';
import { ablationMatrixSchema, annotationSchema, attachmentSchema, dataCapabilitySchema, imagingPipelineSchema, libraryEvaluationSchema, workflowPlanSchema } from './schemas';
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
    expect(formatFactValue('CT')).toBe('CT 计算机断层扫描');
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
      clinical_phase: '影像检查记录复核',
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
      imaging_summary: { study_count: 1, overall_qc_status: 'not_assessed', overall_record_status: 'documented' },
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
      pipeline_version: 'imaging-records-v2',
      study_count: 1,
      input_kind: 'event_metadata',
      overall_qc_status: 'not_assessed',
      overall_record_status: 'documented',
      studies: [{
        study_id: 'IMG_E002', event_id: 'E002', occurred_at: '2026-01-12', title: '影像报告与附件归档',
        modality: null, anatomical_site: null, source_name: 'research_scenario_generator',
        dataset_version: 'lung-scenarios-v1', synthetic: true, source_record_id: null,
        source_record_locator: null, artifact_sha256: null, record_status: 'documented',
        conflict_evidence_ids: [], record_fields: [{
          fact_key: 'imaging_complete', value: true, evidence_id: 'E002:imaging_complete', source_field: null,
        }],
        qc_status: 'not_assessed', qc_score: null, dicom_metadata: null, radiomics: null, svg_slice: null,
      }],
    });
    expect(imaging.studies[0].record_fields[0].evidence_id).toBe('E002:imaging_complete');
    expect(imagingPipelineSchema.safeParse({
      ...imaging, studies: [{ ...imaging.studies[0], qc_status: 'passed', radiomics: { lesion_diameter_mm: 22.4 } }],
    }).success).toBe(false);

    const ablation = ablationMatrixSchema.parse({
      protocol_version: 'mock-matrix-v2',
      execution_mode: 'mock',
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
          trajectory_id: 'B3',
          input_case_version: 1,
          input_trigger_event_id: 'E003',
          visible_events: 3,
          name: 'B3 · 完整门控工作流（本系统）',
          category: '核心机制',
          routing_strategy: '事件路由 + 安全门控',
          selected_agents: ['oncology', 'pathology'],
          agent_calls: 2,
          discussion_rounds: 0,
          valid_opinions: 2,
          failed_calls: 0,
          gate_applied: true,
          pre_gate_decision: 'READY_FOR_REVIEW',
          final_decision: 'READY_FOR_REVIEW',
          missing_count: 0,
          unresolved_conflicts: 0,
          key_finding: '节省 50% 调用',
        },
      ],
    });
    expect(ablation.call_saving_pct).toBe(50);
    const empty = {
      ...ablation.methods[0], method_id: 'B0', trajectory_id: 'B0', selected_agents: ['general_reviewer'],
      agent_calls: 1, failed_calls: 1, valid_opinions: 0, gate_applied: false, pre_gate_decision: null, final_decision: null,
    };
    expect(ablationMatrixSchema.safeParse({ ...ablation, methods: [empty] }).success).toBe(true);
  });

  it('validates real attachments, data capabilities, blind annotations and library evaluation payloads', () => {
    expect(sourceNameLabel('tcga_cbioportal_nsclc')).toBe('TCGA / cBioPortal 肺癌公开队列');
    expect(attachmentSchema.parse({
      attachment_id: 'att_01', case_id: 'LUNG-SYN-001', event_id: 'E002',
      filename: 'ct_slice.dcm', mime_type: 'application/dicom', kind: 'dicom',
      byte_count: 2048, sha256: 'a'.repeat(64), uploaded_at: '2026-11-22T00:00:00+00:00',
      metadata: { format: 'DICOM Part 10', pii_group_0010_skipped: 1 },
    }).kind).toBe('dicom');
    expect(dataCapabilitySchema.parse({
      modality_id: 'real_medical_attachments', title: '真实医学影像', formats: ['.dcm', '.png'],
      processing: '内容寻址与头解析', temporal_guard: '剥离 0x0010 隐私标签', status: '已落地',
    }).formats).toContain('.dcm');
    expect(annotationSchema.parse({
      scenario_id: 'LUNG-SYN-001:v1:E002', case_id: 'LUNG-SYN-001', case_version: 1,
      trigger_event_id: 'E002', annotator_id: 'reviewer_01',
      required_agents: ['oncology', 'radiology'], expected_decision: 'NEED_MORE_INFORMATION',
      missing_fields: ['pathology_confirmed'], rationale: '尚未提供病理分型。',
      updated_at: '2026-11-22T00:00:00+00:00',
    }).required_agents).toHaveLength(2);
    expect(libraryEvaluationSchema.parse({
      protocol_version: 'mdt-library-eval-v1', execution_mode: 'mock', trigger_scope: 'all',
      family_count: 3, scenario_count: 13, annotated_scenario_count: 1, memory_impact_scenarios: 4,
      methods: [{
        method_id: 'B3', name: 'B3 · 完整工作流', category: '基线对照', routing_strategy: '事件路由',
        scenario_count: 13, total_calls: 36, avg_calls: 2.77, avg_discussion_rounds: 0.46,
        call_saving_vs_fixed_pct: 40.0,
        decisions: { READY_FOR_REVIEW: 4, NEED_MORE_INFORMATION: 6, DEFER_DECISION: 3, NO_OUTPUT: 0 },
        gate_interceptions: 1, annotated_count: 1, specialist_recall: 1.0,
        false_pass_rate: 0.0, over_deferral_rate: null, accuracy: 1.0,
      }],
      scenarios: [{
        scenario_id: 'LUNG-SYN-001:v1:E002', case_family_id: 'LUNG-SYN-001', case_id: 'LUNG-SYN-001',
        case_version: 1, case_title: '资料逐步补齐', trigger_event_id: 'E002',
        trigger_event_title: '影像归档', trigger_event_type: 'imaging', occurred_at: '2026-01-12',
        visible_events: 2, annotated: true, b3_decision: 'NEED_MORE_INFORMATION', b3_calls: 4, fixed_calls: 8,
      }],
      latex_table: '\\begin{table}\\end{table}',
      scores_csv: 'scenario_id,method_id\n',
    }).family_count).toBe(3);
  });
});
