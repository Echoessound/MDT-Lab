import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { researchApi } from '../research/api';
import { Icon } from '../ui';
import { jumpResults, type JumpItem } from './navigation';

export function CommandMenu({ close }: { close: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const navigate = useNavigate();
  const searching = query.trim().length > 0;
  const cases = useQuery({ queryKey: ['research-cases'], queryFn: researchApi.cases, enabled: searching, staleTime: 30000 });
  const runs = useQuery({ queryKey: ['research-runs'], queryFn: researchApi.runs, enabled: searching, staleTime: 3000 });
  const items = jumpResults(query, cases.data ?? [], runs.data ?? []);
  const index = Math.min(cursor, Math.max(0, items.length - 1));
  const busy = searching && (cases.isFetching || runs.isFetching);

  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    return () => { element.close(); };
  }, []);

  useEffect(() => {
    const option = dialog.current?.querySelector<HTMLElement>('[aria-selected="true"]');
    const list = option?.parentElement;
    if (!option || !list) return;
    if (option.offsetTop < list.scrollTop) list.scrollTop = option.offsetTop;
    const bottom = option.offsetTop + option.offsetHeight;
    if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight;
  }, [index, query, items.length]);

  function open(item: JumpItem) {
    close();
    navigate(item.href);
  }

  return <dialog ref={dialog} className="jump-dialog" aria-label="快速跳转"
    onCancel={event => { event.preventDefault(); close(); }}
    onClick={event => { if (event.target === event.currentTarget) close(); }}>
    <div className="jump-content">
      <div className="jump-input-row">
        <Icon name="search" size={20} />
        <input autoFocus autoComplete="off" role="combobox" aria-label="搜索页面、病例或运行"
          aria-autocomplete="list" aria-expanded="true" aria-controls="jump-list"
          aria-activedescendant={items.length ? 'jump-option-' + index : undefined}
          value={query} placeholder="搜索页面、病例名称或运行编号"
          onChange={event => { setQuery(event.target.value); setCursor(0); }}
          onKeyDown={event => {
            if (event.nativeEvent.isComposing || event.keyCode === 229 || !items.length) return;
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
              event.preventDefault();
              setCursor((index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length);
            } else if (event.key === 'Enter') {
              event.preventDefault();
              open(items[index]);
            }
          }} />
        <button type="button" className="console-icon" onClick={close} aria-label="关闭快速跳转"><Icon name="close" size={16} /></button>
      </div>
      <div className="jump-list" id="jump-list" role="listbox" aria-label="跳转结果">
        {items.map((item, i) => <button key={item.href} id={'jump-option-' + i} type="button" role="option" tabIndex={-1}
          aria-selected={i === index} className="jump-option" onMouseDown={event => event.preventDefault()}
          onClick={() => open(item)}>
          <Icon name={item.icon} size={17} /><span>{item.label}<small>{item.detail}</small></span><Icon name="enter" size={15} />
        </button>)}
      </div>
      <div role="status" className="jump-status">{!items.length ? (busy ? '正在检索…' : '没有匹配结果') : searching ? `找到 ${items.length} 项` : '常用页面'}{searching && (cases.isError || runs.isError) && ' · 部分记录暂时无法读取'}</div>
      <div className="jump-hint"><span><kbd>↑</kbd> <kbd>↓</kbd> 上下选择</span><span><kbd>回车</kbd> 立即打开</span><span><kbd>Esc</kbd> 关闭窗口</span></div>
    </div>
  </dialog>;
}
