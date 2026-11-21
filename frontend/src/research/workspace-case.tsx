import { useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorState, Icon, Loading } from '../ui';
import { researchApi } from './api';
import { CaseSources, caseKindName } from './data-components';
import { InlineError, RoutingPanel, eventNames, roleNames, scenarioNames, sexName } from './components';
import { selectedModelsReady } from './model-settings';
import { factsSchema, type EventType, type ResearchCase, type RunRequest } from './schemas';
import { WorkspaceViews, currentView, useWorkspaceParams } from './workspace-controls';
import { WorkspaceEvents } from './workspace-events';

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
  return <section className="panel append-event"><div className="section-heading"><div><h2>添加病程事件</h2></div><span className="pill outline">v{item.version} → v{item.version + 1}</span></div><p className="muted">仅填写虚构研究资料，保存后将创建新的病例版本。</p><form className="research-form" onSubmit={event => { event.preventDefault(); save.mutate(); }}><label>事件模板<select value={template} onChange={event => { const value = templates[event.target.value]; setTemplate(event.target.value); setType(value.type); setTitle(value.title); setFacts(JSON.stringify(value.facts, null, 2)); }}>{Object.entries(templates).map(([key, value]) => <option key={key} value={key}>{value.title}</option>)}</select></label><div className="research-form-row"><label>发生日期<input type="date" value={date} onChange={event => setDate(event.target.value)} required /></label><label>事件类型<select value={type} onChange={event => setType(event.target.value as EventType)}>{Object.entries(eventNames).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label></div><label>事件标题<input value={title} onChange={event => setTitle(event.target.value)} maxLength={200} required /></label><label>结构化事实 JSON<textarea rows={5} value={facts} onChange={event => setFacts(event.target.value)} spellCheck={false} /></label><InlineError error={save.error} /><button className="button primary" disabled={save.isPending}>{save.isPending ? '正在保存…' : '保存为新病例版本'}</button></form></section>;
}

const caseViews = [
  { key: 'timeline', label: '病程' }, { key: 'sources', label: '来源资料' }, { key: 'routing', label: '调度依据' },
] as const;

export function ResearchCasePage() {
  const { caseId = '' } = useParams();
  return <CaseWorkspace key={caseId} id={caseId} />;
}

function CaseWorkspace({ id }: { id: string }) {
  const { params, update } = useWorkspaceParams();
  const navigate = useNavigate();
  const location = useLocation();
  const client = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState('');
  const view = currentView(caseViews, params.get('view'));
  const requestedVersion = Number(params.get('version'));
  const version = Number.isSafeInteger(requestedVersion) && requestedVersion > 0 ? requestedVersion : undefined;
  const mode = params.get('mode') === 'llm' ? 'llm' : 'mock';
  const routingMode = params.get('routing') === 'fixed' ? 'fixed' : 'event';
  const requestedScenario = params.get('scenario') ?? '';
  const scenario: RunRequest['mock_scenario'] = mode === 'mock' && Object.hasOwn(scenarioNames, requestedScenario) ? requestedScenario as RunRequest['mock_scenario'] : 'standard';
  const latest = useQuery({ queryKey: ['research-case', id, 'latest'], queryFn: () => researchApi.case(id) });
  const query = useQuery({ queryKey: ['research-case', id, version ?? 'latest'], queryFn: () => researchApi.case(id, version) });
  const models = useQuery({ queryKey: ['research-agent-models'], queryFn: researchApi.agentModels });
  const item = query.data;
  const requestedTrigger = params.get('trigger');
  const trigger = requestedTrigger ? item?.timeline.find(event => event.event_id === requestedTrigger) : item?.timeline.at(-1);
  const routing = useQuery({
    queryKey: ['research-routing', id, item?.version, trigger?.event_id, routingMode],
    queryFn: () => researchApi.routing(id, item!.version, trigger!.event_id, routingMode), enabled: !!item && !!trigger,
  });
  const start = useMutation({
    mutationFn: () => researchApi.start({ case_id: id, case_version: item!.version, trigger_event_id: trigger!.event_id, mode, mock_scenario: scenario, routing_mode: routingMode }),
    onSuccess: run => navigate(`/research/runs/${encodeURIComponent(run.run_id)}`),
  });
  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} retry={() => void query.refetch()} />;
  if (!item) return null;
  if (!trigger || (params.has('version') && !version)) return <section className="panel workspace-column">
    <h1>病例链接无效</h1>
    <p role="alert">{!version && params.has('version') ? '版本号须为正整数。' : `v${item.version} 中找不到触发事件 ${requestedTrigger ?? ''}。`}</p>
    <button type="button" className="button secondary" onClick={() => update({ version: version ? String(version) : '', trigger: '', view: '' })}>打开病程并选择事件</button>
  </section>;
  const modelsReady = selectedModelsReady(routing.data?.selected_agents, models.data);
  const current = item.version === latest.data?.version;
  const scenarioBlocked = scenario === 'persistent_disagreement' && !!routing.data && routing.data.selected_agents.length < 2;
  const canStart = !start.isPending && !!routing.data && !scenarioBlocked && (mode === 'mock' || modelsReady);
  const librarySearch = typeof location.state?.librarySearch === 'string' && location.state.librarySearch.startsWith('?') ? location.state.librarySearch : '';
  function onSaved(saved: ResearchCase) {
    client.setQueryData(['research-case', id, 'latest'], saved);
    void client.invalidateQueries({ queryKey: ['research-cases'] });
    update({ version: '', view: '', trigger: saved.timeline.find(event => event.introduced_in_version === saved.version)?.event_id ?? '' });
    setAdding(false);
    setNotice(`已保存 v${saved.version}，新事件已设为触发事件。`);
  }
  return <div className="page-enter research-page workspace-page">
    <Link to={`/${librarySearch}`} className="back-link"><Icon name="back" size={14} />病例目录</Link>
    <header className="workspace-heading"><div><h1>{item.title}</h1><p><code>{id}</code> · {sexName(item.patient.sex)} · {item.patient.age} 岁 · {caseKindName[item.case_kind]}</p></div>
      <button type="button" className="button secondary" disabled={!current} onClick={() => setAdding(value => !value)}>{adding ? '关闭新增表单' : '添加病程事件'}</button></header>
    {notice && <p className="notice neutral" role="status">{notice}</p>}
    {adding && current && <AddEvent key={item.version} item={item} onSaved={onSaved} />}
    <div className="workspace-case-layout"><div className="workspace-column">
      <section className="panel workspace-case-brief"><div><h2>审阅问题</h2><p>{item.current_question || '尚未记录'}</p></div>
        <label className="workspace-version-select">病例版本<select value={item.version} onChange={event => { const v = Number(event.target.value); update({ version: v === latest.data?.version ? '' : String(v), trigger: '' }); setAdding(false); setNotice(''); }}>
          {Array.from({ length: latest.data?.version ?? item.version }, (_, index) => index + 1).reverse().map(v => <option key={v} value={v}>v{v}{v === latest.data?.version ? ' · 最新' : ' · 历史'}</option>)}
        </select></label>
      </section>
      <WorkspaceViews label="病例视图" tabs={caseViews} value={view} onChange={v => update({ view: v === 'timeline' ? '' : v })} />
      <div id="workspace-panel" role="tabpanel" aria-labelledby={`workspace-tab-${view}`} tabIndex={0}>
        {view === 'timeline' && <WorkspaceEvents key={item.version} events={item.timeline} trigger={trigger.event_id} onTrigger={eventId => update({ trigger: eventId })} />}
        {view === 'sources' && <CaseSources item={item} />}
        {view === 'routing' && (routing.isPending ? <Loading /> : routing.isError ? <InlineError error={routing.error} /> : <RoutingPanel routing={routing.data} />)}
      </div>
    </div><aside className="panel workspace-launch"><h2>新建运行</h2>
      <form className="research-form" onSubmit={event => { event.preventDefault(); if (canStart) start.mutate(); }}>
        <div className="workspace-trigger"><span>触发事件</span><strong>{trigger.title}</strong><small>{trigger.occurred_at} · {trigger.event_id}</small>
          {view !== 'timeline' && <button type="button" className="text-link" onClick={() => update({ view: '' })}>更改事件</button>}</div>
        <label>专科调度<select value={routingMode} onChange={event => update({ routing: event.target.value === 'fixed' ? 'fixed' : '' })}><option value="event">按触发事件</option><option value="fixed">固定全员</option></select></label>
        <div className="workspace-routing"><span>参与专科</span>{routing.data ? <div>{routing.data.selected_agents.map(role => <span key={role}>{roleNames[role]}</span>)}</div> : <p>{routing.isError ? '读取失败' : '正在读取…'}</p>}</div>
        <label>运行模式<select value={mode} onChange={event => update({ mode: event.target.value === 'llm' ? 'llm' : '', scenario: '' })}><option value="mock">本地规则（Mock）</option><option value="llm" disabled={!modelsReady}>模型服务（LLM）{modelsReady ? '' : ' · 未配齐'}</option></select></label>
        {mode === 'mock' && <details className="workspace-advanced" open={scenario !== 'standard' || undefined}><summary>规则场景{scenario !== 'standard' ? ` · ${scenarioNames[scenario]}` : ''}</summary><label className="sr-only" htmlFor="case-scenario">规则场景</label><select id="case-scenario" value={scenario} onChange={event => update({ scenario: event.target.value === 'standard' ? '' : event.target.value })}>{Object.entries(scenarioNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></details>}
        {scenarioBlocked && <p className="inline-error">保留分歧至少需要两名专科。请选择固定全员或更换规则场景。</p>}
        <InlineError error={routing.error || models.error || start.error} />
        <p className="workspace-boundary">运行将使用 v{item.version} 中截至所选事件的资料。</p>
        <button className="button primary full" disabled={!canStart}><Icon name="play" size={15} />{start.isPending ? '正在创建…' : '启动运行'}</button>
        <Link className="text-link" to="/settings/models">模型连接设置 <Icon name="arrow" size={13} /></Link>
      </form>
    </aside></div>
  </div>;
}
