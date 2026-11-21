import { useState } from 'react';
import { eventNames, formatValue } from './components';
import type { ClinicalEvent } from './schemas';
import { PageLinks, pageSlice } from './workspace-controls';

export function WorkspaceEvents({ events, trigger, onTrigger }: {
  events: ClinicalEvent[]; trigger: string; onTrigger?: (id: string) => void;
}) {
  const [keyword, setKeyword] = useState('');
  const [requestedPage, setPage] = useState(1);
  const search = keyword.trim().toLowerCase();
  const filtered = [...events].reverse().filter(event => !search || [event.title, event.event_id, event.occurred_at, eventNames[event.event_type], event.source].some(value => value.toLowerCase().includes(search)));
  const page = pageSlice(filtered, requestedPage, 15);
  return <section className="panel workspace-event-panel" aria-label="病程事件">
    <div className="workspace-section-heading"><h2>病程事件</h2><span className="workspace-meta">{events.length} 条 · 日期倒序</span></div>
    <div className="workspace-toolbar"><label className="workspace-search"><span className="sr-only">查找病程事件</span><input type="search" placeholder="搜索事件、编号、日期或来源" value={keyword} onChange={e => { setKeyword(e.target.value); setPage(1); }} /></label></div>
    {page.rows.map(event => <div className={`workspace-event-row ${event.event_id === trigger ? 'event-used' : ''}`} key={event.event_id}>
      <details><summary><time dateTime={event.occurred_at}>{event.occurred_at}</time><span><strong>{event.title}</strong><small>{eventNames[event.event_type]} · {event.event_id}</small></span></summary>
        <div className="workspace-event-facts"><p>{event.source} · v{event.introduced_in_version}{event.synthetic_extension ? ' · 合成扩展' : ''}</p>{event.source_record_locator && <code>{event.source_record_locator}</code>}
          <dl className="event-facts">{Object.entries(event.facts).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{formatValue(value)}</dd></div>)}</dl>
        </div>
      </details>
      {event.event_id === trigger ? <span className="workspace-event-current">触发事件</span> : onTrigger && <button type="button" className="workspace-tool" aria-label={`以 ${event.event_id} 为触发事件`} onClick={() => onTrigger(event.event_id)}>设为触发</button>}
    </div>)}
    {!filtered.length && <div className="workspace-empty">没有符合条件的事件</div>}
    <footer className="workspace-list-footer"><span>{filtered.length ? `${page.first}–${page.last} / ${filtered.length}` : '0 条事件'}</span><PageLinks {...page} onPage={setPage} /></footer>
  </section>;
}
