# API 与事件契约 V0.3

本地地址 `http://127.0.0.1:8000`，交互文档 `/docs`。研究工作台使用 `/api/v2` 和 SSE；V0.2 的 `/api/v1`、WebSocket 与 CLI 保留兼容。Vite 开发端口 5173 代理 `/api` 到后端。

当前单进程、单 Uvicorn worker 运行；研究服务使用两个工作线程，最多四个未完成任务。数据包含明确标注来源的合成与公开研究病例。

## V0.3 REST

下表路径均省略 `/api/v2`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 版本、实际存储后端/SSE 状态、演示节奏 |
| GET | `/storage` | 实际数据库后端、名称、连接与事务状态，不返回 URI/凭据 |
| GET | `/settings/agents` | 四角色的有效配置、继承来源与已配置状态 |
| GET / PUT / DELETE | `/settings/agents/{agent_id}` | 查看/覆盖/恢复默认，支持四个注册角色 |
| POST | `/settings/agents/{agent_id}/test` | 测试该角色的有效已保存配置 |
| GET | `/cases` | 各病例最新版本 |
| GET | `/cases/{case_id}?version=1` | 指定版本完整病例；省略 version 返回最新 |
| POST | `/cases/{case_id}/events` | 追加合成事件并返回新版本，201 |
| GET | `/cases/{case_id}/routing?trigger_event_id=E002&version=1&routing_mode=event` | 所选事件与版本的路由预览 |
| GET | `/cases/{case_id}/workflow-plan` | 依据可见证据生成审阅计划、建议分工及可追溯补齐建议。实际执行的角色由 routing 接口给出。 |
| GET | `/cases/{case_id}/imaging` | 截点内的影像登记、来源列、证据编号及记录矛盾。仅有事件元数据时，像素质控状态为 `not_assessed`，DICOM、组学、分割与评分为 `null`。 |
| GET | `/cases/{case_id}/ablation` | 执行 `mock-matrix-v2` 标准规则对照，返回 B0–B3、A1–A4 的方法条件、实际调用和标签。 |
| POST | `/cases/{case_id}/auto-enrich` | 按 `expected_version` 和可选 `trigger_event_id` 生成有证据依据的合成扩展版本，成功返回 201。 |
| POST | `/runs` | 创建运行并立即返回快照，202 |
| GET | `/runs` | 最近 100 条运行快照 |
| GET | `/runs/{run_id}` | 权威状态、角色、进度、门控与最后序号 |
| POST | `/runs/{run_id}/cancel` | 请求边界取消；结束或报告已保存时为 409 |
| POST | `/runs/{run_id}/rerun` | 重用病例版本、触发事件和运行选项，新 ID 与 `source_run_id`，202 |
| GET | `/runs/{run_id}/report` | 已保存报告；尚无报告为 409 |
| GET | `/runs/{run_id}/report/download` | JSON 附件 |
| GET | `/runs/{run_id}/audit?after_seq=0&limit=500` | 排他游标增量审计；limit 1–500 |
| GET | `/runs/{run_id}/audit/download` | JSONL 附件，截到请求时快照的已提交末尾 |
| GET | `/runs/{run_id}/events?after_seq=0` | SSE 重放与实时事件 |
| GET / PUT / DELETE | `/settings/llm` | 查看、保存、清除持久共享默认模型设置 |
| POST | `/settings/llm/test` | 使用已保存配置发短请求验证连接，不含病例 |
| GET / POST | `/settings/llm/profiles` | 列出和新建命名连接方案 |
| POST | `/settings/llm/profiles/from-scope` | 从当前范围的有效配置生成独立方案 |
| PUT / DELETE | `/settings/llm/profiles/{profile_id}` | 编辑和删除命名方案 |
| POST | `/settings/llm/profiles/{profile_id}/activate` | 启用到共享默认或指定专科 |
| POST | `/settings/llm/profiles/{profile_id}/test` | 测试指定方案，包括尚未启用的方案 |

新建及编辑接收 `name` 和原模型配置的平铺字段。归档接收 `{scope, name}`，启用接收 `{scope}`。`scope` 可取 `default` 或四个注册专科。列表和保存响应包含 `profile_id`、`name` 和公开连接参数。启用返回所选范围的有效状态。有效状态和运行模型快照在采用方案时附有 `profile_id` 与 `profile_name`。旧范围的直配和历史快照仍可读取。

直接保存共享默认或专科配置会改用该范围自己的连接。归档在服务端复制保存当前参数及密钥，调用者无需重发密钥。在用方案返回 `409 LLM_PROFILE_IN_USE`，重名返回 `409 LLM_PROFILE_NAME_CONFLICT`。更新同一方案且服务地址相同可留空密钥。采用方案的范围转为直接配置时需提供密钥。

普通成功响应为 `{ "data": ... }`，审计分页的 data 为 `{ "events": [], "next_seq": 0 }`。错误至少包含 `{ "error": { "code": "...", "message": "..." } }`，部分共用错误处理还返回 `details`、`retryable`、`request_id`。文件下载与 SSE 不使用 data 外层。客户端应允许附加字段，且不能依赖模型错误返回原始异常或响应正文。

### 截点分析与补齐

工作流计划、影像登记和方法对照均接受 `version` 和 `trigger_event_id`。省略时使用最新版本或该版本末次事件，显式指定不存在的事件返回 404。补齐建议的 `source_evidence_id` 指向冻结事实，`rule_id` 标识映射规则。只有 `can_auto_enrich` 为真时才可写入。无可安全追加的事实返回 422 `NO_SUPPORTED_ENRICHMENT`，版本落后返回 409 `CASE_VERSION_CONFLICT`。当前支持从有日期的病理事件中明确且符合词表的组织学分型映射研究标记。仅有检查登记或无日期汇总时，缺件继续保留。有矛盾的分型须先复核，显式的缺失标记也会阻止自动补齐。

### 创建运行

```json
{
  "case_id": "LUNG-SYN-001",
  "case_version": 1,
  "trigger_event_id": "E002",
  "mode": "mock",
  "mock_scenario": "standard",
  "routing_mode": "event"
}
```

- `mode`：`mock` 或 `llm`。LLM 尚未配置时返回 409，不降级到 Mock。
- `mock_scenario`：`standard`、`partial_failure`、`persistent_disagreement`、`invalid_evidence`。LLM 使用 `standard`；异常场景不能用于真实模型运行。
- `routing_mode`：`event` 按触发类型调度，`fixed` 固定四角色。
- 版本和触发事件必须存在；未知字段或非法值返回 422。达到任务上限返回 429。
- `persistent_disagreement` 需要至少两名角色；只调度一名角色时运行以 `scenario_requires_multiple_agents` 失败。
- 重跑固定原病例和运行选项，但 LLM 配置取重跑启动时的当前设置。运行和报告的 `model_configuration` 保留各角色非敏感参数快照；重跑不会恢复历史密钥或参数。

### 追加病程事件

```json
{
  "expected_version": 1,
  "event": {
    "occurred_at": "2026-02-11",
    "event_type": "pathology",
    "title": "补充病理资料（合成）",
    "facts": {
      "pathology_confirmed": true,
      "pathology_record": "本地人工合成补充记录"
    }
  }
}
```

日期严格使用 `YYYY-MM-DD`；事实为非空对象，值只能为字符串、有限数字、布尔或 `null`。事件类型：`diagnosis`、`imaging`、`pathology`、`molecular_test`、`procedure`、`treatment`、`medication`、`toxicity`、`follow_up`、`progression`、`recurrence`、`observation`。

`expected_version` 过期返回 409 `CASE_VERSION_CONFLICT`。服务器生成事件 ID、来源标记和新版本，不接受客户端覆写来源。新事件不覆盖旧事件或报告；旧版本仍可查询。

### 模型配置

PUT 请求字段为 `provider`、`base_url`、`model`、`api_key`、`timeout_seconds`、`temperature`、`max_output_tokens`。Provider 当前仅允许 `openai-compatible`；默认地址 `https://api.openai.com/v1`，模型标识由使用者填写，不提供默认模型。

参数范围：超时 1–60 秒，temperature 0–2，最大输出 Token 128–8192。首次配置或更换地址必须提供密钥；同地址留空可保留该配置已有密钥；新增独立配置不复制默认或其他角色的密钥。GET 和 PUT 返回 `configured`、`has_api_key` 与非敏感参数，永不返回密钥。

模型服务需支持 Chat Completions 的严格 JSON Schema、`temperature` 和 `max_tokens`。仅接受公开 HTTPS 目的地，不跟随重定向。每次请求至多重试一次；输出必须通过角色、结构和引用校验。连接测试可能产生实际费用，当前工程验收只使用模拟上游，未验证真实服务。

配置经加密持久保存，重启恢复；每个已接受运行冻结启动时配置。`configuration_source` 为 `agent` / `default` / `unconfigured`，`overridden` 表示是否独立覆盖。DELETE 角色配置恢复继承；DELETE 默认配置保留独立覆盖。只要本次选中角色有缺失，创建 LLM 运行即返回 409，尚未创建运行记录。清除设置不改变正在执行的运行。

运行与报告新增 `model_configuration` 数组：`agent_id, configuration_source, provider, base_url, model, timeout_seconds, temperature, max_output_tokens`；Mock 为 `[]`，旧记录可能无此字段。密钥不进入此数组。

`GET /storage` 返回 `{backend:"mongodb",database:"mdt_lab",connected:true,status:"connected",transactions:true,schema_version:1}`。数据库连接故障返回 503；副本集未启用在启动时返回 `MONGODB_TRANSACTIONS_REQUIRED`；无静默降级。

## 数据和输出契约

| 类型 | 关键字段与语义 |
| --- | --- |
| ResearchCase | `case_id, version, case_kind, patient, timeline, provenance`；synthetic / public_research / mixed |
| ClinicalEvent | `event_id, occurred_at, event_type, facts, source, source_record_id, synthetic_extension, confidence, introduced_in_version` |
| Routing | `strategy_version, trigger_event_id, selected_agents, skipped_agents, reasons` |
| EvidenceRef | `evidence_id, event_id, fact_key, value, source_name, source_record_id, dataset_version, synthetic, quote_or_fact`；后端生成 |
| Opinion | `agent_id, decision, summary, evidence_ids, claims, missing_information, confidence, opinion_id, evidence_refs, model_info` |
| Safety | `decision, status, checks, missing_information, warnings`；状态 passed / needs_information / blocked |
| Metrics | `agent_calls, llm_calls, tool_calls, retry_count, prompt_tokens, completion_tokens, elapsed_ms`；未知用量为 null |
| Report | 冻结病例、路由、证据注册表、初始/最终意见、讨论记录、初始/未解决分歧、门控、指标与最终标签 |

证据 ID 格式为 `event_id:fact_key`。断言 `claims` 必须引用已注册 ID，事实键、值和类型必须匹配；不能把字符串 `"true"` 或数字 `1` 当作布尔 `true`。证据来自冻结上下文，未来事件不允许被引用。

最终标签仍为 `READY_FOR_REVIEW`、`NEED_MORE_INFORMATION`、`DEFER_DECISION`，只表示资料审阅流程。角色置信等级不是经过校准的医学可靠性概率。

## 运行状态、事务与事件

快照状态主路径为 `queued → running → completed / incomplete / failed`；取消为 `cancel_requested → cancelled`。门控阻断不必导致工作流 failed：工作流完整执行但保留分歧时可以是 completed，报告结论仍为 DEFER。

`report_ready` 表示报告已经提交且可读取。存在部分/全部角色失败的完整流程仍可生成诊断性研究报告；取消、未进入报告保存的超时或进程中断没有报告。正常保存时，报告、`report.generated` 与终态 `run.completed` 在同一仓储事务（默认 MongoDB）中提交；终态事件 payload 的 `status` 才是最终运行状态，可能为 completed、incomplete 或 failed。

主要阶段为 `INITIALIZING`、`ROUTING`、`AGENTS_RUNNING`、`CONFLICT_CHECK`、`DISCUSSION`、`SAFETY_CHECK`、`REPORTING`。快照包含 `completed_nodes`、`running_nodes`、`pending_nodes`，前端据此绘制真实节点进度。

每条审计的公共结构：

```json
{
  "event_id": "evt_000001",
  "run_id": "run_...",
  "seq": 1,
  "timestamp": "2026-11-07T00:00:00+00:00",
  "type": "run.created",
  "stage": "QUEUED",
  "agent_id": null,
  "payload": { "case_version": 1 }
}
```

以上为结构示意，时间和 ID 由实际运行生成。`seq` 与 `event_id` 只在单次运行内唯一，跨运行关联必须同时使用 `run_id`。

主要类型：`run.created`、`run.started`、`workflow.stage_changed`、`workflow.progress`、`routing.completed`、`tool.completed`、`agent.started`、`agent.completed`、`agent.failed`、`conflict.detected`、`discussion.started`、`discussion.completed`、`safety.completed`、`report.generated`、`run.completed`、`run.failed`、`run.cancel_requested`、`run.cancelled`。

事件保存结构化意见、引用、可审查摘要和状态，不包含模型隐藏推理过程。

### SSE 与恢复

`GET /api/v2/runs/{run_id}/events?after_seq=N` 重放 `seq > N` 的已提交事件，再持续等待新事件。若请求头含 `Last-Event-ID`，取它与 after_seq 的较大值作为起点；非法或负值返回 422。

```text
id: 1
data: {"event_id":"evt_000001","run_id":"run_...","seq":1,...}

```

服务不设置自定义 `event:` 名称，浏览器使用 `EventSource.onmessage`。连接和空闲心跳采用注释行（`: connected` / `: keep-alive`），不占 seq；约 10 秒无事件发送心跳。运行终态且事件已追平时关闭连接。

前端以 REST 初始化和补拉，只推进连续事件游标，乱序或缺口进入缓冲。快照按 `last_seq` 单调合并；活动运行约 900ms 轮询快照作为补充。SSE 断线退避重连，上限 5 秒间隔，约 30 秒仍未恢复则显示手动重连。界面保留最近 500 条审计，下载保留完整已提交日志。

## 来源检查与持久化边界

允许的浏览器来源为本机 8000/5173，`testserver` 供测试。跨来源 POST、PUT、DELETE 等写操作被拒绝；Host 也限制为本机。此机制不是身份认证，不能把当前服务直接当作公网多用户服务。

默认 MongoDB 连接与数据库通过 `MDT_MONGODB_URI`、`MDT_MONGODB_DATABASE` 配置；显式 SQLite 兼容模式路径为 `outputs/research.sqlite3`。重启恢复历史，未完成任务追加 `process_interrupted` 失败记录，不自动重启模型请求。服务的线程、取消标志和模型配置不跨进程共享。

## V0.2 / CLI 兼容接口

旧页面 `/legacy`、`/cases/{case_id}`、`/runs`、`/runs/{run_id}` 和报告路由仍使用 `/api/v1`。

| 接口 | 保留行为 |
| --- | --- |
| GET `/api/v1/health`、`/cases`、`/cases/{case_id}` | 旧合成病例 SYN-001 与三角色流程 |
| GET `/api/v1/llm/status` | 旧版仍返回 enabled=false |
| POST `/api/v1/runs` | `{case_id:"SYN-001",mode:"mock",options:{scenario:"standard",max_discussion_rounds:1}}` |
| GET `/api/v1/runs`、`/runs/{run_id}` | 旧运行列表与快照 |
| POST `/api/v1/runs/{run_id}/cancel`、`/rerun` | 取消与独立新 ID 重跑 |
| GET `/api/v1/runs/{run_id}/audit`、`/audit/download`、`/report`、`/report/download` | 原增量审计与文件报告 |
| WebSocket `/api/v1/runs/{run_id}/events?after_seq=N` | 原 schema_version="1" 事件封装、重放与心跳 |

旧版 Mock 场景为 `standard`、`aligned`、`partial_failure`、`persistent_disagreement`；不能与 V0.3 场景字段混用。旧版普通响应额外带 request_id 和 timestamp，输出仍保存到 `outputs/<run_id>/`。CLI 模式、退出码与输出结构保留，`--mode llm` 仍明确失败；V0.3 模型设置不会自动启用旧版 LLM。

## 契约源码与验证

- V0.3：`src/mdt_demo/research/schemas.py`、`api.py`、`provider.py` 与 `frontend/src/research/schemas.ts`。
- V0.2：`src/mdt_demo/api_schemas.py`、`schemas.py` 与 `frontend/src/schemas.ts`。
- Fixture：`scripts/export_research_contract.py` / `scripts/export_frontend_contract.py` 调用真实临时 API 导出，测试不连接付费模型。

变更契约后重新导出对应 fixture，并运行 Python 测试、前端测试及生产构建。实际验收结果见 [验收记录](验收记录.md)。


## 2026-11-12：外部数据导入与 Agent 群增量

- `GET /api/v2/datasets`：数据源目录、最大文件体积、最近50个已提交批次。
- `POST /api/v2/datasets/connect?source=synthea_csv&max_cases=10`：从内置官方地址下载并返回预检；不直接落库。
- `POST /api/v2/datasets/preview?source=...&max_cases=10`：以 `application/octet-stream` 原始请求体上传 ZIP/CSV/JSON，返回预检。
- `POST /api/v2/datasets/import/{preview_id}`：原子写入并返回批次，支持重复提交。
- `GET /api/v2/datasets/template`：下载研究 JSON 模板，须按来源和许可填写。

`source` 为 `synthea_csv`、`tcia_nsclc_csv` 或 `research_json`，JSON 只支持上传。预检含 `preview_id`、`expires_at`、`batch_id`、`artifact_sha256`、`mapping_version`、病例/事件/未定位资料计数、排除项及告警。预检15分钟过期或服务重启后失效。成功批次另含 `created_at`、`imported_case_ids`、`skipped_case_ids`、`already_imported`。

病例 `case_kind` 扩展为 `synthetic | public_research | mixed`，`provenance` 保留文件指纹、映射版本与引用；事件保留 `source_record_locator`、`source_fields`、`original_timestamp`。`unplaced_records` 保存无可验证时间的相关资料，冻结运行时清空，不能进入模型上下文。证据引用携带 `artifact_sha256`、`source_record_locator`、`source_field`，前端不丢弃这些字段。

Agent 群页复用真实 `/cases`、`/runs`、`/audit` 和 `/events`，展示特定运行的版本、截止事件、参与角色、意见、审计与报告链接，不生成前端伪状态。

常见错误：`DATASET_SIZE_LIMIT` (413)，格式/契约错误 (422)，`IMPORT_PREVIEW_EXPIRED` / `IMPORT_CASE_CONFLICT` (409)，官方下载失败或不允许的跳转 (502)。失败批次不会部分写入。

## 冻结盲标与配对评测

| 请求 | 响应与约束 |
| --- | --- |
| `GET /api/v2/annotations/tasks` | 当前各病例最新版本的任务队列，每项含场景、病例、版本、触发事件编号和是否已标。 |
| `GET /api/v2/annotations/material?case_id=…&version=1&trigger_event_id=…` | 返回 `scenario_id`、`events` 和 `input_sha256`。各事件只含编号、发生日期、类型、标题与事实。指纹取规范化 UTF-8 JSON 对象 `{scenario_id, events}` 的 SHA-256。 |
| `GET /api/v2/annotations/own?scenario_id=…&annotator_id=…` | 该编号已保存的单份参考。无匹配时返回 `data: null`。 |
| `PUT /api/v2/annotations/{scenario_id}` | 保存流程标签、必要专科、缺失字段、依据及 `evidence_ids`。可提交材料指纹，服务器为新记录写入校验后的指纹。引用范围为可见材料中的 `事件ID:事实键`。 |
| `DELETE /api/v2/annotations/{scenario_id}?annotator_id=…` | 按所给编号校验参考归属后删除。 |
| `GET /api/v2/annotations` | 本地评估者导出包含历史版本的全部参考。标注页只请求任务队列、当前材料和本人的记录。 |
| `POST /api/v2/experiments/evaluate` | 请求可含 `case_ids`、`case_versions`、`trigger_scope`（`all` 或 `latest`）。版本表与选集逐一对应，指定版本后可以复算历史截点。仅指定编号时读取所选病例最新版，两个字段均省略时读取全库。 |

材料截取沿用事件日期和同日事件编号的排序。材料投影去除全程摘要、未定位资料、已知系统结论字段及内置病例的作者提示。导入者自定义的标题和临床事实仍需在建立盲标队列时核查。标注人编号服务于本地单参考归属，系统保留评估者的全量导出接口。

评分与保存共用校验。材料指纹冲突返回 `409 ANNOTATION_INPUT_MISMATCH`，引用超出可见范围返回 `422 ANNOTATION_EVIDENCE_OUT_OF_SCOPE`，跨编号覆盖已有参考返回 `409 ANNOTATION_REVIEWER_CONFLICT`。无指纹的历史参考可继续评分，CLI 的统计摘要会单列有材料指纹的参考数。

评测协议 `mdt-library-eval-v2` 返回八组方法及五项配对对比，门控对比是 B3/B2，语义补齐对比是 B3/A2。各对比提供 `metric_numerator`、`metric_denominator`、可评截点及病例族数。零分母时 `point_estimate` 为 null，少于两个可评病例族时区间上下界为 null。`mcnemar_status` 取 `ok`、`no_annotations` 或 `repeated_family`，并附两组中仅一方正确的配对数。错误放行和过度暂缓另有逐方法分子与分母；带参考标注时另返回 `macro_f1`、`confusion_matrix`、`missing_field_f1` 及逐例误差归因 `error_analysis` / `error_analysis_csv`。

## 多人盲标仲裁与独立时间边界审计

| 请求 | 响应与约束 |
| --- | --- |
| `GET /api/v2/review-panel/tasks?annotator_id=…` | 返回各截点提交人数、`own_submitted` 与 `adjudicated` 状态，不暴露同行标注内容。 |
| `GET /api/v2/review-panel/own?scenario_id=…&annotator_id=…` | 仅返回当前标注人本人在该截点的独立初标；无记录返回 `data: null`。 |
| `PUT / DELETE /api/v2/review-panel/submissions/{scenario_id}` | 按 `annotator_id` 独立保存或撤回初标；复用材料指纹与可见证据范围校验。 |
| `GET /api/v2/review-panel/agreement` | 计算多标注人三分类原始一致率、Cohen's κ、3×3 混淆矩阵、必要专科平均 Jaccard 与逐专科 κ，并列出争议截点队列。 |
| `GET / PUT / DELETE /api/v2/review-panel/adjudications/{scenario_id}` | 管理争议截点的共识仲裁定稿；评测接口支持按「仲裁共识 > 多人一致 > 单人标注」自动合并金标准（可通过 `reference_source=single_only` 切换）。 |
| `GET /api/v2/review-panel/export/annotations.jsonl` | 导出计划书 §6.4 格式的独立初标 JSONL。 |
| `GET /api/v2/review-panel/export/adjudication.jsonl` | 导出计划书 §6.4 格式的仲裁共识 JSONL（CLI `--annotations` 可直接读取）。 |
| `GET /api/v2/runs/{run_id}/temporal-audit` | 绕过运行引擎直接从原病例版本重建截点白名单，核查快照时间线、`unplaced_records`、证据注册表、意见引用、同日事件及研究问题未来日期。 |
