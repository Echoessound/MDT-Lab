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
    <header className="workspace-heading"><h1>使用说明</h1></header>
    <section className="panel workspace-help"><h2>常用操作</h2><dl>
      <div><dt><Link to="/research/datasets">导入病例 <Icon name="arrow" size={13} /></Link></dt><dd>选择数据源或上传文件，核对来源、病例数量和跳过记录后提交导入。</dd></div>
      <div><dt><Link to="/">发起运行 <Icon name="arrow" size={13} /></Link></dt><dd>打开病例，选择版本和触发事件。确认参与专科与运行模式后启动。</dd></div>
      <div><dt><Link to="/settings/models">连接模型 <Icon name="arrow" size={13} /></Link></dt><dd>保存共享连接，或为单个专科设置服务地址、模型及密钥。LLM 模式需要全部参与专科具备有效配置。</dd></div>
      <div><dt><Link to="/research/runs">核对报告 <Icon name="arrow" size={13} /></Link></dt><dd>从运行记录打开报告，查看资料缺口、未解决分歧和专科意见，点击引用可核对原始事实。</dd></div>
    </dl></section>
    <section className="panel workspace-help"><h2>运行记录说明</h2><dl>
      <div><dt>病例版本</dt><dd>追加人工合成事件会产生新版本。既有运行仍关联其启动时选定的版本与事件。</dd></div>
      <div><dt>输入范围</dt><dd>运行只使用截至触发事件可见的病程事实。缺少可用日期的相关资料可在来源页查阅。</dd></div>
      <div><dt>运行模式</dt><dd>Mock 使用本地固定规则。LLM 会把本次可见的研究资料发送至参与专科配置的模型服务。</dd></div>
      <div><dt>审阅结果</dt><dd>结果表示研究资料的完整性与证据一致性，供人工复核。</dd></div>
    </dl></section>
  </div>;
}
