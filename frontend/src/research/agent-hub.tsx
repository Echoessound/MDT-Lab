import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ErrorState, Icon, Loading, Status, shortId } from '../ui';
import { researchApi } from './api';
import { AgentCards, AuditPanel, EvidenceDialog, InlineError, WorkflowPanel, roleNames } from './components';
import { DataPath, caseKindName } from './data-components';
import { useResearchRun, useResearchStream } from './realtime';
import type { Evidence } from './schemas';

export function AgentHubPage() {
  const cases = useQuery({ queryKey: ['research-cases'], queryFn: researchApi.cases });
  const runs = useQuery({ queryKey: ['research-runs'], queryFn: researchApi.runs, refetchInterval: 4000 });
  const [chosen, setChosen] = useState('');
  const selected = chosen || runs.data?.[0]?.run_id;
  return <div className="page-enter research-page"><div className="page-heading"><div><div className="eyebrow">AGENT COLLECTIVE / CONNECTED WORKSPACE</div><h1>同一份输入，协同且可追溯<span className="title-period">.</span></h1><p>从病例进入协作，查看各专科真实状态、证据与审计。</p></div><Link className="button primary" to="/research/datasets">接入数据 <Icon name="arrow" /></Link></div>
    <section className="panel"><div className="section-heading"><h2>选择病例，配置协作</h2><span className="pill outline">4 个专科 · 按事件调度</span></div><div className="agent-roster">{Object.entries(roleNames).map(([key, name]) => <span key={key}><Icon name="network" size={16} />{name}</span>)}</div>{cases.isPending ? <Loading /> : cases.isError ? <InlineError error={cases.error} /> : <div className="import-case-list hub-cases">{cases.data.map(item => <Link className="text-link" key={item.case_id} to={`/research/cases/${encodeURIComponent(item.case_id)}`}><span>{item.case_id}<small>{caseKindName[item.case_kind]} · v{item.version} · {item.timeline.length} 条事件</small></span><Icon name="arrow" size={14} /></Link>)}</div>}</section>
    <section className="panel recent-section"><div className="section-heading"><h2>协作运行</h2><Link className="text-link" to="/research/runs">全部运行</Link></div>{runs.isError ? <ErrorState error={runs.error} /> : runs.isPending ? <Loading /> : runs.data.length ? <label className="research-form">查看运行<select value={selected} onChange={event => setChosen(event.target.value)}>{runs.data.map(run => <option key={run.run_id} value={run.run_id}>{run.case_id} · v{run.case_version} · {shortId(run.run_id)} · {run.status}</option>)}</select></label> : <p className="empty-inline">尚无运行。打开一个病例，选择触发事件后启动 MDT。</p>}</section>
    {selected && <LiveAgents key={selected} id={selected} />}
  </div>;
}
function LiveAgents({ id }: { id: string }) {
  const query = useResearchRun(id); const stream = useResearchStream(id);
  const run = query.data; const [evidence, setEvidence] = useState<Evidence>();
  const source = useQuery({ queryKey: ['research-case', run?.case_id, run?.case_version], queryFn: () => researchApi.case(run!.case_id, run!.case_version), enabled: !!run });
  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} />;
  const trigger = source.data?.timeline.find(event => event.event_id === run!.trigger_event_id);
  const frozen = source.data && trigger ? { ...source.data, unplaced_records: [], timeline: source.data.timeline.filter(event => event.occurred_at < trigger.occurred_at || (event.occurred_at === trigger.occurred_at && event.event_id <= trigger.event_id)) } : undefined;
  return <div className="research-stack recent-section"><div className="section-heading"><Status status={run!.status} /><Link className="button secondary" to={`/research/runs/${id}`}>打开完整协作运行 <Icon name="arrow" size={15} /></Link></div><InlineError error={source.error} />{frozen && <DataPath item={frozen} run={run!} />}<WorkflowPanel run={run!} /><AgentCards run={run!} onEvidence={setEvidence} /><AuditPanel events={stream.events} runId={id} connection={stream.connection} reconnect={stream.reconnect} />{run!.report_ready && <Link className="button primary" to={`/research/runs/${id}/report`}>查看报告与证据</Link>}{evidence && <EvidenceDialog evidence={evidence} researchCase={frozen} onClose={() => setEvidence(undefined)} />}</div>;
}
