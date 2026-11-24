import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { DecisionBadge, ErrorState, Icon, Loading } from '../ui';
import { researchApi } from './api';
import { eventNames, InlineError, roleNames, roleOrder } from './components';
import { researchKeys } from './query-keys';
import type { AgreementReport, BlindMaterial, MultiRaterSubmission, ReviewPanelTask, Role } from './schemas';
import { PageLinks, pageSlice } from './workspace-controls';
import { factKeyLabel } from './zh-dict';

type Decision = MultiRaterSubmission['expected_decision'];

const disagreementLabels: Record<string, string> = {
  decision: '流程标签分歧',
  required_agents: '必要专科分歧',
  missing_fields: '缺失字段分歧',
};

function toggle<T>(values: T[], value: T) {
  return values.includes(value) ? values.filter(item => item !== value) : [...values, value];
}

function MultiRaterForm({ task, reviewer, material, existing, onChanged, onSavedAdvance }: {
  task: ReviewPanelTask;
  reviewer: string;
  material: BlindMaterial;
  existing: MultiRaterSubmission | null;
  onChanged: () => void;
  onSavedAdvance?: () => void;
}) {
  const client = useQueryClient();
  const [decision, setDecision] = useState<Decision | ''>(existing?.expected_decision ?? '');
  const [roles, setRoles] = useState<Role[]>(existing?.required_agents ?? []);
  const [evidence, setEvidence] = useState(existing?.evidence_ids ?? []);
  const [missing, setMissing] = useState(existing?.missing_fields.join('\n') ?? '');
  const [rationale, setRationale] = useState(existing?.rationale ?? '');
  const [autoAdvance, setAutoAdvance] = useState(true);
  const ownKey = researchKeys.reviewPanelOwn(task.scenario_id, reviewer);

  const save = useMutation({
    mutationFn: (label: Decision) => researchApi.saveReviewSubmission(task.scenario_id, {
      case_id: task.case_id,
      case_version: task.case_version,
      trigger_event_id: task.trigger_event_id,
      annotator_id: reviewer,
      input_sha256: material.input_sha256,
      evidence_ids: evidence,
      required_agents: roles,
      expected_decision: label,
      missing_fields: [...new Set(missing.split(/\r?\n/).map(field => field.trim()).filter(Boolean))],
      rationale: rationale.trim(),
    }),
    onSuccess: record => {
      client.setQueryData(ownKey, record);
      void client.invalidateQueries({ queryKey: researchKeys.reviewPanelAgreement });
      onChanged();
      if (autoAdvance && onSavedAdvance) onSavedAdvance();
    },
  });

  const remove = useMutation({
    mutationFn: () => researchApi.deleteReviewSubmission(task.scenario_id, reviewer),
    onSuccess: () => {
      client.setQueryData(ownKey, null);
      void client.invalidateQueries({ queryKey: researchKeys.reviewPanelAgreement });
      onChanged();
    },
  });

  const busy = save.isPending || remove.isPending;
  const stale = Boolean(existing?.input_sha256 && existing.input_sha256 !== material.input_sha256);

  return (
    <div className="workspace-column">
      <section className="panel blind-material-panel">
        <div className="workspace-section-heading">
          <div>
            <h2>截点盲审材料（严格屏蔽同行意见与系统预测）</h2>
            <p className="muted">
              {task.case_id} · v{task.case_version} · 截至 {material.events.at(-1)?.occurred_at}（{task.trigger_event_id}）
            </p>
          </div>
          <span className="pill outline">{material.events.length} 条可见记录</span>
        </div>
        <div className="blind-frozen-events">
          {material.events.map(event => (
            <article key={event.event_id} className={`blind-event-card ${event.event_id === task.trigger_event_id ? 'is-cutoff' : ''}`}>
              <div className="blind-event-head">
                <strong>{event.occurred_at} · {event.title}</strong>
                <span className="pill soft">{eventNames[event.event_type]} · {event.event_id}</span>
              </div>
              <div className="blind-evidence-list">
                {Object.entries(event.facts).map(([key, value]) => {
                  const id = `${event.event_id}:${key}`;
                  return (
                    <label key={id} className="blind-evidence-row">
                      <input
                        type="checkbox"
                        aria-label={`引用 ${id}`}
                        checked={evidence.includes(id)}
                        disabled={!reviewer || busy || stale}
                        onChange={() => setEvidence(prev => toggle(prev, id))}
                      />
                      <span><strong>{factKeyLabel(key)}</strong><small>{id}</small></span>
                      <span>{value === null ? '未记录' : typeof value === 'boolean' ? (value ? '是' : '否') : String(value)}</span>
                    </label>
                  );
                })}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="workspace-section-heading">
          <h2>独立初标录入（多人盲标）</h2>
          {existing && <span className="pill status-completed" role="status">本人已提交 · {reviewer}</span>}
        </div>
        {!reviewer ? (
          <p className="muted">请先在左侧填写您的标注人编号（如 <code>rater_1</code>、<code>rater_2</code>），不同标注人可独立提交同一截点且彼此完全不可见。</p>
        ) : (
          <form
            className="research-form"
            onKeyDown={e => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && decision && roles.length && !busy && !stale) {
                e.preventDefault();
                save.mutate(decision);
              }
            }}
            onSubmit={e => {
              e.preventDefault();
              if (decision && roles.length && !busy && !stale) save.mutate(decision);
            }}
          >
            {stale && <p className="notice" role="alert">已保存初标与当前材料指纹不同，请核查病例版本。</p>}
            <label>预期流程结论
              <select value={decision} required onChange={e => setDecision(e.target.value as Decision)}>
                <option value="" disabled>请选择结论</option>
                <option value="READY_FOR_REVIEW">可进入人工资料复核</option>
                <option value="NEED_MORE_INFORMATION">需要补充资料</option>
                <option value="DEFER_DECISION">暂缓判断</option>
              </select>
            </label>
            <fieldset className="blind-roles"><legend>必要参与专科（至少一科）</legend>
              <div className="fact-toggle-grid">
                {roleOrder.map(role => (
                  <label key={role} className={`fact-toggle-chip ${roles.includes(role) ? 'is-active' : ''}`}>
                    <input type="checkbox" checked={roles.includes(role)} onChange={() => setRoles(prev => toggle(prev, role))} />
                    <span>{roleNames[role]}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <label>缺失字段（每行一项）
              <textarea rows={2} value={missing} onChange={e => setMissing(e.target.value)} />
            </label>
            <label>判断依据
              <textarea rows={3} maxLength={2000} value={rationale} onChange={e => setRationale(e.target.value)}
                placeholder="独立说明支持结论的关键事实、资料缺口或同日冲突。" />
            </label>
            <p className="muted">已勾选 {evidence.length} 项可见证据 · 支持快捷键 <kbd>⌘/Ctrl + Enter</kbd> 提交。</p>
            <label className="fact-toggle-chip">
              <input type="checkbox" checked={autoAdvance} onChange={e => setAutoAdvance(e.target.checked)} />
              <span>保存后自动跳至下一本人待标截点</span>
            </label>
            <InlineError error={save.error || remove.error} />
            <div className="button-group">
              <button className="button primary" type="submit" disabled={!decision || !roles.length || busy || stale}>
                <Icon name="check" size={15} />{save.isPending ? '正在保存…' : '保存独立初标'}
              </button>
              {existing && (
                <button className="button secondary" type="button" disabled={busy} onClick={() => remove.mutate()}>
                  撤回我的初标
                </button>
              )}
            </div>
          </form>
        )}
      </section>
    </div>
  );
}

function MultiRaterTaskPanel({ task, reviewer, onChanged, onSavedAdvance }: {
  task: ReviewPanelTask;
  reviewer: string;
  onChanged: () => void;
  onSavedAdvance: () => void;
}) {
  const material = useQuery({ queryKey: researchKeys.blindMaterial(task.scenario_id), queryFn: () => researchApi.blindMaterial(task) });
  const own = useQuery({
    queryKey: researchKeys.reviewPanelOwn(task.scenario_id, reviewer),
    queryFn: () => researchApi.reviewPanelOwn(task.scenario_id, reviewer),
    enabled: Boolean(reviewer),
  });
  if (material.isError || (reviewer && own.isError)) {
    return <ErrorState error={material.error || own.error} retry={() => { void material.refetch(); if (reviewer) void own.refetch(); }} />;
  }
  if (!material.data || (reviewer && own.isPending)) return <Loading />;
  return (
    <MultiRaterForm
      key={JSON.stringify([task.scenario_id, material.data.input_sha256, reviewer, own.data?.updated_at])}
      task={task}
      material={material.data}
      existing={own.data ?? null}
      reviewer={reviewer}
      onChanged={onChanged}
      onSavedAdvance={onSavedAdvance}
    />
  );
}

function DisputeAdjudicationCard({
  dispute,
  adjudicatorId,
  onSaved,
}: {
  dispute: AgreementReport['disputed_scenarios'][number];
  adjudicatorId: string;
  onSaved: () => void;
}) {
  const existing = dispute.adjudication;
  const [decision, setDecision] = useState<Decision>(
    existing?.expected_decision ?? dispute.submissions[0]?.expected_decision ?? 'NEED_MORE_INFORMATION',
  );
  const [roles, setRoles] = useState<Role[]>(
    existing?.required_agents ?? dispute.submissions[0]?.required_agents ?? ['oncology'],
  );
  const [missing, setMissing] = useState(
    (existing?.missing_fields ?? dispute.submissions[0]?.missing_fields ?? []).join('\n'),
  );
  const [rationale, setRationale] = useState(existing?.adjudication_rationale ?? '');

  const save = useMutation({
    mutationFn: () => researchApi.saveAdjudication(dispute.scenario_id, {
      case_id: dispute.case_id,
      case_version: dispute.case_version,
      trigger_event_id: dispute.trigger_event_id,
      adjudicator_id: adjudicatorId,
      required_agents: roles,
      expected_decision: decision,
      input_sha256: dispute.submissions[0]?.input_sha256 ?? null,
      evidence_ids: [...new Set(dispute.submissions.flatMap(s => s.evidence_ids))],
      missing_fields: [...new Set(missing.split(/\r?\n/).map(v => v.trim()).filter(Boolean))],
      adjudication_rationale: rationale.trim(),
    }),
    onSuccess: () => onSaved(),
  });

  return (
    <article className="panel workflow-card">
      <div className="workspace-section-heading">
        <div>
          <h3>{dispute.scenario_id}</h3>
          <p className="muted">
            参与标注人：{dispute.annotators.join('、')} · 分歧维度：{dispute.disagreement_types.map(t => disagreementLabels[t] ?? t).join(' / ')}
          </p>
        </div>
        <span className={`pill ${dispute.adjudicated ? 'status-completed' : 'status-warning'}`}>
          {dispute.adjudicated ? '已仲裁定稿' : '待仲裁'}
        </span>
      </div>

      <div className="contrast-grid contrast-grid-spaced">
        {dispute.submissions.map(sub => (
          <div key={sub.annotator_id} className="contrast-card">
            <div className="contrast-head">
              <strong>标注人：{sub.annotator_id}</strong>
              <DecisionBadge decision={sub.expected_decision} />
            </div>
            <p className="muted">必要专科：{sub.required_agents.map(r => roleNames[r]).join('、')}</p>
            {sub.missing_fields.length > 0 && <p className="muted">缺失字段：{sub.missing_fields.join('、')}</p>}
            {sub.rationale && <p>{sub.rationale}</p>}
          </div>
        ))}
      </div>

      <form className="research-form" onSubmit={e => {
        e.preventDefault();
        if (adjudicatorId.trim() && roles.length) save.mutate();
      }}>
        <label>仲裁最终流程结论
          <select value={decision} onChange={e => setDecision(e.target.value as Decision)}>
            <option value="READY_FOR_REVIEW">可进入人工资料复核</option>
            <option value="NEED_MORE_INFORMATION">需要补充资料</option>
            <option value="DEFER_DECISION">暂缓判断</option>
          </select>
        </label>
        <fieldset className="blind-roles"><legend>仲裁最终必要专科</legend>
          <div className="fact-toggle-grid">
            {roleOrder.map(role => (
              <label key={role} className={`fact-toggle-chip ${roles.includes(role) ? 'is-active' : ''}`}>
                <input type="checkbox" checked={roles.includes(role)} onChange={() => setRoles(prev => toggle(prev, role))} />
                <span>{roleNames[role]}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <label>仲裁确认缺失字段（每行一项）
          <textarea rows={2} value={missing} onChange={e => setMissing(e.target.value)} />
        </label>
        <label>仲裁理由
          <textarea rows={2} value={rationale} onChange={e => setRationale(e.target.value)}
            placeholder="说明为何采纳该结论与专科集合，作为论文争议复核记录。" />
        </label>
        <InlineError error={save.error} />
        <button type="submit" className="button primary" disabled={!adjudicatorId.trim() || !roles.length || save.isPending}>
          <Icon name="check" size={15} />{save.isPending ? '正在保存仲裁…' : '提交仲裁共识金标准'}
        </button>
      </form>
    </article>
  );
}

const REVIEWER_SESSION_KEY = 'mdt-active-reviewer';

function loadSessionReviewer(): string {
  try {
    return sessionStorage.getItem(REVIEWER_SESSION_KEY) ?? '';
  } catch {
    return '';
  }
}

function saveSessionReviewer(value: string) {
  try {
    if (value) sessionStorage.setItem(REVIEWER_SESSION_KEY, value);
    else sessionStorage.removeItem(REVIEWER_SESSION_KEY);
  } catch {
    // Ignore restricted storage environments.
  }
}

export function MultiRaterPanel({ requestedScenario = '', onChanged }: { requestedScenario?: string; onChanged: () => void }) {
  const [subView, setSubView] = useState<'blind' | 'agreement' | 'adjudicate'>('blind');
  const [reviewer, setReviewer] = useState(loadSessionReviewer);
  const [identity, setIdentity] = useState(loadSessionReviewer);
  const [adjudicatorId, setAdjudicatorId] = useState('adjudicator_1');
  const [selected, setSelected] = useState(requestedScenario);
  const [page, setPage] = useState(1);

  const tasksQuery = useQuery({
    queryKey: researchKeys.reviewPanelTasks(reviewer),
    queryFn: () => researchApi.reviewPanelTasks(reviewer || undefined),
  });
  const agreementQuery = useQuery({
    queryKey: researchKeys.reviewPanelAgreement,
    queryFn: researchApi.reviewPanelAgreement,
    enabled: subView !== 'blind',
  });

  useEffect(() => {
    if (!requestedScenario || !tasksQuery.data) return;
    const idx = tasksQuery.data.findIndex(t => t.scenario_id === requestedScenario);
    if (idx >= 0) {
      setSelected(requestedScenario);
      setPage(Math.floor(idx / 20) + 1);
    }
  }, [requestedScenario, tasksQuery.data]);

  if (tasksQuery.isError) return <ErrorState error={tasksQuery.error} retry={() => void tasksQuery.refetch()} />;
  if (!tasksQuery.data) return <Loading />;

  const queue = tasksQuery.data;
  const active = queue.find(t => t.scenario_id === selected) ?? queue[0];
  const { rows, page: currentPage, pages, first } = pageSlice(queue, page);
  const multiRatedCount = queue.filter(t => t.submission_count >= 2).length;

  function advanceNext() {
    if (!active) return;
    const start = queue.indexOf(active) + 1;
    const next = [...queue.slice(start), ...queue.slice(0, start)].find(t => !t.own_submitted && t !== active);
    if (next) {
      setSelected(next.scenario_id);
      setPage(Math.floor(queue.indexOf(next) / 20) + 1);
    }
  }

  return (
    <div className="workspace-column">
      <div className="panel panel-compact">
        <div className="workspace-section-heading heading-flush">
          <div className="scenario-filter-bar" role="tablist" aria-label="多人盲标与仲裁阶段">
            <button type="button" className={`filter-chip ${subView === 'blind' ? 'is-active' : ''}`}
              onClick={() => setSubView('blind')}>1. 独立盲标录入</button>
            <button type="button" className={`filter-chip ${subView === 'agreement' ? 'is-active' : ''}`}
              onClick={() => setSubView('agreement')}>2. 一致性统计 (Cohen&apos;s κ)</button>
            <button type="button" className={`filter-chip ${subView === 'adjudicate' ? 'is-active' : ''}`}
              onClick={() => setSubView('adjudicate')}>3. 争议仲裁定稿</button>
          </div>
          <div className="button-group">
            <a className="button secondary" href="/api/v2/review-panel/export/annotations.jsonl">
              <Icon name="download" size={14} />导出 annotations.jsonl
            </a>
            <a className="button secondary" href="/api/v2/review-panel/export/adjudication.jsonl">
              <Icon name="download" size={14} />导出 adjudication.jsonl
            </a>
          </div>
        </div>
      </div>

      {subView === 'blind' && active && (
        <div className="blind-annotation-layout">
          <aside className="panel blind-scenario-list" aria-label="多人盲标任务队列">
            <div className="workspace-section-heading">
              <h2>截点队列</h2>
              <span className="pill soft">{multiRatedCount} / {queue.length} 已双标</span>
            </div>
            <div className="blind-progress-wrap">
              <progress max={queue.length} value={multiRatedCount} aria-label="双人盲标进度" />
              <form className="research-form" onSubmit={e => {
                e.preventDefault();
                const trimmed = identity.trim();
                saveSessionReviewer(trimmed);
                setReviewer(trimmed);
              }}>
                <label>当前标注人编号
                  <input value={identity} maxLength={80} required readOnly={Boolean(reviewer)}
                    placeholder="如 rater_1 / rater_2" onChange={e => setIdentity(e.target.value)} autoComplete="off" />
                </label>
                {reviewer ? (
                  <button type="button" className="button secondary" onClick={() => {
                    saveSessionReviewer('');
                    setIdentity('');
                    setReviewer('');
                  }}>
                    切换标注人
                  </button>
                ) : (
                  <button className="button secondary" disabled={!identity.trim()}>启用盲标身份</button>
                )}
              </form>
              <button type="button" className="text-link" disabled={!queue.some(t => !t.own_submitted && t !== active)}
                onClick={advanceNext}>
                下一待标截点 <Icon name="arrow" size={14} />
              </button>
            </div>
            <div className="blind-list-scroll">
              {rows.map((task, index) => (
                <button
                  type="button"
                  key={task.scenario_id}
                  aria-current={task === active ? 'true' : undefined}
                  className={`blind-scenario-btn ${task === active ? 'is-selected' : ''}`}
                  onClick={() => setSelected(task.scenario_id)}
                >
                  <strong>任务 {first + index}</strong>
                  <span className={`pill ${task.adjudicated ? 'status-completed' : task.own_submitted ? 'soft' : 'outline'}`}>
                    {task.adjudicated ? '已仲裁' : `${task.submission_count} 人标`}
                  </span>
                </button>
              ))}
            </div>
            <PageLinks page={currentPage} pages={pages} onPage={setPage} />
          </aside>

          <MultiRaterTaskPanel
            key={active.scenario_id}
            task={active}
            reviewer={reviewer}
            onChanged={() => { void tasksQuery.refetch(); onChanged(); }}
            onSavedAdvance={advanceNext}
          />
        </div>
      )}

      {subView === 'agreement' && (
        agreementQuery.isPending ? <Loading /> : agreementQuery.isError ? (
          <ErrorState error={agreementQuery.error} retry={() => void agreementQuery.refetch()} />
        ) : agreementQuery.data && (
          <div className="workspace-column">
            <div className="telemetry-grid">
              <div className="telemetry-card">
                <span>多标注人覆盖截点</span>
                <strong>{agreementQuery.data.multi_rated_scenarios} <small>/ {agreementQuery.data.scenarios_with_submissions}</small></strong>
                <p>参与标注人数：{Object.keys(agreementQuery.data.annotator_counts).length} 人</p>
              </div>
              <div className="telemetry-card accent">
                <span>三分类标签 Cohen&apos;s κ</span>
                <strong>
                  {agreementQuery.data.decision_agreement.cohens_kappa !== null
                    ? agreementQuery.data.decision_agreement.cohens_kappa.toFixed(3)
                    : '—'}
                </strong>
                <p>
                  原始一致率：{agreementQuery.data.decision_agreement.raw_agreement !== null
                    ? `${(agreementQuery.data.decision_agreement.raw_agreement * 100).toFixed(1)}%`
                    : '待双人标注'}
                </p>
              </div>
              <div className="telemetry-card">
                <span>必要专科平均 Jaccard 重合度</span>
                <strong>
                  {agreementQuery.data.specialist_agreement.mean_jaccard !== null
                    ? `${(agreementQuery.data.specialist_agreement.mean_jaccard * 100).toFixed(1)}%`
                    : '—'}
                </strong>
                <p>
                  集合完全一致：{agreementQuery.data.specialist_agreement.exact_set_agreement !== null
                    ? `${(agreementQuery.data.specialist_agreement.exact_set_agreement * 100).toFixed(1)}%`
                    : '—'}
                </p>
              </div>
              <div className="telemetry-card">
                <span>争议与仲裁进度</span>
                <strong>{agreementQuery.data.adjudicated_count} <small>/ {agreementQuery.data.disputed_count} 争议</small></strong>
                <p>待仲裁争议：{agreementQuery.data.unadjudicated_disputes} 个截点</p>
              </div>
            </div>

            <section className="panel workflow-card">
              <div className="workspace-section-heading">
                <h2>逐专科二分类一致率与 Cohen&apos;s κ</h2>
                <span className="pill outline">协议 {agreementQuery.data.protocol_version}</span>
              </div>
              <div className="workspace-table-scroll">
                <table className="workspace-table">
                  <thead>
                    <tr>
                      <th>专科角色</th>
                      <th>配对数</th>
                      <th>原始一致率</th>
                      <th>Cohen&apos;s κ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {roleOrder.map(role => {
                      const st = agreementQuery.data.specialist_agreement.per_role[role];
                      return (
                        <tr key={role}>
                          <td><strong>{roleNames[role]}</strong></td>
                          <td className="workspace-number">{st?.pair_count ?? 0}</td>
                          <td className="workspace-number">
                            {st?.raw_agreement !== null && st?.raw_agreement !== undefined
                              ? `${(st.raw_agreement * 100).toFixed(1)}%`
                              : '—'}
                          </td>
                          <td className="workspace-number">
                            {st?.cohens_kappa !== null && st?.cohens_kappa !== undefined
                              ? st.cohens_kappa.toFixed(3)
                              : '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="notice neutral notice-spaced">
                <Icon name="info" size={16} />
                <span>{agreementQuery.data.summary_note}</span>
              </p>
            </section>
          </div>
        )
      )}

      {subView === 'adjudicate' && (
        agreementQuery.isPending ? <Loading /> : agreementQuery.isError ? (
          <ErrorState error={agreementQuery.error} retry={() => void agreementQuery.refetch()} />
        ) : agreementQuery.data && (
          <div className="workspace-column">
            <section className="panel panel-compact">
              <label className="adjudicator-bar">
                <strong>仲裁人编号</strong>
                <input value={adjudicatorId} maxLength={80} onChange={e => setAdjudicatorId(e.target.value)} />
                <span className="muted">仲裁定稿后的共识金标准将自动作为 8 组配对评测的最高优先级参考。</span>
              </label>
            </section>
            {agreementQuery.data.disputed_scenarios.length === 0 ? (
              <p className="panel workspace-empty">当前没有存在初标分歧的争议截点。请在「独立盲标录入」中由至少两位标注人独立标注后查看。</p>
            ) : (
              agreementQuery.data.disputed_scenarios.map(dispute => (
                <DisputeAdjudicationCard
                  key={dispute.scenario_id}
                  dispute={dispute}
                  adjudicatorId={adjudicatorId}
                  onSaved={() => { void agreementQuery.refetch(); void tasksQuery.refetch(); onChanged(); }}
                />
              ))
            )}
          </div>
        )
      )}
    </div>
  );
}
