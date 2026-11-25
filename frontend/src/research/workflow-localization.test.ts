import { describe, expect, it } from 'vitest';
import { jumpResults } from '../console/navigation';
import { researchKeys } from './query-keys';
import { ablationMatrixSchema, agreementReportSchema, annotationSchema, blindMaterialSchema, attachmentSchema, consensusMetricsSchema, dataCapabilitySchema, imagingPipelineSchema, libraryEvaluationSchema, longitudinalDynamicsSchema, routingModeSchema, temporalAuditSchema, workflowPlanSchema } from './schemas';
import { toggleCutoffTrigger } from './workspace-case';
import { computeSlideDirection } from './workspace-controls';
import {
  clinicalCaseTitle,
  conflictDimensionLabel,
  errorCodeLabel,
  factKeyLabel,
  formatFactValue,
  modeNameZh,
  nodeNameLabel,
  providerLabelZh,
  routingModeNameZh,
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

  it('requires version-bound blind material and keeps legacy references readable', () => {
    const scenario = 'LUNG-SYN-003:v1:E002';
    const material = { scenario_id: scenario, input_sha256: 'a'.repeat(64),
      events: [{ event_id: 'E002', event_type: 'imaging', occurred_at: '2026-04-03',
        title: '合成病程记录', facts: { progression_confirmed: false } }] };
    expect(blindMaterialSchema.parse(material).events[0].facts.progression_confirmed).toBe(false);
    expect(blindMaterialSchema.safeParse({ ...material, input_sha256: 'outdated' }).success).toBe(false);
    const reference = { scenario_id: scenario, case_id: 'LUNG-SYN-003', case_version: 1,
      trigger_event_id: 'E002', annotator_id: 'reviewer', required_agents: ['radiology'],
      expected_decision: 'NEED_MORE_INFORMATION', missing_fields: ['histology'], rationale: '', updated_at: '2026-11-23' };
    expect(annotationSchema.parse(reference).evidence_ids).toEqual([]);
    const bound = { ...reference, input_sha256: material.input_sha256, evidence_ids: ['E002:progression_confirmed'] };
    expect(annotationSchema.parse(bound)).toEqual(bound);
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
      protocol_version: 'mdt-library-eval-v2', execution_mode: 'mock', trigger_scope: 'all',
      family_count: 3, scenario_count: 13, annotated_scenario_count: 1, memory_impact_scenarios: 4,
      methods: [{
        method_id: 'B3', name: 'B3 · 完整工作流', category: '基线对照', routing_strategy: '事件路由',
        scenario_count: 13, total_calls: 36, avg_calls: 2.77, avg_discussion_rounds: 0.46,
        call_saving_vs_fixed_pct: 40.0,
        decisions: { READY_FOR_REVIEW: 4, NEED_MORE_INFORMATION: 6, DEFER_DECISION: 3, NO_OUTPUT: 0 },
        gate_interceptions: 1, annotated_count: 1, specialist_recall: 1.0,
        false_pass_rate: 0.0, false_pass_count: 0, false_pass_denominator: 1,
        over_deferral_rate: null, over_deferral_count: 0, over_deferral_denominator: 0, accuracy: 1.0,
      }],
      scenarios: [{
        scenario_id: 'LUNG-SYN-001:v1:E002', case_family_id: 'LUNG-SYN-001', case_id: 'LUNG-SYN-001',
        case_version: 1, case_title: '资料逐步补齐', trigger_event_id: 'E002',
        trigger_event_title: '影像归档', trigger_event_type: 'imaging', occurred_at: '2026-01-12',
        visible_events: 2, annotated: true, memory_impacted: true, b3_decision: 'NEED_MORE_INFORMATION', b3_calls: 4, fixed_calls: 8,
      }],
      paired_statistics: {
        bootstrap_resamples: 1000,
        bootstrap_seed: 2026,
        cluster_unit: 'case_family_id',
        family_count: 3,
        sample_size_note: '小样本提示',
        contrasts: [{
          contrast_id: 'B3_vs_A3',
          label: 'B3 vs A3',
          metric_name: '专科调用节省比例',
          point_estimate: 40.0,
          ci_low: 25.0,
          ci_high: 50.0,
          unit: '%',
          discordant_scenarios: 8,
          total_scenarios: 13,
          eligible_scenarios: 13, eligible_family_count: 3, metric_numerator: 12, metric_denominator: 30,
          annotated_pairs: 1, b3_only_correct: 0, comparator_only_correct: 0,
          mcnemar_status: 'ok', mcnemar_exact_p: 1.0,
          interpretation: '计算开销压缩幅度',
        }],
      },
      latex_table: '\\begin{table}\\end{table}',
      scores_csv: 'scenario_id,method_id\n',
    }).paired_statistics?.contrasts).toHaveLength(1);
  });

  it('validates multi-rater agreement report and independent temporal audit payloads', () => {
    const agreement = agreementReportSchema.parse({
      protocol_version: 'annotation-protocol-v1',
      scenarios_with_submissions: 2,
      multi_rated_scenarios: 2,
      disputed_count: 1,
      adjudicated_count: 1,
      unadjudicated_disputes: 0,
      annotator_counts: { rater_1: 2, rater_2: 2 },
      decision_agreement: {
        pair_count: 2,
        raw_agreement: 0.5,
        expected_agreement: 0.375,
        cohens_kappa: 0.2,
        confusion_matrix: {
          READY_FOR_REVIEW: { READY_FOR_REVIEW: 1, NEED_MORE_INFORMATION: 0, DEFER_DECISION: 0 },
          NEED_MORE_INFORMATION: { READY_FOR_REVIEW: 0, NEED_MORE_INFORMATION: 0, DEFER_DECISION: 1 },
          DEFER_DECISION: { READY_FOR_REVIEW: 0, NEED_MORE_INFORMATION: 1, DEFER_DECISION: 0 },
        },
      },
      specialist_agreement: {
        pair_count: 2,
        mean_jaccard: 0.6667,
        exact_set_agreement: 0.5,
        per_role: {
          oncology: { pair_count: 2, raw_agreement: 1.0, expected_agreement: 1.0, cohens_kappa: null },
        },
      },
      evidence_mean_jaccard: 1.0,
      missing_fields_mean_jaccard: 0.0,
      disputed_scenarios: [],
      summary_note: '测试摘要',
    });
    expect(agreement.decision_agreement.cohens_kappa).toBe(0.2);

    const audit = temporalAuditSchema.parse({
      audit_version: 'temporal-boundary-audit-v1',
      passed: true,
      case_id: 'LUNG-SYN-001',
      case_version: 1,
      trigger_event_id: 'E002',
      cutoff_date: '2026-01-12',
      original_event_count: 6,
      allowed_event_count: 2,
      excluded_future_event_count: 4,
      original_unplaced_count: 0,
      audited_evidence_count: 5,
      audited_opinion_citations: 4,
      audited_claims: 4,
      same_day_events_on_cutoff: ['E002'],
      future_dates_in_question: [],
      leaked_count: 0,
      leaked_items: [],
      checks: [{ code: 'snapshot_timeline_boundary', status: 'passed', message: '通过' }],
    });
    expect(audit.passed).toBe(true);
  });

  it('provides centralized query keys and Spotlight quick actions for the research loop', () => {
    expect(researchKeys.caseDetail('LUNG-SYN-001', 2)).toEqual(['research-case', 'LUNG-SYN-001', 2]);
    expect(researchKeys.reviewPanelOwn('LUNG-SYN-001:v1:E002', 'rater_1')).toEqual([
      'review-panel-own', 'LUNG-SYN-001:v1:E002', 'rater_1',
    ]);
    const initialJump = jumpResults('', [], []);
    expect(initialJump.some(item => item.href === '/research/experiments?view=annotate')).toBe(true);
    const filteredJump = jumpResults('盲标', [], []);
    expect(filteredJump[0]?.href).toContain('/research/experiments');
  });

  it('toggles cutoff scrubber nodes cleanly (click selects, clicking selected node cancels)', () => {
    expect(toggleCutoffTrigger(null, 'E004')).toBe('E004');
    expect(toggleCutoffTrigger('E004', 'E004')).toBe('');
    expect(toggleCutoffTrigger('E004', 'E002')).toBe('E002');
    expect(toggleCutoffTrigger('', 'E006')).toBe('E006');
    expect(toggleCutoffTrigger('E006', 'E006')).toBe('');
  });

  it('normalizes legacy workflow-progress titles to clinical summaries and validates adaptive metrics schemas', () => {
    expect(routingModeSchema.parse('adaptive')).toBe('adaptive');
    expect(routingModeNameZh('adaptive')).toBe('风险自适应路由');
    expect(clinicalCaseTitle({
      case_id: 'LUNG-SYN-001',
      title: '资料逐步补齐：影像、病理与分子记录',
      disease: '肺癌',
      case_kind: 'synthetic',
      version: 1,
      patient: { age: 58, sex: 'female' },
      current_question: null,
      timeline: [],
      provenance: [],
      unplaced_records: [],
      data_notes: [],
    })).toBe('右肺上叶实性占位伴纵隔淋巴结待查');

    const consensus = consensusMetricsSchema.parse({
      run_id: 'run_1',
      case_id: 'LUNG-SYN-001',
      case_version: 1,
      trigger_event_id: 'E001',
      routing_mode: 'adaptive',
      initial_entropy: 0.6309,
      final_entropy: 0.0,
      entropy_reduction: 0.6309,
      opinions_revised_count: 1,
      converged: true,
      coverage_ratio: 1.0,
      evidence_jaccard_mean: 1.0,
      claim_agreement_rate: 1.0,
      unique_cited_evidence_count: 2,
      evidence_utilization_rate: 0.6667,
      consensus_score: 0.85,
      safety_veto_applied: false,
      final_decision: 'NEED_MORE_INFORMATION',
    });
    expect(consensus.entropy_reduction).toBeGreaterThan(0);

    const dyn = longitudinalDynamicsSchema.parse({
      case_id: 'LUNG-SYN-001',
      case_version: 1,
      checkpoint_count: 1,
      first_ready_event_id: null,
      transition_count: 0,
      decision_oscillation_count: 0,
      cumulative_calls: { event: 2, adaptive: 3, fixed: 4 },
      event_saving_vs_fixed_pct: 50,
      adaptive_saving_vs_fixed_pct: 25,
      adaptive_risk_escalations: 1,
      checkpoints: [{
        event_id: 'E001',
        occurred_at: '2026-01-05',
        event_type: 'diagnosis',
        title: '初诊登记',
        event_selected_agents: ['oncology', 'pathology'],
        adaptive_selected_agents: ['oncology', 'radiology', 'pathology'],
        event_calls: 2,
        adaptive_calls: 3,
        fixed_calls: 4,
        missing_count: 2,
        source_conflict_count: 0,
        event_decision: 'NEED_MORE_INFORMATION',
        adaptive_decision: 'NEED_MORE_INFORMATION',
        imaging_staleness_days: null,
      }],
    });
    expect(dyn.adaptive_risk_escalations).toBe(1);
  });
});
