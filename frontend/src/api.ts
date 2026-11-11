import { z } from 'zod';
import { auditPageSchema, caseSchema, healthSchema, reportSchema, runSchema, type Scenario } from './schemas';

export class APIError extends Error {
  constructor(message: string, public code = 'REQUEST_FAILED', public status = 0) { super(message); }
}

async function request<S extends z.ZodTypeAny>(path: string, schema: S, init?: RequestInit): Promise<z.infer<S>> {
  let response: Response;
  try { response = await fetch(`/api/v1${path}`, init); }
  catch { throw new APIError('无法连接本地服务，请确认后端已经启动。', 'OFFLINE'); }
  const raw: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = z.object({ error: z.object({ message: z.string(), code: z.string() }) }).safeParse(raw);
    throw new APIError(error.success ? error.data.error.message : '服务请求失败，请稍后重试。', error.success ? error.data.error.code : 'REQUEST_FAILED', response.status);
  }
  const envelope = z.object({ data: z.unknown() }).safeParse(raw);
  if (!envelope.success) throw new APIError('服务响应缺少数据封装，请检查接口版本。', 'CONTRACT_ERROR');
  const result = schema.safeParse(envelope.data.data);
  if (!result.success) throw new APIError('服务返回的数据与页面契约不一致，请刷新页面或查看服务版本。', 'CONTRACT_ERROR');
  return result.data;
}
const post = (body?: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
export const api = {
  health: () => request('/health', healthSchema),
  cases: () => request('/cases', z.array(caseSchema)),
  case: (id: string) => request(`/cases/${encodeURIComponent(id)}`, caseSchema),
  runs: () => request('/runs', z.array(runSchema)),
  run: (id: string) => request(`/runs/${encodeURIComponent(id)}`, runSchema),
  start: (caseId: string, scenario: Scenario) => request('/runs', runSchema, post({ case_id: caseId, mode: 'mock', options: { scenario, max_discussion_rounds: 1 } })),
  cancel: (id: string) => request(`/runs/${encodeURIComponent(id)}/cancel`, runSchema, post()),
  rerun: (id: string) => request(`/runs/${encodeURIComponent(id)}/rerun`, runSchema, post()),
  events: (id: string, after = 0) => request(`/runs/${encodeURIComponent(id)}/audit?after_seq=${after}&limit=500`, auditPageSchema),
  report: (id: string) => request(`/runs/${encodeURIComponent(id)}/report`, reportSchema),
};
