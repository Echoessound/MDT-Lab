import { z } from 'zod';
import { APIError } from '../api';
import { adjudicationSchema, agentModelSchema, agreementReportSchema, annotationSchema, annotationTaskSchema, blindMaterialSchema, attachmentSchema, storageSchema, auditPageSchema, caseSchema, consensusMetricsSchema, dataCapabilitySchema, datasetCatalogSchema, importPreviewSchema, importBatchSchema, libraryEvaluationSchema, longitudinalDynamicsSchema, modelProfileSchema, modelStatusSchema, modelTestSchema, multiRaterSubmissionSchema, reportSchema, reviewPanelTaskSchema, routingSchema, runSchema, temporalAuditSchema, workflowPlanSchema, imagingPipelineSchema, ablationMatrixSchema, type ClinicalEvent, type RunRequest, type BlindAnnotation, type AnnotationTask, type Role } from './schemas';

async function request<S extends z.ZodType>(path: string, schema: S, init?: RequestInit): Promise<z.infer<S>> {
  let response: Response;
  try { response = await fetch(`/api/v2${path}`, init); }
  catch { throw new APIError('无法连接本地服务，请检查后端是否已启动。', 'OFFLINE'); }
  const raw: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = z.object({ error: z.object({ code: z.string(), message: z.string() }) }).safeParse(raw);
    throw new APIError(error.success ? error.data.error.message : '服务请求失败。', error.success ? error.data.error.code : 'REQUEST_FAILED', response.status);
  }
  const envelope = z.object({ data: z.unknown() }).safeParse(raw);
  if (!envelope.success) throw new APIError('响应缺少数据封装。', 'CONTRACT_ERROR');
  const parsed = schema.safeParse(envelope.data.data);
  if (!parsed.success) throw new APIError('服务数据与页面契约不一致，请检查版本。', 'CONTRACT_ERROR');
  return parsed.data;
}
const body = (value: unknown, method = 'POST'): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
const id = encodeURIComponent;
export const researchApi = {
  storage: () => request('/storage', storageSchema),
  agentModels: () => request('/settings/agents', z.array(agentModelSchema)),
  configureAgent: (role: Role, value: ModelConfiguration) => request(`/settings/agents/${role}`, agentModelSchema, body(value, 'PUT')),
  clearAgent: (role: Role) => request(`/settings/agents/${role}`, agentModelSchema, { method: 'DELETE' }),
  testAgent: (role: Role) => request(`/settings/agents/${role}/test`, modelTestSchema, body({})),
  datasets: () => request('/datasets', datasetCatalogSchema),
  dataCapabilities: () => request('/datasets/capabilities', z.array(dataCapabilitySchema)),
  connectDataset: (source: string, limit: number) => request(`/datasets/connect?source=${id(source)}&max_cases=${limit}`, importPreviewSchema, body({})),
  previewDataset: (source: string, file: File, limit: number) => request(`/datasets/preview?source=${id(source)}&max_cases=${limit}`, importPreviewSchema, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file }),
  importDataset: (previewId: string) => request(`/datasets/import/${id(previewId)}`, importBatchSchema, body({})),
  cases: () => request('/cases', z.array(caseSchema)),
  case: (caseId: string, version?: number) => request(`/cases/${id(caseId)}${version ? `?version=${version}` : ''}`, caseSchema),
  append: (caseId: string, version: number, event: Pick<ClinicalEvent, 'occurred_at' | 'event_type' | 'title' | 'facts'>) => request(`/cases/${id(caseId)}/events`, caseSchema, body({ expected_version: version, event })),
  routing: (caseId: string, version: number, trigger: string, mode: string) => request(`/cases/${id(caseId)}/routing?version=${version}&trigger_event_id=${id(trigger)}&routing_mode=${id(mode)}`, routingSchema),
  longitudinalDynamics: (caseId: string, version?: number) => request(`/cases/${id(caseId)}/longitudinal-dynamics${version ? `?version=${version}` : ''}`, longitudinalDynamicsSchema),
  workflowPlan: (caseId: string, version: number, trigger: string) => request(`/cases/${id(caseId)}/workflow-plan?version=${version}&trigger_event_id=${id(trigger)}`, workflowPlanSchema),
  imagingPipeline: (caseId: string, version: number, trigger: string) => request(`/cases/${id(caseId)}/imaging?version=${version}&trigger_event_id=${id(trigger)}`, imagingPipelineSchema),
  ablationMatrix: (caseId: string, version: number, trigger: string) => request(`/cases/${id(caseId)}/ablation?version=${version}&trigger_event_id=${id(trigger)}`, ablationMatrixSchema),
  autoEnrich: (caseId: string, expectedVersion: number, triggerEventId?: string) => request(`/cases/${id(caseId)}/auto-enrich`, caseSchema, body({ expected_version: expectedVersion, trigger_event_id: triggerEventId })),
  listAttachments: (caseId: string, eventId?: string) => request(`/cases/${id(caseId)}/attachments${eventId ? `?event_id=${id(eventId)}` : ''}`, z.array(attachmentSchema)),
  uploadAttachment: (caseId: string, eventId: string, file: File) => request(`/cases/${id(caseId)}/events/${id(eventId)}/attachments?filename=${id(file.name)}`, attachmentSchema, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file }),
  deleteAttachment: (caseId: string, attachmentId: string) => request(`/cases/${id(caseId)}/attachments/${id(attachmentId)}`, z.object({ deleted: z.boolean(), attachment_id: z.string() }), { method: 'DELETE' }),
  evaluateExperiments: (value: { case_ids?: string[]; case_versions?: Record<string, number>; trigger_scope: 'all' | 'latest'; reference_source?: 'merged' | 'single_only' }) => request('/experiments/evaluate', libraryEvaluationSchema, body(value)),
  annotations: () => request('/annotations', z.array(annotationSchema)),
  annotationTasks: () => request('/annotations/tasks', z.array(annotationTaskSchema)),
  blindMaterial: (task: Pick<AnnotationTask, 'case_id' | 'case_version' | 'trigger_event_id'>) => request(`/annotations/material?case_id=${id(task.case_id)}&version=${task.case_version}&trigger_event_id=${id(task.trigger_event_id)}`, blindMaterialSchema),
  ownAnnotation: (scenario: string, reviewer: string) => request(`/annotations/own?scenario_id=${id(scenario)}&annotator_id=${id(reviewer)}`, annotationSchema.nullable()),
  saveAnnotation: (scenario: string, value: Omit<BlindAnnotation, 'scenario_id' | 'updated_at'>) => request(`/annotations/${id(scenario)}`, annotationSchema, body(value, 'PUT')),
  deleteAnnotation: (scenario: string, reviewer: string) => request(`/annotations/${id(scenario)}?annotator_id=${id(reviewer)}`, z.object({ deleted: z.boolean(), scenario_id: z.string() }), { method: 'DELETE' }),
  reviewPanelTasks: (annotatorId?: string) => request(`/review-panel/tasks${annotatorId ? `?annotator_id=${id(annotatorId)}` : ''}`, z.array(reviewPanelTaskSchema)),
  reviewPanelOwn: (scenario: string, reviewer: string) => request(`/review-panel/own?scenario_id=${id(scenario)}&annotator_id=${id(reviewer)}`, multiRaterSubmissionSchema.nullable()),
  saveReviewSubmission: (scenario: string, value: { case_id: string; case_version: number; trigger_event_id: string; annotator_id: string; required_agents: Role[]; expected_decision: BlindAnnotation['expected_decision']; input_sha256?: string | null; evidence_ids: string[]; missing_fields: string[]; rationale: string }) => request(`/review-panel/submissions/${id(scenario)}`, multiRaterSubmissionSchema, body(value, 'PUT')),
  deleteReviewSubmission: (scenario: string, reviewer: string) => request(`/review-panel/submissions/${id(scenario)}?annotator_id=${id(reviewer)}`, z.object({ deleted: z.boolean(), scenario_id: z.string(), annotator_id: z.string() }), { method: 'DELETE' }),
  reviewPanelAgreement: () => request('/review-panel/agreement', agreementReportSchema),
  saveAdjudication: (scenario: string, value: { case_id: string; case_version: number; trigger_event_id: string; adjudicator_id: string; required_agents: Role[]; expected_decision: BlindAnnotation['expected_decision']; input_sha256?: string | null; evidence_ids: string[]; missing_fields: string[]; adjudication_rationale: string }) => request(`/review-panel/adjudications/${id(scenario)}`, adjudicationSchema, body(value, 'PUT')),
  deleteAdjudication: (scenario: string) => request(`/review-panel/adjudications/${id(scenario)}`, z.object({ deleted: z.boolean(), scenario_id: z.string() }), { method: 'DELETE' }),
  runs: () => request('/runs', z.array(runSchema)),
  run: (runId: string) => request(`/runs/${id(runId)}`, runSchema),
  start: (value: RunRequest) => request('/runs', runSchema, body(value)),
  cancel: (runId: string) => request(`/runs/${id(runId)}/cancel`, runSchema, body({})),
  rerun: (runId: string) => request(`/runs/${id(runId)}/rerun`, runSchema, body({})),
  events: (runId: string, after = 0) => request(`/runs/${id(runId)}/audit?after_seq=${after}&limit=500`, auditPageSchema),
  report: (runId: string) => request(`/runs/${id(runId)}/report`, reportSchema),
  temporalAudit: (runId: string) => request(`/runs/${id(runId)}/temporal-audit`, temporalAuditSchema),
  consensusMetrics: (runId: string) => request(`/runs/${id(runId)}/consensus-metrics`, consensusMetricsSchema),
  modelProfiles: () => request('/settings/llm/profiles', z.array(modelProfileSchema)),
  createModelProfile: (value: ModelProfileInput) => request('/settings/llm/profiles', modelProfileSchema, body(value)),
  saveScopeAsModelProfile: (scope: 'default' | Role, name: string) => request('/settings/llm/profiles/from-scope',
    modelProfileSchema, body({ scope, name })),
  updateModelProfile: (profileId: string, value: ModelProfileInput) => request(`/settings/llm/profiles/${id(profileId)}`, modelProfileSchema, body(value, 'PUT')),
  deleteModelProfile: (profileId: string) => request(`/settings/llm/profiles/${id(profileId)}`, z.object({ deleted: z.boolean(), profile_id: z.string() }), { method: 'DELETE' }),
  activateModelProfile: (profileId: string, scope: 'default' | Role) => request(`/settings/llm/profiles/${id(profileId)}/activate`,
    scope === 'default' ? modelStatusSchema : agentModelSchema, body({ scope })),
  testModelProfile: (profileId: string) => request(`/settings/llm/profiles/${id(profileId)}/test`, modelTestSchema, body({})),
  modelStatus: () => request('/settings/llm', modelStatusSchema),
  configureModel: (value: ModelConfiguration) => request('/settings/llm', modelStatusSchema, body(value, 'PUT')),
  clearModel: () => request('/settings/llm', modelStatusSchema, { method: 'DELETE' }),
  testModel: () => request('/settings/llm/test', modelTestSchema, body({})),
};
export type ModelConfiguration = { provider: string; base_url: string; model: string; api_key: string; timeout_seconds: number; temperature: number; max_output_tokens: number };
export type ModelProfileInput = ModelConfiguration & { name: string };
