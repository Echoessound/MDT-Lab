import { useId, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { DecisionBadge, Icon, Status } from '../ui';
import { researchApi } from './api';
import { inputThroughTrigger } from './run-input';
import { EvidenceButtons, InlineError, OpinionView, SafetyPanel, formatValue, roleNames } from './components';
import type { Evidence, ResearchCase, Role, Run } from './schemas';
import './agent-console.css';

type Stage = 'input' | 'discussion' | 'gate' | 'report';
type Selection = Role | Stage;
type EvidenceHandler = (evidence: Evidence) => void;
type GraphProps = { run: Run; onEvidence: EvidenceHandler };
const gateState = { passed: '检查通过', needs_information: '资料待补', blocked: '已阻断' };

function InputInspector({ run }: { run: Run }) {
  const source = useQuery({
    queryKey: ['research-case', run.case_id, run.case_version],
    queryFn: () => researchApi.case(run.case_id, run.case_version),
  });
  return <>
    <div className="inspector-title"><h3>运行输入</h3>
      <Link className="text-link" to={`/research/cases/${encodeURIComponent(run.case_id)}?version=${run.case_version}&trigger=${encodeURIComponent(run.trigger_event_id)}&view=sources`}>查看版本来源 <Icon name="arrow" size={13} /></Link>
    </div>
    {source.isPending ? <p role="status">正在读取 v{run.case_version} 病例资料…</p> : source.isError ?
      <InlineError error={source.error} /> : <InputFields source={source.data} run={run} />}
  </>;
}

function InputFields({ source, run }: { source: ResearchCase; run: Run }) {
  const input = inputThroughTrigger(source, run.trigger_event_id);
  const trigger = input?.timeline.at(-1);
  return <dl className="inspector-values">
    <div><dt>版本</dt><dd>{source.case_id} · v{source.version}</dd></div>
    <div><dt>触发事件</dt><dd>{trigger ? `${trigger.occurred_at} · ${trigger.title}` : run.trigger_event_id}</dd></div>
    <div><dt>可见病程</dt><dd>{input ? `${input.timeline.length} 条事件 · ${input.timeline.reduce((count, event) => count + Object.keys(event.facts).length, 0)} 项事实` : '无法定位触发事件'}</dd></div>
    <div><dt>数据来源</dt><dd>{source.provenance.map(source => <span key={source.source_name}>{source.source_name} · {source.dataset_version}</span>)}</dd></div>
  </dl>;
}

function SpecialistInspector({ run, role, onEvidence }: GraphProps & { role: Role }) {
  const agent = run.agents.find(item => item.agent_id === role);
  if (!agent) return null;
  const config = run.model_configuration.find(item => item.agent_id === role);
  const reasons = run.routing?.reasons.filter(item => item.agent_id === role) ?? [];
  return <>
    <div className="inspector-title"><h3>{roleNames[role]}意见</h3>
      <Link className="text-link" to={`/settings/models?agent=${role}`}>模型设置 <Icon name="settings" size={13} /></Link>
    </div>
    {agent.error && <p className="inline-error">调用失败 · {agent.error}</p>}
    {agent.opinion ? <>
      <OpinionView opinion={agent.opinion} onEvidence={onEvidence} />
      {agent.previous_opinion && <details><summary>讨论前意见</summary><OpinionView opinion={agent.previous_opinion} onEvidence={onEvidence} /></details>}
      {agent.opinion.claims.length > 0 && <details>
        <summary>主张与证据（{agent.opinion.claims.length}）</summary>
        <dl className="inspector-values">{agent.opinion.claims.map((claim, index) => {
          const cited = agent.opinion!.evidence_refs.find(item => item.evidence_id === claim.evidence_id);
          return <div key={index}><dt>{claim.fact_key}</dt><dd>{formatValue(claim.value)} {cited ?
            <button className="text-link" type="button" onClick={() => onEvidence(cited)}>{claim.evidence_id}</button> :
            <code>{claim.evidence_id}</code>}</dd></div>;
        })}</dl>
      </details>}
    </> : <p>{agent.status === 'skipped' ? '未参与此运行。' : '尚无有效意见。'}</p>}
    {reasons.length > 0 && <details><summary>调度依据</summary>
      {reasons.map(item => <p key={item.rule_id}>{item.description} <code>{item.rule_id}</code></p>)}
    </details>}
    {config && <details><summary>本次模型参数 · {config.model}</summary>
      <dl className="inspector-values">
        <div><dt>连接</dt><dd>{config.configuration_source === 'agent' ? '独立配置' : '共享默认'} · {config.provider}</dd></div>
        <div><dt>服务地址</dt><dd><code>{config.base_url}</code></dd></div>
        <div><dt>生成参数</dt><dd>超时 {config.timeout_seconds} 秒 · 温度 {config.temperature} · 最大输出 {config.max_output_tokens} tokens</dd></div>
      </dl>
    </details>}
    {!config && run.mode === 'llm' && agent.status !== 'skipped' && <p className="muted">此运行未记录该专科的模型参数。</p>}
  </>;
}

function ReviewInspector({ run, onEvidence, selected }: GraphProps & { selected: 'discussion' | 'gate' }) {
  const report = useQuery({
    queryKey: ['research-report', run.run_id], queryFn: () => researchApi.report(run.run_id),
    enabled: run.report_ready, staleTime: Infinity,
  });
  const refs = report.data?.evidence_registry ?? run.agents.flatMap(item => item.opinion?.evidence_refs ?? []);
  if (selected === 'gate') return run.safety ?
    <SafetyPanel safety={run.safety} evidence={refs} onEvidence={onEvidence} /> : <><h3>证据检查</h3><p>尚无检查结果。</p></>;
  return <>
    <h3>初始分歧</h3>
    {report.data && <p>讨论 {report.data.discussion_rounds} 轮 · 最终保留 {report.data.unresolved_conflicts.length} 项分歧</p>}
    {report.isError && <InlineError error={report.error} />}
    {run.conflicts.length ? run.conflicts.map(conflict => (
      <div className="conflict-row" key={conflict.conflict_id}>
        <strong>{conflict.description}</strong>
        <p>{conflict.agent_ids.map(role => roleNames[role]).join('、')} · {conflict.dimension}
        </p>
        <EvidenceButtons evidence={conflict.evidence_ids.flatMap(id => refs.find(item => item.evidence_id === id) ?? [])} onSelect={onEvidence} />
      </div>
    )) : <p>{run.completed_nodes.includes('conflict_detection') ? '未发现分歧。' : '尚无分歧检查结果。'}</p>}
  </>;
}

function Node({ title, detail, selected, target, active, children, choose }: {
  title: string; detail: string; selected: Selection; target: Selection; active?: boolean; children?: ReactNode;
  choose: (target: Selection) => void;
}) {
  return <button type="button" className="console-flow-node" aria-pressed={selected === target} data-done={!!active}
    onClick={() => choose(target)}>
    <strong>{title}</strong><small>{detail}</small>{children}
  </button>;
}

export function CollaborationGraph({ run, onEvidence }: GraphProps) {
  const [selection, setSelection] = useState<Selection>();
  const selected = selection ?? run.routing?.selected_agents[0] ?? 'input';
  const inspector = useId();
  const conflictDone = run.completed_nodes.includes('conflict_detection');
  const discussionDetail = run.completed_nodes.includes('targeted_discussion') ? '讨论已结束'
    : run.running_nodes.includes('targeted_discussion') ? '正在讨论'
    : conflictDone ? `${run.conflicts.length} 项分歧` : '待检查';
  const shared = { selected, choose: setSelection };
  return <section className="panel console-graph" aria-label="协作流程">
    <div className="model-section-heading"><h2>协作流程</h2><span className="pill outline">{run.mode === 'mock' ? '本地规则 · Mock' : '模型服务 · LLM'}</span></div>
    <div className="console-flow" role="group" aria-label="选择流程节点" aria-controls={inspector}>
      <div className="console-flow-stage"><Node {...shared} target="input" title="病例输入" detail={`v${run.case_version} · ${run.trigger_event_id}`} active={run.completed_nodes.includes('case_validation')} /></div>
      <div className="console-flow-specialists" role="group" aria-label="专科评议">
        {run.agents.map(agent => <div className="specialist-branch" data-skipped={agent.status === 'skipped'} key={agent.agent_id}>
          <Node {...shared} target={agent.agent_id} title={roleNames[agent.agent_id]}
            detail={agent.opinion ? `${agent.opinion.evidence_refs.length} 条引用` : ''}>
            <Status status={agent.status} />
          </Node>
        </div>)}
      </div>
      <div className="console-flow-stage"><Node {...shared} target="discussion" title="分歧讨论" detail={discussionDetail} active={conflictDone} /></div>
      <div className="console-flow-stage" data-gate={run.safety?.status}><Node {...shared} target="gate" title="证据检查"
        detail={run.safety ? gateState[run.safety.status] : '待检查'} active={!!run.safety} /></div>
      <div className="console-flow-stage"><Node {...shared} target="report" title="运行报告" detail={run.report_ready ? '已保存' : '未生成'} active={run.report_ready} /></div>
    </div>
    <div className="console-inspector" id={inspector}>
      {selected === 'input' ? <InputInspector run={run} /> :
        selected === 'discussion' || selected === 'gate' ? <ReviewInspector run={run} onEvidence={onEvidence} selected={selected} /> :
        selected === 'report' ? <>
          <div className="inspector-title"><h3>运行报告</h3>
            {run.report_ready && <Link to={`/research/runs/${run.run_id}/report`} className="text-link">打开报告 <Icon name="arrow" size={13} /></Link>}
          </div>
          {run.safety && <DecisionBadge decision={run.safety.decision} />}
          <p>{run.report_ready ? '报告已保存' : '尚未生成报告'} · 共 {run.last_seq} 条审计记录</p>
        </> : <SpecialistInspector run={run} role={selected} onEvidence={onEvidence} />}
    </div>
  </section>;
}
