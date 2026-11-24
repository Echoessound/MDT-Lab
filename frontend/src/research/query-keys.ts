/**
 * Centralized TanStack Query key registry for `/api/v2` research endpoints.
 * Keeps cache invalidation, optimistic updates, and cross-page navigation predictable.
 */
export const researchKeys = {
  storage: ['research-storage'] as const,
  cases: ['research-cases'] as const,
  caseDetail: (id: string, version: number | 'latest' = 'latest') => ['research-case', id, version] as const,
  routing: (id: string, version: number | undefined, trigger: string | undefined, mode: string) =>
    ['research-routing', id, version, trigger, mode] as const,
  workflowPlan: (id: string, version?: number, trigger?: string) =>
    trigger !== undefined ? (['research-workflow-plan', id, version, trigger] as const) : (['research-workflow-plan', id] as const),
  imaging: (id: string, version?: number, trigger?: string) =>
    trigger !== undefined ? (['research-imaging', id, version, trigger] as const) : (['research-imaging', id] as const),
  ablation: (id: string, version?: number, trigger?: string) =>
    trigger !== undefined ? (['research-ablation', id, version, trigger] as const) : (['research-ablation', id] as const),
  attachments: (id: string, eventId?: string) => ['research-attachments', id, eventId ?? 'all'] as const,
  runs: ['research-runs'] as const,
  runDetail: (runId: string) => ['research-run', runId] as const,
  report: (runId: string) => ['research-report', runId] as const,
  temporalAudit: (runId: string) => ['research-temporal-audit', runId] as const,
  agentModels: ['research-agent-models'] as const,
  modelProfiles: ['research-model-profiles'] as const,
  datasets: ['research-datasets'] as const,
  dataCapabilities: ['research-data-capabilities'] as const,
  annotationTasks: ['blind-tasks'] as const,
  blindMaterial: (scenarioId: string) => ['blind-material', scenarioId] as const,
  ownAnnotation: (scenarioId: string, reviewer: string) => ['own-annotation', scenarioId, reviewer] as const,
  reviewPanelTasks: (reviewer = '') => ['review-panel-tasks', reviewer] as const,
  reviewPanelOwn: (scenarioId: string, reviewer: string) => ['review-panel-own', scenarioId, reviewer] as const,
  reviewPanelAgreement: ['review-panel-agreement'] as const,
};
