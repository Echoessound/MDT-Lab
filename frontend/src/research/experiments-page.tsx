import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { DecisionBadge, ErrorState, Icon, Loading } from '../ui';
import { researchApi } from './api';
import { InlineError, roleNames } from './components';
import { BlindReviewWorkbench } from './blind-review-workbench';
import { MultiRaterPanel } from './multi-rater-panel';
import { researchKeys } from './query-keys';
import type { LibraryEvaluation, ResearchCase, Role } from './schemas';
import { TabPanelTransition, WorkspaceViews, currentView, useWorkspaceParams } from './workspace-controls';

const maxBatchCases = 50;

const expTabs = [
  { key: 'batch', label: '8 组配对实验与导出' },
  { key: 'annotate', label: '独立盲标工作台' },
  { key: 'pipeline', label: '多模态数据接入架构' },
] as const;

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
  const exportReferences = useMutation({
    mutationFn: researchApi.annotations,
    onSuccess: records => {
      const payload = Object.fromEntries(records.map(item => [item.scenario_id, item]));
      downloadText('mdt_blind_annotations.json', JSON.stringify(payload, null, 2) + '\n', 'application/json;charset=utf-8');
    },
  });
  const [scenarioFilter, setScenarioFilter] = useState<'all' | 'memory' | 'annotated' | 'unannotated'>('all');

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
  const filteredScenarios = useMemo(() => {
    if (!evaluation) return [];
    return evaluation.scenarios.filter(item => {
      if (scenarioFilter === 'memory') return Boolean(item.memory_impacted);
      if (scenarioFilter === 'annotated') return item.annotated;
      if (scenarioFilter === 'unannotated') return !item.annotated;
      return true;
    });
  }, [evaluation, scenarioFilter]);

  return (
    <div className="workspace-column">
      <section className="panel exp-control-panel">
        <div className="workspace-section-heading">
          <div>
            <h2>配对实验的病例与截点范围</h2>
            <p className="muted">对所选病例的冻结截点同步执行 8 组确定性规则对照，每批最多选择 {maxBatchCases} 个病例。</p>
          </div>
          <div className="button-group">
            <button type="button" className="button secondary" disabled={exportReferences.isPending}
              onClick={() => exportReferences.mutate()}>
              <Icon name="download" size={15} />导出全库盲标 JSON
            </button>
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
                <input type="checkbox" disabled={!active && selectedIds.length >= maxBatchCases} checked={active} onChange={() => onToggleCase(item.case_id)} />
                <span>{item.case_id}</span>
                <small>v{item.version} · {item.timeline.length} 截点</small>
              </label>
            );
          })}
        </div>
        <InlineError error={error || exportReferences.error} />
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
              <p>移除前序记录后，流程结论或缺失字段数发生变化的截点数</p>
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
                <p className="muted">八组方法均使用确定性规则。错误放行和过度暂缓按各自的参考标签统计分母。</p>
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
                {evaluation.error_analysis && evaluation.error_analysis.length > 0 && (
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() => downloadText('mdt_error_analysis.csv', evaluation.error_analysis_csv ?? '', 'text/csv;charset=utf-8')}
                  >
                    <Icon name="download" size={15} />导出误差归因 CSV
                  </button>
                )}
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
                      <th>过度暂缓或补件率</th>
                      <th>三分类准确率</th>
                      <th>宏 F1</th>
                      <th>缺件 F1</th>
                    </>}
                  </tr>
                </thead>
                <tbody>
                  {evaluation.methods.map(row => {
                    const barScale = Math.max(0.03, row.avg_calls / maxAvgCalls);
                    const stackedVars = {
                      '--ready-fr': `${row.decisions.READY_FOR_REVIEW}fr`,
                      '--need-fr': `${row.decisions.NEED_MORE_INFORMATION}fr`,
                      '--defer-fr': `${row.decisions.DEFER_DECISION}fr`,
                    } as React.CSSProperties;
                    return (
                      <tr key={row.method_id} className={row.method_id === 'B3' ? 'ablation-highlight-row' : ''}>
                        <td>
                          <strong>{row.name}</strong>
                          <small>{row.category} · {row.routing_strategy}</small>
                          {row.method_id === 'A2' && evaluation.annotated_scenario_count > 0 &&
                            <small>一致性评分使用补齐前的截点参考。</small>}
                        </td>
                        <td className="exp-bar-cell">
                          <div className="exp-metric-bar-row">
                            <div className="exp-metric-track">
                              <div
                                className={`exp-metric-fill ${row.method_id === 'B3' ? 'is-primary' : ''}`}
                                style={{ '--bar-scale': barScale } as React.CSSProperties}
                              />
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
                          <div
                            className="exp-stacked-bar"
                            style={stackedVars}
                            title={`可复核 ${row.decisions.READY_FOR_REVIEW} / 需补件 ${row.decisions.NEED_MORE_INFORMATION} / 暂缓 ${row.decisions.DEFER_DECISION}`}
                          >
                            <span className="seg-ready" />
                            <span className="seg-need" />
                            <span className="seg-defer" />
                          </div>
                          <small className="workspace-number">
                            {row.decisions.READY_FOR_REVIEW} / {row.decisions.NEED_MORE_INFORMATION} / {row.decisions.DEFER_DECISION}
                          </small>
                        </td>
                        <td className="workspace-number">{row.gate_interceptions} 次</td>
                        {evaluation.annotated_scenario_count > 0 && <>
                          <td className="workspace-number">{row.specialist_recall !== null ? `${(row.specialist_recall * 100).toFixed(1)}%` : '—'}</td>
                          <td className="workspace-number">{row.false_pass_rate !== null ? `${(row.false_pass_rate * 100).toFixed(1)}%` : '—'}
                            <small>{row.false_pass_count} / {row.false_pass_denominator}</small></td>
                          <td className="workspace-number">{row.over_deferral_rate !== null ? `${(row.over_deferral_rate * 100).toFixed(1)}%` : '—'}
                            <small>{row.over_deferral_count} / {row.over_deferral_denominator}</small></td>
                          <td className="workspace-number">{row.accuracy !== null ? `${(row.accuracy * 100).toFixed(1)}%` : '—'}</td>
                          <td className="workspace-number">{row.macro_f1 !== null && row.macro_f1 !== undefined ? `${(row.macro_f1 * 100).toFixed(1)}%` : '—'}</td>
                          <td className="workspace-number">{row.missing_field_f1 !== null && row.missing_field_f1 !== undefined ? `${(row.missing_field_f1 * 100).toFixed(1)}%` : '—'}</td>
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

          {evaluation.paired_statistics && (
            <section className="panel workflow-card">
              <div className="workspace-section-heading">
                <div>
                  <h2>病例族聚类 Bootstrap 95% 置信区间与配对检验</h2>
                  <p className="muted">
                    以独立病例族（<code>{evaluation.paired_statistics.cluster_unit}</code>）为抽样单元执行{' '}
                    {evaluation.paired_statistics.bootstrap_resamples} 次确定性重抽样（seed={evaluation.paired_statistics.bootstrap_seed}），避免同患者多截点相关性偏差。
                  </p>
                </div>
                <span className="pill soft">聚类单元：{evaluation.paired_statistics.family_count} 个病例族</span>
              </div>

              <div className="contrast-grid">
                {evaluation.paired_statistics.contrasts.map((item, idx) => (
                  <article key={item.contrast_id} className="contrast-card stagger-item" style={{ '--stagger-i': idx } as React.CSSProperties}>
                    <div className="contrast-head">
                      <strong>{item.label}</strong>
                      <span className="pill outline">可评 {item.eligible_scenarios} / {item.total_scenarios} 截点</span>
                    </div>
                    <div className="contrast-metric-row">
                      <span className="contrast-metric-label">{item.metric_name}</span>
                      <strong className="contrast-point workspace-number">{item.point_estimate === null ? '无可评分母' : `${item.point_estimate.toFixed(1)}${item.unit}`}</strong>
                    </div>
                    <small className="muted">分子 / 分母 · {item.metric_numerator} / {item.metric_denominator}{item.contrast_id === 'B3_vs_A3' ? ' 次调用' : ' 个截点'}</small>
                    <div className="contrast-ci-row">
                      <span className="ci-badge workspace-number">
                        {item.ci_low === null || item.ci_high === null
                          ? `可评病例族 ${item.eligible_family_count} 个，区间不可估计`
                          : `95% CI [${item.ci_low.toFixed(1)}${item.unit}, ${item.ci_high.toFixed(1)}${item.unit}]`}
                      </span>
                      {item.mcnemar_exact_p !== null && (
                        <span className={`pill ${item.mcnemar_exact_p < 0.05 ? 'status-completed' : 'outline'} workspace-number`}>
                          盲标正确性 McNemar p = {item.mcnemar_exact_p.toFixed(4)}
                        </span>
                      )}
                    </div>
                    <p className="muted">{item.interpretation}</p>
                    {item.mcnemar_status === 'repeated_family' && <small className="muted">盲标配对含同一病例族的多个截点，未计算独立配对检验。</small>}
                    {item.annotated_pairs > 0 && <small className="muted">盲标配对 {item.annotated_pairs} 个 · 仅 B3 判对 {item.b3_only_correct} 个 · 仅对照组判对 {item.comparator_only_correct} 个</small>}
                  </article>
                ))}
              </div>

              <p className="notice neutral notice-spaced">
                <Icon name="info" size={16} />
                <span>{evaluation.paired_statistics.sample_size_note}</span>
              </p>
            </section>
          )}

          {evaluation.error_analysis && evaluation.error_analysis.length > 0 && (
            <section className="panel workflow-card">
              <div className="workspace-section-heading">
                <div>
                  <h2>逐例误差归因分析（S7 计划交付物）</h2>
                  <p className="muted">自动归类带参考标注截点中的错误放行、过度保守、遗漏必要专科与标签差异，便于论文误差分析与反例复核。</p>
                </div>
                <span className="pill outline">共 {evaluation.error_analysis.length} 条误差记录</span>
              </div>
              <div className="workspace-table-scroll">
                <table className="workspace-table">
                  <thead>
                    <tr>
                      <th>截点 / 方法</th>
                      <th>误差类型</th>
                      <th>参考 vs 预测</th>
                      <th>遗漏专科</th>
                      <th>归因说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evaluation.error_analysis.slice(0, 40).map((err, i) => (
                      <tr key={`${err.scenario_id}-${err.method_id}-${i}`}>
                        <td>
                          <strong>{err.scenario_id}</strong>
                          <small>{err.method_id}</small>
                        </td>
                        <td>
                          <div className="badge-row">
                            {err.error_types.map(t => (
                              <span key={t} className={`pill ${t === 'false_pass' || t === 'no_output' ? 'status-failed' : 'outline'}`}>{t}</span>
                            ))}
                          </div>
                        </td>
                        <td>
                          <DecisionBadge decision={err.expected_decision} />
                          <span className="muted"> → </span>
                          {err.predicted_decision ? <DecisionBadge decision={err.predicted_decision} /> : <span className="pill outline">无输出</span>}
                        </td>
                        <td>{err.missed_agents.length > 0 ? err.missed_agents.map(r => roleNames[r as Role] ?? r).join('、') : '—'}</td>
                        <td>{err.root_cause_hint}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <section className="panel workflow-card">
            <div className="workspace-section-heading">
              <div>
                <h2>逐截点配对明细与快速筛选</h2>
                <p className="muted">可按纵向记忆影响或盲标覆盖状态快速定位典型截点，直接跳转病例工作台复盘证据与工作流。</p>
              </div>
              <div className="scenario-filter-bar" role="group" aria-label="筛选评测截点">
                {([
                  ['all', `全部 (${evaluation.scenarios.length})`],
                  ['memory', `记忆影响 (${evaluation.memory_impact_scenarios})`],
                  ['annotated', `已盲标 (${evaluation.annotated_scenario_count})`],
                  ['unannotated', `待盲标 (${evaluation.scenarios.length - evaluation.annotated_scenario_count})`],
                ] as const).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    className={`filter-chip ${scenarioFilter === key ? 'is-active' : ''}`}
                    onClick={() => setScenarioFilter(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="workspace-table-scroll">
              <table className="workspace-table">
                <thead>
                  <tr>
                    <th>病例 / 触发截点</th>
                    <th>可见事件</th>
                    <th>B3 结论</th>
                    <th>调用对比 (B3 vs A3)</th>
                    <th>特性标记</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredScenarios.map(item => (
                    <tr key={item.scenario_id}>
                      <td>
                        <strong>{item.case_id} · v{item.case_version} · {item.trigger_event_id}</strong>
                        <small>{item.occurred_at} · {item.trigger_event_title}</small>
                      </td>
                      <td className="workspace-number">{item.visible_events} 条</td>
                      <td>{item.b3_decision ? <DecisionBadge decision={item.b3_decision} /> : <span className="pill outline">无输出</span>}</td>
                      <td className="workspace-number">
                        <strong>{item.b3_calls}</strong> / {item.fixed_calls} 次
                      </td>
                      <td>
                        <div className="badge-row">
                          {item.memory_impacted && <span className="pill soft">纵向记忆影响</span>}
                          <span className={`pill ${item.annotated ? 'status-completed' : 'outline'}`}>
                            {item.annotated ? '已盲标' : '待盲标'}
                          </span>
                        </div>
                      </td>
                      <td>
                        <div className="table-quick-links">
                          <Link
                            className="text-link"
                            to={`/research/cases/${encodeURIComponent(item.case_id)}?version=${item.case_version}&trigger=${encodeURIComponent(item.trigger_event_id)}&view=workflow`}
                          >
                            查看工作流 <Icon name="arrow" size={13} />
                          </Link>
                          <Link
                            className="text-link"
                            to={`/research/experiments?view=annotate&scenario=${encodeURIComponent(item.scenario_id)}`}
                          >
                            {item.annotated ? '复核盲标' : '去盲标'}
                          </Link>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {filteredScenarios.length === 0 && (
                    <tr><td colSpan={6} className="muted table-empty-cell">当前筛选条件下无匹配截点。</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function DataCapabilitiesView() {
  const query = useQuery({ queryKey: researchKeys.dataCapabilities, queryFn: researchApi.dataCapabilities });
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
  const { params, update } = useWorkspaceParams();
  const view = currentView(expTabs, params.get('view'));
  const requestedCase = params.get('case') ?? '';
  const requestedScenario = params.get('scenario') ?? '';
  const casesQuery = useQuery({ queryKey: researchKeys.cases, queryFn: researchApi.cases, enabled: view === 'batch' });

  const [scope, setScope] = useState<'all' | 'latest'>('all');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [initialized, setInitialized] = useState(false);
  const [reviewMode, setReviewMode] = useState<'multi' | 'single'>('multi');

  const evaluate = useMutation({
    mutationFn: researchApi.evaluateExperiments,
  });

  useEffect(() => {
    if (casesQuery.data && !initialized) {
      const requested = requestedCase ? casesQuery.data.filter(c => c.case_id === requestedCase) : [];
      if (requested.length > 0) {
        setScope(requested[0].timeline.length <= 80 ? 'all' : 'latest');
        setSelectedIds([requested[0].case_id]);
        setInitialized(true);
        return;
      }
      const compact = casesQuery.data.filter(c => c.timeline.length <= 30);
      const defaultCases = (compact.length > 0 ? compact : casesQuery.data).slice(0, maxBatchCases);
      const totalCutoffs = defaultCases.reduce((sum, c) => sum + c.timeline.length, 0);
      const initialScope: 'all' | 'latest' = totalCutoffs <= 80 ? 'all' : 'latest';
      const ids = defaultCases.map(c => c.case_id);
      setScope(initialScope);
      setSelectedIds(ids);
      setInitialized(true);
    }
  }, [casesQuery.data, initialized, requestedCase]);

  if (view === 'batch' && casesQuery.isPending) return <Loading />;
  if (view === 'batch' && casesQuery.isError) return <ErrorState error={casesQuery.error} retry={() => void casesQuery.refetch()} />;

  function toggleCase(id: string) {
    evaluate.reset();
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  }

  const tabsWithBadges = [
    { key: 'batch' as const, label: '8 组配对实验与导出', badge: evaluate.data ? `${evaluate.data.scenario_count} 截点` : undefined },
    { key: 'annotate' as const, label: '独立盲标工作台' },
    { key: 'pipeline' as const, label: '多模态数据接入架构', badge: '5 类模态' },
  ];

  return (
    <div className="page-enter research-page workspace-page">
      <header className="workspace-heading">
        <div>
          <h1>科研实验、独立盲标与论文导出</h1>
          <p>按冻结截点记录独立参考，比较八组方法的调用开销与流程判断。</p>
        </div>
      </header>

      <WorkspaceViews
        label="实验与评测视图"
        tabs={tabsWithBadges}
        value={view}
        onChange={v => update({ view: v === 'batch' ? '' : v })}
      />

      <TabPanelTransition tabs={expTabs} activeKey={view}>
        {view === 'batch' && casesQuery.data && (
          <BatchEvaluationView
            cases={casesQuery.data}
            evaluation={evaluate.data}
            scope={scope}
            selectedIds={selectedIds}
            busy={evaluate.isPending}
            error={evaluate.error}
            onScopeChange={value => { evaluate.reset(); setScope(value); }}
            onToggleCase={toggleCase}
            onRun={() => evaluate.mutate({
              case_ids: selectedIds, trigger_scope: scope,
              case_versions: Object.fromEntries(casesQuery.data.filter(item => selectedIds.includes(item.case_id))
                .map(item => [item.case_id, item.version])),
            })}
          />
        )}
        {view === 'annotate' && (
          <div className="workspace-column">
            <div className="scenario-filter-bar" role="group" aria-label="盲标模式切换">
              <button type="button" className={`filter-chip ${reviewMode === 'multi' ? 'is-active' : ''}`}
                onClick={() => setReviewMode('multi')}>多人独立盲标与仲裁 (G03)</button>
              <button type="button" className={`filter-chip ${reviewMode === 'single' ? 'is-active' : ''}`}
                onClick={() => setReviewMode('single')}>单人快速参考标注</button>
            </div>
            {reviewMode === 'multi'
              ? <MultiRaterPanel requestedScenario={requestedScenario} onChanged={evaluate.reset} />
              : <BlindReviewWorkbench requestedScenario={requestedScenario} onChanged={evaluate.reset} />}
          </div>
        )}
        {view === 'pipeline' && <DataCapabilitiesView />}
      </TabPanelTransition>
    </div>
  );
}
