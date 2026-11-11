import { Link } from 'react-router-dom';
import { Icon } from '../ui';
import { formatValue } from './components';
import type { ResearchCase, Run } from './schemas';

export const caseKindName = { synthetic: '合成研究病例', public_research: '公开研究病例', mixed: '公开资料 + 合成扩展' };
const safeUrl = (url: string | null) => url && /^https?:\/\//i.test(url) ? url : undefined;

export function CaseSources({ item }: { item: ResearchCase }) {
  return <section className="panel source-panel"><div className="section-heading"><div><div className="eyebrow">DATA PROVENANCE</div><h2>来源与相关资料</h2></div><span className="pill outline">{caseKindName[item.case_kind]}</span></div>
    {item.provenance.map(source => <details key={source.source_name}><summary>{source.source_name} · {source.dataset_version}</summary><p>{source.license}</p>{source.citation && <p>{source.citation}</p>}{safeUrl(source.source_url) && <a className="text-link" href={safeUrl(source.source_url)} target="_blank" rel="noreferrer">查看原始来源 <Icon name="arrow" size={14} /></a>}{source.artifact_sha256 && <p className="source-hash">SHA-256 · {source.artifact_sha256}</p>}</details>)}
    {item.data_notes.map(note => <p className="subtle-note" key={note}>{note}</p>)}
    {!!item.unplaced_records.length && <details><summary>未定位时间的相关资料 · {item.unplaced_records.length} 组</summary><p className="subtle-note">这些资料保留用于核对来源，不进入历史运行的 Agent 输入或报告快照。</p>{item.unplaced_records.map(record => <div className="unplaced-record" key={record.record_id}><h3>{record.title}</h3><dl className="event-facts">{Object.entries(record.facts).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{formatValue(value)}</dd></div>)}</dl><small className="source-locator">{record.source_record_locator}</small><p className="subtle-note">{record.exclusion_reason}</p></div>)}</details>}
  </section>;
}

export function DataPath({ item, run }: { item: ResearchCase; run: Run }) {
  const facts = item.timeline.reduce((sum, event) => sum + Object.keys(event.facts).length, 0);
  return <section className="panel"><div className="section-heading"><div><div className="eyebrow">LIVE DATA PATH</div><h2>本次 Agent 数据通路</h2></div><Link className="text-link" to="/research/agents">Agent 群 <Icon name="arrow" size={14} /></Link></div><div className="data-path">
    <div><small>01 / 来源</small><strong>{item.provenance.map(source => source.source_name).join(' · ')}</strong><span>{caseKindName[item.case_kind]}</span></div>
    <div><small>02 / 冻结输入</small><strong>v{run.case_version} · {item.timeline.length} 条事件</strong><span>{facts} 项事实 · 截至 {run.trigger_event_id}</span></div>
    <div><small>03 / 专科协作</small><strong>{run.routing ? `${run.routing.selected_agents.length} 个参与角色` : '等待调度'}</strong><span>{run.agents.filter(agent => agent.opinion).length} 份当前有效意见</span></div>
    <div><small>04 / 输出</small><strong>{run.report_ready ? '报告已保存' : run.error ? '运行异常' : '等待报告'}</strong><span>{run.last_seq} 条审计 · {run.safety?.decision ?? '等待门控'}</span></div>
  </div></section>;
}
