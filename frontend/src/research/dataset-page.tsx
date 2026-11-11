import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorState, Icon, Loading, dateTime } from '../ui';
import { researchApi } from './api';
import { InlineError } from './components';
import { caseKindName } from './data-components';
import type { ImportBatch, ImportPreview } from './schemas';

export function DatasetPage() {
  const client = useQueryClient();
  const catalog = useQuery({ queryKey: ['datasets'], queryFn: researchApi.datasets });
  const [source, setSource] = useState('synthea_csv');
  const [limit, setLimit] = useState(10);
  const [file, setFile] = useState<File>();
  const [preview, setPreview] = useState<ImportPreview>();
  const [imported, setImported] = useState<ImportBatch>();
  const load = useMutation({ mutationFn: async (online: boolean) => {
    if (!Number.isInteger(limit) || limit < 1 || limit > 50) throw new Error('每批病例数为1至50。');
    if (online) return researchApi.connectDataset(source, limit);
    if (!file) throw new Error('请先选择文件。');
    if (!file.size || file.size > (catalog.data?.max_upload_bytes ?? 20 * 1024 * 1024)) throw new Error('文件应非空且不超过20MB。');
    return researchApi.previewDataset(source, file, limit);
  }, onMutate: () => { setPreview(undefined); setImported(undefined); }, onSuccess: setPreview });
  const commit = useMutation({ mutationFn: () => researchApi.importDataset(preview!.preview_id), onSuccess: result => {
    setImported(result); setPreview(undefined);
    void client.invalidateQueries({ queryKey: ['datasets'] });
    void client.invalidateQueries({ queryKey: ['research-cases'] });
  } });
  const reset = () => { setPreview(undefined); setImported(undefined); load.reset(); commit.reset(); };
  if (catalog.isPending) return <Loading />;
  if (catalog.isError) return <ErrorState error={catalog.error} retry={() => void catalog.refetch()} />;
  const selected = catalog.data.sources.find(item => item.source === source)!;
  const busy = load.isPending || commit.isPending;
  return <div className="page-enter research-page"><div className="page-heading"><div><div className="eyebrow">EXTERNAL DATA / TRACEABLE IMPORT</div><h1>把资料接入协作流程<span className="title-period">.</span></h1><p>连接公开数据源或上传文件，先预检，再写入版本化病例库。</p></div><Link className="button secondary" to="/research/agents">进入 Agent 群 <Icon name="arrow" /></Link></div>
    <div className="research-settings-grid"><section className="panel"><h2>选择数据来源</h2><div className="research-form"><label>数据格式<select value={source} disabled={busy} onChange={event => { setSource(event.target.value); setFile(undefined); reset(); }}>{catalog.data.sources.map(item => <option key={item.source} value={item.source}>{item.name} · {item.format}</option>)}</select></label><p>{selected.description}</p><label>每批最多导入病例数<input type="number" min={1} max={50} value={limit} disabled={busy} onChange={event => { setLimit(Number(event.target.value)); reset(); }} /></label>
      {selected.download_url && <button className="button primary" disabled={busy} onClick={() => load.mutate(true)}><Icon name="network" />{load.isPending ? '正在获取并预检…' : '连接官方数据源并预检'}</button>}
      <label>或上传本地文件 · 最大20MB<input key={source} type="file" disabled={busy} accept={source === 'synthea_csv' ? '.zip' : source === 'research_json' ? '.json' : '.csv'} onChange={event => { setFile(event.target.files?.[0]); reset(); }} /></label><button className="button secondary" disabled={busy || !file} onClick={() => load.mutate(false)}>{load.isPending ? '正在预检…' : '预检所选文件'}</button><InlineError error={load.error || commit.error} /></div></section>
      <aside className="research-stack"><section className="panel"><div className="eyebrow">SOURCE & LICENSE</div><h2>{selected.name}</h2><p>{selected.license}</p><p className="subtle-note">{selected.citation}</p>{selected.source_url && <a className="text-link" href={selected.source_url} target="_blank" rel="noreferrer">官方说明与下载 <Icon name="arrow" size={14} /></a>}</section><section className="panel"><h2>导入相关资料</h2><p>研究 JSON 支持带日期的结构化事实、来源声明及无日期资料。可按模板填写并上传，人工新增内容应声明为合成扩展。</p><a className="text-link" href="/api/v2/datasets/template" download>下载 JSON 模板 <Icon name="download" size={15} /></a><p className="subtle-note">无日期资料仅供核对，不进入历史事件的 Agent 输入。CSV/ZIP 依照各数据源字段映射，不将文件交给模型猜测。</p></section></aside></div>
    {preview && <section className="panel import-preview"><div className="section-heading"><div><div className="eyebrow">PREVIEW / NOT YET SAVED</div><h2>导入前检查</h2></div><span className="pill outline">有效至 {dateTime(preview.expires_at)}</span></div><p>{preview.case_count} 个病例 · {preview.event_count} 条事件 · {preview.unplaced_count} 组未定位资料 · {preview.rejected_count} 个病例未通过</p><p className="source-hash">SHA-256 · {preview.artifact_sha256}</p>{preview.warnings.map(warning => <p className="subtle-note" key={warning.message}>{warning.message}（{warning.count}）</p>)}{preview.rejected.map(item => <p className="inline-error" key={item.case_id}>{item.case_id}：{item.reason}</p>)}<div className="import-case-list">{preview.cases.map(item => <div key={item.case_id}><code>{item.case_id}</code><span>{caseKindName[item.case_kind]} · {item.event_count} 条事件</span></div>)}</div><button className="button primary" disabled={busy || !preview.case_count} onClick={() => commit.mutate()}>{commit.isPending ? '正在写入…' : `确认导入 ${preview.case_count} 个病例`}</button></section>}
    {imported && <section className="panel import-preview" role="status"><h2>{imported.already_imported ? '该批次已经导入' : '导入完成'}</h2><p>新增 {imported.imported_case_ids.length} 个病例，跳过 {imported.skipped_case_ids.length} 个相同病例。原有版本与运行记录保持完整。</p><CaseLinks batch={imported} /></section>}
    <section className="panel recent-section"><div className="section-heading"><h2>导入记录</h2><span className="muted">最近50批 · 持久保存</span></div>{catalog.data.batches.length ? catalog.data.batches.map(batch => <details key={batch.batch_id}><summary>{batch.source_name} · {batch.case_count} 个病例 · {dateTime(batch.created_at)}</summary><p className="source-hash">{batch.batch_id} · SHA-256 {batch.artifact_sha256}</p><p>{batch.mapping_version} · {batch.event_count} 条事件</p><CaseLinks batch={batch} /></details>) : <p className="empty-inline">尚无导入记录。完成预检后确认导入即可开始协作。</p>}</section>
  </div>;
}
function CaseLinks({ batch }: { batch: ImportBatch }) {
  return <div className="import-case-list">{batch.cases.map(item => <Link className="text-link" key={item.case_id} to={`/research/cases/${encodeURIComponent(item.case_id)}`}>{item.case_id} · 打开病例 <Icon name="arrow" size={14} /></Link>)}</div>;
}
