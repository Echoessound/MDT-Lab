import { useQuery } from '@tanstack/react-query';
import { Icon } from '../ui';
import { researchApi } from './api';
import { InlineError } from './components';

export function StorageStatus() {
  const query = useQuery({ queryKey: ['research-storage'], queryFn: researchApi.storage, refetchInterval: 30000 });
  return <section className="panel storage-status" aria-label="数据库状态">
    <div><span className="eyebrow">PERSISTENT WORKSPACE</span><h2>{query.data?.backend === 'mongodb' ? 'MongoDB' : query.data?.backend === 'sqlite' ? 'SQLite' : '数据库连接'}</h2></div>
    {query.isPending ? <p className="muted">正在检查连接…</p> : query.isError ? <div><InlineError error={query.error} /><button className="text-link" onClick={() => void query.refetch()}>重新检查</button></div> : <>
      <div><span className="pill soft"><Icon name="check" size={13} /> 已连接</span><p><code>{query.data.database}</code> · {query.data.transactions ? '事务已启用' : '未启用事务'}</p></div>
      <p className="muted">病例版本、导入记录、协作报告与审计持续保存。<br />模型密钥加密存储。</p>
    </>}
  </section>;
}
