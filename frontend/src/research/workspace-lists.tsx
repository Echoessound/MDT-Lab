import { Link, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ErrorState, Icon, Loading, Status, dateTime, shortId } from '../ui';
import { researchApi } from './api';
import { InlineError, eventNames } from './components';
import { terminal } from './realtime';
import type { ResearchCase, Run } from './schemas';
import { PageLinks, pageSlice, useWorkspaceParams } from './workspace-controls';

const kindLabels = { synthetic: '合成', public_research: '公开研究', mixed: '混合来源' };
const modeLabel = (run: Run) => run.mode === 'llm' ? 'LLM' : 'Mock';
const casePath = (id: string) => `/research/cases/${encodeURIComponent(id)}`;
const runPath = (id: string) => `/research/runs/${encodeURIComponent(id)}`;

function RegistryRows({ items }: { items: ResearchCase[] }) {
  const { search } = useLocation();
  return <div className="workspace-table-scroll"><table className="workspace-table case-register">
    <caption className="sr-only">病例目录</caption>
    <thead><tr><th scope="col">病例名称 / 编号</th><th scope="col">来源类型</th><th scope="col">版本</th><th scope="col">病程事件</th><th scope="col">末次事件</th></tr></thead>
    <tbody>{items.map(item => {
      const last = item.timeline.at(-1);
      return <tr key={item.case_id}>
        <td><Link className="workspace-row-title" to={casePath(item.case_id)} state={{ librarySearch: search }}>{item.title}</Link><code>{item.case_id}</code></td>
        <td><span className={`workspace-type kind-${item.case_kind}`}>{kindLabels[item.case_kind]}</span></td>
        <td><span className="workspace-version">v{item.version}</span></td><td className="workspace-number">{item.timeline.length}</td>
        <td>{last ? <><time dateTime={last.occurred_at}>{last.occurred_at}</time><small>{eventNames[last.event_type]}</small></> : '—'}</td>
      </tr>;
    })}</tbody>
  </table></div>;
}

function RecentRuns() {
  const runs = useQuery({ queryKey: ['research-runs'], queryFn: researchApi.runs, refetchInterval: 5000 });
  return <section className="panel workspace-recent" aria-labelledby="recent-runs-title">
    <div className="workspace-section-heading"><h2 id="recent-runs-title">最近运行</h2><Link className="text-link" to="/research/runs">全部记录 <Icon name="arrow" size={14} /></Link></div>
    {runs.isPending ? <Loading /> : runs.isError ? <InlineError error={runs.error} /> : runs.data.length === 0 ?
      <p className="workspace-empty">暂无运行记录</p> : <ul className="workspace-recent-list">
        {runs.data.slice(0, 4).map(run => <li key={run.run_id}>
          <Link to={runPath(run.run_id)} aria-label={`打开运行 ${shortId(run.run_id)}，病例 ${run.case_id}`}>
            <div><code>{shortId(run.run_id)}</code><Status status={run.status} /></div>
            <strong>{run.case_id}</strong><small>{dateTime(run.created_at)} · v{run.case_version} · {modeLabel(run)}</small>
          </Link>
        </li>)}
      </ul>}
  </section>;
}

export function ResearchHome() {
  const cases = useQuery({ queryKey: ['research-cases'], queryFn: researchApi.cases });
  const { params, update } = useWorkspaceParams();
  const keyword = params.get('q') ?? '';
  const queryText = keyword.trim().toLowerCase();
  const kind = params.get('kind') ?? '';
  const sort = params.get('sort') ?? '';
  if (cases.isPending) return <Loading />;
  if (cases.isError) return <ErrorState error={cases.error} retry={() => void cases.refetch()} />;
  const matches = cases.data.filter(item => (!kind || item.case_kind === kind) && (!queryText || [item.case_id, item.title, item.disease, ...item.provenance.map(source => source.source_name)].some(value => value.toLowerCase().includes(queryText))));
  if (sort === 'latest') matches.sort((a, b) => (b.timeline.at(-1)?.occurred_at ?? '').localeCompare(a.timeline.at(-1)?.occurred_at ?? '') || a.case_id.localeCompare(b.case_id));
  if (sort === 'events') matches.sort((a, b) => b.timeline.length - a.timeline.length || a.case_id.localeCompare(b.case_id));
  const page = pageSlice(matches, Number(params.get('page')));
  const filtered = Boolean(kind || keyword);
  function reset() { update({ q: '', kind: '', page: '' }); }
  return <div className="page-enter research-page workspace-page">
    <header className="workspace-heading"><div><h1>病例工作台</h1><p>{cases.data.length} 份病例 · {cases.data.reduce((count, item) => count + item.timeline.length, 0).toLocaleString()} 条病程事件</p></div>
      <Link className="button primary" to="/research/datasets"><Icon name="download" size={16} />导入病例</Link>
    </header>
    <div className="workspace-library-layout"><section className="panel workspace-registry" aria-labelledby="registry-title">
      <div className="workspace-section-heading"><h2 id="registry-title">病例目录</h2><button type="button" className="workspace-tool" disabled={cases.isFetching} onClick={() => void cases.refetch()}><Icon name="history" size={14} />{cases.isFetching ? '刷新中' : '刷新'}</button></div>
      <div className="workspace-toolbar">
        <label className="workspace-search"><span className="sr-only">查找病例</span><input type="search" value={keyword} onChange={event => update({ q: event.target.value, page: '' })} placeholder="搜索名称、编号或数据来源" /></label>
        <select aria-label="病例来源类型" value={kind} onChange={event => update({ kind: event.target.value, page: '' })}><option value="">全部类型</option>{Object.entries(kindLabels).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select>
        <select aria-label="病例排序" value={sort} onChange={event => update({ sort: event.target.value, page: '' })}><option value="">按编号</option><option value="latest">按末次事件</option><option value="events">按事件数量</option></select>
      </div>
      {matches.length ? <RegistryRows items={page.rows} /> : <div className="workspace-empty"><p>{filtered ? '没有符合条件的病例' : '病例库为空'}</p>{filtered ? <button className="text-link" onClick={reset}>清除筛选</button> : <Link className="text-link" to="/research/datasets">导入病例</Link>}</div>}
      <footer className="workspace-list-footer"><span aria-live="polite">{matches.length ? `显示 ${page.first}–${page.last} / ${matches.length} 份病例` : '0 份病例'}</span>{filtered && matches.length > 0 && <button className="text-link" onClick={reset}>清除筛选</button>}<PageLinks {...page} onPage={next => update({ page: String(next) })} /></footer>
    </section><RecentRuns /></div>
  </div>;
}

const stateFilters = { '': '全部状态', active: '进行中', completed: '已完成', incomplete: '部分失败', failed: '失败', cancelled: '已停止' };

export function ResearchHistoryPage() {
  const { search: historySearch } = useLocation();
  const query = useQuery({ queryKey: ['research-runs'], queryFn: researchApi.runs, refetchInterval: 4000 });
  const { params, update } = useWorkspaceParams();
  const keyword = params.get('q') ?? '';
  const status = params.get('status') ?? '';
  const mode = params.get('mode') ?? '';
  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} retry={() => void query.refetch()} />;
  const search = keyword.trim().toLowerCase();
  const matches = query.data.filter(run => {
    const inState = !status || (status === 'active' ? !terminal(run.status) : run.status === status);
    return inState && (!mode || mode === run.mode) && (!search || [run.case_id, run.run_id, run.trigger_event_id].some(value => value.toLowerCase().includes(search)));
  });
  const page = pageSlice(matches, Number(params.get('page')));
  return <div className="page-enter research-page workspace-page">
    <header className="workspace-heading"><div><h1>运行记录</h1><p>最近 {query.data.length} 次运行 · {query.data.filter(run => !terminal(run.status)).length} 次进行中</p></div><Link className="button primary" to="/">选择病例运行 <Icon name="arrow" size={15} /></Link></header>
    <section className="panel workspace-registry" aria-label="运行队列"><div className="workspace-toolbar">
      <label className="workspace-search"><span className="sr-only">查找运行</span><input type="search" placeholder="搜索运行、病例或触发事件编号" value={keyword} onChange={event => update({ q: event.target.value, page: '' })} /></label>
      <select aria-label="运行状态" value={status} onChange={event => update({ status: event.target.value, page: '' })}>{Object.entries(stateFilters).map(([value, name]) => <option value={value} key={value}>{name}</option>)}</select>
      <select aria-label="运行模式" value={mode} onChange={event => update({ mode: event.target.value, page: '' })}><option value="">全部模式</option><option value="mock">Mock</option><option value="llm">LLM</option></select>
    </div>
    {matches.length ? <div className="workspace-table-scroll"><table className="workspace-table runs-register"><caption className="sr-only">运行结果</caption><thead><tr><th>运行 / 病例</th><th>触发事件</th><th>模式</th><th>状态</th><th>创建时间</th><th>报告</th></tr></thead><tbody>
      {page.rows.map(run => <tr key={run.run_id}><td><Link className="workspace-row-title" state={{ historySearch }} to={runPath(run.run_id)}>{shortId(run.run_id)}</Link><code>{run.case_id} · v{run.case_version}</code></td><td><code>{run.trigger_event_id}</code></td><td>{modeLabel(run)}<small>{run.routing_mode === 'event' ? '按事件' : '固定全员'}</small></td><td><Status status={run.status} /></td><td><time dateTime={run.created_at}>{dateTime(run.created_at)}</time></td><td>{run.report_ready ? <Link to={`${runPath(run.run_id)}/report`} state={{ historySearch }} className="text-link">查看报告</Link> : '—'}</td></tr>)}
    </tbody></table></div> : <div className="workspace-empty"><p>{query.data.length ? '没有符合条件的运行' : '暂无运行记录'}</p></div>}
    <footer className="workspace-list-footer"><span aria-live="polite">{matches.length} 次运行</span>{(keyword || status || mode) && <button className="text-link" onClick={() => update({ status: '', q: '', mode: '', page: '' })}>清除筛选</button>}<PageLinks {...page} onPage={next => update({ page: String(next) })} /></footer></section>
  </div>;
}
