import { DatasetPage } from './research/dataset-page';
import { AgentHubPage } from './research/agent-hub';
import { useEffect, useState } from 'react';
import { Link, NavLink, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';
import { ResearchHome, ResearchCasePage, ResearchRunPage, ResearchReportPage, ResearchHistoryPage, ModelSettingsPage, ResearchRoadmapPage } from './research/pages';
import { isTerminal, useRun, useRunEvents } from './realtime';
import { scenarioSchema, type Scenario } from './schemas';
import { AgentCard, AuditLog, dateTime, DecisionBadge, decisionNames, ErrorState, EvidenceModal, FlowProgress, Icon, Loading, OpinionTable, roleNames, roles, scenarioNames, shortId, Status, Timeline } from './ui';

export function App() {
  const location = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [location.pathname]);
  const [dark, setDark] = useState(() => localStorage.getItem('mdt-theme') === 'dark');
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15000 });
  useEffect(() => { document.documentElement.dataset.theme = dark ? 'dark' : 'light'; localStorage.setItem('mdt-theme', dark ? 'dark' : 'light'); }, [dark]);
  const section = location.pathname === '/research/datasets' ? '外部数据' : location.pathname === '/research/agents' ? 'Agent 群' : location.pathname.includes('/report') ? '结构化报告' : (location.pathname.startsWith('/runs/') || location.pathname.startsWith('/research/runs/')) ? '协作运行' : (location.pathname === '/runs' || location.pathname === '/research/runs') ? '运行记录' : location.pathname === '/settings/models' ? '模型设置' : location.pathname === '/roadmap' ? '研究路线' : '病例工作台';
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">跳转到主要内容</a>
    <aside className="sidebar"><Link to="/" className="brand" aria-label="MDT Lab 首页"><span className="brand-symbol"><Icon name="pulse" size={27} /></span><span>MDT<span className="brand-lab"> Lab</span><small>MULTI-AGENT RESEARCH</small></span></Link>
      <div className="nav-label">研究工作空间</div><nav aria-label="主导航"><NavLink to="/" end aria-label="病例工作台" title="病例工作台"><Icon name="grid" /><span>病例工作台</span><span className="nav-number">01</span></NavLink><NavLink to="/research/datasets" aria-label="外部数据" title="外部数据"><Icon name="file" /><span>外部数据</span></NavLink><NavLink to="/research/agents" aria-label="Agent 群" title="Agent 群"><Icon name="network" /><span>Agent 群</span></NavLink><NavLink to="/research/runs" aria-label="运行记录" title="运行记录"><Icon name="history" /><span>运行记录</span></NavLink><NavLink to="/settings/models" aria-label="模型设置" title="模型设置"><Icon name="network" /><span>模型设置</span></NavLink><NavLink to="/roadmap" aria-label="研究路线" title="研究路线"><Icon name="route" /><span>研究路线</span></NavLink></nav>
      <div className="sidebar-bottom"><div className="workspace-note"><span className="mini-mark"><Icon name="network" size={19} /></span><div>MDT 序贯协作原型<small>事件驱动科研 · V0.3</small></div></div><div className="sidebar-footnote">让每一次协作<br />都有据可循。</div></div>
    </aside>
    <div className="workspace"><header className="topbar"><div className="breadcrumb">研究空间 <span>/</span><strong>{section}</strong></div><div className="topbar-actions"><span className="synthetic-badge"><Icon name="info" size={14} />科研模拟</span><span className={`server-state ${health.isError ? 'server-offline' : ''}`}><span className="status-dot" />{health.isSuccess ? '本地服务在线' : health.isError ? '服务未连接' : '正在连接'}</span><button className="icon-button theme-button" aria-label={dark ? '切换浅色模式' : '切换深色模式'} onClick={() => setDark(value => !value)}><Icon name={dark ? 'sun' : 'moon'} /></button></div></header>
      <main id="main-content" className="main-content"><Routes><Route path="/" element={<ResearchHome />} /><Route path="/research/datasets" element={<DatasetPage />} /><Route path="/research/agents" element={<AgentHubPage />} /><Route path="/legacy" element={<HomePage />} /><Route path="/research/cases/:caseId" element={<ResearchCasePage />} /><Route path="/research/runs" element={<ResearchHistoryPage />} /><Route path="/research/runs/:runId" element={<ResearchRunPage />} /><Route path="/research/runs/:runId/report" element={<ResearchReportPage />} /><Route path="/settings/models" element={<ModelSettingsPage />} /><Route path="/cases/:caseId" element={<CasePage />} /><Route path="/runs" element={<HistoryPage />} /><Route path="/runs/:runId" element={<RunPage />} /><Route path="/runs/:runId/report" element={<ReportPage />} /><Route path="/roadmap" element={<ResearchRoadmapPage />} /><Route path="*" element={<NotFound />} /></Routes></main>
      <footer className="disclaimer"><Icon name="info" size={14} /><span>使用合成或合法公开研究资料开展算法实验；来源逐项标注，不构成医疗建议。</span><span className="footer-version">MDT LAB / V0.3</span></footer>
    </div>
  </div>;
}

function HomePage() {
  const cases = useQuery({ queryKey: ['cases'], queryFn: api.cases });
  const runs = useQuery({ queryKey: ['runs'], queryFn: api.runs });
  if (cases.isPending) return <Loading />;
  if (cases.isError) return <ErrorState error={cases.error} retry={() => void cases.refetch()} />;
  return <div className="page-enter"><div className="page-heading"><div><div className="eyebrow">RESEARCH WORKBENCH</div><h1>病例工作台<span className="title-period">.</span></h1><p>从一份合成病例开始，观察多学科 Agent 如何协作。</p></div><span className="pill outline">离线 Mock 已就绪 <span className="status-dot" /></span></div>
    <section className="intro-banner"><div><span className="banner-kicker">SEQUENTIAL COLLABORATION</span><h2>让协作过程，清晰可见。</h2><p>独立分析、识别分歧、有界讨论。<br />每一步意见与证据，都保留在同一条审计轨迹中。</p><Link className="banner-link" to="/roadmap">了解研究技术路线 <Icon name="arrow" /></Link></div><div className="collaboration-graphic" aria-hidden="true"><div className="graphic-orbit orbit-one" /><div className="graphic-orbit orbit-two" /><div className="graphic-core"><Icon name="network" size={34} /><span>MDT</span></div><span className="graphic-node node-one">独立分析</span><span className="graphic-node node-two">证据回溯</span><span className="graphic-node node-three">定向讨论</span><span className="graphic-caption">3 AGENTS · 1 BOUNDED ROUND</span></div></section>
    <div className="metric-grid"><div className="metric"><span>可用合成病例</span><strong>{String(cases.data.length).padStart(2, '0')}<small>个</small></strong><p>完全虚构，来源可追溯</p><Icon name="file" size={22} /></div><div className="metric"><span>独立专科角色</span><strong>03<small>个</small></strong><p>肿瘤内科 · 外科 · 影像科</p><Icon name="network" size={22} /></div><div className="metric"><span>定向讨论上限</span><strong>01<small>轮</small></strong><p>有明确停止条件的协作流程</p><Icon name="route" size={22} /></div></div>
    <div className="section-heading cases-heading"><div><h2>选择一个研究病例 <span className="count">{cases.data.length}</span></h2><p>已提供标准与异常场景，用于验证协作流程。</p></div><span className="eyebrow">SYNTHETIC CASES</span></div>
    <div className="home-grid"><div>{cases.data.map(item => <article className="panel case-card" key={item.case_id}><div className="case-card-header"><span className="case-id">{item.case_id}</span><span className="pill soft">合成病例</span></div><div className="case-visual"><Icon name="pulse" size={29} /></div><h3>影像资料完整性评议</h3><p>{item.current_question}</p><div className="case-metadata"><span>{({ female: '女性', male: '男性', other: '其他', unknown: '未记录' }[item.patient.sex])} · {item.patient.age} 岁</span><span>{item.timeline.length} 条病程事件</span><span>3 个协作角色</span></div><div className="case-card-bottom"><span><span className="status-dot" />可开始科研模拟</span><Link className="button primary" to={`/cases/${item.case_id}`}>查看病例 <Icon name="arrow" size={16} /></Link></div></article>)}</div><aside className="panel guide-panel"><div className="eyebrow">A TRACEABLE WORKFLOW</div><h2>一轮运行，六个步骤</h2><ol className="mini-steps">{['读取并校验合成病例', '三个 Agent 独立提交意见', '比较标签，识别关键分歧', '最多一轮定向讨论', '生成结构化报告', '保存结果与全过程审计'].map((text, index) => <li key={text}><span>{String(index + 1).padStart(2, '0')}</span>{text}</li>)}</ol><div className="subtle-note"><Icon name="info" size={16} />所有意见均为预设脚本，仅验证工程流程。</div></aside></div>
    <section className="recent-section"><div className="section-heading"><h2>最近运行</h2><Link className="text-link" to="/runs">全部记录 <Icon name="arrow" size={15} /></Link></div>{runs.isError ? <p className="muted">运行记录暂时无法读取。</p> : !runs.data?.length ? <div className="empty-inline bordered">尚无运行记录。选择病例，开始第一轮模拟。</div> : <RunTable runs={runs.data.slice(0, 3)} />}</section>
  </div>;
}

function CasePage() {
  const { caseId = '' } = useParams();
  const navigate = useNavigate();
  const query = useQuery({ queryKey: ['case', caseId], queryFn: () => api.case(caseId) });
  const [scenario, setScenario] = useState<Scenario>('standard');
  const [selected, setSelected] = useState<string>();
  const start = useMutation({ mutationFn: () => api.start(caseId, scenario), onSuccess: run => navigate(`/runs/${run.run_id}`) });
  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} retry={() => void query.refetch()} />;
  const item = query.data;
  const evidence = item.timeline.find(event => event.event_id === selected);
  return <div className="page-enter"><Link to="/" className="back-link"><Icon name="back" size={15} />返回病例工作台</Link><div className="page-heading"><div><div className="eyebrow">CASE DETAIL / {item.case_id}</div><h1>影像资料完整性评议</h1><p>查看原始病例，再启动一次可追溯的多学科模拟。</p></div><span className="pill soft"><Icon name="check" size={14} />合成数据已校验</span></div>
    <div className="case-detail-grid"><div><section className="panel case-summary"><div className="section-heading"><h2>病例概况</h2><code>{item.case_id}</code></div><div className="patient-strip"><span className="patient-mark"><Icon name="pulse" size={26} /></span><div><strong>虚构研究对象</strong><span>{({ female: '女性', male: '男性', other: '其他', unknown: '未记录' }[item.patient.sex])} / {item.patient.age} 岁</span></div><span className="pill outline">无真实患者信息</span></div><div className="question-block"><div className="eyebrow">CURRENT RESEARCH QUESTION</div><h3>{item.current_question}</h3></div><div className="allowed-decisions"><span>允许的流程标签</span>{item.available_options.map(decision => <DecisionBadge key={decision} decision={decision} />)}</div></section>
      <section className="panel timeline-panel"><div className="section-heading"><div><div className="eyebrow">LONGITUDINAL EVENTS</div><h2>病程时间线</h2></div><span className="count">{item.timeline.length} 条事件</span></div><Timeline events={item.timeline} onSelect={setSelected} selected={selected} /></section></div>
      <aside><section className="panel start-panel"><span className="start-icon"><Icon name="network" size={27} /></span><h2>配置本次协作</h2><p>在固定病例上验证正常与异常分支。</p><label htmlFor="mode">运行模式</label><select id="mode" defaultValue="mock"><option value="mock">Mock · 离线预设脚本</option><option disabled value="llm">LLM · 适配器尚未实现</option></select><label htmlFor="scenario">演示场景</label><select id="scenario" value={scenario} onChange={event => setScenario(scenarioSchema.parse(event.target.value))}>{Object.entries(scenarioNames).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select>
      <div className="scenario-description">{scenario === 'standard' ? '初始意见存在分歧，外科角色在一轮讨论后更新标签。' : scenario === 'aligned' ? '初始标签一致，协调器跳过定向讨论，直接生成报告。' : scenario === 'partial_failure' ? '预设外科调用失败，验证错误记录与暂缓决策。' : '预设外科在讨论后保留意见，验证未解决分歧。'}</div><div className="config-facts"><span>参与角色 <strong>3 个</strong></span><span>讨论上限 <strong>1 轮</strong></span><span>外部请求 <strong>无</strong></span></div>{start.error && <div className="inline-error" role="alert">{start.error.message}</div>}<button className="button primary full" disabled={start.isPending} onClick={() => start.mutate()}>{start.isPending ? <span className="spinner" /> : <Icon name="play" size={16} />}{start.isPending ? '正在创建运行…' : '启动 MDT 协作'}</button><p className="start-footnote">真实执行 Python 工作流，页面不预制运行结果。</p></section><div className="small-notice"><Icon name="info" /><p>这些流程标签不代表诊断或治疗方案。Mock 角色不具备真实医学推理能力。</p></div></aside></div>
    {evidence && <EvidenceModal event={evidence} onClose={() => setSelected(undefined)} />}
  </div>;
}

function RunPage() { const { runId = '' } = useParams(); return <RunDashboard key={runId} id={runId} />; }

function RunDashboard({ id }: { id: string }) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const query = useRun(id);
  const stream = useRunEvents(id);
  const [selected, setSelected] = useState<string>();
  const caseQuery = useQuery({ queryKey: ['case', query.data?.case_id], queryFn: () => api.case(query.data!.case_id), enabled: !!query.data });
  const stop = useMutation({ mutationFn: () => api.cancel(id), onSuccess: data => client.setQueryData(['run', id], data), onError: () => void query.refetch() });
  const rerun = useMutation({ mutationFn: () => api.rerun(id), onSuccess: data => navigate(`/runs/${data.run_id}`) });
  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} retry={() => void query.refetch()} />;
  const run = query.data;
  const active = !isTerminal(run.status);
  const evidence = caseQuery.data?.timeline.find(event => event.event_id === selected);
  const connectionLabels = { connecting: '正在连接事件流', connected: '实时连接正常', reconnecting: '正在恢复连接…', synced: '审计已同步', offline: '实时连接不可用' };
  const initialDisagreement = stream.events.find(event => event.type === 'disagreement.detected')?.payload.details;
  return <div className="page-enter"><Link to={`/cases/${run.case_id}`} className="back-link"><Icon name="back" size={15} />{run.case_id} · 病例详情</Link><div className="page-heading run-heading"><div><div className="eyebrow">LIVE COLLABORATION / {shortId(id)}</div><h1>MDT 协作运行 <Status status={run.status} /></h1><p>{scenarioNames[run.scenario]}<span className="text-divider">/</span>离线 Mock<span className="text-divider">/</span>{dateTime(run.created_at)}</p></div><div className="button-group">{active ? <button className="button secondary" disabled={stop.isPending || run.cancel_requested || run.stage === 'SAVE_OUTPUT'} onClick={() => stop.mutate()}><Icon name="stop" size={15} />{run.cancel_requested ? '正在安全停止…' : '停止运行'}</button> : <button className="button secondary" disabled={rerun.isPending} onClick={() => rerun.mutate()}><Icon name="history" size={16} />重新运行</button>}{run.report_ready && <Link to={`/runs/${id}/report`} className="button primary"><Icon name="file" size={16} />查看报告</Link>}</div></div>
    {(stop.error || rerun.error) && <div className="inline-error" role="alert">{(stop.error || rerun.error)?.message}</div>}
    <div className="run-context"><span className="case-id">{run.case_id}</span><p>{caseQuery.data?.current_question ?? '正在加载本次运行的病例问题…'}</p><span className="pill soft">仅合成病例</span></div>
    <section className="panel workflow-panel"><div className="section-heading"><div><div className="eyebrow">ORCHESTRATION</div><h2>序贯协作流程</h2></div><div className={`connection-label ${stream.connection === 'offline' ? 'danger-text' : ''}`} aria-live="polite"><span className="status-dot" />{connectionLabels[stream.connection]}{['offline', 'reconnecting'].includes(stream.connection) && <button className="text-link" onClick={stream.reconnect}>重新连接</button>}</div></div><FlowProgress run={run} /></section>
    {run.status === 'cancelled' && <div className="notice neutral" role="status"><Icon name="stop" /><div><strong>本次运行已停止</strong><p>已保留审计轨迹；没有生成成功报告。可重新运行，创建一条独立记录。</p></div></div>}
    {(run.status === 'incomplete' || run.status === 'failed') && <div className="notice danger" role="alert"><Icon name="alert" /><div><strong>部分角色未完成，本次不得宣称完整 MDT 共识</strong><p>有效意见与错误分别保留。最终流程判断由后端保守规则决定。</p></div></div>}
    <div className="section-heading agents-heading"><h2>专科 Agent <span className="count">3</span></h2><span className="muted">独立研判 · 结构化意见 · 事件引用</span></div><div className="agent-grid">{roles.map(role => <AgentCard key={role} role={role} agent={run.agents[role]} onEvidence={setSelected} />)}</div>
    {run.discussion_triggered && <section className="discussion-panel"><span className="discussion-icon"><Icon name="route" size={23} /></span><div><div className="eyebrow">TARGETED DISCUSSION / ROUND 01</div><h3>围绕资料是否充分，开展定向讨论</h3><p>初始标签存在分歧：外科认为可进入复核，其他角色要求补充资料。讨论前后变化保留在上方角色卡与最终报告中。</p><details><summary>查看初始分歧记录</summary><pre className="json-view compact">{JSON.stringify(initialDisagreement ?? { has_disagreement: true, note: '完整初始意见见最终报告' }, null, 2)}</pre></details></div><span className="pill outline">最多 1 轮</span></section>}
    <div className="run-bottom-grid"><AuditLog events={stream.events} runId={id} /><section className="panel timeline-panel"><div className="section-heading"><div><div className="eyebrow">SOURCE EVENTS</div><h2>病例原始事件</h2></div><Icon name="file" /></div>{caseQuery.isError ? <p className="inline-error">病例事件暂时无法读取。</p> : caseQuery.data ? <Timeline events={caseQuery.data.timeline} onSelect={setSelected} selected={selected} /> : <Loading />}<div className="subtle-note">点击 Agent 的事件引用，可回溯到这份原始输入。</div></section></div>
    {run.report_ready && <div className="report-ready"><span><Icon name="check" size={24} /></span><div><strong>结构化报告已就绪</strong><p>查看最终标签、资料缺口与完整的讨论前后记录。</p></div><Link className="button primary" to={`/runs/${id}/report`}>打开报告 <Icon name="arrow" size={15} /></Link></div>}
    {evidence && <EvidenceModal event={evidence} onClose={() => setSelected(undefined)} />}
  </div>;
}

function ReportPage() {
  const { runId = '' } = useParams();
  const query = useQuery({ queryKey: ['report', runId], queryFn: () => api.report(runId) });
  const [selected, setSelected] = useState<string>();
  const caseQuery = useQuery({ queryKey: ['case', query.data?.case_id], queryFn: () => api.case(query.data!.case_id), enabled: !!query.data });
  if (query.isPending) return <Loading />;
  if (query.isError) return <><Link to={`/runs/${runId}`} className="back-link"><Icon name="back" />返回运行面板</Link><ErrorState error={query.error} retry={() => void query.refetch()} /></>;
  const report = query.data;
  const evidence = caseQuery.data?.timeline.find(event => event.event_id === selected);
  return <div className="page-enter report-page"><Link to={`/runs/${runId}`} className="back-link"><Icon name="back" size={15} />返回协作运行</Link><div className="page-heading"><div><div className="eyebrow">STRUCTURED RESEARCH REPORT</div><h1>MDT 模拟评议报告</h1><p>{report.case_id}<span className="text-divider">/</span>运行 {shortId(runId)}<span className="text-divider">/</span>{report.mode.toUpperCase()}</p></div><a className="button primary" href={`/api/v1/runs/${runId}/report/download`}><Icon name="download" size={16} />下载报告 JSON</a></div>
    {report.unresolved_disagreements.length > 0 && <div className="notice warning" role="alert"><Icon name="alert" /><div><strong>本次模拟 MDT 未形成一致意见</strong><p>报告保留未解决分歧，最终流程标签为暂缓判断。</p></div></div>}
    {report.status !== 'completed' && <div className="notice danger" role="alert"><Icon name="alert" /><div><strong>存在角色失败或无效意见</strong><p>本报告不代表完整 MDT 共识，不能依据剩余意见进行多数表决。</p></div></div>}
    <section className={`report-summary ${report.final_decision === 'DEFER_DECISION' ? 'summary-deferred' : ''}`}><div><div className="eyebrow">FINAL WORKFLOW LABEL</div><h2>{decisionNames[report.final_decision]}</h2><code>{report.final_decision}</code><p>这是资料审阅流程的模拟结果，不是诊断或治疗结论。</p></div><div className="summary-facts"><div><span>工作流状态</span><Status status={report.status} /></div><div><span>讨论轮次</span><strong>{report.discussion_rounds} / 1</strong></div><div><span>有效最终意见</span><strong>{report.final_opinions.length} / 3</strong></div><div><span>未解决分歧</span><strong>{report.unresolved_disagreements.length} 项</strong></div></div></section>
    <section className="panel"><div className="section-heading"><div><div className="eyebrow">INDEPENDENT REVIEW</div><h2>初始专业意见</h2></div><span className="muted">讨论前的原始记录</span></div><OpinionTable opinions={report.initial_opinions} onEvidence={setSelected} /></section>
    <section className="panel"><div className="section-heading"><div><div className="eyebrow">BOUNDED DISCUSSION</div><h2>定向讨论与意见变化</h2></div><span className="pill soft">{report.discussion_triggered ? '已执行 1 轮' : '未触发讨论'}</span></div>{!report.discussion_records.length ? <p className="empty-inline">本次未进入定向讨论。请结合失败记录或初始标签判断原因。</p> : <div className="discussion-records">{report.discussion_records.map(record => <div key={record.agent_name}><strong>{roleNames[record.agent_name]}</strong><DecisionBadge decision={record.before.decision} /><Icon name="arrow" size={17} />{record.after ? <DecisionBadge decision={record.after.decision} /> : <span className="danger-text">讨论失败，无有效更新</span>}<small>{record.changed ? '标签已更新' : '意见保留'} · {record.audit_event_id}</small></div>)}</div>}{report.unresolved_disagreements.map((conflict, index) => <div key={index} className="inline-error"><strong>保留分歧：</strong>{conflict.discussion_topic}（{conflict.conflicting_agents.join(' / ')}）</div>)}</section>
    <section className="panel"><div className="section-heading"><div><div className="eyebrow">FINAL OPINIONS</div><h2>有效最终意见</h2></div></div><OpinionTable opinions={report.final_opinions} onEvidence={setSelected} />{!report.final_opinions.length && <p className="empty-inline">没有有效最终意见。</p>}</section>
    <div className="report-notes-grid"><section className="panel"><div className="section-heading"><h2>待补充信息</h2><Icon name="file" /></div>{report.missing_information.length ? <ul className="plain-list">{report.missing_information.map(item => <li key={item}>{item}</li>)}</ul> : <p className="muted">没有记录额外的资料缺口。</p>}</section><section className="panel"><div className="section-heading"><h2>运行警告</h2><Icon name="alert" /></div><ul className="plain-list">{report.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul></section></div>
    <section className="panel trace-panel"><h2>输入与审计关联</h2><dl className="trace-list"><div><dt>Run ID</dt><dd><code>{report.run_id}</code></dd></div><div><dt>病例 SHA-256</dt><dd><code>{report.case_sha256}</code></dd></div><div><dt>报告保存前审计快照</dt><dd>{report.audit_event_ids.length} 个事件 ID <a className="text-link" href={`/api/v1/runs/${runId}/audit/download`}>下载完整审计 <Icon name="download" size={14} /></a></dd></div></dl><details><summary>查看原始报告 JSON</summary><pre className="json-view">{JSON.stringify(report, null, 2)}</pre></details><div className="report-disclaimer"><Icon name="info" />{report.disclaimer}</div></section>{evidence && <EvidenceModal event={evidence} onClose={() => setSelected(undefined)} />}
  </div>;
}

function RunTable({ runs }: { runs: Awaited<ReturnType<typeof api.runs>> }) {
  return <div className="run-table-wrap"><table className="run-table"><thead><tr><th>运行编号 / 病例</th><th>演示场景</th><th>创建时间</th><th>状态</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{runs.map(run => <tr key={run.run_id}><td><Link to={`/runs/${run.run_id}`}><code>{shortId(run.run_id)}</code></Link><small>{run.case_id} · MOCK</small></td><td>{scenarioNames[run.scenario]}</td><td>{dateTime(run.created_at)}</td><td><Status status={run.status} /></td><td><Link className="table-action" to={`/runs/${run.run_id}`} aria-label={`打开运行 ${shortId(run.run_id)}`}><Icon name="arrow" size={17} /></Link></td></tr>)}</tbody></table></div>;
}

function HistoryPage() {
  const query = useQuery({ queryKey: ['runs'], queryFn: api.runs, refetchInterval: 4000 });
  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} retry={() => void query.refetch()} />;
  return <div className="page-enter"><div className="page-heading"><div><div className="eyebrow">RUN HISTORY</div><h1>运行记录<span className="title-period">.</span></h1><p>每次运行拥有独立 ID、意见与审计轨迹。重跑不会覆盖历史。</p></div><Link to="/" className="button primary">新建模拟运行 <Icon name="arrow" size={16} /></Link></div><div className="panel history-panel"><div className="section-heading"><h2>最近 {query.data.length} 次运行</h2><span className="muted">最多展示最近 100 条</span></div>{query.data.length ? <RunTable runs={query.data} /> : <div className="empty-state"><Icon name="history" size={36} /><h3>第一条协作记录，从这里开始</h3><p>选择合成病例，启动一次模拟运行。</p><Link to="/" className="button primary">选择研究病例</Link></div>}</div></div>;
}

export function LegacyRoadmapPage() {
  const roadmap = [
    ['V0.1', '最小协作闭环', '病例校验、三个独立角色、标签分歧、单轮讨论、报告与审计。', '已完成'],
    ['V0.2', '可追溯科研工作台', 'FastAPI、实时事件、React 仪表盘、停止与重跑、异常场景、报告下载。', '当前版本'],
    ['V0.3', '服务端真实模型适配', '超时、结构化校验、最多一次重试；使用固定模型和服务端凭证。', '下一阶段 · 约 1 周'],
    ['V0.4', '只读证据与合成场景', '工具参数、来源和版本可审查；扩展受控场景，拒绝无来源引用。', '计划 · 1–2 周'],
    ['V0.5', '纵向病程与动态协作', '保留历史事件，按病程阶段选择角色，必要时迁移 LangGraph。', '计划 · 1–2 周'],
    ['V0.6', '对照实验与论文交付', '单智能体与多智能体对照、消融、成本和引用指标、可复现演示。', '计划 · 约 2 周'],
  ];
  return <div className="page-enter"><div className="page-heading"><div><div className="eyebrow">RESEARCH ROADMAP</div><h1>技术方案与研究路线<span className="title-period">.</span></h1><p>先让工程闭环可观察、可追溯，再逐步增加模型与证据能力。</p></div><span className="pill outline">本科毕业设计科研原型</span></div><section className="panel architecture-panel"><div className="section-heading"><h2>一个核心工作流，两种交互入口</h2><Icon name="network" /></div><div className="architecture-flow"><div><span>INTERFACE</span><strong>React 工作台</strong><small>病例 / 实时状态 / 报告</small></div><Icon name="arrow" /><div><span>ADAPTER</span><strong>FastAPI 网关</strong><small>REST + WebSocket + seq</small></div><Icon name="arrow" /><div><span>CORE</span><strong>MDT 协调器</strong><small>三个角色 / 有界讨论</small></div><Icon name="arrow" /><div><span>TRACE</span><strong>JSON + JSONL</strong><small>结果 / 事件 / 输入指纹</small></div></div><p className="subtle-note">原命令行继续复用同一套协调器；前端不执行或替代后端决策规则。</p></section><div className="roadmap-list">{roadmap.map(([version, title, description, status], index) => <article className={`panel roadmap-item ${index === 1 ? 'roadmap-current' : ''}`} key={version}><span className="roadmap-version">{version}</span><div><h2>{title}</h2><p>{description}</p></div><span className={`pill ${index < 2 ? 'soft' : 'outline'}`}>{status}</span></article>)}</div><div className="notice neutral"><Icon name="info" /><div><strong>研究边界</strong><p>排期为单人开发参考。当前输出只验证合成场景的技术流程，不证明临床有效性。公开部署前需另行增加认证与 TLS。</p></div></div></div>;
}

function NotFound() { return <ErrorState error={new Error('这个页面不存在，请返回病例工作台选择一个有效入口。')} />; }
