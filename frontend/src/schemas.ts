import { z } from 'zod';

export const roleSchema = z.enum(['oncology', 'surgery', 'radiology']);
export const decisionSchema = z.enum(['READY_FOR_REVIEW', 'NEED_MORE_INFORMATION', 'DEFER_DECISION']);
export const stageSchema = z.enum(['LOAD_CASE', 'INITIAL_REVIEW', 'DETECT_DISAGREEMENT', 'TARGETED_DISCUSSION', 'BUILD_REPORT', 'SAVE_OUTPUT']);
export const scenarioSchema = z.enum(['standard', 'aligned', 'partial_failure', 'persistent_disagreement']);
export const statusSchema = z.enum(['queued', 'running', 'cancel_requested', 'cancelled', 'completed', 'incomplete', 'failed']);
export const timelineSchema = z.object({ event_id: z.string(), date: z.string(), type: z.string(), description: z.string() });
export const caseSchema = z.object({
  case_id: z.string(), is_synthetic: z.literal(true),
  patient: z.object({ age: z.number().int(), sex: z.enum(['female', 'male', 'other', 'unknown']) }),
  timeline: z.array(timelineSchema), current_question: z.string(), available_options: z.array(decisionSchema),
});
export const opinionSchema = z.object({
  agent_name: roleSchema, decision: decisionSchema, reasoning_summary: z.string(),
  supporting_event_ids: z.array(z.string()), missing_information: z.array(z.string()),
  confidence: z.enum(['low', 'medium', 'high']),
});
const disagreementSchema = z.object({
  has_disagreement: z.boolean(), sufficient_opinions: z.boolean(),
  conflicting_agents: z.array(roleSchema), conflicting_decisions: z.array(decisionSchema),
  missing_agents: z.array(roleSchema), discussion_topic: z.string(),
});
const recordSchema = z.object({
  round: z.literal(1), agent_name: roleSchema, topic: z.string(), before: opinionSchema,
  after: opinionSchema.nullable(), changed: z.boolean(), status: z.enum(['completed', 'failed']), audit_event_id: z.string(),
});
export const reportSchema = z.object({
  run_id: z.string(), case_id: z.string(), mode: z.enum(['mock', 'llm']), status: z.enum(['completed', 'incomplete', 'failed']),
  initial_opinions: z.array(opinionSchema), final_opinions: z.array(opinionSchema),
  discussion_triggered: z.boolean(), discussion_rounds: z.number().int().min(0).max(1), discussion_records: z.array(recordSchema),
  final_decision: decisionSchema, unresolved_disagreements: z.array(disagreementSchema),
  missing_information: z.array(z.string()), warnings: z.array(z.string()),
  disclaimer: z.literal('本报告仅用于合成病例的科研模拟，不构成真实医疗建议。'),
  case_sha256: z.string(), audit_file: z.literal('audit.jsonl'), audit_event_ids: z.array(z.string()),
});
const agentSchema = z.object({
  status: z.enum(['waiting', 'running', 'completed', 'failed']), opinion: opinionSchema.nullable(),
  previous_opinion: opinionSchema.nullable(), error: z.string().nullable(),
});
export const runSchema = z.object({
  run_id: z.string(), case_id: z.string(), mode: z.enum(['mock', 'llm']), scenario: scenarioSchema,
  source_run_id: z.string().nullable(), status: statusSchema, stage: stageSchema,
  created_at: z.string(), updated_at: z.string(),
  agents: z.object({ oncology: agentSchema, surgery: agentSchema, radiology: agentSchema }),
  discussion_triggered: z.boolean(), cancel_requested: z.boolean(), report_ready: z.boolean(), last_seq: z.number().int(),
});
const auditSchema = z.object({
  event_id: z.string(), run_id: z.string(), timestamp: z.string(), stage: stageSchema,
  event_type: z.string(), agent_name: roleSchema.nullable(), details: z.record(z.string(), z.unknown()),
});
export const eventSchema = z.object({
  schema_version: z.literal('1'), seq: z.number().int().positive(), run_id: z.string(),
  timestamp: z.string(), type: z.string(), payload: auditSchema,
}).refine(event => event.run_id === event.payload.run_id, '审计与运行 ID 不一致');
export const auditPageSchema = z.object({ events: z.array(eventSchema), next_seq: z.number().int() });
export const healthSchema = z.object({ status: z.literal('ok'), version: z.string(), mode: z.string(), event_delay: z.number() });
export type Role = z.infer<typeof roleSchema>;
export type Decision = z.infer<typeof decisionSchema>;
export type Stage = z.infer<typeof stageSchema>;
export type Scenario = z.infer<typeof scenarioSchema>;
export type SyntheticCase = z.infer<typeof caseSchema>;
export type TimelineEvent = z.infer<typeof timelineSchema>;
export type Opinion = z.infer<typeof opinionSchema>;
export type Run = z.infer<typeof runSchema>;
export type RunEvent = z.infer<typeof eventSchema>;
export type Report = z.infer<typeof reportSchema>;
