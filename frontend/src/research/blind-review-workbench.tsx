import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorState, Icon, Loading } from '../ui';
import { researchApi } from './api';
import { eventNames, InlineError, roleNames, roleOrder } from './components';
import type { AnnotationTask, BlindAnnotation, BlindMaterial, Role } from './schemas';
import { PageLinks, pageSlice } from './workspace-controls';
import { factKeyLabel } from './zh-dict';

type Decision = BlindAnnotation['expected_decision'];

function toggle<T>(values: T[], value: T) {
  return values.includes(value) ? values.filter(item => item !== value) : [...values, value];
}

function ReferenceForm({ task, reviewer, material, existing, onChanged }: {
  task: AnnotationTask;
  reviewer: string;
  material: BlindMaterial;
  existing: BlindAnnotation | null;
  onChanged: () => void;
}) {
  const client = useQueryClient();
  const [decision, setDecision] = useState<Decision | ''>(existing?.expected_decision ?? '');
  const [roles, setRoles] = useState<Role[]>(existing?.required_agents ?? []);
  const [evidence, setEvidence] = useState(existing?.evidence_ids ?? []);
  const [missing, setMissing] = useState(existing?.missing_fields.join('\n') ?? '');
  const [rationale, setRationale] = useState(existing?.rationale ?? '');
  const ownKey = ['own-annotation', task.scenario_id, reviewer];
  const save = useMutation({
    mutationFn: (label: Decision) => researchApi.saveAnnotation(task.scenario_id, {
      case_id: task.case_id, case_version: task.case_version, trigger_event_id: task.trigger_event_id,
      annotator_id: reviewer, input_sha256: material.input_sha256, evidence_ids: evidence,
      required_agents: roles, expected_decision: label,
      missing_fields: [...new Set(missing.split(/\r?\n/).map(field => field.trim()).filter(Boolean))],
      rationale: rationale.trim(),
    }),
    onSuccess: record => { client.setQueryData(ownKey, record); onChanged(); },
  });
  const remove = useMutation({
    mutationFn: () => researchApi.deleteAnnotation(task.scenario_id, reviewer),
    onSuccess: () => { client.setQueryData(ownKey, null); onChanged(); },
  });
  const busy = save.isPending || remove.isPending;
  const locked = !reviewer || (task.annotated && !existing);
  const stale = Boolean(existing?.input_sha256 && existing.input_sha256 !== material.input_sha256);
  return <div className="workspace-column">
    <section className="panel blind-material-panel">
      <div className="workspace-section-heading">
        <div><h2>截点材料</h2>
          <p className="muted">{task.case_id} · v{task.case_version} · 截至 {material.events.at(-1)?.occurred_at}（{task.trigger_event_id}）</p>
        </div>
        <span className="pill outline">{material.events.length} 条可见记录</span>
      </div>
      <div className="blind-frozen-events">{material.events.map(event =>
        <article key={event.event_id} className={`blind-event-card ${event.event_id === task.trigger_event_id ? 'is-cutoff' : ''}`}>
          <div className="blind-event-head"><strong>{event.occurred_at} · {event.title}</strong>
            <span className="pill soft">{eventNames[event.event_type]} · {event.event_id}</span></div>
          <div className="blind-evidence-list">{Object.entries(event.facts).map(([key, value]) => {
            const id = `${event.event_id}:${key}`;
            return <label key={id} className="blind-evidence-row">
              <input type="checkbox" aria-label={`引用 ${id}`} checked={evidence.includes(id)}
                disabled={locked || busy || stale} onChange={() => setEvidence(prev => toggle(prev, id))} />
              <span><strong>{factKeyLabel(key)}</strong><small>{id}</small></span>
              <span>{value === null ? '未记录' : typeof value === 'boolean' ? (value ? '是' : '否') : String(value)}</span>
            </label>;
          })}</div>
        </article>)}</div>
    </section>
    <section className="panel">
      <div className="workspace-section-heading"><h2>参考判断</h2>
        {existing && <span className="pill soft" role="status">已保存 · {reviewer}</span>}</div>
      {locked ? <p className="muted">{reviewer ? '该截点已有其他标注人的参考，可继续选择待标任务。' : '请先在任务队列中填写标注人编号。'}</p>
        : <form className="research-form" onSubmit={e => {
            e.preventDefault();
            if (decision && roles.length && !busy && !stale) save.mutate(decision);
          }}>
          {stale && <p className="notice" role="alert">已保存参考与当前材料指纹不同。请核查原始标注和病例版本。</p>}
          <label>预期流程结论
            <select value={decision} required onChange={e => setDecision(e.target.value as Decision)}>
              <option value="" disabled>请选择结论</option>
              <option value="READY_FOR_REVIEW">可进入人工资料复核</option>
              <option value="NEED_MORE_INFORMATION">需要补充资料</option>
              <option value="DEFER_DECISION">暂缓判断</option>
            </select></label>
          <fieldset className="blind-roles"><legend>必要参与专科（至少一科）</legend>
            <div className="fact-toggle-grid">{roleOrder.map(role =>
              <label key={role} className={`fact-toggle-chip ${roles.includes(role) ? 'is-active' : ''}`}>
                <input type="checkbox" checked={roles.includes(role)} onChange={() => setRoles(prev => toggle(prev, role))} />
                <span>{roleNames[role]}</span></label>)}</div>
          </fieldset>
          <label>缺失字段（每行一项）
            <textarea rows={2} value={missing} onChange={e => setMissing(e.target.value)} /></label>
          <label>判断依据
            <textarea rows={3} maxLength={2000} value={rationale} onChange={e => setRationale(e.target.value)}
              placeholder="说明已引用事实、资料缺口或仍需核验的矛盾。" /></label>
          <p className="muted">已引用 {evidence.length} 项事实，可在上方截点材料中勾选。</p>
          <InlineError error={save.error || remove.error} />
          <div className="button-group">
            <button className="button primary" type="submit" disabled={!decision || !roles.length || busy || stale}>
              <Icon name="check" size={15} />{save.isPending ? '正在保存…' : '保存参考判断'}</button>
            {existing && <button className="button secondary" type="button" disabled={busy}
              onClick={() => remove.mutate()}>删除我的标注</button>}
          </div>
        </form>}
    </section>
  </div>;
}

function ReviewTask({ task, reviewer, onChanged }: {
  task: AnnotationTask; reviewer: string; onChanged: () => void;
}) {
  const material = useQuery({ queryKey: ['blind-material', task.scenario_id], queryFn: () => researchApi.blindMaterial(task) });
  const own = useQuery({
    queryKey: ['own-annotation', task.scenario_id, reviewer],
    queryFn: () => researchApi.ownAnnotation(task.scenario_id, reviewer), enabled: Boolean(reviewer),
  });
  if (material.isError || (reviewer && own.isError)) return <ErrorState error={material.error || own.error}
    retry={() => { void material.refetch(); if (reviewer) void own.refetch(); }} />;
  if (!material.data || (reviewer && own.isPending)) return <Loading />;
  return <ReferenceForm key={JSON.stringify([task.scenario_id, material.data.input_sha256, reviewer, own.data?.updated_at])}
    task={task} material={material.data} existing={own.data ?? null} reviewer={reviewer} onChanged={onChanged} />;
}

export function BlindReviewWorkbench({ onChanged }: { onChanged: () => void }) {
  const tasks = useQuery({ queryKey: ['blind-tasks'], queryFn: researchApi.annotationTasks });
  const [selected, setSelected] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [identity, setIdentity] = useState('');
  const [page, setPage] = useState(1);
  if (tasks.isError) return <ErrorState error={tasks.error} retry={() => void tasks.refetch()} />;
  if (!tasks.data) return <Loading />;
  const queue = tasks.data;
  const active = queue.find(t => t.scenario_id === selected) ?? queue[0];
  if (!active) return <p className="workspace-empty">当前病例库没有可标注的截点。</p>;
  const done = queue.filter(t => t.annotated).length;
  const { rows, page: currentPage, pages, first } = pageSlice(queue, page);
  const selectNext = () => {
    const start = queue.indexOf(active) + 1;
    const next = [...queue.slice(start), ...queue.slice(0, start)].find(t => !t.annotated && t !== active);
    if (next) { setSelected(next.scenario_id); setPage(Math.floor(queue.indexOf(next) / 20) + 1); }
  };
  return <div className="blind-annotation-layout">
    <aside className="panel blind-scenario-list" aria-label="盲标任务队列">
      <div className="workspace-section-heading"><h2>截点队列</h2><span className="pill soft">{done} / {queue.length} 已标</span></div>
      <div className="blind-progress-wrap">
        <progress max={queue.length} value={done} aria-label="当前版本标注进度" />
        <form className="research-form" onSubmit={e => { e.preventDefault(); setReviewer(identity.trim()); }}>
          <label>标注人编号<input value={identity} maxLength={80} required readOnly={Boolean(reviewer)}
            onChange={e => setIdentity(e.target.value)} autoComplete="off" /></label>
          {reviewer ? <button type="button" className="button secondary" onClick={() => { setIdentity(''); setReviewer(''); }}>切换标注人</button>
            : <button className="button secondary" disabled={!identity.trim()}>使用此编号</button>}
        </form>
        <button type="button" className="text-link" disabled={!queue.some(t => !t.annotated && t !== active)}
          onClick={selectNext}>下一待标截点 <Icon name="arrow" size={14} /></button>
      </div>
      <div className="blind-list-scroll">{rows.map((task, index) =>
        <button type="button" key={task.scenario_id} aria-current={task === active ? 'true' : undefined}
          className={`blind-scenario-btn ${task === active ? 'is-selected' : ''}`} onClick={() => setSelected(task.scenario_id)}>
          <strong>任务 {first + index}</strong>
          <span className={`pill ${task.annotated ? 'status-completed' : 'outline'}`}>{task.annotated ? '已标注' : '待标'}</span>
        </button>)}</div>
      <PageLinks page={currentPage} pages={pages} onPage={setPage} />
    </aside>
    <ReviewTask key={active.scenario_id} task={active} reviewer={reviewer}
      onChanged={() => { void tasks.refetch(); onChanged(); }} />
  </div>;
}
