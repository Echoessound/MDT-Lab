import { useEffect, useRef, useState } from 'react';
import { DecisionBadge, Icon, Modal, Status, dateTime } from '../ui';
import type { AuditEvent, ClinicalEvent, Evidence, Metrics, Opinion, ResearchCase, Role, Routing, Run, Safety } from './schemas';

export const roleNames: Record<Role, string> = { oncology: '肿瘤内科', radiology: '影像科', surgery: '外科', pathology: '病理科' };
export const roleOrder: Role[] = ['oncology', 'radiology', 'surgery', 'pathology'];
export const eventNames = { diagnosis: '诊断记录', imaging: '影像检查', pathology: '病理检查', molecular_test: '分子检测', procedure: '操作记录', treatment: '治疗记录', medication: '用药记录', toxicity: '不良反应', follow_up: '随访', progression: '疾病进展', recurrence: '复发记录', observation: '观察记录' };
export const scenarioNames = { standard: '标准流程', partial_failure: '角色调用失败', persistent_disagreement: '保留分歧', invalid_evidence: '非法证据引用' };
export const stageNames: Record<string, string> = { CREATED: '运行已创建', QUEUED: '等待执行', INITIALIZING: '校验病例', ROUTING: '动态调度', AGENTS_RUNNING: '专科分析', CONFLICT_CHECK: '分歧检测', DISCUSSION: '定向讨论', SAFETY_CHECK: '证据与安全检查', REPORTING: '生成报告', COMPLETED: '运行完成', FAILED: '运行失败', CANCELLED: '运行停止' };
export const sexName = (sex: string) => ({ female: '女性', male: '男性', other: '其他', unknown: '未记录' }[sex] ?? '未记录');
export const formatValue = (value: unknown) => value === null ? '未记录' : value === true ? '是' : value === false ? '否' : String(value);
export function InlineError({ error }: { error: unknown }) { return error ? <div className="inline-error" role="alert">{error instanceof Error ? error.message : '操作失败，请重试。'}</div> : null; }

export function Timeline({ events, trigger, onTrigger }: { events: ClinicalEvent[]; trigger: string; onTrigger?: (id: string) => void }) {
  return <ol className="research-timeline">{events.map(event => <li key={event.event_id} className={trigger === event.event_id ? 'current-event' : ''}>
    <div className="event-heading"><span className="event-date">{event.occurred_at}</span><span className="pill outline">{eventNames[event.event_type]}</span>{trigger === event.event_id && <span className="pill soft">本次触发事件</span>}</div>
    <h3>{event.title}</h3><div className="event-meta"><code>{event.event_id}</code><span>加入于 v{event.introduced_in_version}</span><span>{event.synthetic_extension ? '人工合成扩展' : '来源原始记录'}</span></div>
    <dl className="event-facts">{Object.entries(event.facts).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{formatValue(value)}</dd></div>)}</dl>
    <div className="event-source"><span>来源：{event.source}{event.source_record_locator && <small className="source-locator">{event.source_record_locator}</small>}</span>{onTrigger && <button className="text-link" disabled={trigger === event.event_id} onClick={() => onTrigger(event.event_id)}>{trigger === event.event_id ? '已选为触发事件' : '以此事件发起评议'}<Icon name="arrow" size={14} /></button>}</div>
  </li>)}</ol>;
}

export function RoutingPanel({ routing }: { routing: Routing }) {
  return <section className="panel routing-panel"><div className="section-heading"><div><div className="eyebrow">EVENT-DRIVEN ROUTING</div><h2>本次专科调度</h2></div><span className="pill soft">{routing.selected_agents.length} / {roleOrder.length} 个角色参与</span></div>
    <div className="routing-grid">{roleOrder.map(role => { const selected = routing.selected_agents.includes(role); return <div className={`routing-role ${selected ? 'selected-role' : ''}`} key={role}><span className="routing-mark"><Icon name={selected ? 'check' : 'stop'} size={17} /></span><div><strong>{roleNames[role]}</strong><small>{selected ? '参与本次评议' : '本次跳过'}</small>{routing.reasons.filter(reason => reason.agent_id === role).map(reason => <p key={reason.rule_id}>{reason.description}<code>{reason.rule_id}</code></p>)}</div></div>; })}</div>
    <div className="subtle-note">规则版本 {routing.strategy_version} · 触发事件 {routing.trigger_event_id}。调度仅验证研究规则，不表示临床必需专科已被覆盖。</div>
  </section>;
}

export function EvidenceDialog({ evidence, researchCase, onClose }: { evidence: Evidence; researchCase?: ResearchCase; onClose: () => void }) {
  const event = researchCase?.timeline.find(item => item.event_id === evidence.event_id);
  return <Modal title="证据与原始事实" onClose={onClose}><span className="pill soft">{evidence.synthetic ? '合成事实' : '公开数据事实'}</span><dl className="detail-list">
    <div><dt>证据 ID</dt><dd><code>{evidence.evidence_id}</code></dd></div><div><dt>引用的事实</dt><dd>{evidence.quote_or_fact}</dd></div><div><dt>字段与取值</dt><dd><code>{evidence.fact_key}</code> = {formatValue(evidence.value)}</dd></div>
    <div><dt>冻结的病例版本</dt><dd>{researchCase ? `${researchCase.case_id} / v${researchCase.version}` : '见本次报告的病例快照'}</dd></div><div><dt>原始事件</dt><dd>{event ? `${event.occurred_at} · ${event.title}` : evidence.event_id}</dd></div>
    <div><dt>来源 / 数据版本</dt><dd>{evidence.source_name} / {evidence.dataset_version}<br />记录 ID：{evidence.source_record_id ?? '本地合成记录'}</dd></div>
    {evidence.source_record_locator && <div><dt>原文件 / 字段</dt><dd>{evidence.source_record_locator}<br />{evidence.source_field}</dd></div>}
    {evidence.artifact_sha256 && <div><dt>文件 SHA-256</dt><dd className="source-hash">{evidence.artifact_sha256}</dd></div>}
  </dl><p className="subtle-note">引用校验只证明与本次输入一致，不证明医学正确性。</p></Modal>;
}

export function EvidenceButtons({ evidence, onSelect }: { evidence: Evidence[]; onSelect: (value: Evidence) => void }) {
  return <div className="research-evidence-list">{evidence.map(item => <button className="evidence-chip" key={item.evidence_id} onClick={() => onSelect(item)} aria-label={`查看证据 ${item.evidence_id}`} title={item.quote_or_fact}>{item.event_id} · {item.fact_key}<Icon name="arrow" size={12} /></button>)}</div>;
}

export function OpinionView({ opinion, onEvidence }: { opinion: Opinion; onEvidence: (value: Evidence) => void }) {
  return <div className="research-opinion"><DecisionBadge decision={opinion.decision} /><p>{opinion.summary}</p><EvidenceButtons evidence={opinion.evidence_refs} onSelect={onEvidence} />
    {opinion.missing_information.length > 0 && <p className="opinion-missing">待补：{opinion.missing_information.join('、')}</p>}<div className="opinion-model">{opinion.model_info.provider} / {opinion.model_info.model}<span>{opinion.model_info.attempts} 次尝试</span></div>
  </div>;
}

export function AgentCards({ run, onEvidence }: { run: Run; onEvidence: (value: Evidence) => void }) {
  return <div className="research-agent-grid">{run.agents.map(agent => <article key={agent.agent_id} className={`panel research-agent agent-state-${agent.status}`}><div className="section-heading"><div><span className="eyebrow">{agent.agent_id.toUpperCase()}</span><h3>{roleNames[agent.agent_id]}</h3></div>{agent.status === 'idle' ? <span className="pill">未调度</span> : <Status status={agent.status} />}</div>
    {agent.status === 'skipped' ? <p className="agent-empty">本次事件未选中此角色，不计入有效意见分母。</p> : agent.status === 'failed' ? <><p className="danger-text">未获得有效意见</p><code className="agent-error-code">{agent.error}</code><p className="agent-empty">安全门控将保留错误并暂缓判断。</p></> : agent.opinion ? <><div className="before-label">{agent.previous_opinion && <>讨论前：<DecisionBadge decision={agent.previous_opinion.decision} /></>}</div><OpinionView opinion={agent.opinion} onEvidence={onEvidence} /></> : <p className="agent-empty">{agent.status === 'running' ? '正在读取冻结上下文并生成结构化意见…' : '等待协调器执行本次任务。'}</p>}
  </article>)}</div>;
}

export function SafetyPanel({ safety, evidence = [], onEvidence }: { safety: Safety; evidence?: Evidence[]; onEvidence: (value: Evidence) => void }) {
  return <section className={`panel safety-panel safety-${safety.status}`}><div className="section-heading"><div><div className="eyebrow">EVIDENCE-SAFETY GATE</div><h2>证据与信息充分性检查</h2></div><DecisionBadge decision={safety.decision} /></div>
    <div className="safety-verdict"><Icon name={safety.status === 'passed' ? 'check' : 'alert'} /><strong>{{ passed: '规则检查通过', needs_information: '需要补充信息', blocked: '存在阻断项，暂缓判断' }[safety.status]}</strong></div>
    <div className="safety-checks">{safety.checks.map((check, index) => <div className={`safety-check check-${check.status}`} key={`${check.code}-${index}`}><Icon name={check.status === 'passed' ? 'check' : 'alert'} size={17} /><div><strong>{check.message}</strong><code>{check.code}</code><EvidenceButtons evidence={evidence.filter(item => check.evidence_ids.includes(item.evidence_id))} onSelect={onEvidence} /></div><span className="check-status">{{ passed: '通过', warning: '待补', blocked: '阻断' }[check.status]}</span></div>)}</div>
    {safety.missing_information.length > 0 && <div className="safety-notes"><h3>待补充资料</h3><ul>{safety.missing_information.map(value => <li key={value}>{value}</li>)}</ul></div>}{safety.warnings.length > 0 && <div className="safety-notes"><h3>边界与警告</h3><ul>{safety.warnings.map(value => <li key={value}>{value}</li>)}</ul></div>}
  </section>;
}

export function MetricsPanel({ metrics, mode }: { metrics: Metrics; mode: string }) {
  return <section className="research-metrics" aria-label="真实运行计数"><div><span>Agent 调用</span><strong>{metrics.agent_calls}</strong></div><div><span>模型请求</span><strong>{metrics.llm_calls}</strong></div><div><span>工具调用</span><strong>{metrics.tool_calls}</strong></div><div><span>实际重试</span><strong>{metrics.retry_count}</strong></div><div><span>输入 / 输出 Token</span><strong>{metrics.prompt_tokens === null ? '—' : metrics.prompt_tokens} / {metrics.completion_tokens === null ? '—' : metrics.completion_tokens}</strong><small>{mode === 'mock' ? 'Mock 不产生模型 Token' : '未返回的用量显示为 —'}</small></div><div><span>已记录耗时</span><strong>{(metrics.elapsed_ms / 1000).toFixed(2)}<small> 秒</small></strong></div></section>;
}

export function WorkflowPanel({ run }: { run: Run }) {
  const stages = ['INITIALIZING', 'ROUTING', 'AGENTS_RUNNING', 'CONFLICT_CHECK', 'DISCUSSION', 'SAFETY_CHECK', 'REPORTING'];
  return <section className="panel"><div className="section-heading"><div><div className="eyebrow">LIVE WORKFLOW</div><h2>{stageNames[run.stage] ?? run.stage}</h2></div><span className="pill">{run.completed_nodes.length} 个节点已完成</span></div><div className="research-stage-list">{stages.map(stage => <span key={stage} className={stage === run.stage ? 'current-stage' : ''}>{stageNames[stage]}</span>)}</div><details><summary>查看实际执行节点</summary><div className="node-groups">{[['已完成', run.completed_nodes], ['正在运行', run.running_nodes], ['等待执行', run.pending_nodes]].map(([label, values]) => <div key={String(label)}><strong>{label}</strong><p>{(values as string[]).length ? (values as string[]).join(' · ') : '无'}</p></div>)}</div></details></section>;
}

export const auditSummary = (event: AuditEvent) => {
  const role = event.agent_id ? roleNames[event.agent_id as Role] ?? event.agent_id : '协调器';
  const known: Record<string, string> = { 'workflow.progress': '实际执行节点已更新', 'run.created': '运行记录已创建', 'run.started': '开始执行冻结病例', 'workflow.stage_changed': `进入${stageNames[event.stage] ?? event.stage}`, 'routing.completed': '已确定本次相关专科', 'agent.started': `${role}开始${event.payload.phase === 'discussion' ? '定向讨论' : '独立评议'}`, 'agent.completed': `${role}提交有效结构化意见`, 'agent.failed': `${role}调用或输出校验失败`, 'conflict.detected': '已记录结构化分歧检查', 'discussion.started': '开始有界定向协商', 'discussion.completed': '定向协商结束', 'safety.completed': '证据与安全门控检查完成', 'tool.completed': `已执行只读工具 ${String(event.payload.tool ?? '')}`, 'report.generated': '结构化报告已生成', 'report.ready': '报告已保存，可查看与下载', 'run.completed': '运行结束，结果已保存', 'run.failed': '运行失败，保留审计记录', 'run.cancelled': '运行已停止，保留审计记录', 'run.cancel_requested': '已接受停止请求' };
  return known[event.type] ?? event.type;
};

export function AuditPanel({ events, runId, connection, reconnect }: { events: AuditEvent[]; runId: string; connection: string; reconnect: () => void }) {
  const [filter, setFilter] = useState('all');
  const [follow, setFollow] = useState(true);
  const [selected, setSelected] = useState<AuditEvent>();
  const container = useRef<HTMLDivElement>(null);
  const visible = events.filter(event => filter === 'all' || (filter === 'failed' ? event.type.includes('failed') : event.agent_id === filter));
  useEffect(() => { if (follow && container.current) container.current.scrollTop = container.current.scrollHeight; }, [events, follow]);
  const labels: Record<string, string> = { connecting: '正在连接', connected: '实时事件在线', reconnecting: '正在恢复连接', synced: '完整审计已同步', offline: '事件流暂不可用' };
  return <section className="panel research-audit"><div className="section-heading"><div><div className="eyebrow">SSE / AUDIT TRAIL</div><h2>运行审计 <span className="count">{events.length}</span></h2></div><a className="icon-button" href={`/api/v2/runs/${runId}/audit/download`} aria-label="下载完整运行审计"><Icon name="download" /></a></div><div className="research-connection" role="status"><span className="status-dot" />{labels[connection]}{['offline', 'reconnecting'].includes(connection) && <button className="text-link" onClick={reconnect}>重新连接</button>}</div>
    <div className="audit-toolbar"><label className="sr-only" htmlFor="research-audit-filter">筛选运行审计</label><select id="research-audit-filter" value={filter} onChange={event => setFilter(event.target.value)}><option value="all">全部事件</option>{roleOrder.map(role => <option key={role} value={role}>{roleNames[role]}</option>)}<option value="failed">失败事件</option></select><label className="check-label"><input type="checkbox" checked={follow} onChange={event => setFollow(event.target.checked)} />跟随最新</label></div>
    <div className="audit-scroll" ref={container} onScroll={() => { const element = container.current; if (element && follow && element.scrollHeight - element.scrollTop - element.clientHeight > 50) setFollow(false); }}>{visible.map(event => <button className={`audit-row ${event.type.includes('failed') ? 'audit-error' : ''}`} key={event.seq} onClick={() => setSelected(event)}><span className="audit-seq">{event.seq}</span><time>{dateTime(event.timestamp)}</time><span>{auditSummary(event)}</span><Icon name="arrow" size={13} /></button>)}{!visible.length && <p className="empty-inline">{events.length ? '没有符合筛选条件的事件。' : '等待第一条已记录事件。'}</p>}</div><p className="subtle-note">按连续序号恢复，最多展示最新 500 条。点击事件查看原始记录。</p>
    {selected && <Modal title={`审计事件 · ${selected.seq}`} onClose={() => setSelected(undefined)}><pre className="json-view">{JSON.stringify(selected, null, 2)}</pre></Modal>}
  </section>;
}
