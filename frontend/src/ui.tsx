import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { Decision, Opinion, Role, Run, RunEvent, Stage, TimelineEvent } from './schemas';

export const roles: Role[] = ['oncology', 'surgery', 'radiology'];
export const roleNames: Record<Role, string> = { oncology: '肿瘤内科', surgery: '外科', radiology: '影像科' };
export const roleEnglish: Record<Role, string> = { oncology: 'Oncology', surgery: 'Surgery', radiology: 'Radiology' };
export const stageNames: Record<Stage, string> = { LOAD_CASE: '病例校验', INITIAL_REVIEW: '独立分析', DETECT_DISAGREEMENT: '分歧识别', TARGETED_DISCUSSION: '定向讨论', BUILD_REPORT: '报告生成', SAVE_OUTPUT: '结果保存' };
export const stages = Object.keys(stageNames) as Stage[];
export const scenarioNames = { standard: '标准协作', aligned: '初始意见一致', partial_failure: '单角色失败', persistent_disagreement: '讨论后保留分歧' };
export const decisionNames: Record<Decision, string> = { READY_FOR_REVIEW: '可进入资料复核', NEED_MORE_INFORMATION: '需要补充资料', DEFER_DECISION: '暂缓流程判断' };
export const dateTime = (value: string) => new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
export const shortId = (value: string) => value.replace('run_', '').slice(0, 8).toUpperCase();

const iconPaths: Record<string, ReactNode> = {
  pulse: <path d="M2 12h5l3-8 5 16 3-8h4" />,
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
  history: <><path d="M3 11a9 9 0 1 1 2.6 7M3 4v7h7" /><path d="M12 7v5l3 2" /></>,
  route: <><circle cx="5" cy="5" r="2" /><circle cx="19" cy="19" r="2" /><path d="M7 5h8a4 4 0 0 1 0 8H9a4 4 0 0 0 0 6h8" /></>,
  arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
  back: <path d="M19 12H5m5-5-5 5 5 5" />,
  play: <path d="m8 5 11 7-11 7Z" />,
  stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
  check: <path d="m5 12 4 4L19 6" />,
  file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6M8 13h8m-8 4h6" /></>,
  download: <><path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4" /></>,
  alert: <><path d="m12 3 10 18H2Z" /><path d="M12 9v4m0 4h.01" /></>,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  network: <><circle cx="12" cy="5" r="2" /><circle cx="5" cy="19" r="2" /><circle cx="19" cy="19" r="2" /><path d="M12 7v5H5v5m7-5h7v5" /></>,
  moon: <path d="M20.5 14A9 9 0 0 1 10 3.5 9 9 0 1 0 20.5 14Z" />,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10h.01" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  eye: <><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></>,
};
export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{iconPaths[name] ?? iconPaths.info}</svg>;
}

export function Status({ status }: { status: string }) {
  const text: Record<string, string> = { queued: '排队中', running: '运行中', waiting: '等待分析', completed: '已完成', incomplete: '部分失败', failed: '失败', cancelled: '已停止', cancel_requested: '正在停止', skipped: '已跳过' };
  const active = ['running', 'cancel_requested', 'queued'].includes(status);
  return <span className={`pill status-${status}`}>{active ? <span className="spinner" /> : <span className="status-dot" />}{text[status] ?? status}</span>;
}

export function DecisionBadge({ decision }: { decision: Decision }) {
  return <span className={`decision decision-${decision}`}>{decisionNames[decision]}</span>;
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return <div className="error-state" role="alert"><Icon name="alert" size={26} /><h2>暂时无法加载</h2><p>{error instanceof Error ? error.message : '请检查本地服务连接后重试。'}</p>{retry && <button className="button secondary" onClick={retry}>重新加载</button>}<Link to="/" className="text-link">返回病例工作台 <Icon name="arrow" /></Link></div>;
}

export function Loading() { return <div className="loading-state" role="status"><span className="spinner" />正在读取科研工作台…</div>; }

export function FlowProgress({ run }: { run?: Run }) {
  const current = run ? stages.indexOf(run.stage) : -1;
  const done = run?.status === 'completed' || run?.status === 'incomplete';
  return <div className="flow-steps" aria-label="MDT 六阶段工作流">{stages.map((stage, index) => {
    const skipped = !!run && !run.discussion_triggered && stage === 'TARGETED_DISCUSSION' && current > index;
    const finished = done || index < current;
    const active = index === current && !done && run?.status !== 'cancelled' && run?.status !== 'failed';
    return <div key={stage} className={`flow-step ${finished ? 'finished' : ''} ${active ? 'active' : ''} ${skipped ? 'skipped' : ''}`} aria-current={active ? 'step' : undefined}>
      <span className="step-node">{skipped ? '—' : finished ? <Icon name="check" size={15} /> : String(index + 1).padStart(2, '0')}</span>
      <span className="step-label">{stageNames[stage]}<small>{skipped ? '无分歧，已跳过' : active ? '正在进行' : `STEP ${String(index + 1).padStart(2, '0')}`}</small></span>
    </div>;
  })}</div>;
}

export function AgentCard({ role, agent, onEvidence }: { role: Role; agent: Run['agents'][Role]; onEvidence: (id: string) => void }) {
  const opinion = agent.opinion;
  const changed = agent.previous_opinion && opinion && agent.previous_opinion.decision !== opinion.decision;
  return <article className={`agent-card ${agent.status === 'running' ? 'agent-running' : ''} ${agent.status === 'failed' ? 'agent-failed' : ''}`}>
    <div className="agent-card-top"><span className={`agent-avatar role-${role}`}><Icon name={role === 'radiology' ? 'eye' : role === 'surgery' ? 'pulse' : 'network'} size={22} /></span><Status status={agent.status} /></div>
    <h3>{roleNames[role]} <span>Agent</span></h3><div className="agent-english">{roleEnglish[role]}</div>
    {agent.status === 'failed' ? <div className="agent-result"><strong className="danger-text">角色调用失败</strong><p>本次没有有效意见，系统将保留错误并暂缓判断。</p><code>{agent.error}</code></div> : opinion ? <div className="agent-result">
      {changed && <div className="before-label">讨论前：{decisionNames[agent.previous_opinion!.decision]} <Icon name="arrow" size={13} /></div>}
      <DecisionBadge decision={opinion.decision} /><p>{opinion.reasoning_summary}</p>
    </div> : <div className="agent-result agent-placeholder"><p>等待协调器分配任务。<br />各角色将独立读取同一份合成病例。</p></div>}
    <div className="agent-footer"><span>支持事件</span><div>{opinion ? opinion.supporting_event_ids.map(id => <button className="evidence-chip" key={id} onClick={() => onEvidence(id)} aria-label={`查看${roleNames[role]}证据 ${id}`}>{id}<Icon name="arrow" size={12} /></button>) : <span className="muted">—</span>}</div><span className="confidence">{opinion ? `置信等级 ${opinion.confidence.toUpperCase()}` : '尚无意见'}</span></div>
  </article>;
}

export function Timeline({ events, onSelect, selected }: { events: TimelineEvent[]; onSelect: (id: string) => void; selected?: string }) {
  return <ol className="timeline">{events.map(event => <li key={event.event_id} className={selected === event.event_id ? 'selected' : ''}><span className="timeline-dot" /><div className="timeline-date">{event.date.replaceAll('-', '.')}<button className="evidence-chip" onClick={() => onSelect(event.event_id)}>{event.event_id}<Icon name="arrow" size={12} /></button></div><h4>{event.type === 'imaging' ? '影像信息记录' : '初始评估记录'}</h4><p>{event.description}</p></li>)}</ol>;
}

export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); return () => ref.current?.close(); }, []);
  return <dialog ref={ref} className="detail-dialog" onCancel={onClose} aria-label={title} onClick={event => { if (event.target === event.currentTarget) onClose(); }}><div className="dialog-content"><div className="section-heading"><div><div className="eyebrow">SOURCE & TRACE</div><h2>{title}</h2></div><button className="icon-button" aria-label="关闭详情" onClick={onClose}><Icon name="close" /></button></div>{children}</div></dialog>;
}

export function EvidenceModal({ event, onClose }: { event: TimelineEvent; onClose: () => void }) {
  return <Modal title={`原始事件 · ${event.event_id}`} onClose={onClose}><span className="pill">合成病例来源</span><dl className="detail-list"><div><dt>记录日期</dt><dd>{event.date}</dd></div><div><dt>事件类型</dt><dd><code>{event.type}</code></dd></div><div><dt>原始描述</dt><dd>{event.description}</dd></div></dl><p className="subtle-note">此处展示输入病例的原始事件，不是 Agent 生成的医学证据。</p></Modal>;
}

export function eventSummary(event: RunEvent): string {
  const audit = event.payload;
  const role = audit.agent_name ? roleNames[audit.agent_name] : '协调器';
  switch (audit.event_type) {
    case 'state_transition': return `进入${stageNames[audit.stage]}阶段`;
    case 'case_loaded': return '合成病例校验通过，已记录输入指纹';
    case 'agent_started': return `${role}开始${audit.stage === 'TARGETED_DISCUSSION' ? '定向讨论' : '独立分析'}`;
    case 'agent_completed': return `${role}提交意见：${decisionNames[audit.details.decision as Decision] ?? '查看详情'}`;
    case 'agent_failed': return `${role}调用失败，保留错误记录`;
    case 'disagreement_detected': return audit.details.has_disagreement ? '检测到标签分歧，启动一轮定向讨论' : '意见比较结束，无需额外讨论';
    case 'discussion_started': return '开始定向讨论 · 最多 1 轮';
    case 'discussion_finished': return '定向讨论结束，保留全部意见变化';
    case 'report_generated': return '结构化报告已生成，等待保存';
    case 'report_saved': return '报告文件已保存，可查看与下载';
    case 'cancel_requested': return '已接受停止请求，正在安全边界结束';
    case 'run_finished': return audit.details.status === 'cancelled' ? '运行已停止，审计记录已保留' : '运行结束，结果已记录';
    default: return audit.event_type;
  }
}

export function AuditLog({ events, runId }: { events: RunEvent[]; runId: string }) {
  const [filter, setFilter] = useState('all');
  const [auto, setAuto] = useState(true);
  const [selected, setSelected] = useState<RunEvent | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const visible = events.filter(event => filter === 'all' || (filter === 'failed' ? event.payload.event_type === 'agent_failed' : event.payload.agent_name === filter));
  useEffect(() => { if (auto && container.current) container.current.scrollTop = container.current.scrollHeight; }, [events, auto]);
  return <section className="panel audit-panel"><div className="section-heading"><div><div className="eyebrow">AUDIT TRAIL</div><h2>运行审计 <span className="count">{events.length}</span></h2></div><a className="icon-button" href={`/api/v1/runs/${runId}/audit/download`} aria-label="下载审计日志"><Icon name="download" /></a></div>
    <div className="audit-toolbar"><label className="sr-only" htmlFor="audit-filter">筛选审计事件</label><select id="audit-filter" value={filter} onChange={event => setFilter(event.target.value)}><option value="all">全部事件</option>{roles.map(role => <option key={role} value={role}>{roleNames[role]}</option>)}<option value="failed">仅失败事件</option></select><label className="check-label"><input type="checkbox" checked={auto} onChange={event => setAuto(event.target.checked)} />跟随最新</label></div>
    <div className="audit-scroll" ref={container} onScroll={() => { const element = container.current; if (element && element.scrollHeight - element.scrollTop - element.clientHeight > 40 && auto) setAuto(false); }}>
      {!visible.length && <div className="empty-inline">{events.length ? '没有符合筛选条件的事件。' : '等待第一条真实审计事件…'}</div>}
      {visible.map(event => <button key={event.seq} className={`audit-row ${event.payload.event_type === 'agent_failed' ? 'audit-error' : ''}`} onClick={() => setSelected(event)}><span className="audit-seq">{String(event.seq).padStart(2, '0')}</span><time>{new Date(event.timestamp).toLocaleTimeString('zh-CN', { hour12: false })}</time><span>{eventSummary(event)}</span><Icon name="arrow" size={13} /></button>)}
    </div>{!auto && <button className="audit-follow" onClick={() => setAuto(true)}>跟随最新事件 ↓</button>}
    <div className="audit-note"><span className="status-dot" />仅显示已记录的事件 · 按序号去重 · 点击查看原始 JSON</div>
    {selected && <Modal title={`审计事件 · ${selected.payload.event_id}`} onClose={() => setSelected(null)}><pre className="json-view">{JSON.stringify(selected, null, 2)}</pre></Modal>}
  </section>;
}

export function OpinionTable({ opinions, onEvidence }: { opinions: Opinion[]; onEvidence: (id: string) => void }) {
  return <div className="opinion-list">{opinions.map(opinion => <div className="opinion-row" key={opinion.agent_name}><strong>{roleNames[opinion.agent_name]}</strong><div><DecisionBadge decision={opinion.decision} /><p>{opinion.reasoning_summary}</p></div><div>{opinion.supporting_event_ids.map(id => <button key={id} className="evidence-chip" onClick={() => onEvidence(id)}>{id}<Icon name="arrow" size={12} /></button>)}</div></div>)}</div>;
}
