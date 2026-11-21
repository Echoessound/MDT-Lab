import { useQuery } from '@tanstack/react-query';
import { researchApi } from './api';
import { InlineError } from './components';

export function StorageStatus() {
  const query = useQuery({ queryKey: ['research-storage'], queryFn: researchApi.storage, refetchInterval: 30000 });
  if (query.isPending) return <p className="storage-indicator" role="status">正在检查数据库…</p>;
  if (query.isError) return <div className="storage-indicator">
    <InlineError error={query.error} />
    <button className="text-link" onClick={() => void query.refetch()}>重新检查数据库</button>
  </div>;
  const { backend, database, transactions } = query.data;
  return <div className="storage-indicator" aria-label="数据库状态">
    <span className="status-dot" /><strong>{backend === 'mongodb' ? 'MongoDB' : 'SQLite'} 已连接</strong>
    <code>{database}</code><span>{transactions ? '事务已启用' : '事务未启用'}</span>
  </div>;
}
