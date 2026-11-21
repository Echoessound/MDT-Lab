import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { DecisionBadge, Icon, Loading } from '../ui';
import { researchApi } from './api';
import { InlineError, roleNames } from './components';
import type { AblationMatrix, ImagingPipeline, ImagingStudy, ResearchCase, WorkflowPlan } from './schemas';

type WindowPreset = 'lung' | 'mediastinal' | 'pet';

function ThoracicSliceSvg({ study, preset, showRoi }: {
  study: ImagingStudy;
  preset: WindowPreset;
  showRoi: boolean;
}) {
  const { svg_slice: slice, radiomics } = study;
  const bgFill = preset === 'pet' ? '#130d24' : preset === 'mediastinal' ? '#181c20' : '#0f171e';
  const lungFill = preset === 'pet' ? '#1e1638' : preset === 'mediastinal' ? '#252c33' : '#162430';
  const lesionFill = preset === 'pet'
    ? 'url(#petHotspot)'
    : slice.has_conflict_marker
      ? 'rgba(224, 108, 95, 0.72)'
      : 'rgba(186, 224, 168, 0.68)';
  const lesionStroke = slice.has_conflict_marker ? '#f28b82' : preset === 'pet' ? '#ff9e44' : '#7ee2a8';

  return (
    <div className="imaging-svg-container" data-preset={preset}>
      <svg viewBox="0 0 260 210" className="imaging-slice-svg" role="img" aria-label={`${study.modality_label} 断层仿真视图`}>
        <defs>
          <radialGradient id="petHotspot" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#fff3b0" />
            <stop offset="45%" stopColor="#ff6b35" />
            <stop offset="100%" stopColor="#7b2cbf" stopOpacity="0.85" />
          </radialGradient>
          <pattern id="ctGrid" width="20" height="20" patternUnits="userSpaceOnUse">
            <path d="M 20 0 L 0 0 0 20" fill="none" stroke="rgba(160, 195, 210, 0.08)" strokeWidth="0.6" />
          </pattern>
        </defs>

        {/* Background & Ruler Grid */}
        <rect width="260" height="210" rx="8" fill={bgFill} />
        <rect width="260" height="210" fill="url(#ctGrid)" />

        {/* Thoracic Body Contour */}
        <ellipse cx="130" cy="108" rx="104" ry="76" fill="#232f38" stroke="#3c4f5e" strokeWidth="2" />
        <ellipse cx="130" cy="108" rx="95" ry="67" fill="#1a242b" stroke="#2d3c47" strokeWidth="1.2" strokeDasharray="5 3" />

        {/* Right Lung Field (Viewer Left) */}
        <path
          d="M 116 54 C 76 50, 48 74, 48 112 C 48 145, 74 162, 112 154 C 118 134, 118 82, 116 54 Z"
          fill={lungFill}
          stroke="#3b5366"
          strokeWidth="1.2"
        />

        {/* Left Lung Field (Viewer Right) */}
        <path
          d="M 144 54 C 184 50, 212 74, 212 112 C 212 145, 186 162, 148 154 C 142 134, 142 82, 144 54 Z"
          fill={lungFill}
          stroke="#3b5366"
          strokeWidth="1.2"
        />

        {/* Bronchial & Vascular Markings (visible in lung window) */}
        {preset === 'lung' && (
          <g stroke="rgba(145, 185, 205, 0.25)" strokeWidth="1" fill="none">
            <path d="M 105 95 L 82 80 M 82 80 L 68 72 M 82 80 L 74 92" />
            <path d="M 105 112 L 76 124 M 76 124 L 62 135" />
            <path d="M 155 95 L 178 82 M 178 82 L 192 73 M 178 82 L 185 95" />
            <path d="M 155 112 L 182 126 M 182 126 L 196 136" />
          </g>
        )}

        {/* Mediastinum, Heart & Vertebral Column */}
        <ellipse cx="133" cy="106" rx="18" ry="24" fill={preset === 'mediastinal' ? '#495866' : '#2d3942'} opacity="0.85" />
        <circle cx="130" cy="156" r="11" fill="#5b6d7a" stroke="#7f94a3" strokeWidth="1.2" />
        <circle cx="130" cy="156" r="4" fill="#232f38" />

        {/* Target Lesion & ROI Overlay */}
        {!slice.has_artifact_or_missing ? (
          <g className="lesion-target-group">
            <polygon
              points={slice.contour_polygon}
              fill={lesionFill}
              stroke={showRoi ? lesionStroke : 'none'}
              strokeWidth={showRoi ? '1.6' : '0'}
            />
            {showRoi && (
              <>
                <circle
                  cx={slice.lesion_cx}
                  cy={slice.lesion_cy}
                  r={slice.lesion_radius + 7}
                  fill="none"
                  stroke={lesionStroke}
                  strokeWidth="1"
                  strokeDasharray="3 2"
                  className="roi-pulse-ring"
                />
                <line x1={slice.lesion_cx - 16} y1={slice.lesion_cy} x2={slice.lesion_cx + 16} y2={slice.lesion_cy} stroke={lesionStroke} strokeWidth="0.8" opacity="0.8" />
                <line x1={slice.lesion_cx} y1={slice.lesion_cy - 16} x2={slice.lesion_cx} y2={slice.lesion_cy + 16} stroke={lesionStroke} strokeWidth="0.8" opacity="0.8" />
                <rect x={slice.is_left_lung ? 132 : 14} y="14" width="114" height="32" rx="4" fill="rgba(13, 24, 30, 0.86)" stroke={lesionStroke} strokeWidth="0.9" />
                <text x={slice.is_left_lung ? 138 : 20} y="27" fill="#e5f2ec" fontSize="8.5" fontWeight="600">
                  靶灶长径 {radiomics.lesion_diameter_mm} mm
                </text>
                <text x={slice.is_left_lung ? 138 : 20} y="39" fill="#9ec5b2" fontSize="8">
                  {preset === 'pet' ? `代谢峰值 SUVmax ${radiomics.suvmax}` : `密度均值 ${radiomics.hu_mean} HU`}
                </text>
              </>
            )}
          </g>
        ) : (
          <g>
            <rect x="42" y="78" width="176" height="52" rx="6" fill="rgba(58, 32, 28, 0.88)" stroke="#e07a6c" strokeWidth="1.2" strokeDasharray="4 2" />
            <text x="130" y="101" textAnchor="middle" fill="#f7c6be" fontSize="10" fontWeight="600">
              影像像素序列附件缺失
            </text>
            <text x="130" y="117" textAnchor="middle" fill="#e59b90" fontSize="8.5">
              仅存在检查登记记录，质控门控已拦截
            </text>
          </g>
        )}

        {/* Corner DICOM HUD Metadata */}
        <text x="10" y="198" fill="#7c98a8" fontSize="8" fontFamily="ui-monospace, monospace">
          {study.modality} · 层厚 {study.dicom_metadata.slice_thickness_mm}mm · {study.anatomical_site}
        </text>
        <text x="250" y="198" textAnchor="end" fill="#7c98a8" fontSize="8" fontFamily="ui-monospace, monospace">
          质控评分 {study.qc_score}/100
        </text>
      </svg>
    </div>
  );
}

export function MedicalImagingWorkbench({ imaging }: { imaging: ImagingPipeline }) {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [preset, setPreset] = useState<WindowPreset>('lung');
  const [showRoi, setShowRoi] = useState(true);

  if (!imaging.studies.length) {
    return (
      <section className="panel workflow-card">
        <div className="workspace-section-heading">
          <h2>多模态医学影像处理工作台</h2>
          <span className="pill outline">当前截点无影像事件</span>
        </div>
        <p className="muted">截至当前所选病程触发点，时间线内尚未包含胸部 CT 或 PET-CT 影像检查事件。可切换至包含影像检查的病程截点查看断层分割与组学特征。</p>
      </section>
    );
  }

  const index = Math.min(selectedIdx, imaging.studies.length - 1);
  const study = imaging.studies[index];
  const qcBadge = {
    passed: { label: '影像质控通过', cls: 'status-completed' },
    incomplete: { label: '影像附件缺失', cls: 'status-running' },
    conflict: { label: '同日影像矛盾', cls: 'status-failed' },
  }[study.qc_status];

  return (
    <section className="panel workflow-card imaging-workbench" aria-label="多模态医学影像处理工作台">
      <div className="workspace-section-heading">
        <div>
          <h2>多模态医学影像特征与质控管线</h2>
          <p className="muted">自动完成 DICOM 窗宽窗位归一化、肺部靶病灶 ROI 分割、影像组学特征提取与一致性核验</p>
        </div>
        <span className={`pill ${qcBadge.cls}`}>{qcBadge.label} · {study.qc_score} 分</span>
      </div>

      {imaging.studies.length > 1 && (
        <div className="imaging-study-tabs" role="tablist" aria-label="选择影像检查序列">
          {imaging.studies.map((item, idx) => (
            <button
              key={item.study_id}
              type="button"
              role="tab"
              aria-selected={idx === index}
              className="imaging-study-tab"
              onClick={() => setSelectedIdx(idx)}
            >
              <strong>{item.event_id} · {item.modality}</strong>
              <small>{item.occurred_at}</small>
            </button>
          ))}
        </div>
      )}

      <div className="imaging-viewer-grid">
        <div className="imaging-slice-column">
          <div className="imaging-controls-bar">
            <div className="imaging-window-group" role="group" aria-label="窗宽窗位预设">
              {([
                ['lung', '肺窗'],
                ['mediastinal', '纵隔窗'],
                ['pet', 'PET 代谢伪彩'],
              ] as const).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={preset === key}
                  onClick={() => setPreset(key)}
                >
                  {label}
                </button>
              ))}
            </div>
            <label className="imaging-roi-toggle">
              <input type="checkbox" checked={showRoi} onChange={e => setShowRoi(e.target.checked)} />
              <span>靶区 ROI 标注</span>
            </label>
          </div>

          <ThoracicSliceSvg study={study} preset={preset} showRoi={showRoi} />

          <div className="imaging-morphology-bar">
            <span>识别征象：</span>
            {study.radiomics.morphology_tags.map(tag => (
              <span key={tag} className="pill soft">{tag}</span>
            ))}
          </div>
        </div>

        <div className="imaging-metrics-column">
          <div className="radiomics-grid">
            <div>
              <span>解剖肺叶定位</span>
              <strong>{study.anatomical_site}</strong>
            </div>
            <div>
              <span>靶病灶最大长径</span>
              <strong>{study.radiomics.lesion_diameter_mm} <small>mm</small></strong>
            </div>
            <div>
              <span>CT 密度均值</span>
              <strong>{study.radiomics.hu_mean} <small>HU</small></strong>
            </div>
            <div>
              <span>PET 代谢活性峰值</span>
              <strong>{study.radiomics.suvmax} <small>SUVmax</small></strong>
            </div>
            <div>
              <span>灰度共生矩阵纹理熵</span>
              <strong>{study.radiomics.glcm_entropy}</strong>
            </div>
            <div>
              <span>纵隔淋巴结短径</span>
              <strong>{study.radiomics.lymph_node_mm} <small>mm</small></strong>
            </div>
          </div>

          <div className="imaging-pipeline-steps">
            <h3>影像处理流水线（4 阶算子）</h3>
            {study.pipeline_steps.map(step => (
              <div key={step.step_id} className={`imaging-step-row step-${step.status}`}>
                <span className="imaging-step-icon">
                  <Icon name={step.status === 'passed' ? 'check' : 'alert'} size={15} />
                </span>
                <div>
                  <strong>{step.title}</strong>
                  <p>{step.detail}</p>
                </div>
                <span className="imaging-step-badge">
                  {{ passed: '通过', warning: '待补', blocked: '冲突', skipped: '跳过' }[step.status]}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
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

  const showEnrichAction = isLatestVersion && (
    plan.completeness.can_auto_enrich || plan.completeness.strict_missing.length > 0
  );

  return (
    <section className="panel workflow-card" aria-label="案例自适应医疗流程蓝图">
      <div className="workspace-section-heading">
        <div>
          <h2>案例驱动的自动化医疗流程规划</h2>
          <p className="muted">根据当前病例纵向病程、检查模态与冲突态势，自动定制 6 阶多学科协同工作流与专科任务卡</p>
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
              <strong>智能临床语义映射与完备性推导（已识别 {plan.completeness.semantic_inferred.length} 项隐含证据）</strong>
              <p>外部数据集（如 TCIA / Synthea）原表未附合成布尔完备键，算法已从原始检查与组织学记录自动推导完备性证据链：</p>
            </div>
            {showEnrichAction && (
              <button
                type="button"
                className="button primary"
                disabled={enrich.isPending}
                onClick={() => enrich.mutate()}
              >
                <Icon name="check" size={15} />
                {enrich.isPending ? '正在生成扩展版本…' : `一键生成特征补齐版本 (v${plan.case_version} → v${plan.case_version + 1})`}
              </button>
            )}
          </div>
          <ul className="semantic-inference-list">
            {plan.completeness.semantic_inferred.map(item => (
              <li key={item.fact_key}>
                <span className="pill soft">{item.fact_label}</span>
                <span>{item.reason}</span>
              </li>
            ))}
          </ul>
          <InlineError error={enrich.error} />
        </div>
      )}

      {plan.completeness.semantic_inferred.length === 0 && showEnrichAction && (
        <div className="semantic-inference-box">
          <div className="semantic-box-header">
            <div>
              <strong>检测到阶段必需临床资料缺口：{plan.completeness.strict_missing_labels.join('、')}</strong>
              <p>可点击右侧按钮通过自动化质控算子一键生成合成补齐事件（新版本 v{plan.case_version + 1}），用于配对验证补件前后的流程变化。</p>
            </div>
            <button
              type="button"
              className="button secondary"
              disabled={enrich.isPending}
              onClick={() => enrich.mutate()}
            >
              <Icon name="pulse" size={15} />
              {enrich.isPending ? '正在补齐…' : `一键智能补齐缺口 (v${plan.case_version} → v${plan.case_version + 1})`}
            </button>
          </div>
          <InlineError error={enrich.error} />
        </div>
      )}

      <div className="workflow-dag-grid" aria-label="自动化工作流六阶拓扑">
        {plan.workflow_stages.map(stage => (
          <div key={stage.stage_id} className={`workflow-dag-node status-${stage.status}`}>
            <div className="dag-node-top">
              <span className="dag-step-num">0{stage.step_number}</span>
              <strong>{stage.title}</strong>
              <span className="dag-status-tag">
                {{ active: '自动执行', recommended: '按需就绪', skipped: '智能跳过' }[stage.status]}
              </span>
            </div>
            <p>{stage.description}</p>
          </div>
        ))}
      </div>

      <div className="specialist-task-cards">
        <h3>各专科定制化审阅任务分工（已选中 {plan.selected_agents.length} / 4 个专科）</h3>
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
          <h2>多智能体方法组（B0–B3）与单因素消融实验实时对照</h2>
          <p className="muted">直接落地计划书 §6.2 实验设计：在同一冻结输入快照上横向对比专科调用开销、门控前后结论与消融差异</p>
        </div>
        <span className="pill soft">事件路由节省 {matrix.call_saving_pct}% 调用</span>
      </div>

      <div className="workspace-table-scroll">
        <table className="workspace-table ablation-table">
          <thead>
            <tr>
              <th>实验方法组 / 消融配置</th>
              <th>参与专科</th>
              <th>调用次数</th>
              <th>协商轮次</th>
              <th>门控前结论</th>
              <th>最终门控结论</th>
              <th>待补 / 冲突</th>
              <th>本例核心实验发现</th>
            </tr>
          </thead>
          <tbody>
            {matrix.methods.map(row => (
              <tr key={row.method_id} className={row.method_id === 'B3' ? 'ablation-highlight-row' : ''}>
                <td>
                  <strong>{row.name}</strong>
                  <small>{row.category} · {row.routing_strategy}</small>
                </td>
                <td>{row.selected_agents.map(r => roleNames[r]).join('、')}</td>
                <td className="workspace-number"><strong>{row.agent_calls}</strong> 次</td>
                <td className="workspace-number">{row.discussion_rounds} 轮</td>
                <td><DecisionBadge decision={row.pre_gate_decision} /></td>
                <td><DecisionBadge decision={row.final_decision} /></td>
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
