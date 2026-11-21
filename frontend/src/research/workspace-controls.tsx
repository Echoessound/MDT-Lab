import { useLocation, useSearchParams } from 'react-router-dom';
import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react';

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
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const activeIndex = Math.max(0, tabs.findIndex(t => t.key === value));

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

  const barStyle = {
    '--tab-count': tabs.length,
    '--active-tab-index': activeIndex,
  } as CSSProperties;

  return <div className="workspace-views" role="tablist" aria-label={label} style={barStyle}>
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

export function currentView<K extends string>(tabs: readonly { key: K }[], requested: string | null): K {
  return tabs.find(tab => tab.key === requested)?.key ?? tabs[0].key;
}
