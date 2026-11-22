import { useEffect, useRef, useState, type RefObject } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { APIError } from '../api';
import { ErrorState, Icon, Loading, dateTime } from '../ui';
import { researchApi } from './api';
import { InlineError } from './components';
import { caseKindName } from './data-components';
import type { ImportBatch, ImportPreview } from './schemas';
import './dataset-console.css';

const formats: Record<string, string> = { synthea_csv: '.zip', tcia_nsclc_csv: '.csv', tcga_cbioportal_tsv: '.tsv,.txt,.csv', research_json: '.json' };
const nowExpired = (preview: ImportPreview) => Date.parse(preview.expires_at) <= Date.now();
const formatBytes = (bytes: number) => bytes >= 1024 * 1024
  ? `${(bytes / (1024 * 1024)).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} MB`
  : `${Math.max(1, Math.ceil(bytes / 1024)).toLocaleString('zh-CN')} KB`;

function FileDetails({ record }: { record: ImportBatch | ImportPreview }) {
  return <details className="dataset-disclosure">
    <summary>文件与映射信息</summary>
    <dl className="dataset-properties">
      <div><dt>导入批次编号</dt><dd><code>{record.batch_id}</code></dd></div>
      <div><dt>标准文件名</dt><dd>{record.artifact_name} · {formatBytes(record.byte_count)}</dd></div>
      <div><dt>映射版本</dt><dd>{record.mapping_version}</dd></div>
      <div><dt>数据校验指纹 (SHA-256)</dt><dd><code>{record.artifact_sha256}</code></dd></div>
    </dl>
  </details>;
}

function BatchCases({ record, linked = false }: { record: ImportBatch | ImportPreview; linked?: boolean }) {
  return <div className="dataset-case-list">
    {record.cases.map(item => <div className="dataset-case-row" key={item.case_id}>
      <div>{linked
        ? <Link className="text-link" to={`/research/cases/${encodeURIComponent(item.case_id)}`}>{item.title}<Icon name="arrow" size={13} /></Link>
        : <strong>{item.title}</strong>}
        <small><code>{item.case_id}</code> · {caseKindName[item.case_kind]}</small>
      </div>
      <div className="table-quick-links">
        <span>{item.event_count} 条事件</span>
        {linked && <Link className="text-link" to={`/research/cases/${encodeURIComponent(item.case_id)}?view=workflow`}>智能流程与影像 <Icon name="arrow" size={13} /></Link>}
      </div>
    </div>)}
  </div>;
}

function BatchHistory({ batches }: { batches: ImportBatch[] }) {
  const [filter, setFilter] = useState('');
  const query = filter.trim().toLowerCase();
  const matches = batches.filter(batch => [batch.source_name, batch.batch_id, batch.artifact_name, ...batch.cases.map(item => item.case_id)]
    .some(value => value.toLowerCase().includes(query)));
  return <section className="panel dataset-history">
    <div className="dataset-section-heading"><h2>批次历史 <span className="count">{batches.length}</span></h2>
      {batches.length > 0 && <input className="dataset-search" type="search" aria-label="筛选导入批次" placeholder="搜索来源、批次或病例 ID" value={filter} onChange={event => setFilter(event.target.value)} />}
    </div>
    {matches.map(batch => <details className="dataset-batch" key={batch.batch_id}>
      <summary><span className="dataset-batch-name"><strong>{batch.source_name}</strong><small>{batch.artifact_name}</small></span>
        <span className="dataset-batch-count">{batch.case_count} 个病例</span><time dateTime={batch.created_at}>{dateTime(batch.created_at)}</time>
      </summary>
      <div className="dataset-batch-details">
        <p>新增 {batch.imported_case_ids.length} 个 · 已有 {batch.skipped_case_ids.length} 个 · {batch.event_count} 条事件</p>
        <BatchCases record={batch} linked /><FileDetails record={batch} />
      </div>
    </details>)}
    {!matches.length && <p className="dataset-empty">{batches.length ? '没有匹配的批次。' : '暂无导入批次。'}</p>}
  </section>;
}

function PreviewPanel({ preview, expired, pending, error, onEdit, onImport, headingRef }: {
  preview: ImportPreview; expired: boolean; pending: boolean; error: unknown;
  onEdit: () => void; onImport: () => void; headingRef: RefObject<HTMLHeadingElement | null>;
}) {
  return <section className="panel dataset-review">
    <div className="dataset-section-heading"><div><h2 ref={headingRef} tabIndex={-1}>核对导入内容</h2><p>{preview.source_name}</p></div>
      <span className={expired ? 'pill outline' : 'pill soft'}>{expired ? '预检已失效' : '待确认'}</span>
    </div>
    <dl className="dataset-totals">
      <div><dt>可导入病例</dt><dd>{preview.case_count}</dd></div>
      <div><dt>病程事件</dt><dd>{preview.event_count}</dd></div>
      <div><dt>无日期资料</dt><dd>{preview.unplaced_count}</dd></div>
      <div><dt>排除病例</dt><dd>{preview.rejected_count}</dd></div>
    </dl>
    {preview.unplaced_count > 0 && <p className="dataset-hint">无日期资料保留供核对，历史运行仅使用触发事件前可定位的事实。</p>}
    {preview.warnings.length > 0 && <ul className="dataset-warnings" aria-label="映射提示">{preview.warnings.map(warning =>
      <li key={warning.message}>{warning.message}（{warning.count}）</li>)}</ul>}
    {preview.rejected_count > 0 && <details className="dataset-disclosure"><summary>排除原因（{preview.rejected_count}）</summary>
      <ul>{preview.rejected.map((item, index) => <li key={`${item.case_id}-${index}`}><code>{item.case_id}</code> · {item.reason}</li>)}</ul>
      {preview.rejected_count > preview.rejected.length && <small>显示前 {preview.rejected.length} 条。</small>}
    </details>}
    {preview.case_count > 0 && <BatchCases record={preview} />}
    <FileDetails record={preview} />
    <InlineError error={error} />
    <footer className="dataset-actions">
      <button className="button primary" disabled={pending || expired || !preview.case_count} onClick={onImport}>
        {pending ? '正在写入…' : `确认导入 ${preview.case_count} 个病例`}
      </button>
      <button className="button secondary" disabled={pending} onClick={onEdit}>{expired ? '重新预检' : '返回修改'}</button>
      <small>{expired ? '请重新获取预检结果。' : `有效至 ${dateTime(preview.expires_at)}`}</small>
    </footer>
  </section>;
}

export function DatasetPage() {
  const client = useQueryClient();
  const catalog = useQuery({ queryKey: ['datasets'], queryFn: researchApi.datasets });
  const [source, setSource] = useState('synthea_csv');
  const [method, setMethod] = useState<'online' | 'file'>('online');
  const [limitText, setLimitText] = useState('10');
  const [file, setFile] = useState<File>();
  const [preview, setPreview] = useState<ImportPreview>();
  const [imported, setImported] = useState<ImportBatch>();
  const [expired, setExpired] = useState(false);
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const sourceSelect = useRef<HTMLSelectElement>(null);
  const limit = Number(limitText);
  const limitValid = Number.isInteger(limit) && limit >= 1 && limit <= 50;
  const selected = catalog.data?.sources.find(item => item.source === source);
  const fromWeb = !!selected?.download_url && method === 'online';
  const maxBytes = catalog.data?.max_upload_bytes ?? 20 * 1024 * 1024;

  const load = useMutation({
    mutationFn: async () => {
      if (!limitValid) throw new Error('每批可选择 1 至 50 个病例。');
      if (fromWeb) return researchApi.connectDataset(source, limit);
      if (!file || !file.size || file.size > maxBytes) throw new Error(`请选择非空文件，最大 ${formatBytes(maxBytes)}。`);
      return researchApi.previewDataset(source, file, limit);
    },
    onSuccess: result => { setExpired(nowExpired(result)); setPreview(result); },
  });
  const commit = useMutation({
    mutationFn: (id: string) => researchApi.importDataset(id),
    onSuccess: result => {
      setImported(result);
      setPreview(undefined);
      void client.invalidateQueries({ queryKey: ['datasets'] });
      void client.invalidateQueries({ queryKey: ['research-cases'] });
    },
    onError: error => {
      if (error instanceof APIError && error.code === 'IMPORT_PREVIEW_EXPIRED') setExpired(true);
    },
  });

  useEffect(() => {
    if (!preview) return;
    const expiry = window.setTimeout(() => setExpired(true), Math.max(0, Date.parse(preview.expires_at) - Date.now()));
    return () => window.clearTimeout(expiry);
  }, [preview]);
  useEffect(() => {
    if (preview || imported) reviewHeading.current?.focus();
  }, [preview, imported]);

  if (catalog.isPending) return <Loading />;
  if (catalog.isError) return <ErrorState error={catalog.error} retry={() => void catalog.refetch()} />;
  if (!selected) return <ErrorState error={new Error('当前来源不可用，请刷新来源目录。')} retry={() => void catalog.refetch()} />;

  const busy = load.isPending || commit.isPending;
  const returnToSource = () => {
    setPreview(undefined); setImported(undefined); setExpired(false);
    load.reset(); commit.reset();
    requestAnimationFrame(() => sourceSelect.current?.focus());
  };
  const startNext = () => {
    setFile(undefined);
    if (fileInput.current) fileInput.current.value = '';
    returnToSource();
  };
  return <div className="research-page page-enter dataset-console">
    <header className="page-heading"><div><h1>外部医学数据集导入</h1><p>接入 Synthea、TCIA NSCLC、TCGA / cBioPortal 公开队列或标准研究 JSON，完成指纹校验与时序隔离后原子写入病例库。</p></div>
      <div className="button-group">
        <a className="button secondary" href="/api/v2/datasets/template?source=tcga_cbioportal_tsv" download><Icon name="download" size={15} />TCGA/cBioPortal 模板</a>
        <a className="button secondary" href="/api/v2/datasets/template" download><Icon name="download" size={15} />标准病例模板 (JSON)</a>
      </div>
    </header>
    <div className="dataset-source-grid" hidden={!!preview || !!imported}>
      <section className="panel"><h2>新建导入</h2>
        <form className="research-form dataset-form" onSubmit={event => { event.preventDefault(); if (!busy) load.mutate(); }}>
          <div className="dataset-input-pair">
            <label>数据来源<select ref={sourceSelect} value={source} disabled={busy} onChange={event => {
              const next = event.target.value;
              setSource(next); setFile(undefined); setMethod(catalog.data.sources.find(item => item.source === next)?.download_url ? 'online' : 'file'); load.reset();
            }}>{catalog.data.sources.map(item => <option key={item.source} value={item.source}>{item.name} · {item.format}</option>)}</select></label>
            <label>病例数上限<input type="number" min={1} max={50} step={1} required value={limitText} disabled={busy} onChange={event => { setLimitText(event.target.value); load.reset(); }} /></label>
          </div>
          {selected.download_url && <fieldset className="dataset-method"><legend>获取方式</legend>
            <label><input type="radio" name="dataset-method" checked={fromWeb} disabled={busy} onChange={() => { setMethod('online'); load.reset(); }} />连接官方数据源</label>
            <label><input type="radio" name="dataset-method" checked={!fromWeb} disabled={busy} onChange={() => { setMethod('file'); load.reset(); }} />本地文件</label>
          </fieldset>}
          <div hidden={fromWeb}>
            <label>上传文件 · {selected.format}，最大 {formatBytes(maxBytes)}
              <input ref={fileInput} key={source} type="file" accept={formats[source]} disabled={busy} onChange={event => { setFile(event.target.files?.[0]); load.reset(); }} />
            </label>
          </div>
          <InlineError error={load.error} />
          <div className="dataset-actions"><button className="button primary" disabled={busy || !limitValid || (!fromWeb && !file)}>
            <Icon name={fromWeb ? 'network' : 'file'} size={16} />{load.isPending ? (fromWeb ? '正在连接并预检…' : '正在预检…') : '开始预检'}
          </button><small>{fromWeb ? selected.filename : '仅支持所选来源对应的文件格式。'}</small></div>
        </form>
      </section>
      <aside className="panel dataset-source-info"><h2>来源说明</h2><h3>{selected.name}</h3><p>{selected.description}</p>
        <dl className="dataset-properties"><div><dt>许可</dt><dd>{selected.license}</dd></div><div><dt>引用</dt><dd>{selected.citation}</dd></div></dl>
        {selected.source_url && <a className="text-link" href={selected.source_url} target="_blank" rel="noreferrer">查看官方说明 <Icon name="arrow" size={14} /></a>}
      </aside>
    </div>
    {preview && <PreviewPanel preview={preview} headingRef={reviewHeading} expired={expired} pending={commit.isPending} error={commit.error} onEdit={returnToSource}
      onImport={() => { if (nowExpired(preview)) setExpired(true); else commit.mutate(preview.preview_id); }} />}
    {imported && <section className="panel dataset-result">
      <div className="dataset-section-heading"><div><h2 ref={reviewHeading} tabIndex={-1}>{imported.already_imported ? '批次已存在' : '导入完成'}</h2>
        <p>{imported.already_imported ? '已找到相同批次，本次新增 0 个病例。' : `新增 ${imported.imported_case_ids.length} 个病例，跳过 ${imported.skipped_case_ids.length} 个已有病例。`}</p></div>
        <button className="button secondary" onClick={startNext}>继续导入</button>
      </div><BatchCases record={imported} linked /><FileDetails record={imported} />
    </section>}
    <BatchHistory batches={catalog.data.batches} />
  </div>;
}
