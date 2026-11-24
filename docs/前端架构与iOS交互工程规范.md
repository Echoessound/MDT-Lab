# MDT Lab 前端架构、CSS Grid 布局与 iOS 交互工程规范

> **规范基准**：融合 Apple Human Interface Guidelines (iOS / iPadOS) 与 [emilkowalski/skills](https://github.com/emilkowalski/skills)（`emil-design-eng`、`animate`、`review-animations`、`apple-design`、`mobile-native`）设计工程准则，作为本项目前端开发、代码审查与自动化门禁的强制规范。

---

## 1. 设计工程核心哲学（源自 `emilkowalski/skills`）

临床科研工作台每天面对高密度的纵向时间线、多专科证据链与统计检验表格。优秀的界面工程不是堆砌装饰性动画，而是通过**物理直觉、光学对齐、零布局抖动与克制的触觉反馈**降低研究者的认知负荷：

1. **快而克制（Sub-260ms UI Windows）**：常规界面反馈控制在 `120ms–260ms` 之间；绝不使用拖泥带水的慢速淡入或无意义的循环闪烁。
2. **即时响应曲线（Custom `cubic-bezier` Only）**：全面禁用浏览器默认的 `ease-in` 入场（起步迟滞）与笼统的 `transition: all`。统一使用下表四条语义化物理曲线：
   - `--ease-out-strong: cubic-bezier(0.23, 1, 0.32, 1)` —— 用于下拉、分段内容浮现、悬停反馈与状态切换，点击瞬间即有高初速度响应。
   - `--ease-in-out-strong: cubic-bezier(0.77, 0, 0.175, 1)` —— 用于屏幕内已有元素的位移过渡。
   - `--ease-ios-sheet: cubic-bezier(0.32, 0.72, 0, 1)` —— 复刻 iOS 原生抽屉（Drawer）、Spotlight 搜索框与模态弹窗（Sheet）阻尼落位曲线。
   - `--ease-spring-glider: cubic-bezier(0.32, 1.08, 0.45, 1)` —— 专用于分段控制器（Segmented Control）滑块的轻微物理回弹。
3. **60fps 合成层纪律（Composite-Only Properties）**：
   - 动画与过渡仅允许作用于 **`transform`（`translate3d`、`scale`、`scaleX`、`rotate`）** 与 **`opacity`**（辅以必要的颜色属性 `background-color`、`border-color`、`color`）。
   - **严禁对 `width`、`height`、`top`、`left`、`margin`、`grid-template-columns` 做帧间过渡动画**。所有进度条（运行节点进度、完备度条、方法开销条、分段滑块）一律铺满轨道宽度，通过 `transform: scaleX(var(--bar-scale, 0))` 配合 `transform-origin: 0 50%` 在 GPU 合成线程无重排渲染。
4. **触控与指针设备严格分离（`mobile-native`）**：
   - 所有悬停位移与高亮（`:hover`）必须包裹在 `@media (hover: hover) and (pointer: fine)` 媒体查询内，杜绝触屏设备点击后残留“幽灵悬停态”。
   - 所有可点击控件提供 `:active { transform: scale(0.97); }` 物理按压微回弹，且移动端触控热区最小块级尺寸不低于 `2.75rem`（`44px`）。
   - 全局保留 `@media (prefers-reduced-motion: reduce)` 无障碍兜底，一键关闭非必要位移。
5. **光学细节与同心圆角（Optical Alignment & Concentric Radii）**：
   - 嵌套容器严格遵循同心圆角公式：$R_{\text{outer}} = R_{\text{inner}} + \text{padding}$。例如分段轨道圆角 `12px`、内边距 `3px`，则内部浮动滑块圆角取 `9px`。
   - 摒弃生硬的纯黑实线边框，使用半透明发丝分隔线（`rgba(60, 60, 67, 0.13)` / 深色 `rgba(84, 84, 88, 0.45)`）配合 `background-clip: padding-box` 与双层柔和环境光阴影。
   - 凡涉及病例计数、调用次数、置信区间、`p` 值、时间戳与表格数字，一律开启 `font-variant-numeric: tabular-nums` 等宽数字对齐。

---

## 2. 内在响应式 CSS Grid 布局规范（严禁硬编码死宽高）

本项目前端布局实行 **“Grid 优先、内容驱动尺寸”** 原则，禁止拍脑袋写死像素宽高（如 `width: 112px`、`height: 58px`、`height: 242px`）或滥用多层嵌套 `flex-direction: column`：

| 布局场景 | 标准写法 | 禁止写法（反模式） |
| --- | --- | --- |
| **多卡自适应网格**（态势卡、对比卡、工作流节点、能力矩阵） | `display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr)); gap: 0.875rem;` | 写死 `repeat(4, 1fr)` 再靠三四个 `@media` 补丁强行改列数 |
| **主从双栏工作区**（病例详情+发起栏、盲标队列+材料审阅、模型列表+编辑器） | `display: grid; grid-template-columns: minmax(0, 1.85fr) minmax(min(100%, 18rem), 0.95fr); align-items: start;` | 侧栏写死 `310px` 或固定百分比导致窄屏挤压溢出 |
| **纵向页面与卡片内部流** | `display: grid; align-content: start; gap: ...; min-width: 0;` | 到处堆叠 `display: flex; flex-direction: column` 且遗漏 `min-width: 0` 撑破表格 |
| **比例堆叠条**（三分类决策分布条） | `display: grid; grid-template-columns: var(--ready-fr, 0fr) var(--need-fr, 0fr) var(--defer-fr, 0fr); inline-size: 100%; min-inline-size: 6.5rem;` | 写死 `width: 112px` 及每个子项行内 `style={{ width: '...%' }}` |
| **顶栏、按钮与分支节点高度** | 使用 `min-block-size`（如 `3.5rem`、`2.25rem`）+ 内边距支撑，允许系统大字号自然纵向生长 | 写死 `height: 48px` / `height: 58px` 导致字体放大 125% 时文字裁切 |
| **长列表与影像视窗滚动区** | 使用视口相对边界 `max-block-size: min(65dvh, 36rem); overflow-y: auto;` | 写死 `height: 242px` 或 `max-height: 620px` 造成小屏溢出、大屏留白 |

---

## 3. 前端工程工具链与编码纪律

为确保多人/多智能体协作不劣化代码质量，前端工具链统一如下：

1. **状态与服务端缓存分层**：
   - **URL 查询参数（`useWorkspaceParams`）**：承载页面视图（`view`）、检索词（`q`）、筛选条件、病例版本（`version`）、触发截点（`trigger`）与深链定位（`scenario`、`case`），保证刷新、前进/后退与分享链接 100% 还原上下文。
   - **TanStack Query + 集中式 `queryKeys`（`src/research/query-keys.ts`）**：承载全部后端 `/api/v2` 状态，禁止在组件内散落手写字符串数组 Query Key 或用 `useEffect + fetch` 手工同步服务端数据。
   - **Zod 运行时契约校验（`src/research/schemas.ts`）**：所有 API 响应必须先通过严格 Schema 解析再进入渲染层；不在前端伪造模型输出、Token 或安全门控结论。
2. **行内样式禁令（Inline Style Guardrail）**：
   - `.tsx` 组件严禁使用 `style={{ marginTop: ..., padding: ..., display: ..., maxWidth: ... }}` 等布局行内样式。
   - `style` 属性**仅允许传递动态 CSS 自定义属性（`--*`）**，例如交错序号 `--stagger-i`、合成层缩放比例 `--bar-scale`、网格比例 `--ready-fr` 以及分段器测量坐标 `--glider-x` / `--glider-scale`。
3. **标准化前端检查命令（`frontend/package.json`）**：
   - `npm run typecheck`：TypeScript 严格静态类型检查（`tsc --noEmit`）。
   - `npm run lint:ui`：运行零依赖静态架构守卫 `scripts/check-ui-standards.mjs`，自动扫描并阻断 `transition: all`、`ease-in` 入场曲线、违规行内布局样式及历史遗留硬编码色值。
   - `npm test`：运行 Vitest 契约、状态与本地化单元测试。
   - `npm run check`：一键串行执行 `typecheck + lint:ui + test`（提交前与 CI 必跑门禁）。
   - `npm run build`：执行全量检查并产出按 `framework` / `validation` 分包的 Vite 生产构建。
