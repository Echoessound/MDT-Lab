import { Icon } from '../ui';
import { formatValue } from './components';
import type { ResearchCase } from './schemas';
import './dataset-console.css';

export const caseKindName = { synthetic: '合成研究病例', public_research: '公开研究病例', mixed: '公开资料 + 合成扩展' };
const safeUrl = (url: string | null) => url && /^https?:\/\//i.test(url) ? url : undefined;

export function CaseSources({ item }: { item: ResearchCase }) {
  return <section className="panel source-panel">
    <div className="section-heading"><h2>数据来源</h2><span className="pill outline">{caseKindName[item.case_kind]}</span></div>
    {item.provenance.map(source => <details key={source.source_name}>
      <summary>{source.source_name} · {source.dataset_version}</summary>
      <dl className="dataset-properties">
        <div><dt>使用许可</dt><dd>{source.license}</dd></div>
        {source.citation && <div><dt>引用</dt><dd>{source.citation}</dd></div>}
        {source.artifact_name && <div><dt>文件</dt><dd>{source.artifact_name}</dd></div>}
        {source.artifact_sha256 && <div><dt>SHA-256</dt><dd><code>{source.artifact_sha256}</code></dd></div>}
      </dl>
      {safeUrl(source.source_url) && <a className="text-link" href={safeUrl(source.source_url)} target="_blank" rel="noreferrer">打开来源 <Icon name="arrow" size={14} /></a>}
    </details>)}
    {item.data_notes.map(note => <p className="subtle-note" key={note}>{note}</p>)}
    {!!item.unplaced_records.length && <details>
      <summary>未定位时间的资料（{item.unplaced_records.length} 组）</summary>
      <p className="subtle-note">仅供来源核对，历史运行已排除这些资料。</p>
      {item.unplaced_records.map(record => <div className="unplaced-record" key={record.record_id}>
        <h3>{record.title}</h3>
        <dl className="event-facts">{Object.entries(record.facts).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{formatValue(value)}</dd></div>)}</dl>
        <small className="source-locator">{record.source_record_locator}</small><p className="subtle-note">{record.exclusion_reason}</p>
      </div>)}
    </details>}
  </section>;
}
