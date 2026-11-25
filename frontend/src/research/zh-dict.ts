import type { ResearchCase, Role } from './schemas';

export const factLabelsZh: Record<string, string> = {
  imaging_complete: '影像资料齐备',
  imaging_record: '影像检查记录',
  pathology_confirmed: '病理学已确诊',
  pathology_record: '病理报告记录',
  histology: '组织学病理分型',
  molecular_complete: '分子检测齐备',
  molecular_record: '分子基因检测记录',
  procedure_record_complete: '手术与操作记录齐备',
  treatment_record_complete: '治疗方案记录齐备',
  toxicity_assessed: '不良反应已评估',
  follow_up_complete: '随访资料齐备',
  follow_up_record: '随访观察记录',
  progression_confirmed: '疾病进展已确认',
  progression_event_received: '收到进展复核触发',
  observation_reviewed: '临床观察已审阅',
  disease_label: '疾病诊断标签',
  record_note: '记录核对备注',
  review_note: '人工复核说明',
  supersedes_event_id: '替代历史事件编号',
  modality: '影像检查模态',
  recorded_date: '原始记录日期',
  source_subject_id: '来源受试者编号',
  original_date: '原始日期文本',
  code: '医学标准编码',
  description: '临床检查/诊断描述',
  coding_system: '编码体系',
  unit: '计量单位',
  encounter_id: '就诊记录编号',
  body_site: '解剖部位',
  category: '记录类别',
  record_type: '就诊类别',
  observed_value: '临床观测结果',
  pathological_t: '病理 T 分期（原发肿瘤）',
  pathological_n: '病理 N 分期（区域淋巴结）',
  pathological_m: '病理 M 分期（远处转移）',
  grade: '组织学分化分级',
  smoking_status: '吸烟史状态',
  egfr_status: 'EGFR 基因突变状态',
  kras_status: 'KRAS 基因突变状态',
  alk_status: 'ALK 融合重排状态',
  adjuvant_treatment: '术后辅助治疗',
  chemotherapy: '化疗方案记录',
  radiation: '放疗方案记录',
  recurrence_status: '复发状态汇总',
  survival_status: '生存结局状态',
  imaging_qc_passed: '影像质控核验通过',
  lesion_diameter_mm: '主病灶最大长径 (mm)',
  radiomics_suvmax: 'PET 代谢峰值 (SUVmax)',
};

export function factKeyLabel(key: string): string {
  if (factLabelsZh[key]) return factLabelsZh[key];
  if (key.endsWith('_missing_reason')) {
    const base = key.replace(/_missing_reason$/, '');
    return `${factLabelsZh[base] ?? base}（缺失原因）`;
  }
  return key;
}

const valueTranslations: Record<string, string> = {
  adenocarcinoma: '肺腺癌',
  'squamous cell carcinoma': '肺鳞状细胞癌',
  nsclc: '非小细胞肺癌',
  wildtype: '野生型（未见突变）',
  'wild type': '野生型（未见突变）',
  mutant: '突变阳性',
  mutated: '突变阳性',
  positive: '阳性',
  negative: '阴性',
  alive: '存活',
  dead: '死亡',
  deceased: '死亡',
  yes: '是',
  no: '否',
  'not collected': '未采集',
  'not recorded': '未记录',
  'not available': '不可用',
  'not assessed': '未评估',
  'not performed': '未执行',
  'not tested': '未检测',
  unknown: '未知',
  empty: '空值',
  current: '当前吸烟',
  former: '既往吸烟（已戒烟）',
  nonsmoker: '无吸烟史',
  'never smoker': '无吸烟史',
  ct: 'CT 计算机断层扫描',
  pet: 'PET 正电子代谢显像',
  'pet-ct': 'PET-CT 融合显像',
  mri: '磁共振成像 (MRI)',
  inpatient: '住院诊疗',
  outpatient: '门诊诊疗',
  ambulatory: '门诊随访',
  emergency: '急诊就诊',
  wellness: '健康随访',
};

export function formatFactValue(value: unknown): string {
  if (value === null || value === undefined) return '未记录';
  if (value === true) return '是（已确认）';
  if (value === false) return '否（待补齐）';
  if (typeof value === 'number') return String(value);
  const text = String(value).trim();
  const translated = valueTranslations[text.toLowerCase()];
  return translated ?? text;
}

export const sourceNamesZh: Record<string, string> = {
  research_scenario_generator: '内置合成场景生成器',
  synthea: 'Synthea 合成病程数据集',
  tcia_nsclc_radiogenomics: 'TCIA 肺癌影像基因组公开队列',
  tcga_cbioportal_nsclc: 'TCGA / cBioPortal 肺癌公开队列',
};

export function sourceNameLabel(name: string): string {
  return sourceNamesZh[name] ?? name;
}

export const safetyCheckLabelsZh: Record<string, string> = {
  selected_agent_coverage: '调度专科有效意见覆盖率',
  evidence_integrity: '证据链溯源与事实一致性',
  unresolved_conflicts: '跨专科分歧消解核验',
  required_information: '当前阶段必需资料完备性',
  temporal_boundary: '纵向时间截点防泄漏核验',
};

export function safetyCheckLabel(code: string): string {
  return safetyCheckLabelsZh[code] ?? code;
}

export const conflictDimensionLabelsZh: Record<string, string> = {
  source_fact_conflict: '同日多源记录矛盾',
  information_sufficiency: '资料充分性判定分歧',
  structured_fact_difference: '结构化事实引用分歧',
};

export function conflictDimensionLabel(dimension: string): string {
  return conflictDimensionLabelsZh[dimension] ?? dimension;
}

export const nodeLabelsZh: Record<string, string> = {
  case_validation: '病例版本与时序校验',
  routing: '专科动态路由',
  oncology_review: '肿瘤内科初审',
  radiology_review: '影像科初审',
  surgery_review: '胸外科初审',
  pathology_review: '病理科初审',
  conflict_detection: '多维分歧检测',
  targeted_discussion: '定向协同协商',
  safety_gate: '证据与安全门控',
  report: '结构化报告归档',
};

export function nodeNameLabel(node: string): string {
  return nodeLabelsZh[node] ?? node;
}

export const toolLabelsZh: Record<string, string> = {
  case_timeline: '纵向病程时间线截取',
  evidence_lookup: '冻结证据注册表检索',
  missing_fields: '必需临床资料缺口扫描',
};

export function toolNameLabel(tool: string): string {
  return toolLabelsZh[tool] ?? tool;
}

export const ruleIdLabelsZh: Record<string, string> = {
  fixed_all: '固定全员对照规则',
  adaptive_utility: '纵向风险效用自适应规则',
  event_diagnosis: '初诊综合评估规则',
  event_imaging: '影像复核调度规则',
  event_pathology: '病理确诊调度规则',
  event_molecular_test: '分子检测调度规则',
  event_procedure: '外科操作调度规则',
  event_treatment: '治疗方案调度规则',
  event_medication: '用药记录调度规则',
  event_toxicity: '不良反应调度规则',
  event_follow_up: '随访监测调度规则',
  event_progression: '疾病进展会诊规则',
  event_recurrence: '复发多科会诊规则',
  event_observation: '临床观察审阅规则',
};

export function ruleIdLabel(ruleId: string): string {
  return ruleIdLabelsZh[ruleId] ?? ruleId;
}

export const errorCodeLabelsZh: Record<string, string> = {
  invalid_evidence: '证据引用未通过冻结注册表核验',
  invalid_opinion: '专科输出结构不合规',
  simulated_agent_failure: '预设模拟专科节点调用故障',
  process_interrupted: '本地服务重启导致运行中断',
  run_timeout: '运行超出时间预算（已自动终止）',
  workflow_error: '工作流执行异常',
  scenario_requires_multiple_agents: '所选规则场景至少需要两名参与专科',
  LLM_NOT_CONFIGURED: '大模型连接尚未配置齐全',
  LLM_AUTHENTICATION_ERROR: '大模型服务密钥认证被拒绝',
  LLM_RATE_LIMIT: '大模型接口触发限流',
  LLM_PROVIDER_ERROR: '大模型上游服务暂时不可用',
  LLM_TIMEOUT: '大模型请求响应超时',
  LLM_NETWORK_ERROR: '无法连接到大模型服务地址',
  LLM_INVALID_OUTPUT: '大模型输出未通过 JSON 结构或证据校验',
  LLM_REQUEST_REJECTED: '大模型拒绝请求参数',
  LLM_REFUSED: '大模型安全策略拒绝回答',
  LLM_DNS_ERROR: '大模型服务域名无法解析',
  LLM_PRIVATE_DESTINATION: '安全策略已拦截非公开网络地址',
};

export function errorCodeLabel(code: string | null | undefined): string {
  if (!code) return '未知异常';
  return errorCodeLabelsZh[code] ?? code;
}

export function modeNameZh(mode: string): string {
  return mode === 'llm' ? '大模型推演' : '本地规则仿真';
}

export function providerLabelZh(provider: string, model: string): string {
  if (provider === 'mock') return '内置确定性规则引擎 · 零外部调用';
  const cleanProvider = provider === 'openai-compatible' ? '兼容大模型接口' : provider;
  return `${cleanProvider} · ${model}`;
}

export function roleBadgeColor(role: Role): string {
  const colors: Record<Role, string> = {
    oncology: 'role-badge-oncology',
    radiology: 'role-badge-radiology',
    surgery: 'role-badge-surgery',
    pathology: 'role-badge-pathology',
  };
  return colors[role];
}

export function routingModeNameZh(mode: string): string {
  if (mode === 'adaptive') return '风险自适应路由';
  if (mode === 'fixed') return '固定四科全员';
  return '按事件智能路由';
}

const LEGACY_WORKFLOW_TITLES: Record<string, string> = {
  '资料逐步补齐：影像、病理与分子记录': '右肺上叶实性占位伴纵隔淋巴结待查',
  '资料缺失：等待病理与分子记录': '左肺下叶肿块疑似原发性支气管肺癌',
  '证据冲突：同日记录存在相反标记': '右肺腺癌一线治疗后复查病灶评估',
};

export function clinicalCaseTitle(item: ResearchCase): string {
  if (LEGACY_WORKFLOW_TITLES[item.title]) return LEGACY_WORKFLOW_TITLES[item.title];
  const sexLabel = item.patient.sex === 'female' ? '女性' : item.patient.sex === 'male' ? '男性' : '患者';
  if (item.title === 'Synthea 通用合成病程') {
    const diag = item.timeline.find(ev => ev.event_type === 'diagnosis') ?? item.timeline[0];
    return diag ? `${diag.title}（合成病程）` : `${item.patient.age}岁${sexLabel} · 合成病例`;
  }
  if (/^NSCLC 公开研究病例\s+/.test(item.title)) {
    const modalities = Array.from(new Set(
      item.timeline.map(ev => ev.facts.modality).filter((m): m is string => typeof m === 'string' && m.trim().length > 0),
    ));
    return `${item.patient.age}岁${sexLabel} · 非小细胞肺癌（${modalities.length ? `${modalities.join(' / ')} 队列` : '公开影像队列'}）`;
  }
  if (/^TCGA\/cBioPortal 公开病例\s+/.test(item.title)) {
    return `${item.patient.age}岁${sexLabel} · ${item.disease}`;
  }
  return item.title;
}

const CONFLICT_CHECK_KEYS = new Set([
  'imaging_complete', 'progression_confirmed', 'pathology_confirmed', 'molecular_complete',
  'histology', 'egfr_status', 'kras_status', 'alk_status', 'pathological_t', 'pathological_n', 'pathological_m',
]);
const COMPLETENESS_KEYS = [
  'imaging_complete', 'pathology_confirmed', 'molecular_complete',
  'follow_up_complete', 'procedure_record_complete', 'treatment_record_complete',
];

export function caseBaselineHint(item: ResearchCase): string {
  const byKey = new Map<string, Array<{ eventId: string; date: string; value: unknown; supersedes: unknown }>>();
  const latestScalar: Record<string, unknown> = {};
  for (const ev of item.timeline) {
    for (const [k, v] of Object.entries(ev.facts)) {
      latestScalar[k] = v;
      if (CONFLICT_CHECK_KEYS.has(k) && v !== null) {
        const list = byKey.get(k) ?? [];
        list.push({ eventId: ev.event_id, date: ev.occurred_at, value: v, supersedes: ev.facts.supersedes_event_id });
        byKey.set(k, list);
      }
    }
  }
  for (const records of byKey.values()) {
    const maxDate = records.reduce((acc, r) => (r.date > acc ? r.date : acc), '');
    const sameDay = records.filter(r => r.date === maxDate);
    const superseded = new Set(sameDay.map(r => r.supersedes).filter(Boolean));
    const distinct = new Set(sameDay.filter(r => !superseded.has(r.eventId)).map(r => `${typeof r.value}:${JSON.stringify(r.value)}`));
    if (distinct.size > 1) return '待审阅 · 含同日冲突记录';
  }
  if (COMPLETENESS_KEYS.some(k => latestScalar[k] === false)) {
    return '待审阅 · 存在待补记录';
  }
  return '待审阅 · 资料已登记';
}
