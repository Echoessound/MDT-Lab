# MDT Lab V0.3

毕业设计《面向重大疾病全病程的 MDT 医疗多智能体序贯协同决策框架设计与实现》的本地科研系统原型。当前按《最终方案》推进可运行系统，论文安排在模型、数据与实验完成之后。

已经形成浏览器内的完整链路：**版本化合成病例 → 触发病程事件 → 调度相关专科 → 独立审阅与最多一轮定向讨论 → 证据与资料完整性检查 → 可追溯报告和审计**。页面展示后端实际执行结果，支持追加病程、历史版本、停止、重跑和刷新恢复。

项目提供 3 个手工编写的肺癌合成场景，可导入 Synthea CSV ZIP、TCIA NSCLC 临床 CSV、TCGA/cBioPortal 临床 TSV 与结构化研究 JSON，并保留来源和映射记录。Mock 以确定性规则模拟资料审阅，流程标签仅供科研核对。

- [技术方案与开发计划](docs/技术方案与开发计划.md)：当前实现、差距与后续验收标准。
- [前端架构与 iOS 交互工程规范](docs/前端架构与iOS交互工程规范.md)：融合 `emilkowalski/skills` 的动效曲线、内在 CSS Grid 布局与前端工程门禁规范。
- [API 与事件契约](docs/API与事件契约.md)：V0.3 `/api/v2` 与旧版兼容接口。
- [验收记录](docs/验收记录.md)：实际测试、浏览器检查与已知限制。

## 快速启动

当前默认使用 MongoDB。先启动独立副本集（端口 27018，不改变本机 27017 实例），保持该终端运行：

```bash
.venv/bin/python scripts/start_mongodb.py
```

也可选择 Docker：`docker compose up -d --wait mongodb`（两种方式选一种）。另一个终端启动网页：

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
# 先在另一个终端启动 MongoDB，或执行 docker compose up -d --wait mongodb
./start.sh
```

首次安装需要联网，安装后 Mock 演示可完全离线。当前工作区的 `.python/bin/python3.11` 也可用于重建 `.venv`。

## 控制台工作流

从「病例工作台」按病例名称、编号或数据来源检索，选择版本和触发事件后启动运行。「最近运行」可直接回到正在处理的任务。顶部「快速跳转」支持搜索页面、病例和运行编号。按 `⌘K`（Windows/Linux 为 `Ctrl+K`）打开，用 ↑、↓ 选择，Enter 打开，Esc 关闭。

| 页面 | 用途 |
| --- | --- |
| `/` | 病例目录，可按来源类型筛选、按末次事件或事件数量排序，旁边列出最近四次运行 |
| `/research/datasets` | 选择来源和获取方式、预检、确认导入，按批次或病例编号查询记录 |
| `/research/cases/{case_id}` | 选择版本、触发事件和调度方式，查看来源或追加人工合成事件 |
| `/research/runs` | 按状态、运行模式筛选，按运行、病例或触发事件编号检索 |
| `/research/agents?run={run_id}` | 固定监视一项运行，选择协作图中的专科核对意见与证据，或切换到实时审计 |
| `/research/runs/{run_id}` | 查看协作、运行输入和执行记录，停止进行中的运行或重跑已结束的任务 |
| `/research/runs/{run_id}/report` | 查看资料缺口、未解决分歧、初始与最终意见，下载报告或完整审计 |
| `/settings/models` | 管理命名连接方案，切换共享默认和专科连接，测试已保存的连接 |
| `/roadmap` | 使用说明，包含常用操作、输入范围及审阅结果解释 |
| `/legacy` | V0.2 三角色病例库与原有运行记录 |

### 用内置病例核对运行结果

1. 打开 `LUNG-SYN-001`，选择 v1 / `E002`（影像事件），采用按事件调度。只有肿瘤科与影像科参与，不能看到之后 `E003` 的病理记录；结果需要补充资料。
2. 打开任意证据引用，核对原始事实、来源与冻结版本；刷新后确认运行与审计恢复。
3. 选择 v1 / `E003`（病理事件）再次运行，参与角色变为肿瘤科与病理科，当前资料规则可通过。前后运行均保留独立报告。
4. 在最新病例版本中追加一个合成事件，生成新版本；切回旧版本检查原记录和报告没有被覆盖。
5. 打开 `LUNG-SYN-003` / `E004`，观察同日矛盾事实被保留、最终暂缓判断。也可选择“无效引用”或“角色失败”验证阻断路径。
6. 新建运行后立即停止，检查取消记录存在且不生成报告；在历史页查看或重跑其他已结束运行。

病例目录的检索、筛选、排序和页码保存在 URL 中。病例详情、运行和报告也可用当前链接重新打开选中的视图。宽屏可收起侧栏，窄屏通过顶部菜单切换模块。侧栏和深浅外观偏好保存在当前浏览器。

停止属于协作式取消，在流程或角色调用边界生效。已发出的模型 HTTP 请求需要返回或超时后才能结束。

## 外部数据与 Agent 群

仓库附带一份 ACRIN 6668 本地测试样本，含 12 例非小细胞肺癌患者的 121 个入组、PET、放疗与随访事件，采用 CC BY 3.0 许可。可在「数据导入」上传研究 JSON，将病例上限设为 12。病例 `ACRIN-6668-005` 的首次 PET 检查和判读间隔 16 天，可用于核对判读前后的证据范围。[本地样本](data/acrin_6668/local_sample.json) · [数据来源、字段映射与复算方法](data/acrin_6668/README.md)

打开「数据导入」，选择来源，连接官方数据源或上传本地文件，点击「开始预检」。核对病例数量、排除原因、来源和 SHA-256 后确认导入。点击导入结果中的病例，选择触发事件并启动 MDT。进入「Agent 群」后选择要监视的运行，在协作图中查看各专科的意见与引用，或打开审计及已生成的报告。数据源连接通过后端执行，支持本机 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`（含 SOCKS）环境配置。

- **Synthea CSV ZIP**：读取 patients、conditions 及可选 encounters、imaging_studies、procedures、medications、observations 表。只映射研究所需字段；姓名、地址、证件、保险与费用不导入。每病例超过1000条事件时明确排除，不静默截断。
- **TCIA NSCLC 临床 CSV**：导入可定位日期的检查与随访；无可用日期的病理、分子、治疗和结局字段保留为相关资料，不进入历史 Agent 输入。占位值保留为未知，不转换成阴性。
- **研究 JSON**：页面可下载模板，顶层为 `{"cases": [...]}`。病例遵循 `ResearchCase` 契约，须声明来源、许可、数据版本、病例类型、日期及事实；新导入版本须为1。无日期资料放入 `unplaced_records`。这不是任意 PDF/Word 的自动提取器。

每次最多20MB、1–50个病例；预检保存在内存15分钟，最多保留最近3份，确认后病例和批次在同一事务写入 MongoDB。相同批次重复提交返回已有结果；已有病例内容不同则整批回滚，保护历史版本。公开病例追加人工合成事件后标为混合来源，旧版本与旧报告保持不变。单纯存在检查记录不会被推断成影像或病理资料齐备。

官方地址可能短暂不可用或变更，瞬时下载失败最多自动重试一次，仍失败会返回可重试信息；也可从页面列出的官方地址下载后上传。在线连接只允许内置数据源及受限官方跳转。原始下载文件、数据库、运行输出和模型密钥不提交到 GitHub。仓库内契约测试的公开数据格式行是人工测试数据。

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

同日两条记录更新同一字段时，显式的 `supersedes_event_id` 决定更正关系。资料缺口、规则引用和自适应专科调度共享有效值，原记录仍可在证据表内追溯。对于取值冲突且无法确定更正顺序的关键字段，门控保留分歧。报告的独立审计逐项核对冻结事件、完整证据表和意见中的引用副本。

系统检查流程标签分歧、结构化事实差异和同日来源冲突，最多让相关角色讨论一轮。初始意见完整保留，讨论各角色读取同一份初始意见快照。

| 最终标签 | 含义与触发条件 |
| --- | --- |
| `READY_FOR_REVIEW` | 本次所选角色意见有效、没有未解决分歧、当前科研规则要求的资料齐备，可进入人工资料复核 |
| `NEED_MORE_INFORMATION` | 没有阻断性失败，但仍有资料缺口或有效意见要求补充资料 |
| `DEFER_DECISION` | 角色失败、非法证据、未解决矛盾或有效意见要求暂缓 |

`completed` 只表示工作流执行完毕，可能仍得到 `DEFER_DECISION`。是否可下载报告以 `report_ready` 为准。信息完整性规则是本项目的研究条件，引用校验只说明与输入事实一致，不证明医学正确。

Mock 场景包括 `standard`、`partial_failure`、`persistent_disagreement`、`invalid_evidence`。“保留分歧”至少需要两个参与角色；需要时使用固定全员模式。Mock 不使用 Token，相关计数显示为未知/不适用，不伪造调用用量。

## 离线批量对照

各方法按相同的基础病例、版本和触发事件配对，A1 与 A2 对输入的调整见下表。下列命令在 `mdt-demo` 仓库根目录执行。脚本记录冻结输入的 SHA-256、可见事件数和事实数，运行标准 Mock。

```bash
.venv/bin/python scripts/run_mock_experiments.py --output-dir outputs/experiments/seed --export-paper
.venv/bin/python scripts/run_mock_experiments.py --source tcia_nsclc_csv --input data/raw/external/tcia_nsclc_clinical.csv --max-cases 50 --output-dir outputs/experiments/tcia
.venv/bin/python scripts/run_mock_experiments.py --source synthea_csv --input data/raw/external/synthea_sample_csv.zip --max-cases 3 --triggers latest --output-dir outputs/experiments/synthea
```

`--triggers all` 为默认值，按日期及同日事件编号逐个截取。`latest` 只取每个病例的末次事件。外部来源沿用导入器的纳排和排序规则，TCGA/cBioPortal 和研究 JSON 分别使用 `--source tcga_cbioportal_tsv` 与 `--source research_json`，通过 `--input` 指定文件。`results.json` 保留来源和许可、病例族、场景清单、实现指纹、失败尝试及逐方法结果。用同一命令续跑时，脚本复用 SQLite 检查点的成功记录，只重试失败截点。改变输入、截点范围、执行实现或运行环境后，使用新的输出目录。

| 方法 | 实际比较条件 |
| --- | --- |
| B0 / B1 | B0 由通用角色独立审阅一次。B1 固定四专科各做一次初审，以有效意见的相对多数给出标签。平票记暂缓，零有效意见记为无输出。 |
| B2 / B3 | 二者读取同一条按事件路由、含定向讨论的轨迹。B2 取门控前的有效意见聚合，B3 取门控后的最终标签。 |
| A1 / A3 / A4 | 分别在 B3 上单独移除前序事件、改为固定全员、关闭讨论。调用节省率的分母为 A3 的角色调用数，含讨论轮次。 |
| A2 | 在冻结副本中尝试按证据生成扩展事件。无支持证据时使用 B3 轨迹。结果中记录实际使用的输入版本、触发事件和轨迹编号。 |

**单人盲标与重评分。** 启动网页后，标注人可直接进入单人盲标页，填写编号，按截点材料选择必要专科、流程标签和引用事实。每个截点保存一份参考判断，材料指纹和引用范围在保存及评分时校验。研究者可在「8 组配对实验与导出」选择「导出全库盲标 JSON」，再对同一批次重评分。以浏览器将文件保存到下载目录为例。[打开单人盲标页](http://127.0.0.1:8000/research/experiments?view=annotate)

```bash
.venv/bin/python scripts/run_mock_experiments.py --output-dir outputs/experiments/seed --annotations "$HOME/Downloads/mdt_blind_annotations.json"
```

**统计口径。** B3 与 B2 的门控拦截率以 B2 拟放行的截点为分母，分子为其中 B3 改判补件或暂缓的数量。带独立参考时，错误放行率以参考要求补件或暂缓的截点为分母，专科召回率按可评分截点的必要专科覆盖比例取平均。95% 区间以病例族为单位重抽样 1,000 次，种子为 2026。可评病例族少于两个时省略区间，分母为零时省略点估计。仅在每个有标注病例族贡献一个标注截点时，对两种方法判断正确与否做精确 McNemar 检验。

**核验导出。** `--export-paper` 或 `--annotations` 会在全部截点完成后，从检查点的实际方法记录生成 `scores.csv`、`ablation_table.tex` 和 `statistics_summary.json`。摘要的 `provenance` 保存批次清单、评分代码和参与评分的标注指纹，并计数批次外标注及带材料指纹的标注。可在输出目录执行 `shasum -a 256 results.json scores.csv ablation_table.tex`，逐项对照 `results_sha256`、`scores_csv_sha256` 和 `latex_table_sha256`。

工作台「智能流程与影像」可查看同截点的建议分工、影像检查登记和方法对照。「专科调度依据」显示实际运行的路由。若曾使用 `f8f6bc6` 的自动补齐生成过合成版本，请从补齐前的原始版本重算，再引用研究结果。本轮复算的样本量、标签分布及复核记录见[验收记录](docs/验收记录.md)。

## 真实模型适配器

V0.3 已实现服务端 OpenAI 兼容 Chat Completions 适配器；**当前只用模拟 HTTP 上游测试，尚未使用真实凭据验证任何模型服务，也没有发起付费调用**。

在「模型设置」先选择「共享默认」或具体专科。点击「新建方案」，填写名称、服务地址、模型标识和密钥，再从卡片启用到当前范围。卡片显示直接使用或继承使用状态，也可先测试未启用的方案。首次切离已保存的直接配置时，可以「先存为方案」，之后从列表切回。具有独立连接的专科可选择「恢复共享默认设置」。浏览、创建和测试均为独立动作，通过卡片上的启用按钮切换当前连接。[CC Switch 切换设计](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/zh/2-providers/2.2-switch.md)

共享默认会应用于所有继承该配置的专科。直接绑定到专科的方案通过该专科单独切换。编辑命名方案会更新所有使用它的范围，参数在新建运行时冻结。运行详情保留当时的方案名称、编号和模型参数。正在使用的方案需先解除绑定或切换后才可删除。也可继续在具体范围填写直接配置。切换范围会保留页面内的未保存草稿。

服务需要支持 Chat Completions、严格 JSON Schema、`temperature` 与 `max_tokens` 参数。连接测试向所选服务发送一条不含病例的短请求，可能产生费用。密钥通过 Fernet 加密写入 `model_settings`，网页、运行、报告和审计只读公开配置。加密主密钥位于 `outputs/.model-settings.key`，权限为 0600，也可由 `MDT_SECRET_KEY` 提供。使用同一密钥重启可恢复方案和绑定。更换服务地址，或从方案切回直接配置时，请填写该连接的密钥。

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

访问 <http://127.0.0.1:5173>，Vite 代理 `/api`（包括 SSE 和旧版 WebSocket）到后端。日常本地使用可运行 `./start.sh`。`MDT_DEMO_EVENT_DELAY` 控制网页运行的事件间隔，默认 0.22 秒，范围 0–2 秒。

### Electron 桌面入口

启动本地服务后可以在浏览器打开桌面入口。入口参数 `shell=desktop` 启用哈希路由，页面路径和筛选参数均跟在 `#` 之后。后续 Electron 的 `BrowserWindow.loadURL` 可加载同一入口，由本机 FastAPI 同源提供前端资源、REST、事件流及下载。当前交付为 Web 控制台，Electron 主进程及安装包属于后续工作。[打开桌面病例工作台](http://127.0.0.1:8000/?shell=desktop#/) · [打开影像科模型设置](http://127.0.0.1:8000/?shell=desktop#/settings/models?agent=radiology)

### 运行测试

```bash
MDT_TEST_MONGODB_URI='mongodb://127.0.0.1:27018/?replicaSet=mdt-rs&directConnection=true' .venv/bin/python -m pytest -q
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
│   │   ├── persistence/        # Repository 契约、MongoDB、配置工厂、迁移
│   │   ├── store.py            # 显式 SQLite 兼容适配器
│   │   ├── import_service.py   # 数据预检、过期与批次提交
│   │   ├── service.py          # 有界任务线程、取消、超时、恢复
│   │   ├── api.py              # /api/v2 REST + SSE
│   │   ├── provider.py         # 冻结模型的 HTTP 执行与输出校验
│   │   ├── agent_settings.py   # 共享默认、角色覆盖、运行时分派
│   │   ├── secret_vault.py     # 独立密钥与凭据加密
│   │   └── provider_api.py     # 模型设置 API
│   └── ...                    # 原 CLI / V0.2 实现保留
├── frontend/src/console/      # 控制台导航、快速跳转、外观与侧栏偏好
├── frontend/src/research/     # 病例工作台、运行监视、导入、模型设置与接口契约
├── docs/                      # 技术方案、接口和验收
├── compose.yaml               # 本机 MongoDB 单节点副本集
├── scripts/                   # 契约导出、MongoDB 启动、迁移
├── tests/                     # Python 测试
└── outputs/
    ├── mongodb/               # 本机 MongoDB 数据目录（Docker 使用命名卷）
    ├── .model-settings.key    # 本机加密主密钥，不提交 Git
    ├── research.sqlite3       # 迁移保留的旧库 / 显式兼容模式
    ├── backups/               # 迁移前备份
    └── <legacy_run_id>/       # 旧版报告、审计、快照文件
```

每个服务使用 2 个工作线程，最多接受 4 个未完成任务。必须使用 **单 Uvicorn worker**：任务、取消标志和配置缓存属于当前进程。MongoDB 使用副本集事务、唯一版本/审计序号索引；正常报告、报告事件与终态事件在同一事务中提交。仓储接口保留追加语义，但数据库管理员仍可修改数据，这不是加密防篡改证明。单文档限制为 15MiB，超过时明确拒绝，不截断。

服务重启可读取历史；上次进程未完成的运行标记为 `process_interrupted`，不会自动续跑。历史列表返回最近 100 条，浏览器保留最新 500 条审计，完整日志仍可下载。备份 MongoDB 可使用 `mongodump`，或停止应用与 MongoDB 后备份本地数据目录/命名卷；加密主密钥必须单独安全备份。不要复制正在写入的 MongoDB 原始文件作为一致性备份。

## MongoDB 配置与迁移

复制 `.env.example` 为 `.env` 后按需调整 `MDT_MONGODB_URI` 和 `MDT_MONGODB_DATABASE`。默认数据库 `mdt_lab`，连接单节点 `mdt-rs`。也支持具备事务能力的 MongoDB Atlas/副本集；连接凭据仅放环境配置，不进入页面。选择 MongoDB 后连接失败会停止启动，不会偷偷回退到其他库。

迁移前先停止应用（保留 MongoDB 运行），以免源库或目标库继续变化：

```bash
.venv/bin/python scripts/migrate_mongodb.py                    # 只预检
.venv/bin/python scripts/migrate_mongodb.py --commit           # 原子写入并核对 SHA-256
```

迁移读取旧库，不删除或改写源文件；保留所有病例版本、事件、运行、审计、报告、批次和已有加密模型设置。重复迁移相同记录不重复插入；目标内容不同则整批拒绝。若迁移了模型设置，必须保留原加密主密钥。可用 `--database` 指定新的目标库。

`MDT_STORAGE_BACKEND=sqlite` 是显式兼容选项。自动化测试中的 `create_app(tmp_path)` 默认使用隔离 SQLite；需要 MongoDB 时显式传入 `StorageConfig`。MongoDB 集成测试使用随机独立数据库并清理自己创建的数据，不操作 `mdt_lab`。不提供 `MDT_TEST_MONGODB_URI` 时这些集成测试会跳过；CI 会启动真实副本集执行。

## 当前边界与下一阶段

当前可在本地复算五类来源（含内置病例）的八组 Mock 对照。TCIA 和 TCGA/cBioPortal 提供临床表，日期可定位的资料进入时间线，缺少可用时点的字段保留在来源资料中。影像模块支持检查登记与附件复核。真实影像像素推理、指南检索、临床推荐、身份认证和公网部署仍属后续范围。录入者负责确认自由文本适用于科研共享，`case_kind` 只记录声明的病例来源类别。

正式论文实验仍需冻结测试队列，由独立人员完成参考标注和争议仲裁，使用真实模型先做小样本联调，再按同一协议留存调用、失败、耗时和 Token 记录。当前已支持单人参考标注与多人独立盲标/一致性统计（Cohen's κ、专科 Jaccard）及争议仲裁工作台，并新增独立时间边界防泄漏审计、首轮模型引用校验脱敏计数、`scripts/run_llm_benchmark.py`（G01 真实模型联调与配对消融）及 `scripts/build_repro_pack.py`（病例族分层 `dev/test` 划分与计划书 §6.4 复现包构建）。当前回归结果用于核对流程与复算能力。
