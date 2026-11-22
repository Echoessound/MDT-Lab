import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { DecisionBadge, ErrorState, Icon, Loading } from '../ui';
import { researchApi } from './api';
import { InlineError, eventNames, roleNames, roleOrder } from './components';
import { inputThroughTrigger } from './run-input';
import type { BlindAnnotation, LibraryEvaluation, ResearchCase, Role } from './schemas';
import { TabPanelTransition, WorkspaceViews, currentView, useWorkspaceParams } from './workspace-controls';
import { factKeyLabel, formatFactValue } from './zh-dict';

const expTabs = [
  { key: 'batch', label: '8 组配对实验与导出' },
  { key: 'annotate', label: '独立盲标工作台 (G03)' },
  { key: 'pipeline', label: '多模态数据接入架构' },
] as const;

type Decision = 'READY_FOR_REVIEW' | 'NEED_MORE_INFORMATION' | 'DEFER_DECISION';

function downloadText(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function BatchEvaluationView({
  cases,
  evaluation,
  scope,
  selectedIds,
  busy,
  error,
  onScopeChange,
  onToggleCase,
  onRun,
}: {
  cases: ResearchCase[];
  evaluation?: LibraryEvaluation;
  scope: 'all' | 'latest';
  selectedIds: string[];
  busy: boolean;
  error: unknown;
  onScopeChange: (v: 'all' | 'latest') => void;
  onToggleCase: (id: string) => void;
  onRun: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copyLatex() {
    if (!evaluation) return;
    try {
      await navigator.clipboard.writeText(evaluation.latex_table);
      setCopied(true);
      setTimeout(() => setCopied(false), 2200);
    } catch {
      downloadText('mdt_ablation_table.tex', evaluation.latex_table, 'text/plain;charset=utf-8');
    }
  }

  const b3 = evaluation?.methods.find(m => m.method_id === 'B3');
  const maxAvgCalls = Math.max(1, ...(evaluation?.methods.map(m => m.avg_calls) ?? [4]));

  return (
    <div className="workspace-column">
      <section className="panel exp-control-panel">
        <div className="workspace-section-heading">
          <div>
            <h2>批量配对实验配置（§6.2 B0–B3 基线与 A1–A4 单因素消融）</h2>
            <p className="muted">对所选病例的冻结截点同步执行 8 组确定性规则对照，按病例族汇总调用开销、门控拦截与盲标指标。</p>
          </div>
          <div className="button-group">
            <select aria-label="截点范围" value={scope} onChange={e => onScopeChange(e.target.value as 'all' | 'latest')}>
              <option value="all">全部历史截点（完整纵向评估）</option>
              <option value="latest">仅各病例最新截点</option>
            </select>
            <button type="button" className="button primary" disabled={busy || selectedIds.length === 0} onClick={onRun}>
              <Icon name="play" size={15} />
              {busy ? '正在运行配对评测…' : `运行 8 组配对评测（${selectedIds.length} 例）`}
            </button>
          </div>
        </div>

        <div className="exp-case-chips" role="group" aria-label="选择参与评测的病例">
          {cases.map(item => {
            const active = selectedIds.includes(item.case_id);
            return (
              <label key={item.case_id} className={`fact-toggle-chip ${active ? 'is-active' : ''}`}>
                <input type="checkbox" checked={active} onChange={() => onToggleCase(item.case_id)} />
                <span>{item.case_id}</span>
                <small>({item.timeline.length} 截点)</small>
              </label>
            );
          })}
        </div>
        <InlineError error={error} />
      </section>

      {evaluation && (
        <>
          <div className="telemetry-grid">
            <div className="telemetry-card stagger-item" style={{ '--stagger-i': 0 } as React.CSSProperties}>
              <span>评测规模（病例族 / 截点）</span>
              <strong>{evaluation.family_count} <small>/ {evaluation.scenario_count} 截点</small></strong>
              <p>共生成 {evaluation.scenario_count * evaluation.methods.length} 条配对方法轨迹</p>
            </div>
            <div className="telemetry-card stagger-item accent" style={{ '--stagger-i': 1 } as React.CSSProperties}>
              <span>B3 较固定全员 (A3) 调用节省</span>
              <strong>{b3 ? `${b3.call_saving_vs_fixed_pct}%` : '—'}</strong>
              <p>B3 均值 {b3?.avg_calls ?? 0} 次 vs A3 均值 {evaluation.methods.find(m => m.method_id === 'A3')?.avg_calls ?? 0} 次</p>
            </div>
            <div className="telemetry-card stagger-item" style={{ '--stagger-i': 2 } as React.CSSProperties}>
              <span>纵向记忆影响截点（A1 vs B3）</span>
              <strong>{evaluation.memory_impact_scenarios} <small>/ {evaluation.scenario_count}</small></strong>
              <p>剥离前序历史后结论或缺失项发生变化的截点数</p>
            </div>
            <div className="telemetry-card stagger-item" style={{ '--stagger-i': 3 } as React.CSSProperties}>
              <span>独立盲标参考覆盖</span>
              <strong>{evaluation.annotated_scenario_count} <small>/ {evaluation.scenario_count}</small></strong>
              <p>{evaluation.annotated_scenario_count > 0 ? '已启用召回率与错误放行率评分' : '前往「独立盲标工作台」添加参考答案'}</p>
            </div>
          </div>

          <section className="panel workflow-card">
            <div className="workspace-section-heading">
              <div>
                <h2>方法组横向对比与论文图表导出</h2>
                <p className="muted">固定使用标准确定性规则引擎（零外部付费调用）；已盲标场景自动输出必要专科召回率与错误放行率。</p>
              </div>
              <div className="button-group">
                <button type="button" className="button secondary" onClick={() => void copyLatex()}>
                  <Icon name={copied ? 'check' : 'file'} size={15} />
                  {copied ? '已复制 LaTeX 表格' : '复制 LaTeX 论文表'}
                </button>
                <button
                  type="button"
                  className="button primary"
                  onClick={() => downloadText('mdt_ablation_scores.csv', evaluation.scores_csv, 'text/csv;charset=utf-8')}
                >
                  <Icon name="download" size={15} />导出 scores.csv
                </button>
              </div>
            </div>

            <div className="workspace-table-scroll">
              <table className="workspace-table ablation-table">
                <thead>
                  <tr>
                    <th>方法组</th>
                    <th>平均调用与开销柱状图</th>
                    <th>较全员节省</th>
                    <th>结论分布（复核 / 补件 / 暂缓）</th>
                    <th>门控拦截</th>
                    {evaluation.annotated_scenario_count > 0 && <>
                      <th>必要专科召回</th>
                      <th>错误放行率</th>
                      <th>三分类准确率</th>
                    </>}
                  </tr>
                </thead>
                <tbody>
                  {evaluation.methods.map(row => {
                    const widthPct = Math.round((row.avg_calls / maxAvgCalls) * 100);
                    const totalDec = Math.max(1, row.scenario_count);
                    const readyW = (row.decisions.READY_FOR_REVIEW / totalDec) * 100;
                    const needW = (row.decisions.NEED_MORE_INFORMATION / totalDec) * 100;
                    const deferW = (row.decisions.DEFER_DECISION / totalDec) * 100;
                    return (
                      <tr key={row.method_id} className={row.method_id === 'B3' ? 'ablation-highlight-row' : ''}>
                        <td>
                          <strong>{row.name}</strong>
                          <small>{row.category} · {row.routing_strategy}</small>
                        </td>
                        <td className="exp-bar-cell">
                          <div className="exp-metric-bar-row">
                            <div className="exp-metric-track">
                              <div className={`exp-metric-fill ${row.method_id === 'B3' ? 'is-primary' : ''}`} style={{ width: `${widthPct}%` }} />
                            </div>
                            <strong className="workspace-number">{row.avg_calls.toFixed(2)} 次</strong>
                          </div>
                        </td>
                        <td className="workspace-number">
                          <span className={`pill ${row.call_saving_vs_fixed_pct > 0 ? 'soft' : 'outline'}`}>
                            {row.call_saving_vs_fixed_pct > 0 ? `↓ ${row.call_saving_vs_fixed_pct}%` : `${row.call_saving_vs_fixed_pct}%`}
                          </span>
                        </td>
                        <td>
                          <div className="exp-stacked-bar" title={`可复核 ${row.decisions.READY_FOR_REVIEW} / 需补件 ${row.decisions.NEED_MORE_INFORMATION} / 暂缓 ${row.decisions.DEFER_DECISION}`}>
                            <span className="seg-ready" style={{ width: `${readyW}%` }} />
                            <span className="seg-need" style={{ width: `${needW}%` }} />
                            <span className="seg-defer" style={{ width: `${deferW}%` }} />
                          </div>
                          <small className="workspace-number">
                            {row.decisions.READY_FOR_REVIEW} / {row.decisions.NEED_MORE_INFORMATION} / {row.decisions.DEFER_DECISION}
                          </small>
                        </td>
                        <td className="workspace-number">{row.gate_interceptions} 次</td>
                        {evaluation.annotated_scenario_count > 0 && <>
                          <td className="workspace-number">{row.specialist_recall !== null ? `${(row.specialist_recall * 100).toFixed(1)}%` : '—'}</td>
                          <td className="workspace-number">{row.false_pass_rate !== null ? `${(row.false_pass_rate * 100).toFixed(1)}%` : '—'}</td>
                          <td className="workspace-number">{row.accuracy !== null ? `${(row.accuracy * 100).toFixed(1)}%` : '—'}</td>
                        </>}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <details className="workspace-advanced">
              <summary>预览生成的毕业论文 LaTeX 三线表源码</summary>
              <pre className="json-view">{evaluation.latex_table}</pre>
            </details>
          </section>
        </>
      )}
    </div>
  );
}

function BlindAnnotationWorkbench({
  cases,
  annotations,
  onChanged,
}: {
  cases: ResearchCase[];
  annotations: BlindAnnotation[];
  onChanged: () => void;
}) {
  const scenarios = useMemo(() => {
    return cases.flatMap(c =>
      c.timeline.map(ev => ({
        scenario_id: `${c.case_id}:v${c.version}:${ev.event_id}`,
        case_item: c,
        event: ev,
      }))
    );
  }, [cases]);

  const [selectedScenarioId, setSelectedScenarioId] = useState(scenarios[0]?.scenario_id ?? '');
  const active = scenarios.find(s => s.scenario_id === selectedScenarioId) ?? scenarios[0];
  const existing = annotations.find(a => a.scenario_id === active?.scenario_id);

  const [annotatorId, setAnnotatorId] = useState('reviewer_01');
  const [requiredAgents, setRequiredAgents] = useState<Role[]>(['oncology']);
  const [expectedDecision, setExpectedDecision] = useState<Decision>('NEED_MORE_INFORMATION');
  const [rationale, setRationale] = useState('');
  const [feedback, setFeedback] = useState('');

  useEffect(() => {
    if (!active) return;
    if (existing) {
      setAnnotatorId(existing.annotator_id);
      setRequiredAgents(existing.required_agents);
      setExpectedDecision(existing.expected_decision);
      setRationale(existing.rationale);
    } else {
      setRequiredAgents(['oncology']);
      setExpectedDecision('NEED_MORE_INFORMATION');
      setRationale('');
    }
    setFeedback('');
  }, [active?.scenario_id, existing?.updated_at]);

  const save = useMutation({
    mutationFn: () => researchApi.saveAnnotation(active!.scenario_id, {
      case_id: active!.case_item.case_id,
      case_version: active!.case_item.version,
      trigger_event_id: active!.event.event_id,
      annotator_id: annotatorId.trim() || 'reviewer_01',
      required_agents: requiredAgents,
      expected_decision: expectedDecision,
      missing_fields: [],
      rationale: rationale.trim(),
    }),
    onSuccess: () => {
      setFeedback('独立参考标注已保存，实验评测表将自动重算召回率与错误放行率。');
      onChanged();
    },
  });

  const remove = useMutation({
    mutationFn: () => researchApi.deleteAnnotation(active!.scenario_id),
    onSuccess: () => {
      setFeedback('已移除该截点的独立标注。');
      onChanged();
    },
  });

  if (!active) return <p className="workspace-empty">病例库为空，无法开展盲标。</p>;
  const frozen = inputThroughTrigger(active.case_item, active.event.event_id);

  function toggleRole(role: Role) {
    setRequiredAgents(prev => {
      if (prev.includes(role)) {
        return prev.length > 1 ? prev.filter(r => r !== role) : prev;
      }
      return [...prev, role];
    });
  }

  return (
    <div className="blind-annotation-layout">
      <aside className="panel blind-scenario-list" aria-label="待盲标场景队列">
        <div className="workspace-section-heading">
          <h2>待标注截点队列</h2>
          <span className="pill soft">已标 {annotations.length} / {scenarios.length}</span>
        </div>
        <div className="blind-list-scroll">
          {scenarios.map(item => {
            const done = annotations.some(a => a.scenario_id === item.scenario_id);
            return (
              <button
                key={item.scenario_id}
                type="button"
                className={`blind-scenario-btn ${item.scenario_id === active.scenario_id ? 'is-selected' : ''}`}
                onClick={() => setSelectedScenarioId(item.scenario_id)}
              >
                <div>
                  <strong>{item.case_item.case_id} · {item.event.event_id}</strong>
                  <small>{item.event.occurred_at} · {eventNames[item.event.event_type]}</small>
                </div>
                <span className={`pill ${done ? 'status-completed' : 'outline'}`}>{done ? '已标注' : '待标'}</span>
              </button>
            );
          })}
        </div>
      </aside>

      <div className="workspace-column">
        <section className="panel blind-material-panel">
          <div className="workspace-section-heading">
            <div>
              <h2>盲标冻结材料 · {active.case_item.title}</h2>
              <p className="muted">盲标防偏置协议：已隐藏系统路由规则、规则仿真标签与截点后未来事件，仅呈现截至 {active.event.occurred_at} 的可见事实。</p>
            </div>
            <span className="pill outline">隐藏系统输出</span>
          </div>

          <div className="blind-frozen-events">
            {frozen?.timeline.map(ev => (
              <div key={ev.event_id} className={`blind-event-card ${ev.event_id === active.event.event_id ? 'is-cutoff' : ''}`}>
                <div className="blind-event-head">
                  <strong>{ev.occurred_at} · {ev.title}</strong>
                  <span className="pill soft">{eventNames[ev.event_type]} · {ev.event_id}</span>
                </div>
                <dl className="event-facts">
                  {Object.entries(ev.facts).map(([k, v]) => (
                    <div key={k}><dt>{factKeyLabel(k)}</dt><dd>{formatFactValue(v)}</dd></div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="workspace-section-heading">
            <h2>独立参考判断表单</h2>
            {existing && <DecisionBadge decision={existing.expected_decision} />}
          </div>
          <form className="research-form" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
            <div className="research-form-row">
              <label>
                标注人编号
                <input value={annotatorId} onChange={e => setAnnotatorId(e.target.value)} maxLength={60} required />
              </label>
              <label>
                预期流程结论（参考金标准）
                <select value={expectedDecision} onChange={e => setExpectedDecision(e.target.value as Decision)}>
                  <option value="READY_FOR_REVIEW">可进入人工资料复核 (READY_FOR_REVIEW)</option>
                  <option value="NEED_MORE_INFORMATION">需要补充临床资料 (NEED_MORE_INFORMATION)</option>
                  <option value="DEFER_DECISION">存在矛盾或风险，暂缓判断 (DEFER_DECISION)</option>
                </select>
              </label>
            </div>

            <div className="visual-facts-builder">
              <span className="builder-label">必要参与专科集合（至少选择 1 科，用于计算必要专科召回率）</span>
              <div className="fact-toggle-grid">
                {roleOrder.map(role => (
                  <label key={role} className={`fact-toggle-chip ${requiredAgents.includes(role) ? 'is-active' : ''}`}>
                    <input type="checkbox" checked={requiredAgents.includes(role)} onChange={() => toggleRole(role)} />
                    <span>{roleNames[role]}</span>
                  </label>
                ))}
              </div>
            </div>

            <label>
              标注依据与缺口/矛盾说明
              <textarea
                rows={3}
                value={rationale}
                onChange={e => setRationale(e.target.value)}
                placeholder="记录作出该独立参考判断的依据（如缺少病理分型、存在同日影像矛盾等）…"
              />
            </label>

            <InlineError error={save.error || remove.error} />
            {feedback && <p className="model-feedback" role="status"><Icon name="check" size={15} />{feedback}</p>}

            <div className="button-group">
              <button type="submit" className="button primary" disabled={save.isPending}>
                <Icon name="check" size={15} />
                {save.isPending ? '正在保存标注…' : '保存独立参考标注'}
              </button>
              {existing && (
                <button type="button" className="button secondary" disabled={remove.isPending} onClick={() => remove.mutate()}>
                  删除此条标注
                </button>
              )}
            </div>
          </form>
        </section>
      </div>
    </div>
  );
}

function DataCapabilitiesView() {
  const query = useQuery({ queryKey: ['research-data-capabilities'], queryFn: researchApi.dataCapabilities });
  if (query.isPending) return <Loading />;
  if (query.isError) return <InlineError error={query.error} />;

  return (
    <section className="panel workflow-card">
      <div className="workspace-section-heading">
        <div>
          <h2>后端多类型医学数据接入、去标识与防泄漏管线架构</h2>
          <p className="muted">面向重大疾病全病程研究：针对 5 类异构临床与影像数据的统一解析、溯源与时序隔离规范。</p>
        </div>
        <span className="pill soft">5 类数据模态全覆盖</span>
      </div>
      <div className="capability-grid">
        {query.data.map((item, idx) => (
          <article key={item.modality_id} className="capability-card stagger-item" style={{ '--stagger-i': idx } as React.CSSProperties}>
            <div className="capability-head">
              <span className="dag-step-num">0{idx + 1}</span>
              <h3>{item.title}</h3>
              <span className="pill soft">{item.status}</span>
            </div>
            <div className="capability-formats">
              {item.formats.map(f => <code key={f}>{f}</code>)}
            </div>
            <dl className="capability-dl">
              <div><dt>处理流水线</dt><dd>{item.processing}</dd></div>
              <div><dt>防泄漏与合规守则</dt><dd>{item.temporal_guard}</dd></div>
            </dl>
          </article>
        ))}
      </div>
    </section>
  );
}

export function ExperimentsPage() {
  const client = useQueryClient();
  const { params, update } = useWorkspaceParams();
  const view = currentView(expTabs, params.get('view'));
  const casesQuery = useQuery({ queryKey: ['research-cases'], queryFn: researchApi.cases });
  const annotationsQuery = useQuery({ queryKey: ['research-annotations'], queryFn: researchApi.annotations });

  const [scope, setScope] = useState<'all' | 'latest'>('all');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [initialized, setInitialized] = useState(false);

  const evaluate = useMutation({
    mutationFn: (opts: { case_ids?: string[]; trigger_scope: 'all' | 'latest' }) => researchApi.evaluateExperiments(opts),
  });

  useEffect(() => {
    if (casesQuery.data && !initialized) {
      const ids = casesQuery.data.map(c => c.case_id);
      setSelectedIds(ids);
      setInitialized(true);
      if (ids.length > 0) {
        evaluate.mutate({ case_ids: ids, trigger_scope: 'all' });
      }
    }
  }, [casesQuery.data, initialized]);

  if (casesQuery.isPending) return <Loading />;
  if (casesQuery.isError) return <ErrorState error={casesQuery.error} retry={() => void casesQuery.refetch()} />;

  function toggleCase(id: string) {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  }

  function refreshAll() {
    void client.invalidateQueries({ queryKey: ['research-annotations'] });
    if (selectedIds.length > 0) {
      evaluate.mutate({ case_ids: selectedIds, trigger_scope: scope });
    }
  }

  const tabsWithBadges = [
    { key: 'batch' as const, label: '8 组配对实验与导出', badge: evaluate.data ? `${evaluate.data.scenario_count} 截点` : undefined },
    { key: 'annotate' as const, label: '独立盲标工作台 (G03)', badge: annotationsQuery.data?.length ?? 0 },
    { key: 'pipeline' as const, label: '多模态数据接入架构', badge: '5 类模态' },
  ];

  return (
    <div className="page-enter research-page workspace-page">
      <header className="workspace-heading">
        <div>
          <h1>科研实验、独立盲标与论文导出</h1>
          <p>一站式完成计划 §6.2 的 B0–B3 基线与单因素消融批量评测、G03 盲标金标准核验以及论文 LaTeX / CSV 数据导出</p>
        </div>
      </header>

      <WorkspaceViews
        label="实验与评测视图"
        tabs={tabsWithBadges}
        value={view}
        onChange={v => update({ view: v === 'batch' ? '' : v })}
      />

      <TabPanelTransition tabs={expTabs} activeKey={view}>
        {view === 'batch' && (
          <BatchEvaluationView
            cases={casesQuery.data}
            evaluation={evaluate.data}
            scope={scope}
            selectedIds={selectedIds}
            busy={evaluate.isPending}
            error={evaluate.error}
            onScopeChange={setScope}
            onToggleCase={toggleCase}
            onRun={() => evaluate.mutate({ case_ids: selectedIds, trigger_scope: scope })}
          />
        )}
        {view === 'annotate' && (
          <BlindAnnotationWorkbench
            cases={casesQuery.data}
            annotations={annotationsQuery.data ?? []}
            onChanged={refreshAll}
          />
        )}
        {view === 'pipeline' && <DataCapabilitiesView />}
      </TabPanelTransition>
    </div>
  );
}
