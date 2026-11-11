import { CaseSources, caseKindName, DataPath } from './data-components';
import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { DecisionBadge, ErrorState, Icon, Loading, Status, dateTime, shortId } from '../ui';
import { researchApi, type ModelConfiguration } from './api';
import { AgentCards, AuditPanel, EvidenceDialog, InlineError, MetricsPanel, OpinionView, RoutingPanel, SafetyPanel, Timeline, WorkflowPanel, eventNames, roleNames, scenarioNames, sexName } from './components';
import { factsSchema, type Evidence, type EventType, type ResearchCase, type Run, type RunRequest } from './schemas';
import { terminal, useResearchRun, useResearchStream } from './realtime';
import './styles.css';

export function ResearchHome() {
  const cases = useQuery({ queryKey: ['research-cases'], queryFn: researchApi.cases });
  const runs = useQuery({ queryKey: ['research-runs'], queryFn: researchApi.runs });
  if (cases.isPending) return <Loading />;
  if (cases.isError) return <ErrorState error={cases.error} retry={() => void cases.refetch()} />;
  return <div className="page-enter research-page"><div className="page-heading"><div><div className="eyebrow">LONGITUDINAL MDT / RESEARCH WORKBENCH</div><h1>病程在变化，协作也随之变化<span className="title-period">.</span></h1><p>选择一个病程事件，观察相关专科如何在证据约束下协作。</p></div><span className="pill outline">V0.3 · 事件驱动原型</span></div>
    <section className="intro-banner research-intro"><div><span className="banner-kicker">EVENT → COLLABORATION → EVIDENCE</span><h2>每一次新信息，都是新的评议起点。</h2><p>保留病程版本，按事件调度专科，围绕实际分歧开展一轮讨论。<br />最终报告同时回答：依据是什么，还缺什么。</p><Link className="banner-link" to="/roadmap">查看当前实现与后续计划 <Icon name="arrow" /></Link></div><div className="research-loop" aria-hidden="true"><span>病程事件</span><Icon name="arrow" /><span>相关专科</span><Icon name="arrow" /><span>证据门控</span><small>VERSIONED · BOUNDED · TRACEABLE</small></div></section>
    <div className="metric-grid"><div className="metric"><span>可用研究病例</span><strong>{cases.data.length}<small>个</small></strong><p>来源与合成扩展分别标注</p></div><div className="metric"><span>可调度专科</span><strong>4<small>个</small></strong><p>事件相关角色参与</p></div><div className="metric"><span>定向讨论上限</span><strong>1<small>轮</small></strong><p>保留无法解决的分歧</p></div></div>
    <div className="section-heading"><h2>纵向研究病例</h2><Link className="text-link" to="/research/datasets">导入外部资料 <Icon name="arrow" size={14} /></Link></div><div className="research-case-grid">{cases.data.map(item => <article className="panel research-case-card" key={item.case_id}><div className="section-heading"><code className="case-id">{item.case_id}</code><span className="pill soft">v{item.version}</span></div><div className="case-visual"><Icon name="pulse" size={26} /></div><h2>{item.title}</h2><p>{item.current_question}</p><div className="case-metadata"><span>{sexName(item.patient.sex)} · {item.patient.age} 岁</span><span>{item.timeline.length} 条病程事件</span></div><div className="case-card-bottom"><span>{caseKindName[item.case_kind]}</span><Link className="button primary" to={`/research/cases/${item.case_id}`}>进入工作台 <Icon name="arrow" size={15} /></Link></div></article>)}</div>
    <section className="recent-section"><div className="section-heading"><h2>最近运行</h2><Link to="/research/runs" className="text-link">全部记录 <Icon name="arrow" size={14} /></Link></div>{runs.isError ? <InlineError error={runs.error} /> : runs.data?.length ? <ResearchRunTable runs={runs.data.slice(0, 5)} /> : <div className="panel empty-inline">选择病例与触发事件，创建第一条版本化运行记录。</div>}</section>
    <p className="research-footnote">支持 Synthea、TCIA 临床表及结构化研究 JSON；所有导入记录保留来源与文件指纹。<Link to="/legacy" className="text-link">打开 V0.2 基础 Demo</Link></p>
  </div>;
}

const templates: Record<string, { type: EventType; title: string; facts: Record<string, boolean | string> }> = {
  pathology: { type: 'pathology', title: '补充病理资料（合成）', facts: { pathology_confirmed: true, pathology_record: '本地人工合成补充记录' } },
  imaging: { type: 'imaging', title: '补充影像资料（合成）', facts: { imaging_complete: true } },
  molecular: { type: 'molecular_test', title: '补充分子资料（合成）', facts: { molecular_complete: true } },
  follow_up: { type: 'follow_up', title: '新增随访记录（合成）', facts: { follow_up_complete: true } },
  progression: { type: 'progression', title: '新增进展待核验事件（合成）', facts: { progression_confirmed: false } },
};

function AddEvent({ item, onSaved }: { item: ResearchCase; onSaved: (value: ResearchCase) => void }) {
  const [template, setTemplate] = useState('pathology');
  const [title, setTitle] = useState(templates.pathology.title);
  const [type, setType] = useState<EventType>('pathology');
  const [facts, setFacts] = useState(JSON.stringify(templates.pathology.facts, null, 2));
  const nextDate = new Date(`${item.timeline.at(-1)!.occurred_at}T12:00:00Z`); nextDate.setUTCDate(nextDate.getUTCDate() + 1);
  const [date, setDate] = useState(nextDate.toISOString().slice(0, 10));
  const save = useMutation({ mutationFn: () => {
    let parsed: unknown; try { parsed = JSON.parse(facts); } catch { throw new Error('事实字段必须是合法 JSON 对象。'); }
    const checked = factsSchema.safeParse(parsed);
    if (!checked.success || !Object.keys(checked.data).length) throw new Error('至少填写一项事实；值只能是文本、数字、布尔值或 null。');
    return researchApi.append(item.case_id, item.version, { occurred_at: date, event_type: type, title, facts: checked.data });
  }, onSuccess: onSaved });
  return <section className="panel append-event"><div className="section-heading"><div><div className="eyebrow">APPEND A SYNTHETIC EVENT</div><h2>添加病程事件</h2></div><span className="pill outline">v{item.version} → v{item.version + 1}</span></div><p className="muted">新增记录标记为人工合成扩展，并保留此前所有版本。请仅使用完全虚构的资料。</p><form className="research-form" onSubmit={event => { event.preventDefault(); save.mutate(); }}><label>事件模板<select value={template} onChange={event => { const value = templates[event.target.value]; setTemplate(event.target.value); setType(value.type); setTitle(value.title); setFacts(JSON.stringify(value.facts, null, 2)); }}>{Object.entries(templates).map(([key, value]) => <option key={key} value={key}>{value.title}</option>)}</select></label><div className="research-form-row"><label>发生日期<input type="date" value={date} onChange={event => setDate(event.target.value)} required /></label><label>事件类型<select value={type} onChange={event => setType(event.target.value as EventType)}>{Object.entries(eventNames).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label></div><label>事件标题<input value={title} onChange={event => setTitle(event.target.value)} maxLength={200} required /></label><label>结构化事实 JSON<textarea rows={5} value={facts} onChange={event => setFacts(event.target.value)} spellCheck={false} /></label><InlineError error={save.error} /><button className="button primary" disabled={save.isPending}>{save.isPending ? '正在保存…' : '保存为新病例版本'}</button></form></section>;
}

export function ResearchCasePage() {
  const { caseId = '' } = useParams();
  return <CaseWorkspace key={caseId} id={caseId} />;
}
function CaseWorkspace({ id }: { id: string }) {
  const navigate = useNavigate(); const client = useQueryClient();
  const [version, setVersion] = useState<number>(); const [trigger, setTrigger] = useState('');
  const [mode, setMode] = useState<RunRequest['mode']>('mock');
  const [routingMode, setRoutingMode] = useState<RunRequest['routing_mode']>('event');
  const [scenario, setScenario] = useState<RunRequest['mock_scenario']>('standard');
  const [adding, setAdding] = useState(false); const [notice, setNotice] = useState('');
  const latest = useQuery({ queryKey: ['research-case', id, 'latest'], queryFn: () => researchApi.case(id) });
  const query = useQuery({ queryKey: ['research-case', id, version ?? 'latest'], queryFn: () => researchApi.case(id, version) });
  const models = useQuery({ queryKey: ['research-model'], queryFn: researchApi.modelStatus });
  const item = query.data; const triggerId = item?.timeline.some(event => event.event_id === trigger) ? trigger : item?.timeline.at(-1)?.event_id ?? '';
  const routing = useQuery({ queryKey: ['research-routing', id, item?.version, triggerId, routingMode], queryFn: () => researchApi.routing(id, item!.version, triggerId, routingMode), enabled: !!item && !!triggerId });
  const start = useMutation({ mutationFn: () => researchApi.start({ case_id: id, case_version: item!.version, trigger_event_id: triggerId, mode, mock_scenario: scenario, routing_mode: routingMode }), onSuccess: run => navigate(`/research/runs/${run.run_id}`) });
  if (query.isPending) return <Loading />; if (query.isError) return <ErrorState error={query.error} />;
  if (!item) return null;
  const current = item.version === latest.data?.version;
  return <div className="page-enter research-page"><Link to="/" className="back-link"><Icon name="back" size={15} />返回病例库</Link><div className="page-heading"><div><div className="eyebrow">VERSIONED CASE WORKSPACE / {id}</div><h1>{item.title}</h1><p>{sexName(item.patient.sex)} · {item.patient.age} 岁 · {item.timeline.length} 条事件 · {caseKindName[item.case_kind]}</p></div><button className="button primary" disabled={!current} onClick={() => setAdding(value => !value)}><Icon name={adding ? 'close' : 'plus'} size={16} />{adding ? '收起新增表单' : '添加病程事件'}</button></div>
    {notice && <div className="notice neutral" role="status"><Icon name="check" /><p>{notice}</p></div>}
    <div className="research-case-layout"><div className="research-stack"><section className="panel"><div className="section-heading"><div><div className="eyebrow">CURRENT RESEARCH QUESTION</div><h2>本次资料审阅任务</h2></div><label className="version-selector">查看病例版本<select aria-label="查看病例版本" value={item.version} onChange={event => { const value = Number(event.target.value); setVersion(value === latest.data?.version ? undefined : value); setTrigger(''); setAdding(false); }}>{Array.from({ length: latest.data?.version ?? item.version }, (_, i) => i + 1).reverse().map(value => <option key={value} value={value}>v{value}{value === latest.data?.version ? ' · 最新' : ' · 历史'}</option>)}</select></label></div><p>{item.current_question}</p><p className="subtle-note">运行会冻结所选版本，并仅使用截至触发事件的资料；后续病程不会进入历史事件的上下文。</p></section>
      {adding && current && <AddEvent key={item.version} item={item} onSaved={value => { client.setQueryData(['research-case', id, 'latest'], value); void client.invalidateQueries({ queryKey: ['research-cases'] }); setVersion(undefined); setTrigger(value.timeline.find(event => event.introduced_in_version === value.version)!.event_id); setAdding(false); setNotice(`已保存 v${value.version}。请选择本次运行配置，旧运行与旧报告仍绑定原始版本。`); }} />}
      <CaseSources item={item} />{routing.data && <RoutingPanel routing={routing.data} />}<InlineError error={routing.error} />
      <section className="panel"><div className="section-heading"><div><div className="eyebrow">LONGITUDINAL TIMELINE</div><h2>病程时间线</h2></div><span className="pill outline">点击事件切换评议起点</span></div><Timeline events={item.timeline} trigger={triggerId} onTrigger={setTrigger} /></section>
    </div><aside className="research-stack"><section className="panel research-config"><span className="start-icon"><Icon name="network" size={27} /></span><h2>配置本次协作</h2><form className="research-form" onSubmit={event => { event.preventDefault(); start.mutate(); }}><label>触发事件<select value={triggerId} onChange={event => setTrigger(event.target.value)}>{item.timeline.map(event => <option key={event.event_id} value={event.event_id}>{event.occurred_at} · {eventNames[event.event_type]} · {event.event_id}</option>)}</select></label><label>专科调度<select value={routingMode} onChange={event => setRoutingMode(event.target.value as RunRequest['routing_mode'])}><option value="event">Event-MDT · 按事件调度</option><option value="fixed">固定全员 · 对照模式</option></select></label><label>运行模式<select value={mode} onChange={event => { setMode(event.target.value as RunRequest['mode']); setScenario('standard'); }}><option value="mock">Mock · 本地确定性脚本</option><option value="llm" disabled={!models.data?.configured}>LLM · {models.data?.configured ? models.data.model : '尚未配置'}</option></select></label>{mode === 'mock' && <label>验证场景<select value={scenario} onChange={event => setScenario(event.target.value as RunRequest['mock_scenario'])}>{Object.entries(scenarioNames).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>}
      <div className="config-facts"><span>冻结病例 <strong>v{item.version}</strong></span><span>参与专科 <strong>{routing.data?.selected_agents.length ?? '—'} 个</strong></span><span>讨论上限 <strong>1 轮</strong></span></div><InlineError error={start.error} /><button className="button primary full" disabled={start.isPending || !routing.data || (mode === 'llm' && !models.data?.configured)}><Icon name="play" size={16} />{start.isPending ? '正在创建…' : '启动事件驱动 MDT'}</button><Link className="text-link" to="/settings/models">管理服务端模型配置 <Icon name="arrow" size={14} /></Link></form></section><div className="small-notice"><Icon name="info" /><p>“保留分歧”验证需要至少两名角色。可选择固定全员模式。资料审阅标签不代表临床诊断与治疗建议。</p></div></aside></div>
  </div>;
}

export function ResearchRunPage() { const { runId = '' } = useParams(); return <RunWorkspace key={runId} id={runId} />; }
function RunWorkspace({ id }: { id: string }) {
  const navigate = useNavigate(); const client = useQueryClient();
  const query = useResearchRun(id); const stream = useResearchStream(id); const run = query.data;
  const [evidence, setEvidence] = useState<Evidence>();
  const caseQuery = useQuery({ queryKey: ['research-case', run?.case_id, run?.case_version], queryFn: () => researchApi.case(run!.case_id, run!.case_version), enabled: !!run });
  const stop = useMutation({ mutationFn: () => researchApi.cancel(id), onSuccess: value => client.setQueryData(['research-run', id], value) });
  const rerun = useMutation({ mutationFn: () => researchApi.rerun(id), onSuccess: value => navigate(`/research/runs/${value.run_id}`) });
  if (query.isPending) return <Loading />; if (query.isError) return <ErrorState error={query.error} />; if (!run) return null;
  const trigger = caseQuery.data?.timeline.find(event => event.event_id === run.trigger_event_id);
  const frozen = caseQuery.data && trigger ? { ...caseQuery.data, timeline: caseQuery.data.timeline.filter(event => event.occurred_at < trigger.occurred_at || (event.occurred_at === trigger.occurred_at && event.event_id <= trigger.event_id)) } : undefined;
  return <div className="page-enter research-page"><Link className="back-link" to={`/research/cases/${run.case_id}`}><Icon name="back" size={15} />{run.case_id} · 病例工作台</Link><div className="page-heading"><div><div className="eyebrow">LIVE EVENT-MDT / {shortId(id)}</div><h1>事件驱动协作 <Status status={run.status} /></h1><p>病例 v{run.case_version} · 触发 {run.trigger_event_id} · {run.mode.toUpperCase()} · {run.routing_mode === 'event' ? '按事件调度' : '固定全员对照'}</p></div><div className="button-group">{terminal(run.status) ? <button className="button secondary" disabled={rerun.isPending} onClick={() => rerun.mutate()}>同配置重跑</button> : <button className="button secondary" disabled={stop.isPending || run.cancel_requested || run.report_ready} onClick={() => stop.mutate()}><Icon name="stop" />{run.cancel_requested ? '正在边界停止…' : '停止运行'}</button>}{run.report_ready && <Link className="button primary" to={`/research/runs/${id}/report`}>查看报告 <Icon name="arrow" size={16} /></Link>}</div></div>
    <InlineError error={stop.error || rerun.error} />{run.error && <div className="notice danger"><Icon name="alert" /><div><strong>本次运行未正常完成</strong><p>{run.error === 'scenario_requires_multiple_agents' ? '保留分歧场景需要至少两名角色，请选择固定全员或其他触发事件。' : run.error}</p></div></div>}{run.status === 'cancelled' && <div className="notice neutral" role="status"><Icon name="stop" /><p>已停止运行。审计保留，本次没有生成成功报告。</p></div>}
    <div className="research-stack">{frozen && <DataPath item={frozen} run={run} />}<WorkflowPanel run={run} />{run.routing && <RoutingPanel routing={run.routing} />}<div className="section-heading"><h2>本次专科意见</h2><span className="muted">有效意见分母由实际调度角色决定</span></div><AgentCards run={run} onEvidence={setEvidence} />
      {run.conflicts.length > 0 && <section className="panel"><div className="section-heading"><h2>初始分歧记录</h2><span className="pill outline">最多一轮定向讨论</span></div>{run.conflicts.map(item => <div className="research-conflict" key={item.conflict_id}><strong>{item.description}</strong><p>{item.agent_ids.map(role => roleNames[role]).join(' / ')}</p><code>{item.dimension}</code></div>)}</section>}
      {run.safety && <SafetyPanel safety={run.safety} onEvidence={setEvidence} />}<MetricsPanel metrics={run.metrics} mode={run.mode} /><div className="research-run-bottom"><AuditPanel events={stream.events} runId={id} connection={stream.connection} reconnect={stream.reconnect} /><section className="panel"><div className="section-heading"><div><div className="eyebrow">FROZEN INPUT</div><h2>本次可见病程</h2></div><span className="pill">v{run.case_version}</span></div>{frozen ? <Timeline events={frozen.timeline} trigger={run.trigger_event_id} /> : <Loading />}</section></div>
    </div>{evidence && <EvidenceDialog evidence={evidence} researchCase={frozen} onClose={() => setEvidence(undefined)} />}
  </div>;
}

export function ResearchReportPage() {
  const { runId = '' } = useParams(); const [evidence, setEvidence] = useState<Evidence>();
  const query = useQuery({ queryKey: ['research-report', runId], queryFn: () => researchApi.report(runId) });
  if (query.isPending) return <Loading />; if (query.isError) return <ErrorState error={query.error} />;
  const report = query.data;
  return <div className="page-enter research-page"><Link to={`/research/runs/${runId}`} className="back-link"><Icon name="back" size={15} />返回协作运行</Link><div className="page-heading"><div><div className="eyebrow">FROZEN RESEARCH REPORT</div><h1>可追溯 MDT 评议报告</h1><p>{report.case_id} · v{report.case_version} · 触发 {report.trigger_event_id} · {report.mode.toUpperCase()}</p></div><a className="button primary" href={`/api/v2/runs/${runId}/report/download`}><Icon name="download" />下载报告 JSON</a></div>
    <section className="report-summary"><div><div className="eyebrow">FINAL PROCESS LABEL</div><h2>{{ READY_FOR_REVIEW: '可进入资料复核', NEED_MORE_INFORMATION: '需要补充资料', DEFER_DECISION: '暂缓流程判断' }[report.final_decision]}</h2><code>{report.final_decision}</code><p>资料审阅流程结果 · 不代表诊断、治疗或临床共识</p></div><div className="summary-facts"><div><span>工作流状态</span><Status status={report.status} /></div><div><span>有效最终意见</span><strong>{report.final_opinions.length} / {report.routing.selected_agents.length}</strong></div><div><span>定向讨论</span><strong>{report.discussion_rounds} / 1 轮</strong></div><div><span>未解决分歧</span><strong>{report.unresolved_conflicts.length} 项</strong></div></div></section>
    <div className="research-stack"><RoutingPanel routing={report.routing} /><SafetyPanel safety={report.safety} evidence={report.evidence_registry} onEvidence={setEvidence} />{report.unresolved_conflicts.length > 0 && <section className="panel"><h2>保留的未解决分歧</h2>{report.unresolved_conflicts.map(conflict => <p className="inline-error" key={conflict.conflict_id}>{conflict.description}</p>)}</section>}
      <section className="panel"><div className="section-heading"><h2>初始意见与讨论变化</h2><span className="pill outline">完整保留原始意见</span></div>{report.initial_opinions.map(opinion => { const record = report.discussion_records.find(value => value.agent_id === opinion.agent_id); return <div className="research-report-opinion" key={opinion.agent_id}><h3>{roleNames[opinion.agent_id]}</h3><OpinionView opinion={opinion} onEvidence={setEvidence} />{record && <div className="discussion-change"><span>讨论后</span>{record.after ? <DecisionBadge decision={record.after.decision} /> : <span className="danger-text">讨论失败</span>}<small>{record.changed ? '意见发生变化' : '保留原意见'}</small></div>}</div>; })}</section>
      <section className="panel"><div className="section-heading"><h2>有效最终意见</h2><span className="muted">失败意见不计入最终有效集合</span></div>{report.final_opinions.map(opinion => <div className="research-report-opinion" key={opinion.agent_id}><h3>{roleNames[opinion.agent_id]}</h3><OpinionView opinion={opinion} onEvidence={setEvidence} /></div>)}{!report.final_opinions.length && <p className="empty-inline">没有有效最终意见。</p>}</section><MetricsPanel metrics={report.metrics} mode={report.mode} />
      <section className="panel"><div className="section-heading"><h2>冻结输入与来源</h2><a className="text-link" href={`/api/v2/runs/${runId}/audit/download`}>下载完整审计 <Icon name="download" size={16} /></a></div><p>{report.case_snapshot.timeline.length} 条可见事件 · {report.evidence_registry.length} 项注册事实 · 病例 v{report.case_version}</p><Timeline events={report.case_snapshot.timeline} trigger={report.trigger_event_id} /><details><summary>查看完整报告 JSON</summary><pre className="json-view">{JSON.stringify(report, null, 2)}</pre></details><p className="report-disclaimer">{report.disclaimer}</p></section>
    </div>{evidence && <EvidenceDialog evidence={evidence} researchCase={report.case_snapshot} onClose={() => setEvidence(undefined)} />}
  </div>;
}

function ResearchRunTable({ runs }: { runs: Run[] }) {
  return <div className="run-table-wrap"><table className="run-table"><thead><tr><th>运行 / 病例</th><th>冻结版本 / 触发事件</th><th>模式 / 调度</th><th>状态</th><th>创建时间</th><th>报告</th></tr></thead><tbody>{runs.map(run => <tr key={run.run_id}><td><Link className="text-link" to={`/research/runs/${run.run_id}`}>{shortId(run.run_id)}</Link><small>{run.case_id}</small></td><td>v{run.case_version} / {run.trigger_event_id}</td><td>{run.mode.toUpperCase()} · {run.routing_mode === 'event' ? '按事件' : '固定全员'}</td><td><Status status={run.status} /></td><td>{dateTime(run.created_at)}</td><td>{run.report_ready ? <Link className="text-link" to={`/research/runs/${run.run_id}/report`}>查看报告</Link> : '—'}</td></tr>)}</tbody></table></div>;
}
export function ResearchHistoryPage() {
  const query = useQuery({ queryKey: ['research-runs'], queryFn: researchApi.runs, refetchInterval: 4000 });
  if (query.isPending) return <Loading />; if (query.isError) return <ErrorState error={query.error} />;
  return <div className="page-enter research-page"><div className="page-heading"><div><div className="eyebrow">VERSIONED RUN HISTORY</div><h1>每一次评议，都保留来处<span className="title-period">.</span></h1><p>按病例版本和触发事件区分运行，可打开前后版本报告检查变化。</p></div><Link className="button primary" to="/">创建新运行 <Icon name="arrow" /></Link></div>{query.data.length ? <ResearchRunTable runs={query.data} /> : <div className="panel empty-inline">尚无研究运行记录。</div>}</div>;
}

export function ModelSettingsPage() {
  const client = useQueryClient(); const query = useQuery({ queryKey: ['research-model'], queryFn: researchApi.modelStatus });
  const [form, setForm] = useState<ModelConfiguration>({ provider: 'openai-compatible', base_url: 'https://api.openai.com/v1', model: '', api_key: '', timeout_seconds: 20, temperature: 0, max_output_tokens: 1200 });
  const [message, setMessage] = useState('');
  useEffect(() => { if (query.data) { const value = query.data; setForm({ provider: value.provider, base_url: value.base_url, model: value.model, api_key: '', timeout_seconds: value.timeout_seconds, temperature: value.temperature, max_output_tokens: value.max_output_tokens }); } }, [query.data]);
  const save = useMutation({ mutationFn: () => researchApi.configureModel(form), onSuccess: value => { client.setQueryData(['research-model'], value); setForm(old => ({ ...old, api_key: '' })); setMessage('配置已保存在服务端内存，密码输入已清空。'); } });
  const clear = useMutation({ mutationFn: researchApi.clearModel, onSuccess: value => { client.setQueryData(['research-model'], value); setMessage('已清除服务端配置。正在执行的运行仍使用启动时冻结的配置。'); } });
  const test = useMutation({ mutationFn: researchApi.testModel, onSuccess: value => setMessage(value.message) });
  if (query.isPending) return <Loading />; if (query.isError) return <ErrorState error={query.error} />;
  const update = (key: keyof ModelConfiguration, value: string | number) => setForm(old => ({ ...old, [key]: value }));
  return <div className="page-enter research-page"><div className="page-heading"><div><div className="eyebrow">SERVER-SIDE MODEL CONFIGURATION</div><h1>模型连接设置</h1><p>配置 OpenAI 兼容服务，让同一条工作流调用真实模型。</p></div><span className={`pill ${query.data.configured ? 'soft' : 'outline'}`}>{query.data.configured ? '服务端已配置 · 连通性见测试' : '尚未配置 · Mock 可用'}</span></div><div className="research-settings-grid"><section className="panel"><h2>服务端连接参数</h2><form className="research-form" onSubmit={event => { event.preventDefault(); save.mutate(); }}><label>Provider<input value={form.provider} readOnly /></label><label>Base URL<input type="url" required value={form.base_url} onChange={event => update('base_url', event.target.value)} placeholder="https://api.openai.com/v1" /></label><label>Model<input required value={form.model} onChange={event => update('model', event.target.value)} placeholder="填写服务提供方的模型标识" /></label><label>API Key<input type="password" autoComplete="new-password" value={form.api_key} onChange={event => update('api_key', event.target.value)} placeholder={query.data.has_api_key ? '同服务地址可留空保留已配置密钥' : '输入密钥，仅保存在服务端内存'} /></label><div className="research-form-row"><label>单次超时 / 秒<input type="number" min={1} max={60} value={form.timeout_seconds} onChange={event => update('timeout_seconds', Number(event.target.value))} /></label><label>Temperature<input type="number" min={0} max={2} step={0.1} value={form.temperature} onChange={event => update('temperature', Number(event.target.value))} /></label></div><label>最大输出 Token<input type="number" min={128} max={8192} value={form.max_output_tokens} onChange={event => update('max_output_tokens', Number(event.target.value))} /></label><InlineError error={save.error || clear.error || test.error} />{message && <p className="notice neutral" role="status">{message}</p>}<div className="button-group"><button className="button primary" disabled={save.isPending}>保存服务端配置</button><button type="button" className="button secondary" disabled={!query.data.configured || test.isPending} onClick={() => { setMessage(''); test.mutate(); }}>{test.isPending ? '正在测试…' : '测试已保存配置'}</button></div><button type="button" className="text-link danger-text" disabled={!query.data.configured || clear.isPending} onClick={() => clear.mutate()}>清除服务端配置</button></form></section><aside className="research-stack"><section className="panel"><h2>连接方式</h2><ol className="settings-notes"><li>浏览器通过本机接口保存配置，由后端连接模型服务。</li><li>密钥不回传页面、不写入数据库或审计；服务重启后需要重新配置。</li><li>测试按钮会发送一条不含病例的短请求，可能产生少量模型费用。</li><li>模型需支持 Chat Completions、严格 JSON Schema、temperature 与 max_tokens 参数。</li><li>更换服务地址时需重新填写密钥；不会自动把旧密钥发送到新地址。</li></ol></section><div className="small-notice"><Icon name="info" /><p>当前仅在本机使用。本机页面通过回环地址访问，模型服务必须使用 HTTPS。未配置时 LLM 模式不可启动。</p></div></aside></div></div>;
}

export function ResearchRoadmapPage() {
  const items = [
    ['01', '已实现：事件驱动工作台', '版本化病例、历史上下文截断、四专科调度、单轮定向协商、证据与信息充分性门控、SSE 和 SQLite。'],
    ['02', '接下来：真实模型联调', '配置提供方与模型，执行少量合成病例，核对结构化输出、引用、实际用量和失败路径。当前已具备适配器与模拟上游测试。'],
    ['03', '已接通：外部数据与 Agent 群', 'Synthea、TCIA 临床表与研究 JSON 可预检导入，保留来源和许可；Agent 群读取真实运行、引用、门控与审计。独立标注场景仍需后续建设。'],
    ['04', '接下来：可复现实验', '冻结数据、模型与参数，按基础病例划分开发/测试集。开展单模型、固定多角色、动态协作与完整门控对照。'],
    ['05', '系统与实验完成后：撰写论文', '依据实际实现、运行日志和实验结果形成论文，不把待实现功能或预期收益写成已有结论。'],
  ];
  return <div className="page-enter research-page"><div className="page-heading"><div><div className="eyebrow">IMPLEMENTATION BEFORE CLAIMS</div><h1>先做成形，再形成结论<span className="title-period">.</span></h1><p>按照最终方案推进可运行系统、证据和实验。</p></div></div><section className="panel"><h2>当前技术路线</h2><div className="architecture-flow"><div><span>INPUT</span><strong>版本化病程</strong><small>事件与来源</small></div><Icon name="arrow" /><div><span>EVENT-MDT</span><strong>按事件调度</strong><small>选择相关专科</small></div><Icon name="arrow" /><div><span>CONFLICT-MDT</span><strong>定向协商</strong><small>最多一轮讨论</small></div><Icon name="arrow" /><div><span>EVIDENCE GATE</span><strong>证据门控</strong><small>允许补充和延期</small></div></div></section><div className="roadmap-list research-roadmap">{items.map(([number, title, body]) => <article className="panel roadmap-item" key={number}><span className="roadmap-version">{number}</span><div><h2>{title}</h2><p>{body}</p></div></article>)}</div></div>;
}
