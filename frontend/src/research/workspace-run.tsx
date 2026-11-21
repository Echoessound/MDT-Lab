import { useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { DecisionBadge, ErrorState, Icon, Loading, Status, dateTime, shortId } from '../ui';
import { researchApi } from './api';
import { inputThroughTrigger } from './run-input';
import { AuditPanel, EvidenceDialog, InlineError, MetricsPanel, OpinionView, RoutingPanel, SafetyPanel, WorkflowPanel, roleNames, stageNames } from './components';
import { CaseSources } from './data-components';
import { CollaborationGraph } from './collaboration-graph';
import { terminal, useResearchRun, useResearchStream } from './realtime';
import { WorkspaceViews, currentView, useWorkspaceParams } from './workspace-controls';
import { WorkspaceEvents } from './workspace-events';
import type { Evidence, Report } from './schemas';

const runViews = [
  { key: 'collaboration', label: '协作视图' }, { key: 'input', label: '运行输入' }, { key: 'audit', label: '执行记录' },
] as const;
const reportViews = [
  { key: 'summary', label: '审阅结果' }, { key: 'opinions', label: '专科意见' }, { key: 'input', label: '证据与来源' },
] as const;

export function ResearchRunPage() {
  const { runId = '' } = useParams();
  return <RunWorkspace id={runId} key={runId} />;
}

function RunWorkspace({ id }: { id: string }) {
  const navigate = useNavigate();
  const location = useLocation();
  const historySearch = typeof location.state?.historySearch === 'string' && location.state.historySearch.startsWith('?') ? location.state.historySearch : '';
  const client = useQueryClient();
  const { params, update } = useWorkspaceParams();
  const view = currentView(runViews, params.get('view'));
  const query = useResearchRun(id);
  const run = query.data;
  const stream = useResearchStream(id);
  const [evidence, setEvidence] = useState<Evidence>();
  const caseQuery = useQuery({
    queryKey: ['research-case', run?.case_id, run?.case_version],
    queryFn: () => researchApi.case(run!.case_id, run!.case_version), enabled: !!run,
  });
  const stop = useMutation({ mutationFn: () => researchApi.cancel(id), onSuccess: value => client.setQueryData(['research-run', id], value) });
  const rerun = useMutation({ mutationFn: () => researchApi.rerun(id), onSuccess: value => navigate(`/research/runs/${encodeURIComponent(value.run_id)}`) });
  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} retry={() => void query.refetch()} />;
  if (!run) return null;
  const frozen = caseQuery.data && inputThroughTrigger(caseQuery.data, run.trigger_event_id);
  const trigger = frozen?.timeline.at(-1);
  const caseParams = new URLSearchParams({ version: String(run.case_version), trigger: run.trigger_event_id });
  return <div className="page-enter research-page workspace-page">
    <Link className="back-link" to={`/research/runs${historySearch}`}><Icon name="back" size={14} />运行记录</Link>
    <header className="workspace-heading"><div><div className="workspace-title-line"><h1>运行 {shortId(id)}</h1><Status status={run.status} /></div>
      <p><Link className="text-link" to={`/research/cases/${encodeURIComponent(run.case_id)}?${caseParams}`}>{run.case_id} · v{run.case_version}</Link> · {run.mode === 'mock' ? 'Mock' : 'LLM'} · 创建于 {dateTime(run.created_at)}</p></div>
      <div className="button-group">{terminal(run.status) ? <button className="button secondary" disabled={rerun.isPending} onClick={() => rerun.mutate()} title="沿用病例及运行选项，模型连接取当前配置">{rerun.isPending ? '正在创建…' : '重新运行'}</button> : <button className="button secondary" disabled={stop.isPending || run.cancel_requested || run.report_ready} onClick={() => stop.mutate()}><Icon name="stop" size={15} />{run.cancel_requested ? '正在停止…' : '停止运行'}</button>}
        {run.report_ready && <Link className="button primary" state={{ historySearch, runSearch: location.search }} to={`/research/runs/${encodeURIComponent(id)}/report`}><Icon name="file" size={15} />查看报告</Link>}</div>
    </header>
    <InlineError error={stop.error || rerun.error} />
    {run.error && <p className="notice danger"><Icon name="alert" size={16} />{run.error === 'scenario_requires_multiple_agents' ? '所选规则场景至少需要两名专科。' : `运行异常 · ${run.error}`}</p>}
    {run.status === 'cancelled' && <p className="notice neutral" role="status">运行已停止，执行记录已保留。</p>}
    <dl className="workspace-factbar"><div><dt>执行阶段</dt><dd>{stageNames[run.stage] ?? run.stage}</dd></div><div><dt>触发事件</dt><dd>{trigger?.title ?? run.trigger_event_id}</dd></div><div><dt>参与专科</dt><dd>{run.routing ? run.routing.selected_agents.map(role => roleNames[role]).join('、') : '等待调度'}</dd></div><div><dt>审计记录</dt><dd>{run.last_seq} 条</dd></div></dl>
    <WorkspaceViews label="运行视图" tabs={runViews} value={view} onChange={v => update({ view: v === 'collaboration' ? '' : v })} />
    <div id="workspace-panel" role="tabpanel" aria-labelledby={`workspace-tab-${view}`} tabIndex={0} className="workspace-column">
      {view === 'collaboration' && <CollaborationGraph run={run} onEvidence={setEvidence} />}
      {view === 'input' && (caseQuery.isPending ? <Loading /> : frozen ? <><WorkspaceEvents events={frozen.timeline} trigger={run.trigger_event_id} /><CaseSources item={frozen} />{run.routing && <RoutingPanel routing={run.routing} />}</> : <ErrorState error={caseQuery.error ?? new Error('此病例版本中找不到运行记录的触发事件。')} retry={() => void caseQuery.refetch()} />)}
      {view === 'audit' && <><AuditPanel events={stream.events} runId={id} connection={stream.connection} reconnect={stream.reconnect} /><WorkflowPanel run={run} /><MetricsPanel metrics={run.metrics} mode={run.mode} /></>}
    </div>
    {evidence && <EvidenceDialog evidence={evidence} researchCase={frozen} onClose={() => setEvidence(undefined)} />}
  </div>;
}

function ReportOpinions({ report, onEvidence }: { report: Report; onEvidence: (value: Evidence) => void }) {
  return <section className="panel"><div className="workspace-section-heading"><h2>专科意见</h2><span className="workspace-meta">{report.final_opinions.length} 份有效意见</span></div>
    {report.routing.selected_agents.map(role => {
      const initial = report.initial_opinions.find(opinion => opinion.agent_id === role);
      const final = report.final_opinions.find(opinion => opinion.agent_id === role);
      const discussion = report.discussion_records.find(record => record.agent_id === role);
      return <article className="workspace-report-opinion" key={role}><h3>{roleNames[role]}</h3>
        {final ? <OpinionView opinion={final} onEvidence={onEvidence} /> : <p className="subtle-note">无有效最终意见</p>}
        {discussion && <p className="workspace-meta">{!discussion.after ? '讨论阶段未获得有效意见' : discussion.changed ? '讨论后已修订意见' : '讨论后保持原意见'}</p>}
        {initial && (discussion || !final) && <details><summary>初始意见</summary><OpinionView opinion={initial} onEvidence={onEvidence} /></details>}
      </article>;
    })}
  </section>;
}

export function ResearchReportPage() {
  const { runId = '' } = useParams();
  const { state } = useLocation();
  const runSearch = typeof state?.runSearch === 'string' && state.runSearch.startsWith('?') ? state.runSearch : '';
  const { params, update } = useWorkspaceParams();
  const view = currentView(reportViews, params.get('view'));
  const [evidence, setEvidence] = useState<Evidence>();
  const [jsonOpen, setJsonOpen] = useState(false);
  const query = useQuery({ queryKey: ['research-report', runId], queryFn: () => researchApi.report(runId) });
  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} retry={() => void query.refetch()} />;
  const report = query.data;
  const runPath = `/research/runs/${encodeURIComponent(runId)}`;
  return <div className="page-enter research-page workspace-page">
    <Link to={runPath + runSearch} state={state} className="back-link"><Icon name="back" size={14} />运行 {shortId(runId)}</Link>
    <header className="workspace-heading"><div><div className="workspace-title-line"><h1>评议报告</h1><DecisionBadge decision={report.final_decision} /></div>
      <p>{report.case_id} · v{report.case_version} · {report.trigger_event_id} · {report.mode === 'mock' ? 'Mock' : 'LLM'}</p></div>
      <a className="button secondary" href={`/api/v2/runs/${encodeURIComponent(runId)}/report/download`}><Icon name="download" size={15} />下载报告 JSON</a></header>
    <dl className="workspace-factbar"><div><dt>运行状态</dt><dd><Status status={report.status} /></dd></div><div><dt>有效意见 / 参与专科</dt><dd>{report.final_opinions.length} / {report.routing.selected_agents.length}</dd></div><div><dt>讨论轮次</dt><dd>{report.discussion_rounds}</dd></div><div><dt>未解决分歧</dt><dd>{report.unresolved_conflicts.length} 项</dd></div></dl>
    <WorkspaceViews label="报告视图" value={view} tabs={reportViews} onChange={v => update({ view: v === 'summary' ? '' : v })} />
    <div id="workspace-panel" role="tabpanel" aria-labelledby={`workspace-tab-${view}`} tabIndex={0} className="workspace-column">
      {view === 'summary' && <>
        {report.unresolved_conflicts.length > 0 && <section className="panel"><h2>未解决分歧</h2>{report.unresolved_conflicts.map(conflict => <div className="research-conflict" key={conflict.conflict_id}><strong>{conflict.description}</strong><p>{conflict.agent_ids.map(role => roleNames[role]).join('、')}</p></div>)}</section>}
        <SafetyPanel safety={report.safety} evidence={report.evidence_registry} onEvidence={setEvidence} />
        <Link className="text-link" state={state} to={`${runPath}?view=audit`}>查看执行记录与用量 <Icon name="arrow" size={14} /></Link>
      </>}
      {view === 'opinions' && <><ReportOpinions report={report} onEvidence={setEvidence} /><RoutingPanel routing={report.routing} /></>}
      {view === 'input' && <><WorkspaceEvents events={report.case_snapshot.timeline} trigger={report.trigger_event_id} /><CaseSources item={report.case_snapshot} /><section className="panel"><div className="workspace-section-heading"><h2>原始记录</h2><a className="text-link" href={`/api/v2/runs/${encodeURIComponent(runId)}/audit/download`}>下载完整审计 <Icon name="download" size={14} /></a></div><details onToggle={event => setJsonOpen(event.currentTarget.open)}><summary>报告 JSON</summary>{jsonOpen && <pre className="json-view">{JSON.stringify(report, null, 2)}</pre>}</details></section></>}
    </div><p className="workspace-disclaimer">{report.disclaimer}</p>{evidence && <EvidenceDialog evidence={evidence} researchCase={report.case_snapshot} onClose={() => setEvidence(undefined)} />}
  </div>;
}
