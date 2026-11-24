import { useLocation, useSearchParams } from 'react-router-dom';
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react';
import type { Run } from './schemas';
import { terminal } from './realtime';

export function useWorkspaceParams() {
  const [params, setParams] = useSearchParams();
  const { state } = useLocation();
  function update(changes: Record<string, string>) {
    setParams(previous => {
      const next = new URLSearchParams(previous);
      for (const [name, value] of Object.entries(changes)) {
        if (value) next.set(name, value);
        else next.delete(name);
      }
      return next;
    }, { replace: true, preventScrollReset: true, state });
  }
  return { params, update };
}

export function pageSlice<T>(rows: T[], requested: number, size = 20) {
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const page = Number.isFinite(requested) ? Math.max(1, Math.min(pages, Math.floor(requested))) : 1;
  const offset = (page - 1) * size;
  return { rows: rows.slice(offset, offset + size), page, pages, first: rows.length ? offset + 1 : 0, last: Math.min(rows.length, offset + size) };
}

export function PageLinks({ page, pages, onPage }: { page: number; pages: number; onPage: (page: number) => void }) {
  return pages > 1 ? <div className="workspace-pagination" aria-label="分页">
    <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)}>上一页</button>
    <span>第 {page} / {pages} 页</span>
    <button type="button" disabled={page >= pages} onClick={() => onPage(page + 1)}>下一页</button>
  </div> : null;
}

export function computeSlideDirection<K extends string>(
  tabs: readonly { key: K }[],
  previousKey: K,
  nextKey: K,
): 'right' | 'left' | 'none' {
  if (previousKey === nextKey) return 'none';
  const prevIdx = tabs.findIndex(t => t.key === previousKey);
  const nextIdx = tabs.findIndex(t => t.key === nextKey);
  if (prevIdx === -1 || nextIdx === -1) return 'right';
  return nextIdx > prevIdx ? 'right' : 'left';
}

export function WorkspaceViews<K extends string>({ label, tabs, value, onChange }: {
  label: string;
  tabs: readonly { key: K; label: string; badge?: string | number }[];
  value: K;
  onChange: (key: K) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const activeIndex = Math.max(0, tabs.findIndex(t => t.key === value));
  const [glider, setGlider] = useState<{ left: number; width: number; ready: boolean }>({ left: 0, width: 0, ready: false });

  useLayoutEffect(() => {
    const sync = () => {
      const btn = buttons.current[activeIndex];
      if (!btn) return;
      setGlider({ left: btn.offsetLeft, width: btn.offsetWidth, ready: true });
    };
    sync();
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(sync);
    observer.observe(container);
    const activeBtn = buttons.current[activeIndex];
    if (activeBtn) observer.observe(activeBtn);
    return () => observer.disconnect();
  }, [activeIndex, tabs.length]);

  function moveFocus(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const keys = ['ArrowRight', 'ArrowLeft', 'Home', 'End'];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    let next = event.key === 'Home' ? 0 : tabs.length - 1;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
    buttons.current[next]?.focus();
    onChange(tabs[next].key);
  }

  const gliderStyle = {
    '--glider-x': `${glider.left}px`,
    '--glider-w': `${glider.width}px`,
  } as CSSProperties;

  return <div ref={containerRef} className="workspace-views" role="tablist" aria-label={label}>
    {glider.ready && <span aria-hidden="true" className="workspace-views-glider" style={gliderStyle} />}
    {tabs.map((tab, index) => <button key={tab.key} type="button" role="tab" aria-selected={value === tab.key}
      id={`workspace-tab-${tab.key}`} aria-controls="workspace-panel" tabIndex={value === tab.key ? 0 : -1}
      ref={element => { buttons.current[index] = element; }} onKeyDown={event => moveFocus(event, index)}
      onClick={() => onChange(tab.key)}>
      <span>{tab.label}</span>
      {tab.badge !== undefined && <small className="workspace-tab-badge">{tab.badge}</small>}
    </button>)}
  </div>;
}

export function TabPanelTransition<K extends string>({
  tabs,
  activeKey,
  className = '',
  children,
}: {
  tabs: readonly { key: K }[];
  activeKey: K;
  className?: string;
  children: ReactNode;
}) {
  const prevKeyRef = useRef<K>(activeKey);
  const [direction, setDirection] = useState<'right' | 'left' | 'none'>('none');

  useEffect(() => {
    if (prevKeyRef.current !== activeKey) {
      setDirection(computeSlideDirection(tabs, prevKeyRef.current, activeKey));
      prevKeyRef.current = activeKey;
    }
  }, [activeKey, tabs]);

  const animClass = direction === 'left' ? 'tab-slide-left' : 'tab-slide-right';

  return <div
    key={activeKey}
    id="workspace-panel"
    role="tabpanel"
    aria-labelledby={`workspace-tab-${activeKey}`}
    tabIndex={0}
    className={`tab-panel-animated ${animClass} ${className}`.trim()}
  >
    {children}
  </div>;
}

export function RunProgressStrip({ run }: { run: Run }) {
  const total = run.completed_nodes.length + run.running_nodes.length + run.pending_nodes.length;
  const completed = run.completed_nodes.length;
  const pct = total > 0 ? Math.round((completed / total) * 100) : (run.status === 'completed' ? 100 : 0);
  const isActive = !terminal(run.status);
  const tone = run.status === 'failed' || run.status === 'incomplete'
    ? 'is-danger'
    : run.status === 'cancelled'
      ? 'is-muted'
      : 'is-active';

  return (
    <div className="run-progress-strip" aria-label="真实节点执行进度">
      <div className="run-progress-meta">
        <span>工作流真实节点进度</span>
        <strong>{total > 0 ? `${completed} / ${total} 个节点已完成（${pct}%）` : '等待任务节点初始化…'}</strong>
      </div>
      <div className="run-progress-track">
        <div
          className={`run-progress-fill ${tone} ${isActive ? 'is-shimmering' : ''}`}
          style={{ '--bar-scale': Math.max(isActive ? 0.08 : 0, pct / 100) } as CSSProperties}
        />
      </div>
    </div>
  );
}

export function currentView<K extends string>(tabs: readonly { key: K }[], requested: string | null): K {
  return tabs.find(tab => tab.key === requested)?.key ?? tabs[0].key;
}
