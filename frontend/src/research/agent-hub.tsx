import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ErrorState, Icon, Loading, Status, dateTime, shortId } from '../ui';
import { researchApi } from './api';
import { AuditPanel, EvidenceDialog, InlineError, stageNames } from './components';
import { CollaborationGraph } from './collaboration-graph';
import { terminal, useResearchRun, useResearchStream } from './realtime';
import type { Evidence, Run } from './schemas';
import './agent-console.css';

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
      <h1>Agent 群</h1>
      <div className="button-group">
        <Link className="button secondary" to="/settings/models"><Icon name="settings" size={15} />模型设置</Link>
        <Link className="button primary" to="/">选择病例运行 <Icon name="arrow" size={15} /></Link>
      </div>
    </header>
    {runs.isPending ? <Loading /> : runs.isError ? <ErrorState error={runs.error} retry={() => void runs.refetch()} /> :
      runs.data.length || selected ? <>
        <div className="agent-run-selector">
          <label htmlFor="monitored-run">监视运行</label>
          <select id="monitored-run" value={selected ?? initialRun?.run_id} onChange={event => selectRun(event.target.value)}>
            {selected && !runs.data.some(run => run.run_id === selected) && <option value={selected}>运行 {shortId(selected)}</option>}
            {runs.data.map(run => <option key={run.run_id} value={run.run_id}>{dateTime(run.created_at)} · {run.case_id} · v{run.case_version} · {shortId(run.run_id)}</option>)}
          </select>
          <Link to="/research/runs" className="text-link">运行记录 <Icon name="arrow" size={13} /></Link>
        </div>
        {(selected || initialRun) && <RunMonitor key={selected ?? initialRun!.run_id} id={selected ?? initialRun!.run_id} />}
      </> : <section className="panel console-blank">
        <h2>暂无协作运行</h2><p>在病例中选择触发事件并启动运行后，可在这里查看各专科的进度和意见。</p>
        <Link className="button secondary" to="/">打开病例库</Link>
      </section>}
  </div>;
}

function RunMonitor({ id }: { id: string }) {
  const query = useResearchRun(id);
  const [evidence, setEvidence] = useState<Evidence>();
  const [params, setParams] = useSearchParams();
  const auditView = params.get('view') === 'audit';
  const source = useQuery({
    queryKey: ['research-case', query.data?.case_id, query.data?.case_version],
    queryFn: () => researchApi.case(query.data!.case_id, query.data!.case_version),
    enabled: !!query.data && !!evidence,
  });
  const showAudit = (audit: boolean) => setParams(next => {
    if (audit) next.set('view', 'audit');
    else next.delete('view');
    return next;
  }, { replace: true });

  if (query.isPending) return <Loading />;
  if (!query.data) return <ErrorState error={query.error} retry={() => void query.refetch()} />;
  const run = query.data;
  return <div className="monitor-workspace">
    <section className="panel monitor-overview" aria-label="所选运行">
      <div className="monitor-summary">
        <div className="monitor-title"><Link to={`/research/cases/${encodeURIComponent(run.case_id)}?version=${run.case_version}&trigger=${encodeURIComponent(run.trigger_event_id)}`}>{run.case_id}</Link><Status status={run.status} /></div>
        <div className="monitor-actions">
          <Link className="text-link" to={`/research/runs/${run.run_id}`}>运行详情 <Icon name="arrow" size={13} /></Link>
          {run.report_ready && <Link className="button secondary" to={`/research/runs/${run.run_id}/report`}><Icon name="file" size={14} />查看报告</Link>}
        </div>
      </div>
      <dl className="monitor-metrics">
        <div><dt>病例版本</dt><dd>v{run.case_version}</dd></div>
        <div><dt>触发事件</dt><dd>{run.trigger_event_id}</dd></div>
        <div><dt>当前阶段</dt><dd>{stageNames[run.stage] ?? run.stage}</dd></div>
        <div><dt>最后更新</dt><dd><time dateTime={run.updated_at}>{dateTime(run.updated_at)}</time></dd></div>
      </dl>
    </section>
    {query.isError && <InlineError error={query.error} />}
    <div className="monitor-switch" role="group" aria-label="监视内容">
      <button type="button" aria-pressed={!auditView} onClick={() => showAudit(false)}><Icon name="network" size={15} />协作视图</button>
      <button type="button" aria-pressed={auditView} onClick={() => showAudit(true)}><Icon name="history" size={15} />运行审计 <span>{run.last_seq}</span></button>
    </div>
    {auditView ? <RunAudit run={run} /> : <CollaborationGraph run={run} onEvidence={setEvidence} />}
    {evidence && <EvidenceDialog evidence={evidence} researchCase={source.data} onClose={() => setEvidence(undefined)} />}
  </div>;
}

function RunAudit({ run }: { run: Run }) {
  const stream = useResearchStream(run.run_id);
  return <AuditPanel events={stream.events} connection={stream.connection} reconnect={stream.reconnect} runId={run.run_id} />;
}
