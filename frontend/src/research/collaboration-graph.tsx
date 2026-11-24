import { useId, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { DecisionBadge, Icon, Status } from '../ui';
import { researchApi } from './api';
import { inputThroughTrigger } from './run-input';
import { EvidenceButtons, InlineError, OpinionView, SafetyPanel, roleNames } from './components';
import type { Evidence, ResearchCase, Role, Run } from './schemas';
import {
  conflictDimensionLabel,
  errorCodeLabel,
  factKeyLabel,
  formatFactValue,
  providerLabelZh,
  ruleIdLabel,
  sourceNameLabel,
} from './zh-dict';
import './agent-console.css';

type Stage = 'input' | 'discussion' | 'gate' | 'report';
type Selection = Role | Stage;
type EvidenceHandler = (evidence: Evidence) => void;
type GraphProps = { run: Run; onEvidence: EvidenceHandler };
const gateState = { passed: '核验通过', needs_information: '资料待补', blocked: '门控阻断' };

function InputInspector({ run }: { run: Run }) {
  const source = useQuery({
    queryKey: ['research-case', run.case_id, run.case_version],
    queryFn: () => researchApi.case(run.case_id, run.case_version),
  });
  return <>
    <div className="inspector-title"><h3>冻结病程输入快照</h3>
      <Link className="text-link" to={`/research/cases/${encodeURIComponent(run.case_id)}?version=${run.case_version}&trigger=${encodeURIComponent(run.trigger_event_id)}&view=sources`}>查看数据来源与溯源 <Icon name="arrow" size={13} /></Link>
    </div>
    {source.isPending ? <p role="status">正在读取 v{run.case_version} 病例资料…</p> : source.isError ?
      <InlineError error={source.error} /> : <InputFields source={source.data} run={run} />}
  </>;
}

function InputFields({ source, run }: { source: ResearchCase; run: Run }) {
  const input = inputThroughTrigger(source, run.trigger_event_id);
  const trigger = input?.timeline.at(-1);
  return <dl className="inspector-values">
    <div><dt>锁定病例版本</dt><dd><code>{source.case_id}</code> · 版本 v{source.version}</dd></div>
    <div><dt>触发截点事件</dt><dd>{trigger ? `${trigger.occurred_at} · ${trigger.title}（${trigger.event_id}）` : run.trigger_event_id}</dd></div>
    <div><dt>可见病程边界</dt><dd>{input ? `纳入截点前 ${input.timeline.length} 条事件 · 共 ${input.timeline.reduce((count, event) => count + Object.keys(event.facts).length, 0)} 项结构化临床事实` : '无法定位触发事件'}</dd></div>
    <div><dt>数据来源声明</dt><dd>{source.provenance.map(item => <span key={item.source_name}>{sourceNameLabel(item.source_name)}（版本 {item.dataset_version}）</span>)}</dd></div>
  </dl>;
}

function SpecialistInspector({ run, role, onEvidence }: GraphProps & { role: Role }) {
  const agent = run.agents.find(item => item.agent_id === role);
  if (!agent) return null;
  const config = run.model_configuration.find(item => item.agent_id === role);
  const reasons = run.routing?.reasons.filter(item => item.agent_id === role) ?? [];
  return <>
    <div className="inspector-title"><h3>{roleNames[role]}审阅详情</h3>
      <Link className="text-link" to={`/settings/models?agent=${role}`}>专科模型配置 <Icon name="settings" size={13} /></Link>
    </div>
    {agent.error && <p className="inline-error">专科调用或校验未通过 · {errorCodeLabel(agent.error)}</p>}
    {agent.opinion ? <>
      <OpinionView opinion={agent.opinion} onEvidence={onEvidence} />
      {agent.previous_opinion && <details><summary>展开定向协商前的初审意见</summary><OpinionView opinion={agent.previous_opinion} onEvidence={onEvidence} /></details>}
      {agent.opinion.claims.length > 0 && <details open>
        <summary>结构化临床主张与证据链（{agent.opinion.claims.length} 项）</summary>
        <dl className="inspector-values">{agent.opinion.claims.map((claim, index) => {
          const cited = agent.opinion!.evidence_refs.find(item => item.evidence_id === claim.evidence_id);
          return <div key={index}><dt>{factKeyLabel(claim.fact_key)}</dt><dd>{formatFactValue(claim.value)} {cited ?
            <button className="text-link" type="button" onClick={() => onEvidence(cited)}>溯源证据 {claim.evidence_id}</button> :
            <code>{claim.evidence_id}</code>}</dd></div>;
        })}</dl>
      </details>}
    </> : <p>{agent.status === 'skipped' ? '当前触发事件无需该专科介入，系统已自动跳过以节省调用。' : '尚无有效结构化审阅意见。'}</p>}
    {reasons.length > 0 && <details><summary>查看路由调度依据</summary>
      {reasons.map(item => <p key={item.rule_id}>{item.description} <code>{ruleIdLabel(item.rule_id)}</code></p>)}
    </details>}
    {config && <details><summary>本次冻结模型配置 · {config.model}</summary>
      <dl className="inspector-values">
        <div><dt>配置来源</dt><dd>{config.configuration_source === 'agent' ? '专科独立连接' : '继承共享默认'} · {providerLabelZh(config.provider, config.model)}</dd></div>
        {config.profile_name && <div><dt>运行采用的方案</dt><dd>{config.profile_name}</dd></div>}
        <div><dt>服务地址</dt><dd><code>{config.base_url}</code></dd></div>
        <div><dt>生成参数</dt><dd>超时 {config.timeout_seconds} 秒 · 采样温度 {config.temperature} · 最大输出 {config.max_output_tokens} 字词</dd></div>
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
    <SafetyPanel safety={run.safety} evidence={refs} onEvidence={onEvidence} /> : <><h3>证据与安全门控</h3><p>等待专科审阅完成后执行门控核验…</p></>;
  return <>
    <div className="inspector-title">
      <h3>跨专科分歧检测与定向协商</h3>
      {report.data && <span className="pill soft">协商 {report.data.discussion_rounds} 轮 · 最终保留 {report.data.unresolved_conflicts.length} 项分歧</span>}
    </div>
    {report.isError && <InlineError error={report.error} />}
    {run.conflicts.length ? run.conflicts.map(conflict => (
      <div className="conflict-row" key={conflict.conflict_id}>
        <strong>{conflict.description}</strong>
        <p>涉及专科：{conflict.agent_ids.map(role => roleNames[role]).join('、')} · 分歧类型：<span className="pill outline">{conflictDimensionLabel(conflict.dimension)}</span></p>
        <EvidenceButtons evidence={conflict.evidence_ids.flatMap(id => refs.find(item => item.evidence_id === id) ?? [])} onSelect={onEvidence} />
      </div>
    )) : <p>{run.completed_nodes.includes('conflict_detection') ? '各参与专科初审意见与底层事实一致，未检测到分歧，无需启动额外协商。' : '尚无分歧检查结果。'}</p>}
  </>;
}

function Node({ title, detail, selected, target, active, running, children, choose }: {
  title: string; detail: string; selected: Selection; target: Selection; active?: boolean; running?: boolean; children?: ReactNode;
  choose: (target: Selection) => void;
}) {
  return <button type="button" className={`console-flow-node ${running ? 'node-is-running' : ''}`} aria-pressed={selected === target} data-done={!!active}
    onClick={() => choose(target)}>
    <strong>{title}</strong><small>{detail}</small>{children}
  </button>;
}

export function CollaborationGraph({ run, onEvidence }: GraphProps) {
  const [selection, setSelection] = useState<Selection>();
  const selected = selection ?? run.routing?.selected_agents[0] ?? 'input';
  const inspector = useId();
  const conflictDone = run.completed_nodes.includes('conflict_detection');
  const discussionDetail = run.completed_nodes.includes('targeted_discussion') ? '协商已完成'
    : run.running_nodes.includes('targeted_discussion') ? '正在定向协商'
    : conflictDone ? (run.conflicts.length ? `检出 ${run.conflicts.length} 项分歧` : '意见一致免协商') : '待检查';
  const shared = { selected, choose: setSelection };
  return <section className="panel console-graph" aria-label="协作流程">
    <div className="model-section-heading">
      <div>
        <h2>多智能体序贯协同拓扑图</h2>
        <p className="muted">点击任意流程节点或专科卡片，下方将滑入对应的证据引用、分歧协商及门控核验明细</p>
      </div>
      <span className="pill outline">{run.mode === 'mock' ? '本地规则仿真' : '大模型智能推演'}</span>
    </div>
    <div className="console-flow" role="group" aria-label="选择流程节点" aria-controls={inspector}>
      <div className="console-flow-stage">
        <Node {...shared} target="input" title="冻结病例输入" detail={`v${run.case_version} · 截点 ${run.trigger_event_id}`}
          active={run.completed_nodes.includes('case_validation')} running={run.running_nodes.includes('case_validation')} />
      </div>
      <div className="console-flow-specialists" role="group" aria-label="专科评议">
        {run.agents.map(agent => <div className="specialist-branch" data-skipped={agent.status === 'skipped'} key={agent.agent_id}>
          <Node {...shared} target={agent.agent_id} title={roleNames[agent.agent_id]}
            active={agent.status === 'completed'} running={agent.status === 'running'}
            detail={agent.opinion ? `已引用 ${agent.opinion.evidence_refs.length} 条证据` : agent.status === 'skipped' ? '按规则跳过' : ''}>
            <Status status={agent.status} />
          </Node>
        </div>)}
      </div>
      <div className="console-flow-stage">
        <Node {...shared} target="discussion" title="分歧检测与协商" detail={discussionDetail}
          active={conflictDone} running={run.running_nodes.includes('targeted_discussion') || run.running_nodes.includes('conflict_detection')} />
      </div>
      <div className="console-flow-stage" data-gate={run.safety?.status}>
        <Node {...shared} target="gate" title="证据与安全门控"
          detail={run.safety ? gateState[run.safety.status] : '待核验'} active={!!run.safety}
          running={run.running_nodes.includes('safety_gate')} />
      </div>
      <div className="console-flow-stage">
        <Node {...shared} target="report" title="评议报告归档" detail={run.report_ready ? '已原子落库' : '未生成'}
          active={run.report_ready} running={run.running_nodes.includes('report')} />
      </div>
    </div>
    <div className="console-inspector inspector-enter" id={inspector} key={selected}>
      {selected === 'input' ? <InputInspector run={run} /> :
        selected === 'discussion' || selected === 'gate' ? <ReviewInspector run={run} onEvidence={onEvidence} selected={selected} /> :
        selected === 'report' ? <>
          <div className="inspector-title"><h3>结构化评议报告</h3>
            {run.report_ready && <Link to={`/research/runs/${run.run_id}/report`} className="button primary"><Icon name="file" size={14} />打开完整评议报告</Link>}
          </div>
          {run.safety && <DecisionBadge decision={run.safety.decision} />}
          <p>{run.report_ready ? '报告与终态审计事件已在同一事务中落库保存。' : '工作流尚未生成最终报告。'} · 累计记录 {run.last_seq} 条审计事件</p>
        </> : <SpecialistInspector run={run} role={selected} onEvidence={onEvidence} />}
    </div>
  </section>;
}
