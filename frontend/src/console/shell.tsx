import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { researchApi } from '../research/api';
import { Icon } from '../ui';
import { CommandMenu } from './command-menu';
import { destinations, help, locationContext } from './navigation';
import { usePreference } from './preferences';

function WorkspaceNav({ active, onNavigate }: { active: string; onNavigate?: () => void }) {
  function link(item: { label: string; href: string; icon: string }) {
    return <Link key={item.href} to={item.href} className="console-nav-item"
      aria-current={active === item.href ? 'page' : undefined} aria-label={item.label}
      title={item.label} onClick={onNavigate}>
      <Icon name={item.icon} size={17} /><span>{item.label}</span>
    </Link>;
  }
  return <nav className="console-nav" aria-label="主导航">
    {(['工作区', '管理'] as const).map(group => <div className="console-nav-group" key={group}>
      <div className="console-nav-label">{group}</div>
      {destinations.filter(item => item.group === group).map(link)}
    </div>)}
    <div className="console-nav-foot">{link(help)}</div>
  </nav>;
}

function Brand() {
  return <Link className="console-brand" to="/" aria-label="MDT 医疗协同工作台首页">
    <span className="console-brand-symbol"><Icon name="pulse" size={21} /></span>
    <span className="console-brand-text"><strong>MDT 协同台</strong><small>多学科智能决策</small></span>
  </Link>;
}

function NavigationDrawer({ active, close }: { active: string; close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = ref.current!;
    element.showModal();
    const wide = window.matchMedia('(min-width: 761px)');
    const handleResize = () => { if (wide.matches) close(); };
    wide.addEventListener('change', handleResize);
    return () => { wide.removeEventListener('change', handleResize); element.close(); };
  }, [close]);
  return <dialog id="workspace-drawer" ref={ref} aria-label="工作区导航" className="console-drawer"
    onCancel={event => { event.preventDefault(); close(); }}
    onClick={event => { if (event.target === event.currentTarget) close(); }}>
    <div className="console-drawer-body">
      <div className="console-drawer-title"><strong>MDT 协同台</strong><button type="button" onClick={close} className="console-icon" aria-label="关闭导航"><Icon name="close" /></button></div>
      <WorkspaceNav active={active} onNavigate={close} />
    </div>
  </dialog>;
}

function ConnectionState() {
  const query = useQuery({ queryKey: ['research-storage'], queryFn: researchApi.storage, refetchInterval: 30000, staleTime: 10000 });
  const database = query.data?.backend === 'mongodb' ? '主存储 (MongoDB)' : query.data?.backend === 'sqlite' ? '本地库 (SQLite)' : '存储服务';
  const label = query.isError ? '存储未连接' : query.data ? database + ' 已就绪' : '正在连接';
  return <div className="console-connection" data-status={query.isError ? 'offline' : query.data ? 'online' : 'waiting'}>
    <span aria-hidden="true" className="connection-led" /><span role="status">{label}</span>
    {query.isError && <button type="button" aria-label="重新检查连接" title="重新检查连接" onClick={() => void query.refetch()}><Icon name="refresh" size={13} /></button>}
  </div>;
}

export function ConsoleShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const { section, detail } = locationContext(pathname);
  const main = useRef<HTMLElement>(null);
  const previousPath = useRef(pathname);
  const [dark, toggleTheme] = usePreference('mdt-theme', () => matchMedia('(prefers-color-scheme: dark)').matches, 'dark', 'light');
  const [collapsed, toggleRail] = usePreference('mdt-sidebar', () => false, 'collapsed', 'expanded');
  const [menuOpen, setMenuOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  }, [dark]);
  useLayoutEffect(() => {
    document.title = [detail, section.label, 'MDT 协同台'].filter(Boolean).join(' · ');
    if (previousPath.current !== pathname) {
      main.current?.scrollTo(0, 0);
      main.current?.focus({ preventScroll: true });
      previousPath.current = pathname;
    }
  }, [pathname, section.label, detail]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.isComposing || event.altKey || event.shiftKey || !(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'k') return;
      if (document.querySelector('dialog[open]:not(.jump-dialog)')) return;
      event.preventDefault();
      setMenuOpen(open => !open);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  const shortcut = /mac|iphone|ipad/i.test(navigator.platform) ? '⌘ K' : 'Ctrl K';

  return <div className="console-app" data-collapsed={collapsed}>
    <button type="button" className="skip-link" onClick={() => main.current?.focus()}>跳至工作区</button>
    <aside className="console-rail">
      <div className="console-brand-row"><Brand /></div>
      <WorkspaceNav active={section.href} />
    </aside>
    <div className="console-workspace">
      <header className="console-bar">
        <button type="button" className="console-icon rail-toggle" aria-label={collapsed ? '展开侧栏' : '收起侧栏'}
          title={collapsed ? '展开侧栏' : '收起侧栏'} aria-expanded={!collapsed} onClick={toggleRail}><Icon name="sidebar" size={18} /></button>
        <button type="button" className="console-icon drawer-toggle" aria-label="打开导航" aria-haspopup="dialog"
          aria-expanded={drawerOpen} aria-controls={drawerOpen ? 'workspace-drawer' : undefined}
          onClick={() => setDrawerOpen(true)}><Icon name="menu" /></button>
        <div className="console-crumb" aria-label="当前位置">
          <span className="console-crumb-root">控制台</span><span className="console-separator" aria-hidden="true">/</span>
          {detail ? <><Link to={section.href}>{section.label}</Link><span className="console-separator" aria-hidden="true">/</span><strong>{detail}</strong></> : <strong>{section.label}</strong>}
        </div>
        <div className="console-tools">
          <button type="button" className="jump-launch" onClick={() => setMenuOpen(true)} aria-label="快速跳转" aria-keyshortcuts="Control+k Meta+k" aria-haspopup="dialog">
            <Icon name="search" size={15} /><span>快速跳转</span><kbd>{shortcut}</kbd>
          </button>
          <ConnectionState />
          <button type="button" className="console-icon" aria-label={dark ? '使用浅色外观' : '使用深色外观'}
            title={dark ? '使用浅色外观' : '使用深色外观'} onClick={toggleTheme}><Icon name={dark ? 'sun' : 'moon'} size={16} /></button>
        </div>
      </header>
      <main ref={main} id="main-content" tabIndex={-1} className="console-main">
        <div className="console-content">{children}</div>
      </main>
    </div>
    {drawerOpen && <NavigationDrawer active={section.href} close={closeDrawer} />}
    {menuOpen && <CommandMenu close={() => setMenuOpen(false)} />}
  </div>;
}
