export type Destination = {
  label: string;
  href: string;
  icon: string;
  group: '工作区' | '管理';
};

export const destinations: Destination[] = [
  { label: '病例工作台', href: '/', icon: 'grid', group: '工作区' },
  { label: '运行记录', href: '/research/runs', icon: 'history', group: '工作区' },
  { label: 'Agent 群', href: '/research/agents', icon: 'network', group: '工作区' },
  { label: '数据导入', href: '/research/datasets', icon: 'database', group: '管理' },
  { label: '模型设置', href: '/settings/models', icon: 'settings', group: '管理' },
];

export const help = { label: '使用说明', href: '/roadmap', icon: 'book' };

export function locationContext(path: string) {
  const [, first, second, third, fourth] = path.split('/');
  if (first === 'research' && second === 'cases' && third) {
    return { section: destinations[0], detail: third };
  }
  if (first === 'research' && second === 'runs' && third) {
    return { section: destinations[1], detail: fourth === 'report' ? '运行报告' : '运行详情' };
  }
  if (['legacy', 'cases', 'runs'].includes(first)) {
    return { section: { label: '旧版工作台', href: '/legacy' }, detail: '' };
  }
  const normalized = path.replace(/\/+$/, '') || '/';
  const section = [...destinations, help].find(item => item.href === normalized);
  return { section: section ?? { label: '页面未找到', href: '' }, detail: '' };
}

export type JumpItem = { label: string; detail: string; href: string; icon: string };
type SearchCase = { case_id: string; title: string };
type SearchRun = { run_id: string; case_id: string; case_version: number };

export function jumpResults(raw: string, cases: SearchCase[], runs: SearchRun[]): JumpItem[] {
  const term = raw.trim().toLocaleLowerCase();
  const matches = (...fields: string[]) => fields.some(field => field.toLocaleLowerCase().includes(term));
  const pages = [...destinations, help]
    .filter(page => matches(page.label))
    .map(page => ({ ...page, detail: '页面' }));
  if (!term) return pages;
  const matchingCases = cases.filter(item => matches(item.case_id, item.title)).slice(0, 6);
  const matchingRuns = runs.filter(item => matches(item.run_id, item.case_id)).slice(0, 6);
  return [
    ...pages,
    ...matchingCases.map(item => ({
      label: item.title, detail: item.case_id, icon: 'file',
      href: '/research/cases/' + encodeURIComponent(item.case_id),
    })),
    ...matchingRuns.map(item => ({
      label: item.run_id, detail: item.case_id + ' · v' + item.case_version, icon: 'history',
      href: '/research/runs/' + encodeURIComponent(item.run_id),
    })),
  ];
}
