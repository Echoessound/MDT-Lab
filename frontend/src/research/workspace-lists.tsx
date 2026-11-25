import { Link, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { DecisionBadge, ErrorState, Icon, Loading, Status, dateTime, shortId } from '../ui';
import { researchApi } from './api';
import { InlineError, sexName, stageNames } from './components';
import { researchKeys } from './query-keys';
import { terminal } from './realtime';
import type { ResearchCase, Run } from './schemas';
import { PageLinks, pageSlice, useWorkspaceParams } from './workspace-controls';
import { caseBaselineHint, clinicalCaseTitle, modeNameZh, routingModeNameZh } from './zh-dict';

const kindLabels = { synthetic: '合成场景', public_research: '公开队列', mixed: '混合扩展' };
const modeLabel = (run: Run) => modeNameZh(run.mode);
const casePath = (id: string) => `/research/cases/${encodeURIComponent(id)}`;
const runPath = (id: string) => `/research/runs/${encodeURIComponent(id)}`;

function RegistryRows({ items, runs }: { items: ResearchCase[]; runs: Run[] }) {
  const { search } = useLocation();
  return <div className="workspace-table-scroll"><table className="workspace-table case-register">
    <caption className="sr-only">病例目录</caption>
    <thead><tr><th scope="col">病例编号 / 临床摘要</th><th scope="col">来源与版本</th><th scope="col">病程记录</th><th scope="col">工作流进度</th><th scope="col">操作</th></tr></thead>
    <tbody>{items.map(item => {
      const last = item.timeline.at(-1);
      const caseRuns = runs.filter(r => r.case_id === item.case_id);
      const activeRun = caseRuns.find(r => !terminal(r.status));
      const latestRun = caseRuns[0];
      return <tr key={item.case_id}>
        <td>
          <Link className="case-id-title" to={casePath(item.case_id)} state={{ librarySearch: search }}>{item.case_id}</Link>
          <span className="case-clinical-name">{clinicalCaseTitle(item)}</span>
          <small>{sexName(item.patient.sex)} · {item.patient.age} 岁 · {item.disease}</small>
        </td>
        <td>
          <span className={`workspace-type kind-${item.case_kind}`}>{kindLabels[item.case_kind]}</span>
          <small className="workspace-version">v{item.version}</small>
        </td>
        <td>
          <span className="workspace-number">{item.timeline.length} 条</span>
          <small>{last ? `最新 ${last.occurred_at} (${last.event_id})` : '—'}</small>
        </td>
        <td>
          {activeRun ? (
            <div className="case-progress-cell">
              <Status status={activeRun.status} />
              <small>
                <Link className="text-link" to={runPath(activeRun.run_id)}>
                  {stageNames[activeRun.stage] ?? activeRun.stage} · 截点 {activeRun.trigger_event_id}
                </Link>
              </small>
            </div>
          ) : latestRun ? (
            <div className="case-progress-cell">
              {latestRun.safety ? <DecisionBadge decision={latestRun.safety.decision} /> : <Status status={latestRun.status} />}
              <small>
                <Link className="text-link" to={latestRun.report_ready ? `${runPath(latestRun.run_id)}/report` : runPath(latestRun.run_id)}>
                  截点 {latestRun.trigger_event_id} · 共 {caseRuns.length} 次运行
                </Link>
              </small>
            </div>
          ) : (
            <div className="case-progress-cell">
              <span className="pill outline">未运行</span>
              <small>{caseBaselineHint(item)}</small>
            </div>
          )}
        </td>
        <td>
          <div className="table-quick-links">
            <Link className="text-link" to={casePath(item.case_id)} state={{ librarySearch: search }}>审阅</Link>
            <Link className="text-link" to={`${casePath(item.case_id)}?view=workflow`} state={{ librarySearch: search }}>流程</Link>
            {last && (
              <Link
                className="text-link"
                to={`/research/experiments?view=annotate&scenario=${encodeURIComponent(`${item.case_id}:v${item.version}:${last.event_id}`)}`}
              >
                盲标
              </Link>
            )}
          </div>
        </td>
      </tr>;
    })}</tbody>
  </table></div>;
}

function RecentRuns() {
  const runs = useQuery({ queryKey: researchKeys.runs, queryFn: researchApi.runs, refetchInterval: 5000 });
  return <section className="panel workspace-recent" aria-labelledby="recent-runs-title">
    <div className="workspace-section-heading"><h2 id="recent-runs-title">最近协同运行</h2><Link className="text-link" to="/research/runs">全部记录 <Icon name="arrow" size={14} /></Link></div>
    {runs.isPending ? <Loading /> : runs.isError ? <InlineError error={runs.error} /> : runs.data.length === 0 ?
      <p className="workspace-empty">暂无协同运行记录</p> : <ul className="workspace-recent-list">
        {runs.data.slice(0, 4).map(run => <li key={run.run_id}>
          <Link to={runPath(run.run_id)} aria-label={`打开运行 ${shortId(run.run_id)}，病例 ${run.case_id}`}>
            <div><code>#{shortId(run.run_id)}</code><Status status={run.status} /></div>
            <strong>{run.case_id}</strong><small>{dateTime(run.created_at)} · v{run.case_version} · {modeLabel(run)}</small>
          </Link>
        </li>)}
      </ul>}
  </section>;
}

export function ResearchHome() {
  const cases = useQuery({ queryKey: researchKeys.cases, queryFn: researchApi.cases });
  const runs = useQuery({ queryKey: researchKeys.runs, queryFn: researchApi.runs, refetchInterval: 5000 });
  const { params, update } = useWorkspaceParams();
  const keyword = params.get('q') ?? '';
  const queryText = keyword.trim().toLowerCase();
  const kind = params.get('kind') ?? '';
  const sort = params.get('sort') ?? '';
  if (cases.isPending) return <Loading />;
  if (cases.isError) return <ErrorState error={cases.error} retry={() => void cases.refetch()} />;
  const matches = cases.data.filter(item => (!kind || item.case_kind === kind) && (!queryText || [item.case_id, item.title, clinicalCaseTitle(item), item.disease, ...item.provenance.map(source => source.source_name)].some(value => value.toLowerCase().includes(queryText))));
  if (sort === 'latest') matches.sort((a, b) => (b.timeline.at(-1)?.occurred_at ?? '').localeCompare(a.timeline.at(-1)?.occurred_at ?? '') || a.case_id.localeCompare(b.case_id));
  if (sort === 'events') matches.sort((a, b) => b.timeline.length - a.timeline.length || a.case_id.localeCompare(b.case_id));
  const page = pageSlice(matches, Number(params.get('page')));
  const filtered = Boolean(kind || keyword);
  function reset() { update({ q: '', kind: '', page: '' }); }
  const activeRuns = runs.data?.filter(r => !terminal(r.status)).length ?? 0;
  const totalRuns = runs.data?.length ?? 0;

  return <div className="page-enter research-page workspace-page">
    <header className="workspace-heading">
      <div>
        <h1>病例工作台</h1>
        <p>共 {cases.data.length} 份病例 · {activeRuns > 0 ? `${activeRuns} 项运行中` : `累计 ${totalRuns} 次运行`} · <Link className="text-link" to="/roadmap">使用说明</Link></p>
      </div>
      <div className="button-group">
        <Link className="button secondary" to="/research/experiments"><Icon name="route" size={16} />实验与盲标</Link>
        <Link className="button primary" to="/research/datasets"><Icon name="download" size={16} />导入病例</Link>
      </div>
    </header>
    <div className="workspace-library-layout"><section className="panel workspace-registry" aria-labelledby="registry-title">
      <div className="workspace-section-heading"><h2 id="registry-title">纵向病例名录</h2><button type="button" className="workspace-tool" disabled={cases.isFetching} onClick={() => void cases.refetch()}><Icon name="refresh" size={14} />{cases.isFetching ? '刷新中…' : '刷新'}</button></div>
      <div className="workspace-toolbar">
        <label className="workspace-search"><span className="sr-only">查找病例</span><input type="search" value={keyword} onChange={event => update({ q: event.target.value, page: '' })} placeholder="搜索病例编号、临床名称、病种或数据来源…" /></label>
        <select aria-label="病例来源类型" value={kind} onChange={event => update({ kind: event.target.value, page: '' })}><option value="">全部来源类型</option>{Object.entries(kindLabels).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select>
        <select aria-label="病例排序" value={sort} onChange={event => update({ sort: event.target.value, page: '' })}><option value="">按病例编号排序</option><option value="latest">按最新事件日期</option><option value="events">按病程事件数量</option></select>
      </div>
      {matches.length ? <RegistryRows items={page.rows} runs={runs.data ?? []} /> : <div className="workspace-empty"><p>{filtered ? '没有符合筛选条件的病例' : '病例库为空'}</p>{filtered ? <button className="text-link" onClick={reset}>重置筛选条件</button> : <Link className="text-link" to="/research/datasets">前往导入病例</Link>}</div>}
      <footer className="workspace-list-footer"><span aria-live="polite">{matches.length ? `显示第 ${page.first}–${page.last} 份 / 共 ${matches.length} 份病例` : '0 份病例'}</span>{filtered && matches.length > 0 && <button className="text-link" onClick={reset}>重置筛选</button>}<PageLinks {...page} onPage={next => update({ page: String(next) })} /></footer>
    </section><RecentRuns /></div>
  </div>;
}

const stateFilters = { '': '全部运行状态', active: '进行中', completed: '已完成', incomplete: '部分异常', failed: '执行失败', cancelled: '已停止' };

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
    <header className="workspace-heading"><div><h1>协同运行历史记录</h1><p>最近 {query.data.length} 次运行 · {query.data.filter(run => !terminal(run.status)).length} 次正在执行</p></div><Link className="button primary" to="/">选择病例发起运行 <Icon name="arrow" size={15} /></Link></header>
    <section className="panel workspace-registry" aria-label="运行队列"><div className="workspace-toolbar">
      <label className="workspace-search"><span className="sr-only">查找运行</span><input type="search" placeholder="搜索运行编号、病例编号或触发事件编号…" value={keyword} onChange={event => update({ q: event.target.value, page: '' })} /></label>
      <select aria-label="运行状态" value={status} onChange={event => update({ status: event.target.value, page: '' })}>{Object.entries(stateFilters).map(([value, name]) => <option value={value} key={value}>{name}</option>)}</select>
      <select aria-label="运行模式" value={mode} onChange={event => update({ mode: event.target.value, page: '' })}><option value="">全部执行模式</option><option value="mock">本地规则仿真</option><option value="llm">大模型智能推演</option></select>
    </div>
    {matches.length ? <div className="workspace-table-scroll"><table className="workspace-table runs-register"><caption className="sr-only">运行结果</caption><thead><tr><th>运行编号 / 关联病例</th><th>锁定触发截点</th><th>执行模式与路由</th><th>运行状态</th><th>创建时间</th><th>操作与报告</th></tr></thead><tbody>
      {page.rows.map(run => <tr key={run.run_id}>
        <td><Link className="workspace-row-title" state={{ historySearch }} to={runPath(run.run_id)}>#{shortId(run.run_id)}</Link><code>{run.case_id} · v{run.case_version}</code></td>
        <td><code>{run.trigger_event_id}</code></td>
        <td>{modeLabel(run)}<small>{routingModeNameZh(run.routing_mode)}</small></td>
        <td><Status status={run.status} /></td>
        <td><time dateTime={run.created_at}>{dateTime(run.created_at)}</time></td>
        <td>
          <div className="table-quick-links">
            <Link to={runPath(run.run_id)} state={{ historySearch }} className="text-link">运行详情</Link>
            {run.report_ready && <Link to={`${runPath(run.run_id)}/report`} state={{ historySearch }} className="text-link">评议报告</Link>}
          </div>
        </td>
      </tr>)}
    </tbody></table></div> : <div className="workspace-empty"><p>{query.data.length ? '没有符合筛选条件的运行记录' : '暂无协同运行记录'}</p></div>}
    <footer className="workspace-list-footer"><span aria-live="polite">共 {matches.length} 次运行</span>{(keyword || status || mode) && <button className="text-link" onClick={() => update({ status: '', q: '', mode: '', page: '' })}>重置筛选</button>}<PageLinks {...page} onPage={next => update({ page: String(next) })} /></footer></section>
  </div>;
}
