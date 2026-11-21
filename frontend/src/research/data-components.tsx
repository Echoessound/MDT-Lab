import { Icon } from '../ui';
import type { ResearchCase } from './schemas';
import { factKeyLabel, formatFactValue, sourceNameLabel } from './zh-dict';
import './dataset-console.css';

export const caseKindName = { synthetic: '合成研究病例', public_research: '公开队列病例', mixed: '公开资料 + 合成扩展' };
const safeUrl = (url: string | null) => url && /^https?:\/\//i.test(url) ? url : undefined;

export function CaseSources({ item }: { item: ResearchCase }) {
  return <section className="panel source-panel">
    <div className="section-heading"><h2>数据来源与合规溯源</h2><span className="pill outline">{caseKindName[item.case_kind]}</span></div>
    {item.provenance.map(source => <details key={source.source_name} open>
      <summary><strong>{sourceNameLabel(source.source_name)}</strong> · 版本 {source.dataset_version}</summary>
      <dl className="dataset-properties">
        <div><dt>使用许可</dt><dd>{source.license}</dd></div>
        {source.citation && <div><dt>文献引用</dt><dd>{source.citation}</dd></div>}
        {source.artifact_name && <div><dt>原始文件</dt><dd>{source.artifact_name}</dd></div>}
        {source.artifact_sha256 && <div><dt>校验指纹</dt><dd><code>{source.artifact_sha256}</code></dd></div>}
      </dl>
      {safeUrl(source.source_url) && <a className="text-link" href={safeUrl(source.source_url)} target="_blank" rel="noreferrer">访问官方数据源说明 <Icon name="arrow" size={14} /></a>}
    </details>)}
    {item.data_notes.map(note => <p className="subtle-note" key={note}>{note}</p>)}
    {!!item.unplaced_records.length && <details open>
      <summary>未定位时间戳的关联临床资料（{item.unplaced_records.length} 组）</summary>
      <p className="subtle-note">原表未提供精确采样日期，为防止历史时点信息泄漏，默认不直接混入历史截点提示词；可通过「智能流程与影像」页签一键锚定推导。</p>
      {item.unplaced_records.map(record => <div className="unplaced-record" key={record.record_id}>
        <h3>{record.title}</h3>
        <dl className="event-facts">{Object.entries(record.facts).map(([key, value]) => <div key={key}><dt>{factKeyLabel(key)}</dt><dd>{formatFactValue(value)}</dd></div>)}</dl>
        <small className="source-locator">源文件位置：{record.source_record_locator}</small><p className="subtle-note">{record.exclusion_reason}</p>
      </div>)}
    </details>}
  </section>;
}
