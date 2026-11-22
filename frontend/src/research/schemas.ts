import { z } from 'zod';

export const roleSchema = z.enum(['oncology', 'radiology', 'surgery', 'pathology']);
export const decisionSchema = z.enum(['READY_FOR_REVIEW', 'NEED_MORE_INFORMATION', 'DEFER_DECISION']);
export const eventTypeSchema = z.enum(['diagnosis', 'imaging', 'pathology', 'molecular_test', 'procedure', 'treatment', 'medication', 'toxicity', 'follow_up', 'progression', 'recurrence', 'observation']);
export const scalarSchema = z.union([z.string(), z.number(), z.boolean(), z.null()]);
export const factsSchema = z.record(z.string(), scalarSchema);
export const clinicalEventSchema = z.object({
  event_id: z.string(), occurred_at: z.string(), event_type: eventTypeSchema,
  title: z.string(), facts: factsSchema, source: z.string(), source_record_id: z.string().nullable(),
  synthetic_extension: z.boolean(), confidence: z.string(), introduced_in_version: z.number().int(),
  original_timestamp: z.string().nullable().optional(), source_record_locator: z.string().nullable().optional(),
  source_fields: z.record(z.string(), z.string()).default({}), time_note: z.string().nullable().optional(),
});
export const caseSchema = z.object({
  case_id: z.string(), title: z.string(), disease: z.string(), case_kind: z.enum(['synthetic', 'public_research', 'mixed']),
  version: z.number().int().positive(), patient: z.object({ age: z.number(), sex: z.string() }),
  current_question: z.string().nullable(), timeline: z.array(clinicalEventSchema),
  provenance: z.array(z.object({ source_name: z.string(), source_url: z.string().nullable(), dataset_version: z.string(), license: z.string(), synthetic: z.boolean(),
    artifact_sha256: z.string().nullable().optional(), artifact_name: z.string().nullable().optional(),
    mapping_version: z.string().nullable().optional(), citation: z.string().nullable().optional() })),
  unplaced_records: z.array(z.object({ record_id: z.string(), title: z.string(), facts: factsSchema,
    source: z.string(), source_record_id: z.string(), source_record_locator: z.string(),
    source_fields: z.record(z.string(), z.string()), exclusion_reason: z.string() })).default([]),
  data_notes: z.array(z.string()).default([]),
});
export const evidenceSchema = z.object({
  evidence_id: z.string(), event_id: z.string(), fact_key: z.string(), value: scalarSchema,
  source_name: z.string(), source_record_id: z.string().nullable(), dataset_version: z.string(),
  synthetic: z.boolean(), quote_or_fact: z.string(),
  artifact_sha256: z.string().nullable().optional(), source_record_locator: z.string().nullable().optional(),
  source_field: z.string().nullable().optional(),
});
export const opinionSchema = z.object({
  opinion_id: z.string(), agent_id: roleSchema, decision: decisionSchema, summary: z.string(),
  evidence_ids: z.array(z.string()), evidence_refs: z.array(evidenceSchema),
  claims: z.array(z.object({ fact_key: z.string(), value: scalarSchema, evidence_id: z.string() })),
  missing_information: z.array(z.string()), confidence: z.enum(['low', 'medium', 'high']),
  model_info: z.object({ provider: z.string(), model: z.string(), prompt_version: z.string(), attempts: z.number().int(), prompt_tokens: z.number().nullable(), completion_tokens: z.number().nullable() }),
});
export const routingSchema = z.object({
  strategy_version: z.string(), trigger_event_id: z.string(), selected_agents: z.array(roleSchema), skipped_agents: z.array(roleSchema),
  reasons: z.array(z.object({ agent_id: roleSchema, rule_id: z.string(), description: z.string() })),
});
export const conflictSchema = z.object({ conflict_id: z.string(), dimension: z.string(), agent_ids: z.array(roleSchema), description: z.string(), evidence_ids: z.array(z.string()) });
export const safetySchema = z.object({
  decision: decisionSchema, status: z.enum(['passed', 'needs_information', 'blocked']),
  checks: z.array(z.object({ code: z.string(), status: z.enum(['passed', 'warning', 'blocked']), message: z.string(), evidence_ids: z.array(z.string()) })),
  missing_information: z.array(z.string()), warnings: z.array(z.string()),
});
export const metricsSchema = z.object({ agent_calls: z.number(), llm_calls: z.number(), tool_calls: z.number(), retry_count: z.number(), prompt_tokens: z.number().nullable(), completion_tokens: z.number().nullable(), elapsed_ms: z.number() });
export const modeSchema = z.enum(['mock', 'llm']);
export const scenarioSchema = z.enum(['standard', 'partial_failure', 'persistent_disagreement', 'invalid_evidence']);
export const routingModeSchema = z.enum(['event', 'fixed']);
export const runRequestSchema = z.object({ case_id: z.string(), case_version: z.number().int(), trigger_event_id: z.string(), mode: modeSchema, mock_scenario: scenarioSchema, routing_mode: routingModeSchema });
export const modelSnapshotSchema = z.object({ agent_id: roleSchema, configuration_source: z.enum(['agent', 'default']), provider: z.string(), base_url: z.string(), model: z.string(), timeout_seconds: z.number(), temperature: z.number(), max_output_tokens: z.number() });
export const runSchema = z.object({
  run_id: z.string(), case_id: z.string(), case_version: z.number().int(), trigger_event_id: z.string(), mode: modeSchema,
  mock_scenario: scenarioSchema, routing_mode: routingModeSchema, status: z.string(), stage: z.string(),
  created_at: z.string(), updated_at: z.string(), last_seq: z.number().int().nonnegative(), routing: routingSchema.nullable(),
  agents: z.array(z.object({ agent_id: roleSchema, status: z.enum(['idle', 'queued', 'running', 'completed', 'failed', 'skipped']), opinion: opinionSchema.nullable(), previous_opinion: opinionSchema.nullable(), error: z.string().nullable() })),
  conflicts: z.array(conflictSchema), safety: safetySchema.nullable(), report_ready: z.boolean(), cancel_requested: z.boolean(),
  completed_nodes: z.array(z.string()), running_nodes: z.array(z.string()), pending_nodes: z.array(z.string()), metrics: metricsSchema, error: z.string().nullable(),
  model_configuration: z.array(modelSnapshotSchema).default([]),
});
export const auditEventSchema = z.object({ event_id: z.string(), run_id: z.string(), seq: z.number().int().positive(), timestamp: z.string(), type: z.string(), stage: z.string(), agent_id: z.string().nullable(), payload: z.record(z.string(), z.unknown()) });
export const auditPageSchema = z.object({ events: z.array(auditEventSchema), next_seq: z.number().int().nonnegative() });
export const reportSchema = z.object({
  run_id: z.string(), case_id: z.string(), case_version: z.number().int(), trigger_event_id: z.string(), mode: modeSchema, mock_scenario: scenarioSchema, routing_mode: routingModeSchema,
  case_snapshot: caseSchema, routing: routingSchema, evidence_registry: z.array(evidenceSchema), initial_opinions: z.array(opinionSchema), final_opinions: z.array(opinionSchema),
  conflicts: z.array(conflictSchema), unresolved_conflicts: z.array(conflictSchema),
  discussion_records: z.array(z.object({ agent_id: roleSchema, before: opinionSchema, after: opinionSchema.nullable(), changed: z.boolean() })), discussion_rounds: z.number().int(),
  safety: safetySchema, final_decision: decisionSchema, status: z.string(), metrics: metricsSchema, disclaimer: z.string(),
  model_configuration: z.array(modelSnapshotSchema).default([]),
});
export const modelStatusSchema = z.object({
  provider: z.string(), base_url: z.string(), model: z.string(), has_api_key: z.boolean(),
  configured: z.boolean().optional(), timeout_seconds: z.number(), temperature: z.number(), max_output_tokens: z.number(),
});
export const modelTestSchema = z.object({ ok: z.boolean(), message: z.string(), model: z.string().optional() });
export const agentModelSchema = modelStatusSchema.extend({ agent_id: roleSchema, configuration_source: z.enum(['agent', 'default', 'unconfigured']), overridden: z.boolean(), configured: z.boolean() });
export const storageSchema = z.object({ backend: z.enum(['mongodb', 'sqlite']), database: z.string(), status: z.literal('connected'), connected: z.literal(true), transactions: z.boolean(), schema_version: z.number() });
export type AgentModelStatus = z.infer<typeof agentModelSchema>;

export type ResearchCase = z.infer<typeof caseSchema>;
export type ClinicalEvent = z.infer<typeof clinicalEventSchema>;
export type EventType = z.infer<typeof eventTypeSchema>;
export type Evidence = z.infer<typeof evidenceSchema>;
export type Opinion = z.infer<typeof opinionSchema>;
export type Routing = z.infer<typeof routingSchema>;
export type Safety = z.infer<typeof safetySchema>;
export type Run = z.infer<typeof runSchema>;
export type RunRequest = z.infer<typeof runRequestSchema>;
export type AuditEvent = z.infer<typeof auditEventSchema>;
export type Report = z.infer<typeof reportSchema>;
export type Role = z.infer<typeof roleSchema>;
export type Metrics = z.infer<typeof metricsSchema>;
export type ModelStatus = z.infer<typeof modelStatusSchema>;

export const datasetSourceSchema = z.object({
  source: z.string(), name: z.string(), format: z.string(), filename: z.string(), synthetic: z.boolean().nullable(),
  source_url: z.string().nullable(), download_url: z.string().nullable(), license: z.string(), citation: z.string(), description: z.string(),
});
export const importSummarySchema = z.object({
  batch_id: z.string(), source: z.string(), source_name: z.string(), artifact_sha256: z.string(), artifact_name: z.string(),
  byte_count: z.number(), mapping_version: z.string(), requested_limit: z.number(), case_count: z.number(), event_count: z.number(),
  unplaced_count: z.number(), table_counts: z.record(z.string(), z.number()),
  warnings: z.array(z.object({ message: z.string(), count: z.number() })),
  rejected: z.array(z.object({ case_id: z.string(), reason: z.string() })), rejected_count: z.number(),
  cases: z.array(z.object({ case_id: z.string(), title: z.string(), case_kind: caseSchema.shape.case_kind, event_count: z.number(), unplaced_count: z.number() })),
});
export const importPreviewSchema = importSummarySchema.extend({ preview_id: z.string(), expires_at: z.string() });
export const importBatchSchema = importSummarySchema.extend({ created_at: z.string(), imported_case_ids: z.array(z.string()), skipped_case_ids: z.array(z.string()), already_imported: z.boolean() });
export const datasetCatalogSchema = z.object({ sources: z.array(datasetSourceSchema), max_upload_bytes: z.number(), batches: z.array(importBatchSchema) });
export type ImportPreview = z.infer<typeof importPreviewSchema>;
export type ImportBatch = z.infer<typeof importBatchSchema>;

export const semanticCompletenessSchema = z.object({
  trigger_event_id: z.string(),
  trigger_event_type: eventTypeSchema,
  required_fields: z.array(z.object({
    fact_key: z.string(),
    fact_label: z.string(),
    strict_satisfied: z.boolean(),
    semantic_satisfied: z.boolean(),
  })),
  strict_missing: z.array(z.string()),
  strict_missing_labels: z.array(z.string()),
  semantic_inferred: z.array(z.object({
    fact_key: z.string(),
    fact_label: z.string(),
    inferred_value: scalarSchema,
    source_event_id: z.string(),
    source_evidence_id: z.string(),
    rule_id: z.string(),
    confidence: z.string(),
    reason: z.string(),
  })),
  post_inference_missing: z.array(z.string()),
  post_inference_missing_labels: z.array(z.string()),
  strict_completeness_score: z.number(),
  semantic_completeness_score: z.number(),
  can_auto_enrich: z.boolean(),
  recommended_facts: factsSchema,
});

const imagingRecordStatus = z.enum(['documented', 'incomplete', 'conflict']);
const overallImagingRecordStatus = z.enum(['documented', 'incomplete', 'conflict', 'no_studies']);

export const workflowPlanSchema = z.object({
  workflow_id: z.string(),
  case_id: z.string(),
  case_version: z.number().int(),
  trigger_event_id: z.string(),
  trigger_event_title: z.string(),
  trigger_event_type: eventTypeSchema,
  strategy_version: z.string(),
  clinical_phase: z.string(),
  complexity_level: z.enum(['standard', 'elevated', 'high_risk']),
  complexity_label: z.string(),
  visible_event_count: z.number().int(),
  excluded_future_event_count: z.number().int(),
  unplaced_record_count: z.number().int(),
  source_conflict_count: z.number().int(),
  selected_agents: z.array(roleSchema),
  specialist_plan: z.array(z.object({
    agent_id: roleSchema,
    agent_label: z.string(),
    selected: z.boolean(),
    routing_type: z.string(),
    focus: z.string(),
    clinical_tasks: z.array(z.string()),
  })),
  workflow_stages: z.array(z.object({
    stage_id: z.string(),
    step_number: z.number().int(),
    title: z.string(),
    category: z.string(),
    status: z.enum(['active', 'recommended', 'skipped']),
    automated_operator: z.string(),
    description: z.string(),
  })),
  completeness: semanticCompletenessSchema,
  imaging_summary: z.object({
    study_count: z.number().int(),
    overall_qc_status: z.literal('not_assessed'),
    overall_record_status: overallImagingRecordStatus,
  }),
  predicted_decisions: z.object({
    strict_rule_decision: decisionSchema,
    semantic_enriched_decision: decisionSchema,
  }),
});

export const imagingStudySchema = z.object({
  study_id: z.string(),
  event_id: z.string(),
  occurred_at: z.string(),
  title: z.string(),
  modality: z.string().nullable(),
  anatomical_site: z.string().nullable(),
  source_name: z.string(),
  dataset_version: z.string(),
  synthetic: z.boolean(),
  source_record_id: z.string().nullable(),
  source_record_locator: z.string().nullable(),
  artifact_sha256: z.string().nullable(),
  record_status: imagingRecordStatus,
  conflict_evidence_ids: z.array(z.string()),
  record_fields: z.array(z.object({
    fact_key: z.string(), value: scalarSchema, evidence_id: z.string(), source_field: z.string().nullable(),
  })),
  qc_status: z.literal('not_assessed'),
  qc_score: z.null(),
  dicom_metadata: z.null(),
  radiomics: z.null(),
  svg_slice: z.null(),
});

export const imagingPipelineSchema = z.object({
  case_id: z.string(),
  case_version: z.number().int(),
  trigger_event_id: z.string(),
  pipeline_version: z.string(),
  study_count: z.number().int(),
  input_kind: z.literal('event_metadata'),
  overall_qc_status: z.literal('not_assessed'),
  overall_record_status: overallImagingRecordStatus,
  studies: z.array(imagingStudySchema),
});

export const ablationMatrixSchema = z.object({
  protocol_version: z.string(),
  execution_mode: z.literal('mock'),
  case_id: z.string(),
  case_version: z.number().int(),
  trigger_event_id: z.string(),
  visible_events: z.number().int(),
  call_saving_pct: z.number(),
  fixed_total_calls: z.number().int(),
  routed_total_calls: z.number().int(),
  methods: z.array(z.object({
    method_id: z.string(),
    trajectory_id: z.string(),
    input_case_version: z.number().int().positive(),
    input_trigger_event_id: z.string(),
    visible_events: z.number().int().positive(),
    name: z.string(),
    category: z.string(),
    routing_strategy: z.string(),
    selected_agents: z.array(z.union([roleSchema, z.literal('general_reviewer')])),
    agent_calls: z.number().int(),
    discussion_rounds: z.number().int(),
    valid_opinions: z.number().int().nonnegative(),
    failed_calls: z.number().int().nonnegative(),
    gate_applied: z.boolean(),
    pre_gate_decision: decisionSchema.nullable(),
    final_decision: decisionSchema.nullable(),
    missing_count: z.number().int(),
    unresolved_conflicts: z.number().int(),
    key_finding: z.string(),
  })),
});

export type WorkflowPlan = z.infer<typeof workflowPlanSchema>;
export type ImagingStudy = z.infer<typeof imagingStudySchema>;
export type ImagingPipeline = z.infer<typeof imagingPipelineSchema>;
export type AblationMatrix = z.infer<typeof ablationMatrixSchema>;
