import { Link } from 'react-router-dom';
import { Icon } from '../ui';
import './styles.css';
import './workspace.css';

export { ResearchHome, ResearchHistoryPage } from './workspace-lists';
export { ResearchCasePage } from './workspace-case';
export { ResearchRunPage, ResearchReportPage } from './workspace-run';
export { ModelSettingsPage } from './model-settings';

// The original /roadmap bookmark now opens the workspace reference.
export function ResearchRoadmapPage() {
  return <div className="page-enter research-page workspace-page">
    <header className="workspace-heading">
      <div>
        <h1>系统使用指南与架构说明</h1>
        <p>面向重大疾病全病程的多学科多智能体（MDT）序贯协同决策研究工作台</p>
      </div>
    </header>
    <section className="panel workspace-help"><h2>核心科研工作流</h2><dl>
      <div><dt><Link to="/research/datasets">1. 数据集导入 <Icon name="arrow" size={13} /></Link></dt><dd>接入公开医学研究队列（TCIA 肺癌临床表、Synthea 合成病程）或上传结构化病例文件，经预检校验指纹后原子落库。</dd></div>
      <div><dt><Link to="/">2. 智能流程与影像 <Icon name="arrow" size={13} /></Link></dt><dd>打开病例并选定病程触发截点，预览案例驱动的 6 阶自动化医疗工作流蓝图、CT/PET 断层靶灶分割组学特征与语义完备度推导。</dd></div>
      <div><dt><Link to="/settings/models">3. 专科模型配置 <Icon name="arrow" size={13} /></Link></dt><dd>配置全局默认连接或为肿瘤内科、影像科、胸外科、病理科独立设置异构大模型接口与密钥。</dd></div>
      <div><dt><Link to="/research/agents">4. 协同审阅与消融 <Icon name="arrow" size={13} /></Link></dt><dd>实时监视多专科序贯初审、单轮有界定向协商与证据安全门控，并在报告页横向对比 B0–B3 基线与单因素消融实验结果。</dd></div>
    </dl></section>
    <section className="panel workspace-help"><h2>核心机制与方法学边界</h2><dl>
      <div><dt>纵向版本与时序截断</dt><dd>每次追加合成病程或智能补齐均生成新版本（v1 → v2），旧版本与历史报告严格不可变。运行仅截取触发截点前的可见事实，杜绝未来信息泄漏。</dd></div>
      <div><dt>影像管线与语义推导</dt><dd>针对外部数据集自动提取 DICOM 层厚、肺窗/纵隔窗/PET 伪彩断层视图及靶病灶长径、SUVmax 等组学指标，并自动推导完备性证据链。</dd></div>
      <div><dt>有界协商与安全门控</dt><dd>仅针对存在分歧的专科启动单轮快照隔离协商；不以多数票强行抹除同日来源矛盾，任何未解分歧或非法证据引用均由安全门控拦截。</dd></div>
      <div><dt>科研审阅结果定位</dt><dd>最终标签（可进入资料复核 / 需要补充资料 / 暂缓流程判断）仅表征研究资料完备性与证据一致性，不构成真实临床诊断或处方建议。</dd></div>
    </dl></section>
  </div>;
}
