import { useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorState, Icon, Loading } from '../ui';
import { researchApi } from './api';
import { CaseSources, caseKindName } from './data-components';
import { InlineError, RoutingPanel, eventNames, roleNames, scenarioNames, sexName } from './components';
import { selectedModelsReady } from './model-settings';
import { researchKeys } from './query-keys';
import { factsSchema, type EventType, type ResearchCase, type RunRequest } from './schemas';
import { TabPanelTransition, WorkspaceViews, currentView, useWorkspaceParams } from './workspace-controls';
import { WorkspaceEvents } from './workspace-events';
import { CaseWorkflowAndImagingSection } from './workflow-visualizer';
import { factKeyLabel } from './zh-dict';

const templates: Record<string, { type: EventType; title: string; facts: Record<string, boolean | string> }> = {
  pathology: { type: 'pathology', title: '补充组织病理学确诊记录（合成）', facts: { pathology_confirmed: true, histology: '肺腺癌', pathology_record: '本地人工合成病理确诊补充记录' } },
  imaging: { type: 'imaging', title: '补充胸部增强 CT 影像归档（合成）', facts: { imaging_complete: true, modality: 'CT', imaging_record: '胸部 CT 断层序列与报告已完整归档' } },
  molecular: { type: 'molecular_test', title: '补充驱动基因分子检测报告（合成）', facts: { molecular_complete: true, egfr_status: '突变阳性', molecular_record: 'NGS 分子检测报告已归档' } },
  follow_up: { type: 'follow_up', title: '新增纵向随访评估记录（合成）', facts: { follow_up_complete: true, follow_up_record: '随访期临床与影像评估资料齐备' } },
  progression: { type: 'progression', title: '新增疾病进展多科复核事件（合成）', facts: { progression_confirmed: true, imaging_complete: true, pathology_confirmed: true } },
};

const QUICK_BOOLEAN_KEYS = [
  'pathology_confirmed',
  'imaging_complete',
  'molecular_complete',
  'follow_up_complete',
  'progression_confirmed',
  'procedure_record_complete',
  'treatment_record_complete',
] as const;

function AddEvent({ item, onSaved }: { item: ResearchCase; onSaved: (value: ResearchCase) => void }) {
  const [template, setTemplate] = useState('pathology');
  const [title, setTitle] = useState(templates.pathology.title);
  const [type, setType] = useState<EventType>('pathology');
  const [facts, setFacts] = useState(JSON.stringify(templates.pathology.facts, null, 2));
  const [noteText, setNoteText] = useState('本地人工合成病理确诊补充记录');
  const nextDate = new Date(`${item.timeline.at(-1)!.occurred_at}T12:00:00Z`);
  nextDate.setUTCDate(nextDate.getUTCDate() + 1);
  const [date, setDate] = useState(nextDate.toISOString().slice(0, 10));

  function parseFactsObj(): Record<string, unknown> {
    try {
      const obj = JSON.parse(facts);
      return obj && typeof obj === 'object' && !Array.isArray(obj) ? obj : {};
    } catch {
      return {};
    }
  }

  function toggleFactFlag(key: string, checked: boolean) {
    const current = parseFactsObj();
    if (checked) current[key] = true;
    else delete current[key];
    setFacts(JSON.stringify(current, null, 2));
  }

  function updateNote(text: string) {
    setNoteText(text);
    const current = parseFactsObj();
    if (text.trim()) current.record_note = text.trim();
    else delete current.record_note;
    setFacts(JSON.stringify(current, null, 2));
  }

  const currentObj = parseFactsObj();

  const save = useMutation({
    mutationFn: () => {
      let parsed: unknown;
      try { parsed = JSON.parse(facts); } catch { throw new Error('事实字段格式有误，请检查结构化字段。'); }
      const checked = factsSchema.safeParse(parsed);
      if (!checked.success || !Object.keys(checked.data).length) {
        throw new Error('请至少勾选或填写一项临床事实指标。');
      }
      return researchApi.append(item.case_id, item.version, { occurred_at: date, event_type: type, title, facts: checked.data });
    },
    onSuccess: onSaved,
  });

  return (
    <section className="panel append-event tab-slide-right">
      <div className="section-heading">
        <div>
          <h2>追加合成病程事件</h2>
          <p className="muted">保存后将生成新版本 v{item.version + 1}，既有历史版本 v{item.version} 与报告保持不可变。</p>
        </div>
        <span className="pill outline">版本演进 v{item.version} → v{item.version + 1}</span>
      </div>
      <form className="research-form" onSubmit={event => { event.preventDefault(); save.mutate(); }}>
        <div className="research-form-row">
          <label>
            预设临床事件模板
            <select value={template} onChange={event => {
              const key = event.target.value;
              const value = templates[key];
              setTemplate(key);
              setType(value.type);
              setTitle(value.title);
              setFacts(JSON.stringify(value.facts, null, 2));
            }}>
              {Object.entries(templates).map(([key, value]) => <option key={key} value={key}>{value.title}</option>)}
            </select>
          </label>
          <label>
            事件分类
            <select value={type} onChange={event => setType(event.target.value as EventType)}>
              {Object.entries(eventNames).map(([value, name]) => <option key={value} value={value}>{name}</option>)}
            </select>
          </label>
        </div>

        <div className="research-form-row">
          <label>
            事件发生日期
            <input type="date" value={date} onChange={event => setDate(event.target.value)} required />
          </label>
          <label>
            事件标题说明
            <input value={title} onChange={event => setTitle(event.target.value)} maxLength={200} required />
          </label>
        </div>

        <div className="visual-facts-builder">
          <span className="builder-label">关键临床完备性指标（点击快速勾选）</span>
          <div className="fact-toggle-grid">
            {QUICK_BOOLEAN_KEYS.map(key => {
              const active = currentObj[key] === true;
              return (
                <label key={key} className={`fact-toggle-chip ${active ? 'is-active' : ''}`}>
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={e => toggleFactFlag(key, e.target.checked)}
                  />
                  <span>{factKeyLabel(key)}</span>
                </label>
              );
            })}
          </div>
          <label className="builder-note-input">
            补充临床记录摘要
            <input
              type="text"
              value={noteText}
              onChange={e => updateNote(e.target.value)}
              placeholder="输入补充的病理、影像或随访文字摘要…"
            />
          </label>
        </div>

        <details className="workspace-advanced">
          <summary>高级结构化键值编辑 (JSON)</summary>
          <label className="sr-only" htmlFor="raw-facts-json">结构化事实 JSON</label>
          <textarea id="raw-facts-json" rows={4} value={facts} onChange={event => setFacts(event.target.value)} spellCheck={false} />
        </details>

        <InlineError error={save.error} />
        <div className="button-group">
          <button type="submit" className="button primary" disabled={save.isPending}>
            <Icon name="check" size={15} />
            {save.isPending ? '正在写入新版本…' : `保存并生成 v${item.version + 1} 版本`}
          </button>
        </div>
      </form>
    </section>
  );
}

const caseViews = [
  { key: 'timeline', label: '病程时间线' },
  { key: 'workflow', label: '智能流程与影像' },
  { key: 'routing', label: '专科调度依据' },
  { key: 'sources', label: '数据来源与溯源' },
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
  const latest = useQuery({ queryKey: researchKeys.caseDetail(id, 'latest'), queryFn: () => researchApi.case(id) });
  const query = useQuery({ queryKey: researchKeys.caseDetail(id, version ?? 'latest'), queryFn: () => researchApi.case(id, version) });
  const models = useQuery({ queryKey: researchKeys.agentModels, queryFn: researchApi.agentModels });
  const item = query.data;
  const requestedTrigger = params.get('trigger');
  const trigger = requestedTrigger ? item?.timeline.find(event => event.event_id === requestedTrigger) : item?.timeline.at(-1);
  const routing = useQuery({
    queryKey: researchKeys.routing(id, item?.version, trigger?.event_id, routingMode),
    queryFn: () => researchApi.routing(id, item!.version, trigger!.event_id, routingMode),
    enabled: !!item && !!trigger,
  });
  const start = useMutation({
    mutationFn: (overrideTrigger?: string) => researchApi.start({
      case_id: id,
      case_version: item!.version,
      trigger_event_id: overrideTrigger ?? trigger!.event_id,
      mode,
      mock_scenario: scenario,
      routing_mode: routingMode,
    }),
    onSuccess: run => navigate(`/research/runs/${encodeURIComponent(run.run_id)}`),
  });

  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} retry={() => void query.refetch()} />;
  if (!item) return null;
  if (!trigger || (params.has('version') && !version)) return <section className="panel workspace-column">
    <h1>病例链接参数无效</h1>
    <p role="alert">{!version && params.has('version') ? '版本号须为正整数。' : `版本 v${item.version} 中找不到触发事件 ${requestedTrigger ?? ''}。`}</p>
    <button type="button" className="button secondary" onClick={() => update({ version: version ? String(version) : '', trigger: '', view: '' })}>重置并查看病程事件</button>
  </section>;

  const modelsReady = selectedModelsReady(routing.data?.selected_agents, models.data);
  const current = item.version === latest.data?.version;
  const scenarioBlocked = scenario === 'persistent_disagreement' && !!routing.data && routing.data.selected_agents.length < 2;
  const canStart = !start.isPending && !!routing.data && !scenarioBlocked && (mode === 'mock' || modelsReady);
  const librarySearch = typeof location.state?.librarySearch === 'string' && location.state.librarySearch.startsWith('?') ? location.state.librarySearch : '';

  function onSaved(saved: ResearchCase) {
    client.setQueryData(['research-case', id, 'latest'], saved);
    void client.invalidateQueries({ queryKey: ['research-cases'] });
    void client.invalidateQueries({ queryKey: ['research-workflow-plan', id] });
    void client.invalidateQueries({ queryKey: ['research-imaging', id] });
    void client.invalidateQueries({ queryKey: ['research-ablation', id] });
    const latestEvt = saved.timeline.find(event => event.introduced_in_version === saved.version)?.event_id ?? saved.timeline.at(-1)?.event_id ?? '';
    update({ version: '', trigger: latestEvt });
    setAdding(false);
    setNotice(`已生成新版本 v${saved.version}，并将新增事件（${latestEvt}）自动设为当前触发截点。`);
  }

  const tabsWithBadges = [
    { key: 'timeline' as const, label: '病程时间线', badge: item.timeline.length },
    { key: 'workflow' as const, label: '智能流程与影像', badge: '算法增强' },
    { key: 'routing' as const, label: '专科调度依据', badge: routing.data ? `${routing.data.selected_agents.length} 科` : undefined },
    { key: 'sources' as const, label: '数据来源与溯源', badge: item.unplaced_records.length ? `+${item.unplaced_records.length}` : undefined },
  ];

  return <div className="page-enter research-page workspace-page">
    <Link to={`/${librarySearch}`} className="back-link"><Icon name="back" size={14} />返回病例工作台</Link>
    <header className="workspace-heading">
      <div>
        <h1>{item.title}</h1>
        <p>
          编号 <code>{id}</code> · {sexName(item.patient.sex)} · {item.patient.age} 岁 · {item.disease} · <span className="pill soft">{caseKindName[item.case_kind]}</span>
        </p>
      </div>
      <div className="button-group">
        {view !== 'workflow' && (
          <button type="button" className="button secondary" onClick={() => update({ view: 'workflow' })}>
            <Icon name="route" size={15} />智能流程与影像分析
          </button>
        )}
        <button type="button" className="button secondary" disabled={!current} onClick={() => setAdding(value => !value)}>
          <Icon name={adding ? 'close' : 'file'} size={15} />
          {adding ? '收起追加表单' : '追加合成病程'}
        </button>
      </div>
    </header>
    {notice && <p className="notice neutral" role="status"><Icon name="check" size={16} /><span>{notice}</span></p>}
    {adding && current && <AddEvent key={item.version} item={item} onSaved={onSaved} />}

    <div className="workspace-case-layout">
      <div className="workspace-column">
        <section className="panel workspace-case-brief">
          <div>
            <h2>本次多学科审阅目标</h2>
            <p>{item.current_question || '截至所选病程截点，核对临床、影像与病理资料是否完整且内部一致。'}</p>
          </div>
          <label className="workspace-version-select">
            当前检视版本
            <select value={item.version} onChange={event => {
              const v = Number(event.target.value);
              update({ version: v === latest.data?.version ? '' : String(v), trigger: '' });
              setAdding(false);
              setNotice('');
            }}>
              {Array.from({ length: latest.data?.version ?? item.version }, (_, index) => index + 1).reverse().map(v => (
                <option key={v} value={v}>v{v}{v === latest.data?.version ? ' · 最新版本' : ' · 历史快照'}</option>
              ))}
            </select>
          </label>
        </section>

        {item.timeline.length <= 24 && (
          <section className="panel timeline-scrubber-panel" aria-label="纵向病程时间轴与冻结截点速览">
            <div className="scrubber-header">
              <span><strong>纵向病程时间轴滑轨</strong> · 点击任意节点即时移动历史冻结截点</span>
              <small>已纳入 {item.timeline.findIndex(e => e.event_id === trigger.event_id) + 1} / {item.timeline.length} 条事件</small>
            </div>
            <div className="timeline-scrubber-rail" role="group" aria-label="选择病程冻结截点">
              {item.timeline.map((ev, idx) => {
                const triggerIdx = item.timeline.findIndex(e => e.event_id === trigger.event_id);
                const state = idx === triggerIdx ? 'is-trigger' : idx < triggerIdx ? 'is-included' : 'is-future';
                return (
                  <button
                    key={ev.event_id}
                    type="button"
                    className={`scrubber-node ${state}`}
                    aria-pressed={idx === triggerIdx}
                    title={`${ev.occurred_at} · ${ev.title} (${eventNames[ev.event_type]})`}
                    onClick={() => update({ trigger: ev.event_id })}
                  >
                    <span className="scrubber-dot" />
                    <strong>{ev.event_id}</strong>
                    <small>{eventNames[ev.event_type]}</small>
                    <time>{ev.occurred_at.slice(5)}</time>
                  </button>
                );
              })}
            </div>
          </section>
        )}

        <WorkspaceViews
          label="病例视图切换"
          tabs={tabsWithBadges}
          value={view}
          onChange={v => update({ view: v === 'timeline' ? '' : v })}
        />

        <TabPanelTransition tabs={caseViews} activeKey={view}>
          {view === 'timeline' && (
            <WorkspaceEvents
              key={item.version}
              events={item.timeline}
              trigger={trigger.event_id}
              onTrigger={eventId => update({ trigger: eventId })}
              onQuickRun={canStart ? eventId => { update({ trigger: eventId }); start.mutate(eventId); } : undefined}
            />
          )}
          {view === 'workflow' && (
            <CaseWorkflowAndImagingSection
              caseId={id}
              version={item.version}
              triggerEventId={trigger.event_id}
              isLatestVersion={current}
              onEnriched={onSaved}
            />
          )}
          {view === 'sources' && <CaseSources item={item} />}
          {view === 'routing' && (routing.isPending ? <Loading /> : routing.isError ? <InlineError error={routing.error} /> : <RoutingPanel routing={routing.data} />)}
        </TabPanelTransition>
      </div>

      <aside className="panel workspace-launch">
        <div className="section-heading">
          <h2>发起 MDT 协同审阅</h2>
          <span className="pill outline">v{item.version}</span>
        </div>
        <form className="research-form" onSubmit={event => { event.preventDefault(); if (canStart) start.mutate(undefined); }}>
          <div className="workspace-trigger">
            <span>当前锁定触发截点</span>
            <strong>{trigger.title}</strong>
            <small>{trigger.occurred_at} · 事件编号 <code>{trigger.event_id}</code> · {eventNames[trigger.event_type]}</small>
            {view !== 'timeline' && (
              <button type="button" className="text-link" onClick={() => update({ view: '' })}>
                返回时间线更换截点 <Icon name="arrow" size={12} />
              </button>
            )}
          </div>

          <label>
            专科调度策略
            <select value={routingMode} onChange={event => update({ routing: event.target.value === 'fixed' ? 'fixed' : '' })}>
              <option value="event">按事件智能路由（推荐）</option>
              <option value="fixed">固定四专科全员对照</option>
            </select>
          </label>

          <div className="workspace-routing">
            <span>本次参与专科（{routing.data?.selected_agents.length ?? 0} / 4 科）</span>
            {routing.data ? (
              <div>{routing.data.selected_agents.map(role => <span key={role}>{roleNames[role]}</span>)}</div>
            ) : (
              <p>{routing.isError ? '调度规则读取失败' : '正在计算路由…'}</p>
            )}
          </div>

          <label>
            执行引擎模式
            <select value={mode} onChange={event => update({ mode: event.target.value === 'llm' ? 'llm' : '', scenario: '' })}>
              <option value="mock">本地确定性规则仿真</option>
              <option value="llm" disabled={!modelsReady}>大模型智能推演{modelsReady ? '' : '（需先配置模型）'}</option>
            </select>
          </label>

          <div className="llm-readiness-box" data-ready={modelsReady}>
            <span>
              <strong>{modelsReady ? '专科大模型已就绪' : '大模型尚未配置密钥'}</strong>
              {' · '}
              {modelsReady ? '可直接切换为大模型智能推演' : '当前可用本地规则仿真离线验证'}
            </span>
            <Link className="text-link" to="/settings/models">
              {modelsReady ? '管理方案' : '去配置'} <Icon name="arrow" size={12} />
            </Link>
          </div>

          {mode === 'mock' && (
            <details className="workspace-advanced" open={scenario !== 'standard' || undefined}>
              <summary>异常与边界验证场景{scenario !== 'standard' ? ` · ${scenarioNames[scenario]}` : ''}</summary>
              <label className="sr-only" htmlFor="case-scenario">规则场景</label>
              <select id="case-scenario" value={scenario} onChange={event => update({ scenario: event.target.value === 'standard' ? '' : event.target.value })}>
                {Object.entries(scenarioNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </details>
          )}

          {scenarioBlocked && <p className="inline-error">「跨科保留分歧」场景至少需要 2 个参与专科，请切换为“固定四专科全员对照”或更换触发事件。</p>}
          <InlineError error={routing.error || models.error || start.error} />
          <p className="workspace-boundary">
            系统将严格截取 v{item.version} 中截至 <code>{trigger.event_id}</code> 的病程记录，自动屏蔽未来事件。
          </p>
          <button type="submit" className="button primary full" disabled={!canStart}>
            <Icon name="play" size={15} />
            {start.isPending ? '正在启动协同工作流…' : '启动 MDT 协同运行'}
          </button>
          <div className="launch-footer-links">
            <button type="button" className="text-link" onClick={() => update({ view: 'workflow' })}>
              <Icon name="eye" size={13} />工作流与影像
            </button>
            <Link
              className="text-link"
              to={`/research/experiments?view=annotate&scenario=${encodeURIComponent(`${id}:v${item.version}:${trigger.event_id}`)}`}
            >
              <Icon name="check" size={13} />盲标当前截点
            </Link>
            <Link className="text-link" to={`/research/experiments?case=${encodeURIComponent(id)}`}>
              <Icon name="route" size={13} />对比 8 组消融
            </Link>
            <Link className="text-link" to="/settings/models">
              <Icon name="settings" size={13} />专科模型设置
            </Link>
          </div>
        </form>
      </aside>
    </div>
  </div>;
}
