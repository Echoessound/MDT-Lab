import { useLocation, useSearchParams } from 'react-router-dom';
import { useRef, type KeyboardEvent } from 'react';

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
    <span>{page} / {pages}</span>
    <button type="button" disabled={page >= pages} onClick={() => onPage(page + 1)}>下一页</button>
  </div> : null;
}

export function WorkspaceViews<K extends string>({ label, tabs, value, onChange }: {
  label: string; tabs: readonly { key: K; label: string }[]; value: K; onChange: (key: K) => void;
}) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
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
  return <div className="workspace-views" role="tablist" aria-label={label}>
    {tabs.map((tab, index) => <button key={tab.key} type="button" role="tab" aria-selected={value === tab.key}
      id={`workspace-tab-${tab.key}`} aria-controls="workspace-panel" tabIndex={value === tab.key ? 0 : -1}
      ref={element => { buttons.current[index] = element; }} onKeyDown={event => moveFocus(event, index)}
      onClick={() => onChange(tab.key)}>{tab.label}</button>)}
  </div>;
}

export function currentView<K extends string>(tabs: readonly { key: K }[], requested: string | null): K {
  return tabs.find(tab => tab.key === requested)?.key ?? tabs[0].key;
}
