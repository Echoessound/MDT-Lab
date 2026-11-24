import { Link } from 'react-router-dom';
import { Icon } from '../ui';
import './styles.css';
import './workspace.css';

export { ResearchHome, ResearchHistoryPage } from './workspace-lists';
export { ResearchCasePage } from './workspace-case';
export { ResearchRunPage, ResearchReportPage } from './workspace-run';
export { ModelSettingsPage } from './model-settings';

// The /roadmap route serves as the interactive usage guide & milestone roadmap.
export function ResearchRoadmapPage() {
  return (
    <div className="page-enter research-page workspace-page">
      <header className="workspace-heading">
        <div>
          <h1>系统使用指南、总体开发进程与后续排期</h1>
          <p>面向重大疾病全病程的多学科多智能体（MDT）序贯协同决策研究工作台</p>
        </div>
        <div className="button-group">
          <Link className="button secondary" to="/research/experiments?view=annotate"><Icon name="check" size={15} />进入盲标工作台</Link>
          <Link className="button primary" to="/"><Icon name="grid" size={15} />进入病例工作台</Link>
        </div>
      </header>

      <section className="panel workspace-help">
        <h2>四步科研闭环操作指南</h2>
        <dl>
          <div>
            <dt><Link to="/research/datasets">01. 队列构建与导入 <Icon name="arrow" size={13} /></Link></dt>
            <dd>接入公开肿瘤与临床队列（TCIA NSCLC 临床 CSV、TCGA/cBioPortal 宽表 TSV、Synthea CSV ZIP）或研究 JSON，经预检核验 SHA-256 指纹后原子写入；支持为事件挂载真实去标识医学附件（剥离 DICOM 0x0010 隐私组）。</dd>
          </div>
          <div>
            <dt><Link to="/">02. 纵向截点协同审阅 <Icon name="arrow" size={13} /></Link></dt>
            <dd>在病例页顶部时间轴滑轨选定任意历史事件截点，右侧实时预检参与专科路由与大模型方案就绪状态。启动后可在「多智能体协同」监视初审、单轮快照隔离协商与安全门控，并在报告页执行独立时序防泄漏审计。</dd>
          </div>
          <div>
            <dt><Link to="/research/experiments?view=annotate">03. 多人盲标与仲裁 <Icon name="arrow" size={13} /></Link></dt>
            <dd>标注人在严格屏蔽系统预测与同行意见的截点材料上独立录入结论、必要专科与关键证据；系统自动统计三分类原始一致率、Cohen&apos;s κ 与专科 Jaccard 重合度，将分歧推送至仲裁工作台定稿并导出 JSONL。</dd>
          </div>
          <div>
            <dt><Link to="/research/experiments">04. 8 组消融与论文导出 <Icon name="arrow" size={13} /></Link></dt>
            <dd>对同一冻结截点同步执行 B0–B3 基线与 A1–A4 消融，按病例族聚类 Bootstrap 1,000 次输出 95% 置信区间、精确 McNemar p 值、Macro-F1、逐例误差归因表及毕业论文 LaTeX 三线表。</dd>
          </div>
        </dl>
      </section>

      <section className="panel workflow-card">
        <div className="workspace-section-heading">
          <div>
            <h2>总体开发进程与后续冲刺里程碑</h2>
            <p className="muted">P0–P4 工程与评测底座已全部合入主干；后续重点推进 M1–M6 真实大模型取证、锁定队列双盲标注与毕业论文定稿。</p>
          </div>
          <span className="pill status-completed">平台底座已就绪</span>
        </div>
        <div className="roadmap-grid">
          <article className="roadmap-phase-card is-done">
            <div className="pipeline-step-top">
              <span className="dag-step-num">P0 – P2</span>
              <span className="pill status-completed">已交付</span>
            </div>
            <h3>纵向引擎、持久化与多模态防泄漏接入</h3>
            <p>完成四专科事件路由、单轮隔离协商、安全门控、MongoDB 副本集事务、SSE 序号重放及 5 类临床/影像去标识数据管线。</p>
          </article>
          <article className="roadmap-phase-card is-done">
            <div className="pipeline-step-top">
              <span className="dag-step-num">P3 – P4</span>
              <span className="pill status-completed">已交付</span>
            </div>
            <h3>科研统计闭环与 iOS Grid 设计工程化</h3>
            <p>落地命名模型方案、多人盲标仲裁、独立时序审计、§6.4 复现包构建器，并按 Apple HIG 与 emilkowalski/skills 完成内在 CSS Grid 与 60fps 动效重构。</p>
          </article>
          <article className="roadmap-phase-card is-active">
            <div className="pipeline-step-top">
              <span className="dag-step-num">M1 – M3</span>
              <span className="pill soft">第 1–4 周</span>
            </div>
            <h3>真实模型 G01 联调、队列冻结与双盲仲裁</h3>
            <p>运行 run_llm_benchmark.py 完成真实模型三场景联调，锁定 dev/test 病例族划分，完成双人独立盲标与争议仲裁金标准归档。</p>
          </article>
          <article className="roadmap-phase-card">
            <div className="pipeline-step-top">
              <span className="dag-step-num">M4 – M6</span>
              <span className="pill outline">第 4–8 周</span>
            </div>
            <h3>先导冻结、正式测试集评测与论文答辩</h3>
            <p>在开发集确定预算与协议后解封锁定测试集，生成正式配对置信区间与逐例误差归因，完成毕业论文第 3–5 章与三条现场演示路线。</p>
          </article>
        </div>
      </section>

      <section className="panel workspace-help">
        <h2>核心方法学与学术诚实边界</h2>
        <dl>
          <div><dt>纵向版本与时序截断</dt><dd>运行按所选版本、日期和事件编号冻结病程。无日期资料（unplaced_records）严格隔离于来源层，报告页内嵌独立重建核验器确保零未来泄漏。</dd></div>
          <div><dt>有界协商与安全门控</dt><dd>仅针对存在分歧的专科启动单轮快照隔离协商；禁止多数票掩盖同日来源矛盾，任何未解分歧或越界证据引用均由门控拦截为暂缓判断。</dd></div>
          <div><dt>科研审阅结果定位</dt><dd>最终标签（可进入资料复核 / 需要补充资料 / 暂缓判断）仅评价研究记录完备性与内部一致性，不构成临床诊断、治疗或处方建议。</dd></div>
        </dl>
      </section>
    </div>
  );
}
