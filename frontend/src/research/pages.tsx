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
      <div><dt><Link to="/">2. 智能流程与影像 <Icon name="arrow" size={13} /></Link></dt><dd>选定病程截点，查看可见影像记录、来源字段和建议参与的专科。启动审阅后，可在运行页查看事件路由或固定全员模式实际调用的角色。</dd></div>
      <div><dt><Link to="/settings/models">3. 专科模型配置 <Icon name="arrow" size={13} /></Link></dt><dd>配置全局默认连接或为肿瘤内科、影像科、胸外科、病理科独立设置异构大模型接口与密钥。</dd></div>
      <div><dt><Link to="/research/agents">4. 协同审阅与消融 <Icon name="arrow" size={13} /></Link></dt><dd>监视本次运行的专科初审、定向协商和资料门控。在报告页可对同一截点运行本地 Mock 对照。</dd></div>
    </dl></section>
    <section className="panel workspace-help"><h2>核心机制与方法学边界</h2><dl>
      <div><dt>纵向版本与时序截断</dt><dd>运行按所选版本、日期和事件编号冻结病程。无日期资料单列于来源页。有可追溯依据的补齐会生成新版本，可与原版本逐项核对。</dd></div>
      <div><dt>影像登记与证据来源</dt><dd>工作台展示来源表里的日期、检查模态和已记录的解剖部位，可沿证据编号定位原字段。当前输入仅包含登记元数据，像素质控和病灶测量尚未执行。</dd></div>
      <div><dt>有界协商与安全门控</dt><dd>仅针对存在分歧的专科启动单轮快照隔离协商；不以多数票强行抹除同日来源矛盾，任何未解分歧或非法证据引用均由安全门控拦截。</dd></div>
      <div><dt>科研审阅结果定位</dt><dd>最终标签（可进入资料复核 / 需要补充资料 / 暂缓流程判断）仅表征研究资料完备性与证据一致性，不构成真实临床诊断或处方建议。</dd></div>
    </dl></section>
  </div>;
}
