import { DatasetPage } from './research/dataset-page';
import { AgentHubPage } from './research/agent-hub';
import { useState } from 'react';
import { ConsoleShell } from './console/shell';
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';
import { ResearchHome, ResearchCasePage, ResearchRunPage, ResearchReportPage, ResearchHistoryPage, ModelSettingsPage, ResearchRoadmapPage } from './research/pages';
import { isTerminal, useRun, useRunEvents } from './realtime';
import { scenarioSchema, type Scenario } from './schemas';
import { AgentCard, AuditLog, dateTime, DecisionBadge, decisionNames, ErrorState, EvidenceModal, FlowProgress, Icon, Loading, OpinionTable, roleNames, roles, scenarioNames, shortId, Status, Timeline } from './ui';

export function App() {
  return <ConsoleShell>
    <Routes>
      <Route path="/" element={<ResearchHome />} />
      <Route path="/research/datasets" element={<DatasetPage />} />
      <Route path="/research/agents" element={<AgentHubPage />} />
      <Route path="/legacy" element={<HomePage />} />
      <Route path="/research/cases/:caseId" element={<ResearchCasePage />} />
      <Route path="/research/runs" element={<ResearchHistoryPage />} />
      <Route path="/research/runs/:runId" element={<ResearchRunPage />} />
      <Route path="/research/runs/:runId/report" element={<ResearchReportPage />} />
      <Route path="/settings/models" element={<ModelSettingsPage />} />
      <Route path="/cases/:caseId" element={<CasePage />} />
      <Route path="/runs" element={<HistoryPage />} />
      <Route path="/runs/:runId" element={<RunPage />} />
      <Route path="/runs/:runId/report" element={<ReportPage />} />
      <Route path="/roadmap" element={<ResearchRoadmapPage />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  </ConsoleShell>;
}

function HomePage() {
  const cases = useQuery({ queryKey: ['cases'], queryFn: api.cases });
  const runs = useQuery({ queryKey: ['runs'], queryFn: api.runs });
  if (cases.isPending) return <Loading />;
  if (cases.isError) return <ErrorState error={cases.error} retry={() => void cases.refetch()} />;
  return <div className="page-enter"><div className="page-heading"><div><h1>旧版病例库</h1><p>V0.2 · 本地 Mock</p></div><Link className="button secondary" to="/">进入病例工作台</Link></div>
    <section className="panel" aria-label="旧版病例目录"><div className="section-heading"><h2>病例目录</h2><span className="count">{cases.data.length} 份病例</span></div>
      {cases.data.map(item => <article key={item.case_id}>
        <Link className="text-link" to={`/cases/${encodeURIComponent(item.case_id)}`}>{item.case_id}<Icon name="arrow" size={14} /></Link>
        <p>{item.current_question}</p><small className="muted">{item.patient.age} 岁 · {item.timeline.length} 条病程事件 · 合成病例</small>
      </article>)}
    </section>
    <section className="recent-section"><div className="section-heading"><h2>最近运行</h2><Link className="text-link" to="/runs">全部记录 <Icon name="arrow" size={15} /></Link></div>{runs.isError ? <p className="muted">运行记录暂时无法读取。</p> : !runs.data?.length ? <div className="empty-inline bordered">暂无运行记录。</div> : <RunTable runs={runs.data.slice(0, 3)} />}</section>
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
  return <div className="page-enter"><Link to="/legacy" className="back-link"><Icon name="back" size={15} />旧版病例目录</Link><div className="page-heading"><div><h1>影像资料完整性评议</h1><p>{item.case_id} · V0.2</p></div><span className="pill soft"><Icon name="check" size={14} />合成数据已校验</span></div>
    <div className="case-detail-grid"><div><section className="panel case-summary"><div className="section-heading"><h2>病例概况</h2><code>{item.case_id}</code></div><div className="patient-strip"><span className="patient-mark"><Icon name="pulse" size={26} /></span><div><strong>虚构研究对象</strong><span>{({ female: '女性', male: '男性', other: '其他', unknown: '未记录' }[item.patient.sex])} / {item.patient.age} 岁</span></div><span className="pill outline">无真实患者信息</span></div><div className="question-block"><h3>{item.current_question}</h3></div><div className="allowed-decisions"><span>允许的流程标签</span>{item.available_options.map(decision => <DecisionBadge key={decision} decision={decision} />)}</div></section>
      <section className="panel timeline-panel"><div className="section-heading"><div><h2>病程时间线</h2></div><span className="count">{item.timeline.length} 条事件</span></div><Timeline events={item.timeline} onSelect={setSelected} selected={selected} /></section></div>
      <aside><section className="panel start-panel"><span className="start-icon"><Icon name="network" size={27} /></span><h2>配置本次协作</h2><p>此运行使用三个专科的本地规则。</p><label htmlFor="mode">运行模式</label><select id="mode" defaultValue="mock"><option value="mock">Mock · 离线预设脚本</option><option disabled value="llm">LLM · 适配器尚未实现</option></select><label htmlFor="scenario">运行场景</label><select id="scenario" value={scenario} onChange={event => setScenario(scenarioSchema.parse(event.target.value))}>{Object.entries(scenarioNames).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select>
      <div className="scenario-description">{scenario === 'standard' ? '初始意见存在分歧，外科角色在一轮讨论后更新标签。' : scenario === 'aligned' ? '初始标签一致，协调器跳过定向讨论，直接生成报告。' : scenario === 'partial_failure' ? '预设外科调用失败，验证错误记录与暂缓决策。' : '预设外科在讨论后保留意见，验证未解决分歧。'}</div><div className="config-facts"><span>参与角色 <strong>3 个</strong></span><span>讨论上限 <strong>1 轮</strong></span><span>外部请求 <strong>无</strong></span></div>{start.error && <div className="inline-error" role="alert">{start.error.message}</div>}<button className="button primary full" disabled={start.isPending} onClick={() => start.mutate()}>{start.isPending ? <span className="spinner" /> : <Icon name="play" size={16} />}{start.isPending ? '正在创建运行…' : '启动 MDT 协作'}</button></section><div className="small-notice"><Icon name="info" /><p>这些流程标签不代表诊断或治疗方案。Mock 角色不具备真实医学推理能力。</p></div></aside></div>
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
  return <div className="page-enter"><Link to={`/cases/${run.case_id}`} className="back-link"><Icon name="back" size={15} />{run.case_id} · 病例详情</Link><div className="page-heading run-heading"><div><h1>MDT 协作运行 <Status status={run.status} /></h1><p>{scenarioNames[run.scenario]}<span className="text-divider">/</span>离线 Mock<span className="text-divider">/</span>{dateTime(run.created_at)}</p></div><div className="button-group">{active ? <button className="button secondary" disabled={stop.isPending || run.cancel_requested || run.stage === 'SAVE_OUTPUT'} onClick={() => stop.mutate()}><Icon name="stop" size={15} />{run.cancel_requested ? '正在安全停止…' : '停止运行'}</button> : <button className="button secondary" disabled={rerun.isPending} onClick={() => rerun.mutate()}><Icon name="history" size={16} />重新运行</button>}{run.report_ready && <Link to={`/runs/${id}/report`} className="button primary"><Icon name="file" size={16} />查看报告</Link>}</div></div>
    {(stop.error || rerun.error) && <div className="inline-error" role="alert">{(stop.error || rerun.error)?.message}</div>}
    <div className="run-context"><span className="case-id">{run.case_id}</span><p>{caseQuery.data?.current_question ?? '正在加载本次运行的病例问题…'}</p><span className="pill soft">仅合成病例</span></div>
    <section className="panel workflow-panel"><div className="section-heading"><div><h2>序贯协作流程</h2></div><div className={`connection-label ${stream.connection === 'offline' ? 'danger-text' : ''}`} aria-live="polite"><span className="status-dot" />{connectionLabels[stream.connection]}{['offline', 'reconnecting'].includes(stream.connection) && <button className="text-link" onClick={stream.reconnect}>重新连接</button>}</div></div><FlowProgress run={run} /></section>
    {run.status === 'cancelled' && <div className="notice neutral" role="status"><Icon name="stop" /><div><strong>本次运行已停止</strong><p>已保留审计轨迹；没有生成成功报告。可重新运行，创建一条独立记录。</p></div></div>}
    {(run.status === 'incomplete' || run.status === 'failed') && <div className="notice danger" role="alert"><Icon name="alert" /><div><strong>部分角色未完成，本次不得宣称完整 MDT 共识</strong><p>有效意见与错误分别保留。最终流程判断由后端保守规则决定。</p></div></div>}
    <div className="section-heading agents-heading"><h2>专科 Agent <span className="count">3</span></h2><span className="muted">独立研判 · 结构化意见 · 事件引用</span></div><div className="agent-grid">{roles.map(role => <AgentCard key={role} role={role} agent={run.agents[role]} onEvidence={setSelected} />)}</div>
    {run.discussion_triggered && <section className="discussion-panel"><span className="discussion-icon"><Icon name="route" size={23} /></span><div><h3>围绕资料是否充分，开展定向讨论</h3><p>初始标签存在分歧：外科认为可进入复核，其他角色要求补充资料。讨论前后变化保留在上方角色卡与最终报告中。</p><details><summary>查看初始分歧记录</summary><pre className="json-view compact">{JSON.stringify(initialDisagreement ?? { has_disagreement: true, note: '完整初始意见见最终报告' }, null, 2)}</pre></details></div><span className="pill outline">最多 1 轮</span></section>}
    <div className="run-bottom-grid"><AuditLog events={stream.events} runId={id} /><section className="panel timeline-panel"><div className="section-heading"><div><h2>病例原始事件</h2></div><Icon name="file" /></div>{caseQuery.isError ? <p className="inline-error">病例事件暂时无法读取。</p> : caseQuery.data ? <Timeline events={caseQuery.data.timeline} onSelect={setSelected} selected={selected} /> : <Loading />}<div className="subtle-note">点击 Agent 的事件引用，可回溯到这份原始输入。</div></section></div>
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
  return <div className="page-enter report-page"><Link to={`/runs/${runId}`} className="back-link"><Icon name="back" size={15} />返回协作运行</Link><div className="page-heading"><div><h1>MDT 模拟评议报告</h1><p>{report.case_id}<span className="text-divider">/</span>运行 {shortId(runId)}<span className="text-divider">/</span>{report.mode.toUpperCase()}</p></div><a className="button primary" href={`/api/v1/runs/${runId}/report/download`}><Icon name="download" size={16} />下载报告 JSON</a></div>
    {report.unresolved_disagreements.length > 0 && <div className="notice warning" role="alert"><Icon name="alert" /><div><strong>本次模拟 MDT 未形成一致意见</strong><p>报告保留未解决分歧，最终流程标签为暂缓判断。</p></div></div>}
    {report.status !== 'completed' && <div className="notice danger" role="alert"><Icon name="alert" /><div><strong>存在角色失败或无效意见</strong><p>本报告不代表完整 MDT 共识，不能依据剩余意见进行多数表决。</p></div></div>}
    <section className={`report-summary ${report.final_decision === 'DEFER_DECISION' ? 'summary-deferred' : ''}`}><div><h2>{decisionNames[report.final_decision]}</h2><code>{report.final_decision}</code><p>这是资料审阅流程的模拟结果，不是诊断或治疗结论。</p></div><div className="summary-facts"><div><span>工作流状态</span><Status status={report.status} /></div><div><span>讨论轮次</span><strong>{report.discussion_rounds} / 1</strong></div><div><span>有效最终意见</span><strong>{report.final_opinions.length} / 3</strong></div><div><span>未解决分歧</span><strong>{report.unresolved_disagreements.length} 项</strong></div></div></section>
    <section className="panel"><div className="section-heading"><div><h2>初始专业意见</h2></div><span className="muted">讨论前的原始记录</span></div><OpinionTable opinions={report.initial_opinions} onEvidence={setSelected} /></section>
    <section className="panel"><div className="section-heading"><div><h2>定向讨论与意见变化</h2></div><span className="pill soft">{report.discussion_triggered ? '已执行 1 轮' : '未触发讨论'}</span></div>{!report.discussion_records.length ? <p className="empty-inline">本次未进入定向讨论。请结合失败记录或初始标签判断原因。</p> : <div className="discussion-records">{report.discussion_records.map(record => <div key={record.agent_name}><strong>{roleNames[record.agent_name]}</strong><DecisionBadge decision={record.before.decision} /><Icon name="arrow" size={17} />{record.after ? <DecisionBadge decision={record.after.decision} /> : <span className="danger-text">讨论失败，无有效更新</span>}<small>{record.changed ? '标签已更新' : '意见保留'} · {record.audit_event_id}</small></div>)}</div>}{report.unresolved_disagreements.map((conflict, index) => <div key={index} className="inline-error"><strong>保留分歧：</strong>{conflict.discussion_topic}（{conflict.conflicting_agents.join(' / ')}）</div>)}</section>
    <section className="panel"><div className="section-heading"><div><h2>有效最终意见</h2></div></div><OpinionTable opinions={report.final_opinions} onEvidence={setSelected} />{!report.final_opinions.length && <p className="empty-inline">没有有效最终意见。</p>}</section>
    <div className="report-notes-grid"><section className="panel"><div className="section-heading"><h2>待补充信息</h2><Icon name="file" /></div>{report.missing_information.length ? <ul className="plain-list">{report.missing_information.map(item => <li key={item}>{item}</li>)}</ul> : <p className="muted">没有记录额外的资料缺口。</p>}</section><section className="panel"><div className="section-heading"><h2>运行警告</h2><Icon name="alert" /></div><ul className="plain-list">{report.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul></section></div>
    <section className="panel trace-panel"><h2>输入与审计关联</h2><dl className="trace-list"><div><dt>Run ID</dt><dd><code>{report.run_id}</code></dd></div><div><dt>病例 SHA-256</dt><dd><code>{report.case_sha256}</code></dd></div><div><dt>报告保存前审计快照</dt><dd>{report.audit_event_ids.length} 个事件 ID <a className="text-link" href={`/api/v1/runs/${runId}/audit/download`}>下载完整审计 <Icon name="download" size={14} /></a></dd></div></dl><details><summary>查看原始报告 JSON</summary><pre className="json-view">{JSON.stringify(report, null, 2)}</pre></details><div className="report-disclaimer"><Icon name="info" />{report.disclaimer}</div></section>{evidence && <EvidenceModal event={evidence} onClose={() => setSelected(undefined)} />}
  </div>;
}

function RunTable({ runs }: { runs: Awaited<ReturnType<typeof api.runs>> }) {
  return <div className="run-table-wrap"><table className="run-table"><thead><tr><th>运行编号 / 病例</th><th>运行场景</th><th>创建时间</th><th>状态</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{runs.map(run => <tr key={run.run_id}><td><Link to={`/runs/${run.run_id}`}><code>{shortId(run.run_id)}</code></Link><small>{run.case_id} · MOCK</small></td><td>{scenarioNames[run.scenario]}</td><td>{dateTime(run.created_at)}</td><td><Status status={run.status} /></td><td><Link className="table-action" to={`/runs/${run.run_id}`} aria-label={`打开运行 ${shortId(run.run_id)}`}><Icon name="arrow" size={17} /></Link></td></tr>)}</tbody></table></div>;
}

function HistoryPage() {
  const query = useQuery({ queryKey: ['runs'], queryFn: api.runs, refetchInterval: 4000 });
  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} retry={() => void query.refetch()} />;
  return <div className="page-enter"><div className="page-heading"><div><h1>运行记录</h1><p>每次运行拥有独立 ID、意见与审计轨迹。重跑不会覆盖历史。</p></div><Link to="/legacy" className="button primary">新建模拟运行 <Icon name="arrow" size={16} /></Link></div><div className="panel history-panel"><div className="section-heading"><h2>最近 {query.data.length} 次运行</h2><span className="muted">最多展示最近 100 条</span></div>{query.data.length ? <RunTable runs={query.data} /> : <div className="empty-state"><Icon name="history" size={36} /><h3>暂无运行记录</h3><p>选择合成病例，启动运行。</p><Link to="/legacy" className="button primary">选择研究病例</Link></div>}</div></div>;
}

function NotFound() { return <ErrorState error={new Error('这个页面不存在，请返回病例工作台选择一个有效入口。')} />; }
