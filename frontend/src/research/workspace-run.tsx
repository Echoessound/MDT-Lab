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
import { RunProgressStrip, TabPanelTransition, WorkspaceViews, currentView, useWorkspaceParams } from './workspace-controls';
import { WorkspaceEvents } from './workspace-events';
import { AblationExperimentMatrix, MedicalImagingWorkbench } from './workflow-visualizer';
import type { Evidence, Report } from './schemas';
import { conflictDimensionLabel, errorCodeLabel, modeNameZh } from './zh-dict';

const runViews = [
  { key: 'collaboration', label: '协作拓扑视图' },
  { key: 'input', label: '冻结输入与影像' },
  { key: 'audit', label: '实时审计与指标' },
] as const;

const reportViews = [
  { key: 'summary', label: '审阅结论与门控' },
  { key: 'opinions', label: '各专科意见演进' },
  { key: 'ablation', label: '基线与消融对照' },
  { key: 'input', label: '冻结证据与来源' },
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
    queryFn: () => researchApi.case(run!.case_id, run!.case_version),
    enabled: !!run,
  });
  const imagingQuery = useQuery({
    queryKey: ['research-imaging', run?.case_id, run?.case_version, run?.trigger_event_id],
    queryFn: () => researchApi.imagingPipeline(run!.case_id, run!.case_version, run!.trigger_event_id),
    enabled: !!run && view === 'input',
  });
  const stop = useMutation({
    mutationFn: () => researchApi.cancel(id),
    onSuccess: value => client.setQueryData(['research-run', id], value),
  });
  const rerun = useMutation({
    mutationFn: () => researchApi.rerun(id),
    onSuccess: value => navigate(`/research/runs/${encodeURIComponent(value.run_id)}`),
  });
  const contrastRun = useMutation({
    mutationFn: () => researchApi.start({
      case_id: run!.case_id,
      case_version: run!.case_version,
      trigger_event_id: run!.trigger_event_id,
      mode: run!.mode,
      mock_scenario: run!.mock_scenario,
      routing_mode: run!.routing_mode === 'event' ? 'fixed' : 'event',
    }),
    onSuccess: value => navigate(`/research/runs/${encodeURIComponent(value.run_id)}`),
  });

  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} retry={() => void query.refetch()} />;
  if (!run) return null;
  const frozen = caseQuery.data && inputThroughTrigger(caseQuery.data, run.trigger_event_id);
  const trigger = frozen?.timeline.at(-1);
  const caseParams = new URLSearchParams({ version: String(run.case_version), trigger: run.trigger_event_id });
  const isDone = terminal(run.status);

  return <div className="page-enter research-page workspace-page">
    <Link className="back-link" to={`/research/runs${historySearch}`}><Icon name="back" size={14} />返回运行记录</Link>
    <header className="workspace-heading">
      <div>
        <div className="workspace-title-line"><h1>协同运行 #{shortId(id)}</h1><Status status={run.status} /></div>
        <p>
          关联病例 <Link className="text-link" to={`/research/cases/${encodeURIComponent(run.case_id)}?${caseParams}`}>{run.case_id} · 版本 v{run.case_version}</Link> · {modeNameZh(run.mode)}（{run.routing_mode === 'event' ? '按事件智能路由' : '固定四科全员'}） · 创建于 {dateTime(run.created_at)}
        </p>
      </div>
      <div className="button-group">
        <Link className="button secondary" to={`/research/agents?run=${encodeURIComponent(id)}`}>
          <Icon name="network" size={15} />协同中心监视
        </Link>
        {isDone ? (
          <>
            <button
              type="button"
              className="button secondary"
              disabled={contrastRun.isPending}
              onClick={() => contrastRun.mutate()}
              title="在同一冻结快照下切换路由模式发起配对对照运行"
            >
              <Icon name="route" size={15} />
              {contrastRun.isPending ? '正在创建对照…' : `切换${run.routing_mode === 'event' ? '固定全员' : '事件路由'}对照`}
            </button>
            <button
              type="button"
              className="button secondary"
              disabled={rerun.isPending}
              onClick={() => rerun.mutate()}
              title="沿用相同病例版本及运行选项重新执行"
            >
              <Icon name="refresh" size={15} />
              {rerun.isPending ? '正在创建…' : '同配置重跑'}
            </button>
          </>
        ) : (
          <button
            type="button"
            className="button secondary"
            disabled={stop.isPending || run.cancel_requested || run.report_ready}
            onClick={() => stop.mutate()}
          >
            <Icon name="stop" size={15} />
            {run.cancel_requested ? '正在安全停止…' : '停止运行'}
          </button>
        )}
        {run.report_ready && (
          <Link className="button primary" state={{ historySearch, runSearch: location.search }} to={`/research/runs/${encodeURIComponent(id)}/report`}>
            <Icon name="file" size={15} />查看评议报告
          </Link>
        )}
      </div>
    </header>
    <InlineError error={stop.error || rerun.error || contrastRun.error} />
    {run.error && <p className="notice danger"><Icon name="alert" size={16} /><span>运行异常终止 · {errorCodeLabel(run.error)}</span></p>}
    {run.status === 'cancelled' && <p className="notice neutral" role="status"><Icon name="stop" size={16} /><span>本次运行已响应人工停止指令，已提交的审计轨迹完整保留，未生成不完整报告。</span></p>}
    <dl className="workspace-factbar">
      <div><dt>当前执行阶段</dt><dd>{stageNames[run.stage] ?? run.stage}</dd></div>
      <div><dt>锁定触发截点</dt><dd>{trigger ? `${trigger.title}（${run.trigger_event_id}）` : run.trigger_event_id}</dd></div>
      <div><dt>本次调度专科</dt><dd>{run.routing ? run.routing.selected_agents.map(role => roleNames[role]).join('、') : '等待动态调度'}</dd></div>
      <div><dt>已归档审计事件</dt><dd>{run.last_seq} 条</dd></div>
    </dl>
    <RunProgressStrip run={run} />
    <WorkspaceViews
      label="运行视图"
      tabs={[
        { key: 'collaboration', label: '协作拓扑视图' },
        { key: 'input', label: '冻结输入与影像', badge: frozen?.timeline.length },
        { key: 'audit', label: '实时审计与指标', badge: run.last_seq },
      ]}
      value={view}
      onChange={v => update({ view: v === 'collaboration' ? '' : v })}
    />
    <TabPanelTransition tabs={runViews} activeKey={view} className="workspace-column">
      {view === 'collaboration' && <CollaborationGraph run={run} onEvidence={setEvidence} />}
      {view === 'input' && (caseQuery.isPending ? <Loading /> : frozen ? <>
        {imagingQuery.data && imagingQuery.data.study_count > 0 && <MedicalImagingWorkbench imaging={imagingQuery.data} />}
        <WorkspaceEvents events={frozen.timeline} trigger={run.trigger_event_id} />
        <CaseSources item={frozen} />
        {run.routing && <RoutingPanel routing={run.routing} />}
      </> : <ErrorState error={caseQuery.error ?? new Error('此病例版本中找不到运行记录的触发事件。')} retry={() => void caseQuery.refetch()} />)}
      {view === 'audit' && <><AuditPanel events={stream.events} runId={id} connection={stream.connection} reconnect={stream.reconnect} /><WorkflowPanel run={run} /><MetricsPanel metrics={run.metrics} mode={run.mode} /></>}
    </TabPanelTransition>
    {evidence && <EvidenceDialog evidence={evidence} researchCase={frozen} onClose={() => setEvidence(undefined)} />}
  </div>;
}

function ReportOpinions({ report, onEvidence }: { report: Report; onEvidence: (value: Evidence) => void }) {
  return <section className="panel"><div className="workspace-section-heading"><h2>各专科审阅意见与协商演进</h2><span className="workspace-meta">共 {report.final_opinions.length} / {report.routing.selected_agents.length} 份有效最终意见</span></div>
    {report.routing.selected_agents.map(role => {
      const initial = report.initial_opinions.find(opinion => opinion.agent_id === role);
      const final = report.final_opinions.find(opinion => opinion.agent_id === role);
      const discussion = report.discussion_records.find(record => record.agent_id === role);
      return <article className="workspace-report-opinion" key={role}>
        <div className="opinion-header-row">
          <h3>{roleNames[role]}</h3>
          {discussion && (
            <span className="pill soft">
              {!discussion.after ? '协商阶段未获有效更新' : discussion.changed ? '经定向协商已修订意见' : '经定向协商维持原判'}
            </span>
          )}
        </div>
        {final ? <OpinionView opinion={final} onEvidence={onEvidence} /> : <p className="subtle-note">该专科本次未产出有效最终意见</p>}
        {initial && (discussion || !final) && <details><summary>展开定向协商前的初审意见快照</summary><OpinionView opinion={initial} onEvidence={onEvidence} /></details>}
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
  const report = query.data;
  const temporalAuditQuery = useQuery({
    queryKey: ['research-temporal-audit', runId],
    queryFn: () => researchApi.temporalAudit(runId),
    enabled: !!report && view === 'summary',
  });
  const ablationQuery = useQuery({
    queryKey: ['research-ablation', report?.case_id, report?.case_version, report?.trigger_event_id],
    queryFn: () => researchApi.ablationMatrix(report!.case_id, report!.case_version, report!.trigger_event_id),
    enabled: !!report && view === 'ablation',
  });

  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} retry={() => void query.refetch()} />;
  if (!report) return null;
  const runPath = `/research/runs/${encodeURIComponent(runId)}`;
  return <div className="page-enter research-page workspace-page">
    <Link to={runPath + runSearch} state={state} className="back-link"><Icon name="back" size={14} />返回协同运行 #{shortId(runId)}</Link>
    <header className="workspace-heading">
      <div>
        <div className="workspace-title-line"><h1>多学科协同评议报告</h1><DecisionBadge decision={report.final_decision} /></div>
        <p>病例 <code>{report.case_id}</code> · 版本 v{report.case_version} · 触发截点 <code>{report.trigger_event_id}</code> · {modeNameZh(report.mode)}</p>
      </div>
      <div className="button-group">
        <a className="button secondary" href={`/api/v2/runs/${encodeURIComponent(runId)}/audit/download`}>
          <Icon name="download" size={15} />导出审计日志 (JSONL)
        </a>
        <a className="button primary" href={`/api/v2/runs/${encodeURIComponent(runId)}/report/download`}>
          <Icon name="download" size={15} />下载结构化报告 (JSON)
        </a>
      </div>
    </header>
    <dl className="workspace-factbar">
      <div><dt>工作流终态</dt><dd><Status status={report.status} /></dd></div>
      <div><dt>有效意见 / 调度专科</dt><dd>{report.final_opinions.length} / {report.routing.selected_agents.length} 科</dd></div>
      <div><dt>定向协商轮次</dt><dd>{report.discussion_rounds} 轮（上限 1 轮）</dd></div>
      <div><dt>最终保留分歧</dt><dd>{report.unresolved_conflicts.length} 项</dd></div>
    </dl>
    <WorkspaceViews
      label="报告视图"
      value={view}
      tabs={[
        { key: 'summary', label: '审阅结论与门控' },
        { key: 'opinions', label: '各专科意见演进', badge: report.final_opinions.length },
        { key: 'ablation', label: '基线与消融对照', badge: 'B0–B3' },
        { key: 'input', label: '冻结证据与来源', badge: report.evidence_registry.length },
      ]}
      onChange={v => update({ view: v === 'summary' ? '' : v })}
    />
    <TabPanelTransition tabs={reportViews} activeKey={view} className="workspace-column">
      {view === 'summary' && <>
        {report.unresolved_conflicts.length > 0 && (
          <section className="panel">
            <div className="workspace-section-heading">
              <h2>未消解的跨科或同日来源分歧（安全门控已拦截）</h2>
              <span className="pill status-failed">禁止多数票掩盖</span>
            </div>
            {report.unresolved_conflicts.map(conflict => (
              <div className="research-conflict" key={conflict.conflict_id}>
                <strong>{conflict.description}</strong>
                <p>涉及专科：{conflict.agent_ids.map(role => roleNames[role]).join('、')} · 分歧类型：{conflictDimensionLabel(conflict.dimension)}</p>
              </div>
            ))}
          </section>
        )}
        <SafetyPanel safety={report.safety} evidence={report.evidence_registry} onEvidence={setEvidence} />
        {temporalAuditQuery.data && (
          <section className="panel">
            <div className="workspace-section-heading">
              <div>
                <h2>时间边界防泄漏独立审计</h2>
                <p className="muted">绕过运行引擎直接从原病例版本重建截点白名单，逐项核查时间线、无日期记录、证据注册表与意见引用。</p>
              </div>
              <span className={`pill ${temporalAuditQuery.data.passed ? 'status-completed' : 'status-failed'}`}>
                {temporalAuditQuery.data.passed ? '独立核验通过 · 0 泄漏' : `发现 ${temporalAuditQuery.data.leaked_count} 项越界`}
              </span>
            </div>
            <div className="workspace-table-scroll">
              <table className="workspace-table">
                <thead>
                  <tr><th>审计维度</th><th>状态</th><th>核验结论</th></tr>
                </thead>
                <tbody>
                  {temporalAuditQuery.data.checks.map(chk => (
                    <tr key={chk.code}>
                      <td><code>{chk.code}</code></td>
                      <td>
                        <span className={`pill ${chk.status === 'passed' ? 'status-completed' : chk.status === 'warning' ? 'status-warning' : 'status-failed'}`}>
                          {chk.status === 'passed' ? '通过' : chk.status === 'warning' ? '提示' : '越界'}
                        </span>
                      </td>
                      <td>{chk.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
        <MetricsPanel metrics={report.metrics} mode={report.mode} />
      </>}
      {view === 'opinions' && <><ReportOpinions report={report} onEvidence={setEvidence} /><RoutingPanel routing={report.routing} /></>}
      {view === 'ablation' && (
        ablationQuery.isPending ? <Loading /> : ablationQuery.isError ? <InlineError error={ablationQuery.error} /> : <AblationExperimentMatrix matrix={ablationQuery.data} />
      )}
      {view === 'input' && <>
        <WorkspaceEvents events={report.case_snapshot.timeline} trigger={report.trigger_event_id} />
        <CaseSources item={report.case_snapshot} />
        <section className="panel">
          <div className="workspace-section-heading">
            <h2>底层报告原始载荷</h2>
            <a className="text-link" href={`/api/v2/runs/${encodeURIComponent(runId)}/audit/download`}>下载完整审计 <Icon name="download" size={14} /></a>
          </div>
          <details onToggle={event => setJsonOpen(event.currentTarget.open)}>
            <summary>展开完整报告结构化 JSON</summary>
            {jsonOpen && <pre className="json-view">{JSON.stringify(report, null, 2)}</pre>}
          </details>
        </section>
      </>}
    </TabPanelTransition>
    <p className="workspace-disclaimer">{report.disclaimer}</p>
    {evidence && <EvidenceDialog evidence={evidence} researchCase={report.case_snapshot} onClose={() => setEvidence(undefined)} />}
  </div>;
}
