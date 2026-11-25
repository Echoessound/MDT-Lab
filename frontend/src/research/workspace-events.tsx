import { useState } from 'react';
import { Icon } from '../ui';
import { eventNames } from './components';
import type { ClinicalEvent } from './schemas';
import { PageLinks, pageSlice } from './workspace-controls';
import { factKeyLabel, formatFactValue, sourceNameLabel } from './zh-dict';

export function WorkspaceEvents({ events, trigger, isPinned = true, onTrigger, onQuickRun }: {
  events: ClinicalEvent[];
  trigger: string;
  isPinned?: boolean;
  onTrigger?: (id: string) => void;
  onQuickRun?: (id: string) => void;
}) {
  const [keyword, setKeyword] = useState('');
  const [requestedPage, setPage] = useState(1);
  const [chronological, setChronological] = useState(true);
  const search = keyword.trim().toLowerCase();

  const triggerIndex = isPinned ? events.findIndex(e => e.event_id === trigger) : -1;
  const ordered = chronological ? [...events] : [...events].reverse();
  const filtered = ordered.filter(event => !search || [
    event.title,
    event.event_id,
    event.occurred_at,
    eventNames[event.event_type],
    sourceNameLabel(event.source),
    ...Object.keys(event.facts).map(factKeyLabel),
  ].some(value => value.toLowerCase().includes(search)));

  const page = pageSlice(filtered, requestedPage, 15);
  const includedCount = triggerIndex >= 0 ? triggerIndex + 1 : events.length;
  const excludedCount = isPinned && triggerIndex >= 0 ? Math.max(0, events.length - includedCount) : 0;

  return <section className="panel workspace-event-panel" aria-label="病程事件">
    <div className="workspace-section-heading">
      <div>
        <h2>纵向病程事件时间线</h2>
        <span className="workspace-meta">
          共 {events.length} 条 · {isPinned ? `已纳入截点前 ${includedCount} 条` : '当前为全病程视图'}
          {excludedCount > 0 ? ` · 截点后屏蔽 ${excludedCount} 条未来事件` : ''}
        </span>
      </div>
      <button
        type="button"
        className="workspace-tool"
        onClick={() => setChronological(v => !v)}
        title="切换病程时间排序方式"
      >
        <Icon name="clock" size={14} />
        {chronological ? '时间正序 ↑' : '时间倒序 ↓'}
      </button>
    </div>
    <div className="workspace-toolbar">
      <label className="workspace-search">
        <span className="sr-only">查找病程事件</span>
        <input
          type="search"
          placeholder="搜索事件标题、编号、日期、临床指标或来源"
          value={keyword}
          onChange={e => { setKeyword(e.target.value); setPage(1); }}
        />
      </label>
    </div>
    {page.rows.map(event => {
      const idx = events.findIndex(e => e.event_id === event.event_id);
      const isTrigger = isPinned && event.event_id === trigger;
      const isFuture = isPinned && triggerIndex >= 0 && idx > triggerIndex;
      const rowStateClass = isTrigger ? 'event-used' : isFuture ? 'event-future-excluded' : 'event-included';
      return (
        <div className={`workspace-event-row ${rowStateClass}`} key={event.event_id}>
          <details open={isTrigger || events.length <= 6}>
            <summary>
              <time dateTime={event.occurred_at}>{event.occurred_at}</time>
              <span>
                <strong>{event.title}</strong>
                <small>
                  {eventNames[event.event_type]} · 编号 <code>{event.event_id}</code> · {Object.keys(event.facts).length} 项临床事实
                </small>
              </span>
            </summary>
            <div className="workspace-event-facts">
              <p>来源：{sourceNameLabel(event.source)} · 引入版本 v{event.introduced_in_version}{event.synthetic_extension ? ' · 人工合成扩展' : ' · 原始记录'}</p>
              {event.source_record_locator && <code>定位：{event.source_record_locator}</code>}
              <dl className="event-facts">
                {Object.entries(event.facts).map(([key, value]) => (
                  <div key={key}>
                    <dt>{factKeyLabel(key)}</dt>
                    <dd>{formatFactValue(value)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </details>
          <div className="workspace-event-actions">
            {isTrigger ? (
              <>
                <span className="workspace-event-current"><Icon name="check" size={13} />当前锁定截点</span>
                {onTrigger && (
                  <button
                    type="button"
                    className="workspace-tool"
                    onClick={() => onTrigger('')}
                  >
                    取消锁定
                  </button>
                )}
                {onQuickRun && (
                  <button type="button" className="workspace-tool primary-tool" onClick={() => onQuickRun(event.event_id)}>
                    <Icon name="play" size={12} />立即运行
                  </button>
                )}
              </>
            ) : (
              <>
                {isPinned && (
                  <span className={`event-cutoff-tag ${isFuture ? 'tag-future' : 'tag-included'}`}>
                    {isFuture ? '截点后屏蔽' : '已纳入范围'}
                  </span>
                )}
                {onTrigger && (
                  <button
                    type="button"
                    className="workspace-tool"
                    aria-label={`以 ${event.event_id} 为触发事件`}
                    onClick={() => onTrigger(event.event_id)}
                  >
                    设为截点
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      );
    })}
    {!filtered.length && <div className="workspace-empty">没有符合筛选条件的病程事件</div>}
    <footer className="workspace-list-footer">
      <span>{filtered.length ? `显示第 ${page.first}–${page.last} 条 / 共 ${filtered.length} 条事件` : '0 条事件'}</span>
      <PageLinks {...page} onPage={setPage} />
    </footer>
  </section>;
}
