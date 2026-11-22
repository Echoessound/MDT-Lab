import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorState, Icon, Loading, Status, dateTime, shortId } from '../ui';
import { researchApi } from './api';
import { AuditPanel, EvidenceDialog, InlineError, roleNames, stageNames } from './components';
import { CollaborationGraph } from './collaboration-graph';
import { terminal, useResearchRun, useResearchStream } from './realtime';
import { RunProgressStrip, TabPanelTransition, WorkspaceViews } from './workspace-controls';
import type { Evidence, Run } from './schemas';
import { modeNameZh } from './zh-dict';
import './agent-console.css';

const monitorTabs = [
  { key: 'graph', label: '协同拓扑与意见' },
  { key: 'audit', label: '实时执行审计' },
] as const;

export function AgentHubPage() {
  const [params, setParams] = useSearchParams();
  const runs = useQuery({ queryKey: ['research-runs'], queryFn: researchApi.runs, refetchInterval: 4000 });
  const selected = params.get('run');
  const initialRun = runs.data?.find(run => !terminal(run.status)) ?? runs.data?.[0];

  // Pin the initial selection, so an arriving run never replaces the one being inspected.
  useEffect(() => {
    if (!selected && initialRun) {
      setParams(next => { next.set('run', initialRun.run_id); return next; }, { replace: true });
    }
  }, [selected, initialRun?.run_id, setParams]);

  const selectRun = (id: string) => setParams(next => { next.set('run', id); return next; });
  return <div className="page-enter research-page agent-console">
    <header className="page-heading">
      <div>
        <h1>多智能体专科协同中心</h1>
        <p>实时监视多专科序贯审阅进度、跨科分歧定向协商、证据链溯源与安全门控状态</p>
      </div>
      <div className="button-group">
        <Link className="button secondary" to="/settings/models"><Icon name="settings" size={15} />专科模型设置</Link>
        <Link className="button primary" to="/">选择病例发起运行 <Icon name="arrow" size={15} /></Link>
      </div>
    </header>
    {runs.isPending ? <Loading /> : runs.isError ? <ErrorState error={runs.error} retry={() => void runs.refetch()} /> :
      runs.data.length || selected ? <>
        <div className="agent-run-selector">
          <label htmlFor="monitored-run">当前监视任务</label>
          <select id="monitored-run" value={selected ?? initialRun?.run_id} onChange={event => selectRun(event.target.value)}>
            {selected && !runs.data.some(run => run.run_id === selected) && <option value={selected}>运行 #{shortId(selected)}</option>}
            {runs.data.map(run => <option key={run.run_id} value={run.run_id}>{dateTime(run.created_at)} · {run.case_id} (v{run.case_version}) · #{shortId(run.run_id)} · {modeNameZh(run.mode)}</option>)}
          </select>
          <Link to="/research/runs" className="text-link">全部运行历史 <Icon name="arrow" size={13} /></Link>
        </div>
        {(selected || initialRun) && <RunMonitor key={selected ?? initialRun!.run_id} id={selected ?? initialRun!.run_id} onSelectRun={selectRun} />}
      </> : <section className="panel console-blank">
        <h2>暂无活动或历史协同运行</h2><p>请在病例工作台中选择病程触发截点并启动 MDT 协同运行，此处将实时呈现四专科协同拓扑。</p>
        <Link className="button primary" to="/">前往病例工作台</Link>
      </section>}
  </div>;
}

function RunMonitor({ id, onSelectRun }: { id: string; onSelectRun: (runId: string) => void }) {
  const client = useQueryClient();
  const query = useResearchRun(id);
  const [evidence, setEvidence] = useState<Evidence>();
  const [params, setParams] = useSearchParams();
  const activeTab: 'graph' | 'audit' = params.get('view') === 'audit' ? 'audit' : 'graph';
  const source = useQuery({
    queryKey: ['research-case', query.data?.case_id, query.data?.case_version],
    queryFn: () => researchApi.case(query.data!.case_id, query.data!.case_version),
    enabled: !!query.data && !!evidence,
  });
  const stop = useMutation({
    mutationFn: () => researchApi.cancel(id),
    onSuccess: value => client.setQueryData(['research-run', id], value),
  });
  const rerun = useMutation({
    mutationFn: () => researchApi.rerun(id),
    onSuccess: value => {
      void client.invalidateQueries({ queryKey: ['research-runs'] });
      onSelectRun(value.run_id);
    },
  });

  const setTab = (key: 'graph' | 'audit') => setParams(next => {
    if (key === 'audit') next.set('view', 'audit');
    else next.delete('view');
    return next;
  }, { replace: true });

  if (query.isPending) return <Loading />;
  if (!query.data) return <ErrorState error={query.error} retry={() => void query.refetch()} />;
  const run = query.data;
  const isDone = terminal(run.status);

  return <div className="monitor-workspace">
    <section className="panel monitor-overview" aria-label="所选运行">
      <div className="monitor-summary">
        <div className="monitor-title">
          <Link to={`/research/cases/${encodeURIComponent(run.case_id)}?version=${run.case_version}&trigger=${encodeURIComponent(run.trigger_event_id)}`}>
            {run.case_id} · 版本 v{run.case_version}
          </Link>
          <Status status={run.status} />
        </div>
        <div className="monitor-actions">
          {isDone ? (
            <button type="button" className="button secondary" disabled={rerun.isPending} onClick={() => rerun.mutate()}>
              <Icon name="refresh" size={14} />{rerun.isPending ? '正在重跑…' : '重新运行'}
            </button>
          ) : (
            <button type="button" className="button secondary" disabled={stop.isPending || run.cancel_requested || run.report_ready} onClick={() => stop.mutate()}>
              <Icon name="stop" size={14} />{run.cancel_requested ? '正在停止…' : '停止运行'}
            </button>
          )}
          <Link className="button secondary" to={`/research/runs/${run.run_id}`}>运行详情 <Icon name="arrow" size={13} /></Link>
          {run.report_ready && <Link className="button primary" to={`/research/runs/${run.run_id}/report`}><Icon name="file" size={14} />查看评议报告</Link>}
        </div>
      </div>
      <dl className="monitor-metrics">
        <div><dt>锁定触发截点</dt><dd><code>{run.trigger_event_id}</code></dd></div>
        <div><dt>当前执行阶段</dt><dd>{stageNames[run.stage] ?? run.stage}</dd></div>
        <div><dt>参与专科</dt><dd>{run.routing ? run.routing.selected_agents.map(r => roleNames[r]).join('、') : '待调度'}</dd></div>
        <div><dt>最后更新时间</dt><dd><time dateTime={run.updated_at}>{dateTime(run.updated_at)}</time></dd></div>
      </dl>
      <RunProgressStrip run={run} />
    </section>
    <InlineError error={query.error || stop.error || rerun.error} />
    <WorkspaceViews
      label="监视内容切换"
      tabs={[
        { key: 'graph', label: '协同拓扑与意见' },
        { key: 'audit', label: '实时执行审计', badge: run.last_seq },
      ]}
      value={activeTab}
      onChange={setTab}
    />
    <TabPanelTransition tabs={monitorTabs} activeKey={activeTab}>
      {activeTab === 'audit' ? <RunAudit run={run} /> : <CollaborationGraph run={run} onEvidence={setEvidence} />}
    </TabPanelTransition>
    {evidence && <EvidenceDialog evidence={evidence} researchCase={source.data} onClose={() => setEvidence(undefined)} />}
  </div>;
}

function RunAudit({ run }: { run: Run }) {
  const stream = useResearchStream(run.run_id);
  return <AuditPanel events={stream.events} connection={stream.connection} reconnect={stream.reconnect} runId={run.run_id} />;
}
