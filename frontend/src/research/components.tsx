import { useEffect, useMemo, useRef, useState } from 'react';
import './dataset-console.css';
import { DecisionBadge, Icon, Modal, dateTime } from '../ui';
import type { AuditEvent, Evidence, Metrics, Opinion, ResearchCase, Role, Routing, Run, Safety } from './schemas';
import {
  errorCodeLabel,
  factKeyLabel,
  formatFactValue,
  nodeNameLabel,
  providerLabelZh,
  ruleIdLabel,
  safetyCheckLabel,
  sourceNameLabel,
  toolNameLabel,
} from './zh-dict';

export const roleNames: Record<Role, string> = { oncology: '肿瘤内科', radiology: '影像科', surgery: '胸外科', pathology: '病理科' };
export const roleOrder: Role[] = ['oncology', 'radiology', 'surgery', 'pathology'];
export const eventNames = { diagnosis: '初诊登记', imaging: '影像检查', pathology: '病理检查', molecular_test: '分子检测', procedure: '外科操作', treatment: '综合治疗', medication: '用药记录', toxicity: '不良反应', follow_up: '随访监测', progression: '疾病进展', recurrence: '复发记录', observation: '临床观察' };
export const scenarioNames = { standard: '标准协同流程', partial_failure: '单专科节点故障', persistent_disagreement: '跨科保留分歧', invalid_evidence: '非法证据引用拦截' };
export const stageNames: Record<string, string> = { CREATED: '已创建', QUEUED: '排队等待', INITIALIZING: '病例时序校验', ROUTING: '专科动态调度', AGENTS_RUNNING: '多专科独立初审', CONFLICT_CHECK: '多维分歧检测', DISCUSSION: '有界定向协商', SAFETY_CHECK: '证据与安全门控', REPORTING: '结构化报告归档', COMPLETED: '执行完成', FAILED: '执行异常', CANCELLED: '已人工停止' };
export const sexName = (sex: string) => ({ female: '女性', male: '男性', other: '其他', unknown: '未记录' }[sex] ?? '未记录');
export const formatValue = (value: unknown) => formatFactValue(value);
export function InlineError({ error }: { error: unknown }) { return error ? <div className="inline-error" role="alert">{error instanceof Error ? error.message : '操作失败，请重试。'}</div> : null; }

export function RoutingPanel({ routing }: { routing: Routing }) {
  return <section className="panel routing-panel"><div className="section-heading"><h2>专科动态调度方案</h2><span className="pill soft">已调度 {routing.selected_agents.length} / {roleOrder.length} 个专科</span></div>
    <div className="routing-grid">{roleOrder.map(role => { const selected = routing.selected_agents.includes(role); return <div className={`routing-role ${selected ? 'selected-role' : ''}`} key={role}><span className="routing-mark"><Icon name={selected ? 'check' : 'stop'} size={17} /></span><div><strong>{roleNames[role]}</strong><small>{selected ? '参与本次协同审阅' : '本次自动跳过（节省调用）'}</small>{routing.reasons.filter(reason => reason.agent_id === role).map(reason => <p key={reason.rule_id}>{reason.description}<code>{ruleIdLabel(reason.rule_id)}</code></p>)}</div></div>; })}</div>
    <div className="subtle-note">路由策略：事件驱动专科路由 · 触发截点 {routing.trigger_event_id} · 仅被调度的专科计入有效覆盖率分母。</div>
  </section>;
}

export function EvidenceDialog({ evidence, researchCase, onClose }: { evidence: Evidence; researchCase?: ResearchCase; onClose: () => void }) {
  const event = researchCase?.timeline.find(item => item.event_id === evidence.event_id);
  return <Modal title="证据溯源与原始临床事实" onClose={onClose}><span className="pill soft">{evidence.synthetic ? '合成研究事实' : '公开队列原始事实'}</span><dl className="detail-list">
    <div><dt>证据唯一编号</dt><dd><code>{evidence.evidence_id}</code></dd></div>
    <div><dt>临床事实语义</dt><dd><strong>{factKeyLabel(evidence.fact_key)}</strong> = {formatFactValue(evidence.value)} <small className="muted">（字段名：<code>{evidence.fact_key}</code>）</small></dd></div>
    <div><dt>冻结病例快照</dt><dd>{researchCase ? `${researchCase.case_id} · 版本 v${researchCase.version}` : '取自本次报告冻结快照'}</dd></div>
    <div><dt>所属病程事件</dt><dd>{event ? `${event.occurred_at} · ${event.title}（${event.event_id}）` : evidence.event_id}</dd></div>
    <div><dt>数据来源与版本</dt><dd>{sourceNameLabel(evidence.source_name)}（{evidence.dataset_version}）<br />原始记录号：{evidence.source_record_id ?? '本地合成记录'}</dd></div>
    {evidence.source_record_locator && <div><dt>源文件定位符</dt><dd><code>{evidence.source_record_locator}</code>{evidence.source_field ? ` · 源列：${evidence.source_field}` : ''}</dd></div>}
    {evidence.artifact_sha256 && <div><dt>数据校验指纹 (SHA-256)</dt><dd className="source-hash">{evidence.artifact_sha256}</dd></div>}
  </dl><p className="subtle-note">证据门控已核验该引用与冻结输入快照完全一致，未引用截点后未来信息。</p></Modal>;
}

export function EvidenceButtons({ evidence, onSelect }: { evidence: Evidence[]; onSelect: (value: Evidence) => void }) {
  return <div className="research-evidence-list">{evidence.map(item => <button className="evidence-chip" key={item.evidence_id} onClick={() => onSelect(item)} aria-label={`查看证据 ${item.evidence_id}`} title={`${factKeyLabel(item.fact_key)}: ${formatFactValue(item.value)}`}>{item.event_id} · {factKeyLabel(item.fact_key)}<Icon name="arrow" size={12} /></button>)}</div>;
}

export function OpinionView({ opinion, onEvidence }: { opinion: Opinion; onEvidence: (value: Evidence) => void }) {
  return <div className="research-opinion"><DecisionBadge decision={opinion.decision} /><p>{opinion.summary}</p><EvidenceButtons evidence={opinion.evidence_refs} onSelect={onEvidence} />
    {opinion.missing_information.length > 0 && <p className="opinion-missing">待补临床资料：{opinion.missing_information.map(factKeyLabel).join('、')}</p>}
    <div className="opinion-model"><span>{providerLabelZh(opinion.model_info.provider, opinion.model_info.model)}</span><span>执行 {opinion.model_info.attempts} 次尝试</span></div>
  </div>;
}

export function SafetyPanel({ safety, evidence = [], onEvidence }: { safety: Safety; evidence?: Evidence[]; onEvidence: (value: Evidence) => void }) {
  return <section className={`panel safety-panel safety-${safety.status}`}><div className="section-heading"><h2>证据链与资料完备性门控</h2><DecisionBadge decision={safety.decision} /></div>
    <div className="safety-verdict"><Icon name={safety.status === 'passed' ? 'check' : 'alert'} /><strong>{{ passed: '全部门控规则核验通过，可进入人工资料复核', needs_information: '存在关键临床资料缺口，需补充资料后再审', blocked: '存在未解分歧、非法证据或节点故障，安全门控已阻断放行' }[safety.status]}</strong></div>
    <div className="safety-checks">{safety.checks.map((check, index) => <div className={`safety-check check-${check.status}`} key={`${check.code}-${index}`}><Icon name={check.status === 'passed' ? 'check' : 'alert'} size={17} /><div><strong>{check.message}</strong><code>{safetyCheckLabel(check.code)}</code><EvidenceButtons evidence={evidence.filter(item => check.evidence_ids.includes(item.evidence_id))} onSelect={onEvidence} /></div><span className="check-status">{{ passed: '通过', warning: '待补', blocked: '阻断' }[check.status]}</span></div>)}</div>
    {safety.missing_information.length > 0 && <div className="safety-notes"><h3>待补充临床资料清单</h3><ul>{safety.missing_information.map(value => <li key={value}><strong>{factKeyLabel(value)}</strong> <small className="muted">({value})</small></li>)}</ul></div>}
    {safety.warnings.length > 0 && <div className="safety-notes"><h3>系统边界与核查提示</h3><ul>{safety.warnings.map(value => <li key={value}>{value}</li>)}</ul></div>}
  </section>;
}

export function MetricsPanel({ metrics, mode }: { metrics: Metrics; mode: string }) {
  return <section className="research-metrics" aria-label="运行指标">
    <div><span>专科审阅调用</span><strong>{metrics.agent_calls} <small>次</small></strong></div>
    <div><span>大模型接口请求</span><strong>{metrics.llm_calls} <small>次</small></strong></div>
    <div><span>前置核查算子</span><strong>{metrics.tool_calls} <small>项</small></strong></div>
    <div><span>纠错重试次数</span><strong>{metrics.retry_count} <small>次</small></strong></div>
    <div><span>输入 / 输出字词开销</span><strong>{metrics.prompt_tokens === null ? '—' : metrics.prompt_tokens} / {metrics.completion_tokens === null ? '—' : metrics.completion_tokens}</strong><small>{mode === 'mock' ? '本地规则仿真无外部字词开销' : '模型服务返回的 Token 用量'}</small></div>
    <div><span>工作流执行耗时</span><strong>{(metrics.elapsed_ms / 1000).toFixed(2)}<small> 秒</small></strong></div>
  </section>;
}

export function WorkflowPanel({ run }: { run: Run }) {
  const stages = ['INITIALIZING', 'ROUTING', 'AGENTS_RUNNING', 'CONFLICT_CHECK', 'DISCUSSION', 'SAFETY_CHECK', 'REPORTING'];
  return <section className="panel"><div className="section-heading"><h2>序贯执行阶段 · {stageNames[run.stage] ?? run.stage}</h2><span className="pill">{run.completed_nodes.length} 个工作流节点已完成</span></div><div className="research-stage-list">{stages.map(stage => <span key={stage} className={stage === run.stage ? 'current-stage' : ''}>{stageNames[stage]}</span>)}</div><details><summary>展开节点执行明细</summary><div className="node-groups">{[['已完成节点', run.completed_nodes], ['正在执行', run.running_nodes], ['待执行队列', run.pending_nodes]].map(([label, values]) => <div key={String(label)}><strong>{label}</strong><p>{(values as string[]).length ? (values as string[]).map(nodeNameLabel).join(' · ') : '无'}</p></div>)}</div></details></section>;
}

export const auditSummary = (event: AuditEvent) => {
  const role = event.agent_id ? roleNames[event.agent_id as Role] ?? event.agent_id : '协同调度器';
  const toolName = toolNameLabel(String(event.payload.tool ?? ''));
  const known: Record<string, string> = {
    'workflow.progress': '工作流节点状态已推进',
    'run.created': '协同运行任务已创建并锁定版本',
    'run.started': '开始执行冻结病程快照',
    'workflow.stage_changed': `进入「${stageNames[event.stage] ?? event.stage}」阶段`,
    'routing.completed': '已完成事件驱动专科路由',
    'agent.started': `${role}开始${event.payload.phase === 'discussion' ? '跨科定向协商' : '独立资料初审'}`,
    'agent.completed': `${role}已提交结构化审阅意见与证据引用`,
    'agent.failed': `${role}调用或证据校验未通过（${errorCodeLabel(String(event.payload.error_code ?? ''))}）`,
    'conflict.detected': '已完成跨专科分歧与同日矛盾检测',
    'discussion.started': '启动单轮有界定向协商（共享初审隔离快照）',
    'discussion.completed': '定向协商阶段结束，已归档意见演进记录',
    'safety.completed': '证据一致性与资料完备性门控核验完成',
    'tool.completed': `已完成前置只读核查算子：${toolName}`,
    'report.generated': '结构化多学科评议报告已生成',
    'report.ready': '报告与终态事件已原子落库，支持查阅与下载',
    'run.completed': '协同工作流执行完毕，结果已归档',
    'run.failed': '运行异常终止，已完整保留审计轨迹',
    'run.cancelled': '运行已响应人工停止，未生成不完整报告',
    'run.cancel_requested': '已接收安全边界停止指令',
  };
  return known[event.type] ?? event.type;
};

export function AuditPanel({ events, runId, connection, reconnect }: { events: AuditEvent[]; runId: string; connection: string; reconnect: () => void }) {
  const [filter, setFilter] = useState('all');
  const [follow, setFollow] = useState(true);
  const [selected, setSelected] = useState<AuditEvent>();
  const container = useRef<HTMLDivElement>(null);
  const [search, setSearch] = useState('');
  const visible = useMemo(() => {
    const query = search.trim().toLowerCase();
    return events.filter(event => {
      const matchesRole = filter === 'all' || (filter === 'failed' ? event.type.includes('failed') : event.agent_id === filter);
      if (!matchesRole) return false;
      if (!query) return true;
      const text = [event.seq, event.type, event.stage, event.event_id, stageNames[event.stage], auditSummary(event), event.agent_id ? roleNames[event.agent_id as Role] : '协同调度器'];
      return text.join(' ').toLowerCase().includes(query);
    });
  }, [events, filter, search]);

  useEffect(() => {
    if (follow && container.current) container.current.scrollTop = container.current.scrollHeight;
  }, [visible, follow]);
  const labels: Record<string, string> = { connecting: '正在连接实时事件流', connected: '实时事件流已连接', reconnecting: '连接中断，正在重连…', synced: '审计日志已完整同步', offline: '事件流已离线' };
  return <section className="panel research-audit audit-console">
    <div className="section-heading"><h2>实时执行审计日志</h2>
      <a className="text-link" href={`/api/v2/runs/${encodeURIComponent(runId)}/audit/download`} download aria-label="下载完整运行审计"><Icon name="download" size={15} />导出完整日志</a>
    </div>
    <div className="research-connection" role="status"><span className="status-dot" />{labels[connection] ?? connection}
      {['offline', 'reconnecting'].includes(connection) && <button className="text-link" onClick={reconnect}>立即重连</button>}
    </div>
    <div className="audit-toolbar">
      <input type="search" aria-label="搜索审计事件" placeholder="搜索序号、专科、阶段或事件描述" value={search} onChange={event => setSearch(event.target.value)} />
      <select aria-label="筛选运行审计" value={filter} onChange={event => setFilter(event.target.value)}>
        <option value="all">全部事件</option>{roleOrder.map(role => <option key={role} value={role}>{roleNames[role]}</option>)}<option value="failed">仅异常/阻断事件</option>
      </select>
      <label className="check-label"><input type="checkbox" checked={follow} onChange={event => setFollow(event.target.checked)} />自动滚动至最新</label>
    </div>
    <div className="audit-scroll" ref={container} onScroll={() => {
      const element = container.current;
      if (element && follow && element.scrollHeight - element.scrollTop - element.clientHeight > 50) setFollow(false);
    }}>
      {visible.map(event => <button className={`audit-row ${event.type.includes('failed') ? 'audit-error' : ''}`} key={event.seq} onClick={() => setSelected(event)}>
        <span className="audit-seq">#{event.seq}</span><time dateTime={event.timestamp}>{dateTime(event.timestamp)}</time><span>{auditSummary(event)}</span><Icon name="arrow" size={13} />
      </button>)}
      {!visible.length && <p className="empty-inline">{events.length ? '没有匹配的审计记录。' : '暂无审计记录。'}</p>}
    </div>
    <p className="audit-metrics">当前展示 {visible.length} / {events.length} 条记录{events.length >= 500 && ' · 更早的历史记录请点击右上角导出查看'}</p>
    {selected && <Modal title={`审计事件详情 · 序号 #${selected.seq}`} onClose={() => setSelected(undefined)}>
      <p><strong>{auditSummary(selected)}</strong></p>
      <dl className="detail-list">
        <div><dt>事件编号</dt><dd><code>{selected.event_id}</code></dd></div>
        <div><dt>所属阶段</dt><dd>{stageNames[selected.stage] ?? selected.stage}</dd></div>
        <div><dt>执行主体</dt><dd>{selected.agent_id ? roleNames[selected.agent_id as Role] ?? selected.agent_id : '系统协同调度器'}</dd></div>
        <div><dt>记录时间</dt><dd>{dateTime(selected.timestamp)}</dd></div>
      </dl>
      <details><summary>展开底层结构化载荷</summary><pre className="json-view">{JSON.stringify(selected, null, 2)}</pre></details>
    </Modal>}
  </section>;
}
