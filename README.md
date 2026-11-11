# MDT Lab V0.3

毕业设计《面向重大疾病全病程的 MDT 医疗多智能体序贯协同决策框架设计与实现》的本地科研系统原型。当前按《最终方案》推进可运行系统，论文安排在模型、数据与实验完成之后。

已经形成浏览器内的完整链路：**版本化合成病例 → 触发病程事件 → 调度相关专科 → 独立审阅与最多一轮定向讨论 → 证据与资料完整性检查 → 可追溯报告和审计**。页面展示后端实际执行结果，支持追加病程、历史版本、停止、重跑和刷新恢复。

提供 3 个手工编写的肺癌合成场景，并支持 Synthea、TCIA 临床表与结构化研究 JSON 导入，全部明确标注来源。Mock 是确定性流程脚本，不是医学推理；资料审阅标签不构成诊断、治疗或处方建议。

- [技术方案与开发计划](docs/技术方案与开发计划.md)：当前实现、差距与后续验收标准。
- [API 与事件契约](docs/API与事件契约.md)：V0.3 `/api/v2` 与旧版兼容接口。
- [验收记录](docs/验收记录.md)：实际测试、浏览器检查与已知限制。

## 快速启动

当前工作区已安装依赖：

```bash
cd "/Users/echo/真正的代码库/毕业论文/mdt-demo"
./start.sh
```

打开 <http://127.0.0.1:8000>。脚本使用已有依赖重新构建前端，以单 worker 启动服务；不会下载依赖或自动请求外部模型。按 `Ctrl+C` 关闭。端口固定为 8000，启动前需确保没有另一个本项目服务占用端口。

迁移到其他电脑时使用 Python 3.11+ 和兼容 Vite 的 Node.js（建议 22 LTS 或 24 LTS），先安装：

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e ".[api,dev]"
cd frontend
npm ci
npm run build
cd ..
./start.sh
```

首次安装需要联网，安装后 Mock 演示可完全离线。当前工作区的 `.python/bin/python3.11` 也可用于重建 `.venv`。

## 页面与演示路径

| 页面 | 用途 |
| --- | --- |
| `/` | 自建与导入的版本化病例及最近运行 |
| `/research/datasets` | 官方数据连接、文件预检、确认导入、批次记录与 JSON 模板 |
| `/research/agents` | Agent 群：病例入口、实际角色状态、冻结输入数据通路、SSE 审计与报告 |
| `/research/cases/{case_id}` | 选择病例版本、触发事件和调度方式；追加合成事件 |
| `/research/runs/{run_id}` | 实际节点进度、四专科状态、讨论、证据检查与 SSE 审计 |
| `/research/runs/{run_id}/report` | 冻结输入、初始/最终意见、未解决分歧、报告与审计下载 |
| `/research/runs` | 历史运行，按版本和触发事件追溯 |
| `/settings/models` | 服务端模型连接配置、短请求测试与清除配置 |
| `/roadmap` | 当前实现与后续开发顺序 |
| `/legacy` | 保留的 V0.2 三角色基础 Demo |

建议先用标准 Mock 场景演示以下过程：

1. 打开 `LUNG-SYN-001`，选择 v1 / `E002`（影像事件），采用按事件调度。只有肿瘤科与影像科参与，不能看到之后 `E003` 的病理记录；结果需要补充资料。
2. 打开任意证据引用，核对原始事实、来源与冻结版本；刷新后确认运行与审计恢复。
3. 选择 v1 / `E003`（病理事件）再次运行，参与角色变为肿瘤科与病理科，当前资料规则可通过。前后运行均保留独立报告。
4. 在最新病例版本中追加一个合成事件，生成新版本；切回旧版本检查原记录和报告没有被覆盖。
5. 打开 `LUNG-SYN-003` / `E004`，观察同日矛盾事实被保留、最终暂缓判断。也可选择“无效引用”或“角色失败”验证阻断路径。
6. 新建运行后立即停止，检查取消记录存在且不生成报告；在历史页查看或重跑其他已结束运行。

支持桌面与移动端、深浅主题、证据弹窗、审计筛选及 JSON 查看。停止属于协作式取消，在流程或角色调用边界生效；已发出的模型 HTTP 请求需要返回或超时后才能结束。

## 外部数据与 Agent 群

打开 `/research/datasets`，选择数据源，使用“连接官方数据源并预检”或上传本地文件；核对数量、排除原因、来源和 SHA-256 后确认导入。点击导入结果中的病例，选择触发事件并启动 MDT，在 `/research/agents` 或运行详情查看真实进度与报告。数据源连接通过后端执行，支持本机 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`（含 SOCKS）环境配置。

- **Synthea CSV ZIP**：读取 patients、conditions 及可选 encounters、imaging_studies、procedures、medications、observations 表。只映射研究所需字段；姓名、地址、证件、保险与费用不导入。每病例超过1000条事件时明确排除，不静默截断。
- **TCIA NSCLC 临床 CSV**：导入可定位日期的检查与随访；无可用日期的病理、分子、治疗和结局字段保留为相关资料，不进入历史 Agent 输入。占位值保留为未知，不转换成阴性。
- **研究 JSON**：页面可下载模板，顶层为 `{"cases": [...]}`。病例遵循 `ResearchCase` 契约，须声明来源、许可、数据版本、病例类型、日期及事实；新导入版本须为1。无日期资料放入 `unplaced_records`。这不是任意 PDF/Word 的自动提取器。

每次最多20MB、1–50个病例；预检保存在内存15分钟，最多保留最近3份，确认后病例和批次在同一事务写入 SQLite。相同批次重复提交返回已有结果；已有病例内容不同则整批回滚，保护历史版本。公开病例追加人工合成事件后标为混合来源，旧版本与旧报告保持不变。单纯存在检查记录不会被推断成影像或病理资料齐备。

官方地址可能短暂不可用或变更，失败会返回可重试信息；也可从页面列出的官方地址下载后上传。在线连接只允许内置数据源及受限官方跳转。原始下载文件、数据库、运行输出和模型密钥不提交到 GitHub。仓库内契约测试的公开数据格式行是人工测试数据。

命令行也可执行同样的流程：

```bash
.venv/bin/python scripts/download_datasets.py synthea_csv
.venv/bin/python scripts/import_dataset.py synthea_csv data/raw/external/synthea_sample_csv.zip --max-cases 3
# 核对预检结果后写入本地数据库
.venv/bin/python scripts/import_dataset.py synthea_csv data/raw/external/synthea_sample_csv.zip --max-cases 3 --commit
```

## 调度、讨论与门控规则

当前注册角色为肿瘤科、影像科、外科、病理科。按事件调度根据显式规则选择参与者；“固定全员对照”调用全部四个角色。被跳过的角色不会计为失败，覆盖率分母是本次实际选择的角色数。

病例按日期与事件 ID 排序，运行只使用所选版本中截至触发事件的记录。每个事实由后端生成 `event_id:fact_key` 形式的证据 ID，并附带来源元数据。模型输出必须匹配角色、引用 ID、事实键、值及类型；来源不由模型自行填写。

系统检查流程标签分歧、结构化事实差异和同日来源冲突，最多让相关角色讨论一轮。初始意见完整保留，讨论各角色读取同一份初始意见快照。

| 最终标签 | 含义与触发条件 |
| --- | --- |
| `READY_FOR_REVIEW` | 本次所选角色意见有效、没有未解决分歧、当前科研规则要求的资料齐备，可进入人工资料复核 |
| `NEED_MORE_INFORMATION` | 没有阻断性失败，但仍有资料缺口或有效意见要求补充资料 |
| `DEFER_DECISION` | 角色失败、非法证据、未解决矛盾或有效意见要求暂缓 |

`completed` 只表示工作流执行完毕，可能仍得到 `DEFER_DECISION`。是否可下载报告以 `report_ready` 为准。信息完整性规则是本项目的研究条件，引用校验只说明与输入事实一致，不证明医学正确。

Mock 场景包括 `standard`、`partial_failure`、`persistent_disagreement`、`invalid_evidence`。“保留分歧”至少需要两个参与角色；需要时使用固定全员模式。Mock 不使用 Token，相关计数显示为未知/不适用，不伪造调用用量。

## 真实模型适配器

V0.3 已实现服务端 OpenAI 兼容 Chat Completions 适配器；**当前只用模拟 HTTP 上游测试，尚未使用真实凭据验证任何模型服务，也没有发起付费调用**。

在“模型设置”填写服务地址、模型标识与密钥后，可测试已保存配置，再选择 LLM 运行。服务需要支持 Chat Completions、严格 JSON Schema、`temperature` 与 `max_tokens` 参数；不能据此假定所有兼容服务或所有模型都可直接使用。测试按钮发送不含病例的短请求，实际使用时可能产生费用。

密钥只保存在后端进程内存中，不回传、不写入数据库或审计；浏览器提交成功后清空密码框。服务重启后需要重新配置。每次运行冻结其模型配置，后续更改或清除设置不会改写已启动运行。改变服务地址时必须重新输入密钥。

模型连接只接受公开 HTTPS 目标，拒绝本机/内网地址和重定向。单次请求最多重试一次，验证失败按失败处理；未配置 LLM 时拒绝启动，不自动替换为 Mock。上游未提供 Token 用量时记录为 `null`。

旧 `.env` / CLI 配置不负责 V0.3 模型连接；旧 CLI `--mode llm` 仍未实现。新模型能力仅通过 `/api/v2` 和研究工作台提供。

## 开发与验证

开发时分别启动后端与前端：

```bash
# 终端 A
.venv/bin/python -m uvicorn mdt_demo.api:app --host 127.0.0.1 --port 8000 --reload
```

```bash
# 终端 B
cd frontend
npm run dev
```

访问 <http://127.0.0.1:5173>，Vite 代理 `/api`（包括 SSE 和旧版 WebSocket）到后端。正式本地演示用 `./start.sh`。`MDT_DEMO_EVENT_DELAY` 控制网页演示节奏，默认 0.22 秒，范围 0–2 秒；不会给旧 CLI 添加延迟。

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m mdt_demo --case data/synthetic_case_001.json --mode mock
cd frontend
npm run test
npm run build
```

前端契约 fixture 由真实临时 API 输出生成。后端契约变更后，从项目根目录运行对应导出脚本，再测试前端：

```bash
.venv/bin/python scripts/export_research_contract.py
.venv/bin/python scripts/export_frontend_contract.py
```

最新测试数量、构建结果、浏览器检查与警告统一记录在 [验收记录](docs/验收记录.md)。测试验证软件行为，不评价临床有效性。

## 目录与数据保存

```text
mdt-demo/
├── start.sh
├── src/mdt_demo/
│   ├── api.py                  # 共用 FastAPI 入口、来源检查、前端静态服务
│   ├── research/
│   │   ├── schemas.py          # 版本病例、证据、意见、报告契约
│   │   ├── seeds.py            # 三个明确标注来源的手工合成场景
│   │   ├── engine.py           # 时序冻结、路由、讨论与证据门控
│   │   ├── store.py            # SQLite 病例版本、运行、审计、报告
│   │   ├── service.py          # 有界任务线程、取消、超时、恢复
│   │   ├── api.py              # /api/v2 REST + SSE
│   │   ├── provider.py         # 服务端模型适配器与内存配置
│   │   └── provider_api.py     # 模型设置 API
│   └── ...                    # 原 CLI / V0.2 实现保留
├── frontend/src/research/     # React 页面、Zod 契约、SSE 恢复与样式
├── docs/                      # 技术方案、接口和验收
├── scripts/                   # 契约导出
├── tests/                     # Python 测试
└── outputs/
    ├── research.sqlite3       # V0.3 数据库（运行时可能有 -wal / -shm）
    └── <legacy_run_id>/       # 旧版报告、审计、快照文件
```

每个服务使用 2 个工作线程，最多接受 4 个未完成任务。必须使用 **单 Uvicorn worker**：任务、取消标志和模型设置属于当前进程。运行历史与病例版本写入 SQLite；正常报告、报告事件与终态事件在同一事务中提交。病例版本、病程事件与审计表禁止通过普通 SQL 更新/删除，但这不构成加密防篡改证明。

服务重启可读取历史；上次进程未完成的运行标记为 `process_interrupted`，不会自动续跑。历史列表返回最近 100 条，浏览器保留最新 500 条审计，完整日志仍可下载。备份时先停止服务，再复制整个 `outputs/`，保留可能存在的 SQLite 附属文件。

## 当前边界与下一阶段

已接入 Synthea CSV ZIP、TCIA/NSCLC-Radiogenomics 临床 CSV 与研究 JSON；TCGA/cBioPortal 尚未接入。当前没有真实影像推理、指南检索、临床推荐、认证或公网部署能力。`case_kind="synthetic"` 和来源标记不能自动证明用户填写的自由文本确实不含真实信息。

后续依次完成：**真实模型小样本验证 → 扩展数据映射与独立场景标注 → 基线/消融实验 → 依据实际结果撰写论文**。现有固定全员模式可用于观察调用差异，但还不是完整的实验平台。
