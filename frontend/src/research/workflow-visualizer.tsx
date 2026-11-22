import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { DecisionBadge, Icon, Loading } from '../ui';
import { researchApi } from './api';
import { InlineError, roleNames } from './components';
import type { AblationMatrix, ImagingPipeline, ResearchCase, WorkflowPlan } from './schemas';

import { factKeyLabel, sourceNameLabel } from './zh-dict';

export function MedicalImagingWorkbench({ imaging }: { imaging: ImagingPipeline }) {
  const [selectedId, setSelectedId] = useState('');
  const study = imaging.studies.find(item => item.study_id === selectedId) ?? imaging.studies[0];
  if (!study) {
    return <section className="panel workflow-card"><h2>影像检查登记</h2>
      <p className="muted">截至 {imaging.trigger_event_id} 没有可见的影像检查记录。</p>
    </section>;
  }
  const badge = {
    documented: { label: '已有登记', cls: 'outline' },
    incomplete: { label: '登记注明资料不全', cls: 'status-running' },
    conflict: { label: '同日记录有矛盾', cls: 'status-failed' },
  }[study.record_status];

  return (
    <section className="panel workflow-card" aria-label="影像检查登记">
      <div className="workspace-section-heading">
        <div>
          <h2>影像检查登记</h2>
          <p className="muted">截至 {imaging.trigger_event_id} 共 {imaging.study_count} 条。当前仅有登记元数据，像素质控与病灶测量均未执行。</p>
        </div>
        <span className={`pill ${badge.cls}`}>{badge.label}</span>
      </div>
      {imaging.studies.length > 1 && (
        <label className="workspace-version-select">选择检查
          <select value={study.study_id} onChange={event => setSelectedId(event.target.value)}>
            {imaging.studies.map(item => (
              <option key={item.study_id} value={item.study_id}>{item.occurred_at} · {item.title}（{item.event_id}）</option>
            ))}
          </select>
        </label>
      )}
      <div>
        <h3>{study.title}</h3>
        <p className="workspace-meta">{study.occurred_at} · {study.event_id} · {sourceNameLabel(study.source_name)}（{study.synthetic ? '合成来源' : '公开来源'}）</p>
      </div>
      {study.record_fields.length > 0 && (
        <div className="workspace-table-scroll">
          <table className="workspace-table">
            <thead><tr><th>登记字段</th><th>记录值</th><th>原始列</th><th>证据编号</th></tr></thead>
            <tbody>{study.record_fields.map(field => (
              <tr key={field.evidence_id}>
                <td>{factKeyLabel(field.fact_key)}</td>
                <td>{field.value === null ? '未记录' : typeof field.value === 'boolean' ? (field.value ? '是' : '否') : String(field.value)}</td>
                <td>{field.source_field ?? '—'}</td><td><code>{field.evidence_id}</code></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {study.conflict_evidence_ids.length > 0 && (
        <p className="subtle-note">需核对的相反记录　{study.conflict_evidence_ids.join('、')}</p>
      )}
      <details className="workspace-advanced">
        <summary>查看来源定位</summary>
        <dl className="detail-list">
          <div><dt>来源版本</dt><dd>{study.dataset_version}</dd></div>
          {study.source_record_id && <div><dt>记录编号</dt><dd>{study.source_record_id}</dd></div>}
          {study.source_record_locator && <div><dt>原始位置</dt><dd>{study.source_record_locator}</dd></div>}
          {study.artifact_sha256 && <div><dt>文件指纹 SHA-256</dt><dd><code>{study.artifact_sha256}</code></dd></div>}
        </dl>
      </details>
    </section>
  );
}

export function AutomatedWorkflowBlueprint({
  plan,
  isLatestVersion,
  onEnriched,
}: {
  plan: WorkflowPlan;
  isLatestVersion: boolean;
  onEnriched?: (updated: ResearchCase) => void;
}) {
  const enrich = useMutation({
    mutationFn: () => researchApi.autoEnrich(plan.case_id, plan.case_version, plan.trigger_event_id),
    onSuccess: updated => {
      onEnriched?.(updated);
    },
  });

  const complexityBadge = {
    standard: 'status-completed',
    elevated: 'status-running',
    high_risk: 'status-failed',
  }[plan.complexity_level];

  const showEnrichAction = isLatestVersion && plan.completeness.can_auto_enrich;

  return (
    <section className="panel workflow-card" aria-label="案例自适应医疗流程蓝图">
      <div className="workspace-section-heading">
        <div>
          <h2>当前截点的审阅计划</h2>
          <p className="muted">以下是根据可见病程生成的建议。实际参与专科可在「专科调度依据」中查看。</p>
        </div>
        <span className={`pill ${complexityBadge}`}>{plan.complexity_label}</span>
      </div>

      <div className="workflow-summary-banner">
        <div>
          <span>当前临床审阅阶段</span>
          <strong>{plan.clinical_phase}</strong>
          <small>已纳入 {plan.visible_event_count} 条可见事件 · 屏蔽 {plan.excluded_future_event_count} 条未来事件</small>
        </div>
        <div>
          <span>严格规则资料完备度</span>
          <strong>{plan.completeness.strict_completeness_score}%</strong>
          <div className="completeness-bar">
            <div style={{ width: `${plan.completeness.strict_completeness_score}%` }} />
          </div>
        </div>
        <div>
          <span>语义推导后完备度</span>
          <strong>{plan.completeness.semantic_completeness_score}%</strong>
          <div className="completeness-bar semantic">
            <div style={{ width: `${plan.completeness.semantic_completeness_score}%` }} />
          </div>
        </div>
        <div>
          <span>预期审阅结论对比</span>
          <div className="predicted-badges">
            <DecisionBadge decision={plan.predicted_decisions.strict_rule_decision} />
            {plan.predicted_decisions.semantic_enriched_decision !== plan.predicted_decisions.strict_rule_decision && (
              <>
                <Icon name="arrow" size={13} />
                <DecisionBadge decision={plan.predicted_decisions.semantic_enriched_decision} />
              </>
            )}
          </div>
        </div>
      </div>

      {plan.completeness.semantic_inferred.length > 0 && (
        <div className="semantic-inference-box">
          <div className="semantic-box-header">
            <div>
              <strong>有来源证据的补齐建议（{plan.completeness.semantic_inferred.length} 项）</strong>
              <p>生成新版本后，可沿证据编号复核所用的历史记录。</p>
            </div>
            {showEnrichAction && (
              <button
                type="button"
                className="button primary"
                disabled={enrich.isPending}
                onClick={() => enrich.mutate()}
              >
                <Icon name="check" size={15} />
                {enrich.isPending ? '正在生成版本…' : `按证据生成 v${plan.case_version + 1}`}
              </button>
            )}
          </div>
          <ul className="semantic-inference-list">
            {plan.completeness.semantic_inferred.map(item => (
              <li key={item.fact_key}>
                <span className="pill soft">{item.fact_label}</span>
                <span>{item.reason}</span>
                <code>{item.source_evidence_id}</code>
              </li>
            ))}
          </ul>
          <InlineError error={enrich.error} />
        </div>
      )}

      {plan.completeness.post_inference_missing.length > 0 && (
        <p className="subtle-note">当前证据仍不足以确认{plan.completeness.post_inference_missing_labels.join('、')}。请核对该截点已有的来源记录。</p>
      )}

      <div className="workflow-dag-grid" aria-label="自动化工作流六阶拓扑">
        {plan.workflow_stages.map(stage => (
          <div key={stage.stage_id} className={`workflow-dag-node status-${stage.status}`}>
            <div className="dag-node-top">
              <span className="dag-step-num">0{stage.step_number}</span>
              <strong>{stage.title}</strong>
              <span className="dag-status-tag">
                {{ active: '已纳入计划', recommended: '按需', skipped: '跳过' }[stage.status]}
              </span>
            </div>
            <p>{stage.description}</p>
          </div>
        ))}
      </div>

      <div className="specialist-task-cards">
        <h3>建议的任务分工（{plan.selected_agents.length} 个专科）</h3>
        <div className="specialist-task-grid">
          {plan.specialist_plan.map(spec => (
            <div key={spec.agent_id} className={`specialist-task-card ${spec.selected ? 'is-selected' : 'is-skipped'}`}>
              <div className="specialist-card-head">
                <strong>{spec.agent_label}</strong>
                <span className={`pill ${spec.selected ? 'soft' : 'outline'}`}>{spec.routing_type}</span>
              </div>
              <p className="specialist-focus">{spec.focus}</p>
              <ul>
                {spec.clinical_tasks.map((task, idx) => <li key={idx}>{task}</li>)}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function AblationExperimentMatrix({ matrix }: { matrix: AblationMatrix }) {
  return (
    <section className="panel workflow-card" aria-label="基线方法组与单因素消融实验矩阵">
      <div className="workspace-section-heading">
        <div>
          <h2>规则仿真方法对照</h2>
          <p className="muted">按当前病例版本和截点运行标准 Mock。B2 与 B3 共享同一批意见。聚合时采用相对多数，平票暂缓，无有效意见时记为无输出。</p>
        </div>
        <span className="pill soft">B3 调用 {matrix.routed_total_calls} 次，固定全员 A3 调用 {matrix.fixed_total_calls} 次，节省率 {matrix.call_saving_pct}%</span>
      </div>

      <div className="workspace-table-scroll">
        <table className="workspace-table ablation-table">
          <thead>
            <tr>
              <th>实验方法组 / 消融配置</th>
              <th>审阅角色</th>
              <th>规则调用 / 失败</th>
              <th>协商轮次</th>
              <th>有效意见聚合</th>
              <th>方法结论</th>
              <th>待补 / 冲突</th>
              <th>比较条件</th>
            </tr>
          </thead>
          <tbody>
            {matrix.methods.map(row => (
              <tr key={row.method_id} className={row.method_id === 'B3' ? 'ablation-highlight-row' : ''}>
                <td>
                  <strong>{row.name}</strong>
                  <small>{row.category} · {row.routing_strategy}</small>
                </td>
                <td>{row.selected_agents.map(r => r === 'general_reviewer' ? '通用审阅者' : roleNames[r]).join('、')}</td>
                <td className="workspace-number"><strong>{row.agent_calls}</strong> / {row.failed_calls}</td>
                <td className="workspace-number">{row.discussion_rounds} 轮</td>
                <td>{row.pre_gate_decision ? <DecisionBadge decision={row.pre_gate_decision} /> : '无输出'}</td>
                <td>{row.final_decision ? <DecisionBadge decision={row.final_decision} /> : '无输出'}</td>
                <td className="workspace-number">{row.missing_count} 项缺口 / {row.unresolved_conflicts} 项冲突</td>
                <td className="ablation-finding-cell">{row.key_finding}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function CaseWorkflowAndImagingSection({
  caseId,
  version,
  triggerEventId,
  isLatestVersion,
  onEnriched,
}: {
  caseId: string;
  version: number;
  triggerEventId: string;
  isLatestVersion: boolean;
  onEnriched?: (updated: ResearchCase) => void;
}) {
  const planQuery = useQuery({
    queryKey: ['research-workflow-plan', caseId, version, triggerEventId],
    queryFn: () => researchApi.workflowPlan(caseId, version, triggerEventId),
  });
  const imagingQuery = useQuery({
    queryKey: ['research-imaging', caseId, version, triggerEventId],
    queryFn: () => researchApi.imagingPipeline(caseId, version, triggerEventId),
  });
  const ablationQuery = useQuery({
    queryKey: ['research-ablation', caseId, version, triggerEventId],
    queryFn: () => researchApi.ablationMatrix(caseId, version, triggerEventId),
  });

  if (planQuery.isPending || imagingQuery.isPending || ablationQuery.isPending) {
    return <Loading />;
  }
  if (planQuery.isError || imagingQuery.isError || ablationQuery.isError) {
    return <InlineError error={planQuery.error || imagingQuery.error || ablationQuery.error} />;
  }

  return (
    <div className="workspace-column">
      <AutomatedWorkflowBlueprint
        plan={planQuery.data}
        isLatestVersion={isLatestVersion}
        onEnriched={onEnriched}
      />
      <MedicalImagingWorkbench imaging={imagingQuery.data} />
      <AblationExperimentMatrix matrix={ablationQuery.data} />
    </div>
  );
}
