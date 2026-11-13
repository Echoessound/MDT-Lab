import { useState } from 'react';
import { Link } from 'react-router-dom';
import { DecisionBadge, Icon, Status } from '../ui';
import { OpinionView, SafetyPanel, formatValue, roleNames } from './components';
import type { Evidence, Role, Run } from './schemas';

type Selection = Role | 'input' | 'discussion' | 'gate' | 'report';

export function CollaborationGraph({ run, onEvidence }: { run: Run; onEvidence: (evidence: Evidence) => void }) {
  const [selected, setSelected] = useState<Selection>('oncology');
  const agent = run.agents.find(item => item.agent_id === selected);
  const configuration = run.model_configuration.find(item => item.agent_id === selected);
  const discussionDone = run.completed_nodes.includes('targeted_discussion');
  const conflictDone = run.completed_nodes.includes('conflict_detection');
  const evidence = run.agents.flatMap(item => item.opinion?.evidence_refs ?? []).filter((item, index, items) => items.findIndex(other => other.evidence_id === item.evidence_id) === index);
  const node = (key: Selection, title: string, subtitle: string, active: boolean) => <button type="button" className={`collaboration-node ${selected === key ? 'node-selected' : ''} ${active ? 'node-done' : ''}`} aria-pressed={selected === key} onClick={() => setSelected(key)}><strong>{title}</strong><small>{subtitle}</small></button>;
  return <section className="panel collaboration-panel">
    <div className="section-heading"><div><span className="eyebrow">EXPLAINABLE COLLABORATION</span><h2>从输入到意见，每一步可查看</h2></div><span className="pill outline">{run.mode === 'mock' ? 'Mock 规则演示' : '真实模型运行'}</span></div>
    <p className="muted">点击节点，查看本次记录的依据与结果。连线表示数据传递关系。</p>
    <div className="collaboration-map" aria-label="多 Agent 协作数据流">
      <svg className="collaboration-lines" viewBox="0 0 1000 320" preserveAspectRatio="none" aria-hidden="true"><g fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M140 160 H185 V40 H245 M185 160 V120 H245 M185 160 V200 H245 M185 160 V280 H245 M380 40 H420 V280 H380 M380 120 H420 M380 200 H420 M420 160 H500 M620 160 H690 M810 160 H865" /></g></svg>
      <div className="graph-input">{node('input', '冻结输入', `病例 v${run.case_version}`, run.completed_nodes.includes('case_validation'))}</div>
      <div className="graph-agents">{run.agents.map(item => <button type="button" key={item.agent_id} className={`collaboration-node graph-agent agent-state-${item.status} ${selected === item.agent_id ? 'node-selected' : ''}`} aria-pressed={selected === item.agent_id} onClick={() => setSelected(item.agent_id)}><span><strong>{roleNames[item.agent_id]}</strong><small>{item.opinion ? `${item.opinion.evidence_refs.length} 条引用` : item.status === 'skipped' ? '未命中调度规则' : '等待有效意见'}</small></span><Status status={item.status} /></button>)}</div>
      <div className="graph-discussion">{node('discussion', '分歧与讨论', discussionDone ? '一轮讨论已完成' : run.running_nodes.includes('targeted_discussion') ? '正在定向讨论' : conflictDone ? `${run.conflicts.length} 项初始分歧` : '等待分歧检查', conflictDone)}</div>
      <div className="graph-gate" data-status={run.safety?.status}>{node('gate', '证据门控', run.safety ? ({ passed: '检查通过', needs_information: '需要补充资料', blocked: '存在阻断项' }[run.safety.status]) : '等待校验', !!run.safety)}</div>
      <div className="graph-report">{node('report', '持久报告', run.report_ready ? '已保存 · 可追溯' : run.status === 'cancelled' || run.status === 'failed' ? '未生成报告' : '等待保存', run.report_ready)}</div>
    </div>
    <div className="graph-inspector" aria-live="polite">
      {agent && <><div className="section-heading"><h3>{roleNames[agent.agent_id]} · 本次执行依据</h3><Link className="text-link" to="/settings/models">修改后续运行配置 <Icon name="arrow" size={13} /></Link></div>
        {run.routing?.reasons.filter(reason => reason.agent_id === agent.agent_id).map(reason => <p className="subtle-note" key={reason.rule_id}>{reason.description} <code>{reason.rule_id}</code></p>)}
        {agent.error && <p className="danger-text">本次调用失败：{agent.error}。已有意见仅作为历史记录。</p>}
        {agent.previous_opinion && <details><summary>讨论前的原始意见</summary><OpinionView opinion={agent.previous_opinion} onEvidence={onEvidence} /></details>}
        {agent.opinion ? <><OpinionView opinion={agent.opinion} onEvidence={onEvidence} /><details><summary>结构化主张与对应证据（{agent.opinion.claims.length}）</summary><dl className="event-facts">{agent.opinion.claims.map((claim, index) => <div key={index}><dt>{claim.fact_key}</dt><dd>{formatValue(claim.value)}<br /><code>{claim.evidence_id}</code></dd></div>)}</dl></details></> : <p className="agent-empty">{agent.status === 'skipped' ? '本次跳过，不参与有效意见统计。' : '尚无有效结构化意见。'}</p>}
        {configuration ? <div className="model-provenance"><strong>运行时冻结配置 · {configuration.configuration_source === 'agent' ? '独立设置' : '共享默认'}</strong><p>{configuration.provider} / {configuration.model}</p><code>{configuration.base_url}</code><p>超时 {configuration.timeout_seconds}s · Temperature {configuration.temperature} · 最大输出 {configuration.max_output_tokens} tokens</p></div> : <p className="subtle-note">{run.mode === 'mock' ? '本次使用确定性 Mock，无外部模型请求。' : '此历史运行没有保存独立配置快照；模型信息见有效意见。'}</p>}
      </>}
      {selected === 'input' && <><h3>版本与时间边界</h3><p>病例 {run.case_id} / v{run.case_version}，触发事件 {run.trigger_event_id}。只使用截至该事件可见的病程；无可用日期的资料不进入模型上下文。</p><Link className="text-link" to={`/research/cases/${run.case_id}`}>打开病例与来源 <Icon name="arrow" size={13} /></Link></>}
      {selected === 'discussion' && <><h3>初始分歧与有界协商</h3>{run.conflicts.map(conflict => <div className="research-conflict" key={conflict.conflict_id}><strong>{conflict.description}</strong><p>{conflict.agent_ids.map(role => roleNames[role]).join(' / ')}</p><code>{conflict.dimension}</code></div>)}{!run.conflicts.length && <p className="muted">{conflictDone ? '本次没有检测到结构化分歧，无需定向讨论。' : '尚未完成分歧检查。'}</p>}<p className="subtle-note">最多一轮讨论；点击专科节点查看前后意见。最终未解决分歧保留在报告中。</p></>}
      {selected === 'gate' && (run.safety ? <SafetyPanel safety={run.safety} evidence={evidence} onEvidence={onEvidence} /> : <p className="muted">门控尚未执行。会检查证据引用、资料完整性、失败角色与未解决分歧。</p>)}
      {selected === 'report' && <><h3>{run.report_ready ? '报告与完成事件已一起保存' : '报告尚未保存'}</h3>{run.safety && <DecisionBadge decision={run.safety.decision} />}<p className="subtle-note">报告保留冻结输入、初始与最终意见、分歧、证据和模型参数。审计序列已记录至 #{run.last_seq}。</p>{run.report_ready && <Link className="button primary" to={`/research/runs/${run.run_id}/report`}>查看完整报告 <Icon name="arrow" size={14} /></Link>}</>}
    </div>
  </section>;
}
