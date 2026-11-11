import { z } from 'zod';
import { APIError } from '../api';
import { auditPageSchema, caseSchema, datasetCatalogSchema, importPreviewSchema, importBatchSchema, modelStatusSchema, modelTestSchema, reportSchema, routingSchema, runSchema, type ClinicalEvent, type RunRequest } from './schemas';

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
  datasets: () => request('/datasets', datasetCatalogSchema),
  connectDataset: (source: string, limit: number) => request(`/datasets/connect?source=${id(source)}&max_cases=${limit}`, importPreviewSchema, body({})),
  previewDataset: (source: string, file: File, limit: number) => request(`/datasets/preview?source=${id(source)}&max_cases=${limit}`, importPreviewSchema, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file }),
  importDataset: (previewId: string) => request(`/datasets/import/${id(previewId)}`, importBatchSchema, body({})),
  cases: () => request('/cases', z.array(caseSchema)),
  case: (caseId: string, version?: number) => request(`/cases/${id(caseId)}${version ? `?version=${version}` : ''}`, caseSchema),
  append: (caseId: string, version: number, event: Pick<ClinicalEvent, 'occurred_at' | 'event_type' | 'title' | 'facts'>) => request(`/cases/${id(caseId)}/events`, caseSchema, body({ expected_version: version, event })),
  routing: (caseId: string, version: number, trigger: string, mode: string) => request(`/cases/${id(caseId)}/routing?version=${version}&trigger_event_id=${id(trigger)}&routing_mode=${id(mode)}`, routingSchema),
  runs: () => request('/runs', z.array(runSchema)),
  run: (runId: string) => request(`/runs/${id(runId)}`, runSchema),
  start: (value: RunRequest) => request('/runs', runSchema, body(value)),
  cancel: (runId: string) => request(`/runs/${id(runId)}/cancel`, runSchema, body({})),
  rerun: (runId: string) => request(`/runs/${id(runId)}/rerun`, runSchema, body({})),
  events: (runId: string, after = 0) => request(`/runs/${id(runId)}/audit?after_seq=${after}&limit=500`, auditPageSchema),
  report: (runId: string) => request(`/runs/${id(runId)}/report`, reportSchema),
  modelStatus: () => request('/settings/llm', modelStatusSchema),
  configureModel: (value: ModelConfiguration) => request('/settings/llm', modelStatusSchema, body(value, 'PUT')),
  clearModel: () => request('/settings/llm', modelStatusSchema, { method: 'DELETE' }),
  testModel: () => request('/settings/llm/test', modelTestSchema, body({})),
};
export type ModelConfiguration = { provider: string; base_url: string; model: string; api_key: string; timeout_seconds: number; temperature: number; max_output_tokens: number };
