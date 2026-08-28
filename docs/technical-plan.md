# Reachout 求职助手技术方案

状态：Draft v1
日期：2026-08-19
目标用户：个人求职者，优先本地自用，架构预留桌面应用分发能力

> 2026-08-28 架构更新：本文保留为 local-first 初始实现方案。多来源整合、Campaign
> 分流以及 BOSS 固定招呼语的最新决策，以 `goal-一条龙系统蓝图.md` v2 为准；其中
> 「每个 BOSS 岗位生成草稿」已不再是目标流程。

## 1. 结论

项目采用 **local-first 桌面应用**：基于 `BossZhiPin_Job_Search` 的 MIT 代码继续开发，保留其 nodriver 浏览器自动化、简历 RAG、LLM 匹配与 Tauri 桌面界面；将现有“发现岗位后立即生成并发送”的单体循环拆成三个独立阶段：

1. 捕捉岗位并持久化；
2. 评分、生成草稿并等待人工审核；
3. 只发送已批准草稿，并可靠记录结果。

MVP 默认不自动发送，不建设云端、多用户后台或账号体系。

## 2. 产品目标与非目标

### 2.1 MVP 目标

- 从当前用户正常可见的 BOSS 推荐岗位中增量捕捉岗位。
- 保存结构化岗位信息，重复运行不重复处理同一岗位。
- 根据用户简历、关键词和排除规则进行两层匹配。
- 为通过筛选的岗位生成个性化招呼语草稿。
- 用户可以批准、修改或跳过每条草稿。
- 只向已批准的岗位发送消息，并限制每日发送数量。
- 本地记录岗位、评分、草稿、发送结果和错误。
- 发送状态不确定时禁止自动重试，避免重复联系。

### 2.2 暂不包含

- 云端账号、团队协作和多租户权限。
- 服务端托管 BOSS Cookie 或代用户长期登录。
- 绕过验证码、设备指纹伪造或反检测增强。
- 并发抓取、高频发送和无人值守群发。
- 支付、订阅、远程配置和集中式运营后台。
- 自动回复招聘者；回复跟进只作为后续可选能力。

## 3. 上游基线

主骨架：`upstream/BossZhiPin_Job_Search`

- Python 3.11+。
- nodriver + 独立 Chrome Profile 保存登录态。
- OpenAI-compatible LLM 接口。
- PDF 简历解析、Chroma 和 sentence-transformers RAG。
- 关键词粗筛 + LLM 精筛。
- LLM 招呼语生成与 `validate_letter` 发送前校验。
- PyTauri + React + Zustand 桌面界面。
- JSONL 招呼语审计与 LLM telemetry。

需要改变的现状：

- `write_response.send_job_descriptions_to_chat` 将捕捉、评分、生成和发送耦合在一个循环中。
- `finding_jobs.get_job_description_by_index` 只返回 JD 文本，缺少岗位稳定标识和结构化字段。
- JSONL 适合审计，不适合查询、去重、审核队列和状态迁移。
- `dry_run` 是整轮开关，不等同于逐条人工审批。
- 发送成功与页面返回失败已有区分，但尚未形成数据库级幂等保护。

## 4. 总体架构

```text
┌──────────────────────────────────────────────────────────┐
│                    Tauri / React UI                      │
│  发现岗位  |  待审核  |  已联系  |  历史  |  设置        │
└───────────────────────────┬──────────────────────────────┘
                            │ typed IPC
┌───────────────────────────▼──────────────────────────────┐
│                    Application Services                  │
│ CaptureService | EvaluationService | DraftService        │
│ ReviewService  | OutreachService   | HistoryService      │
└───────────────┬───────────────────────┬──────────────────┘
                │                       │
┌───────────────▼──────────────┐  ┌─────▼──────────────────┐
│      Domain + Persistence    │  │     Platform Adapter   │
│ SQLAlchemy / SQLite          │  │ BossBrowserAdapter     │
│ repositories + migrations   │  │ nodriver / Chrome      │
│ state transitions           │  │ capture / send         │
└───────────────┬──────────────┘  └────────────────────────┘
                │
┌───────────────▼─────────────────────────────────────────┐
│ LLM + Resume                                            │
│ keyword filter | match score | RAG | letter generation │
│ validate_letter | telemetry                            │
└─────────────────────────────────────────────────────────┘
```

### 4.1 设计原则

- UI 不直接操作浏览器或数据库，只调用应用服务。
- 浏览器适配层只负责读取页面和执行明确动作，不决定业务状态。
- 每个发送动作必须经过 `OutreachService`。
- 每个状态变化在数据库事务中完成，并写审计事件。
- LLM 输出永远不能直接发送，必须经过校验和用户批准。
- 浏览器错误显式暴露；不把“点击成功”直接等同于“消息已发送”。

## 5. 目标代码结构

在主骨架 `src/boss_zhipin/` 中演进：

```text
src/boss_zhipin/
├── application/
│   ├── capture_service.py
│   ├── evaluation_service.py
│   ├── draft_service.py
│   ├── review_service.py
│   ├── outreach_service.py
│   └── history_service.py
├── domain/
│   ├── models.py
│   ├── enums.py
│   ├── transitions.py
│   └── job_identity.py
├── persistence/
│   ├── database.py
│   ├── repositories.py
│   ├── schema.py
│   └── migrations/
├── platform/
│   └── boss/
│       ├── adapter.py
│       ├── selectors.py
│       └── types.py
├── models/                 # 保留现有 LLM、prompt、matcher
├── audit/                  # 保留现有校验和 telemetry
├── website_oper/           # 逐步收敛为 platform adapter 的底层实现
├── gui/
└── tauri/
```

首期允许在现有模块旁边渐进添加，不做一次性目录大迁移。

## 6. 数据模型

使用 SQLite + SQLAlchemy 2.x。数据库位于应用数据目录，例如：

```text
<app_data>/reachout.db
```

数据库启用外键、WAL 和 schema migration。时间统一存 UTC ISO 时间或 UTC timestamp，UI 再转换为本地时区。

### 6.1 `profiles`

求职配置。MVP 只使用一个 active profile，但数据模型支持未来多个求职方向。

| 字段 | 说明 |
|---|---|
| `id` | UUID |
| `name` | 配置名称，如“AI 产品经理” |
| `display_name` | 招呼语署名 |
| `resume_path` | 本地简历路径 |
| `search_label` | BOSS 推荐标签 |
| `min_match_score` | 最低匹配分 |
| `min_keyword_match` | 关键词粗筛门槛 |
| `exclude_keywords_json` | 排除规则 |
| `is_active` | 是否启用 |
| `created_at/updated_at` | 时间戳 |

### 6.2 `jobs`

| 字段 | 说明 |
|---|---|
| `id` | 本地 UUID |
| `platform` | 固定 `boss_zhipin`，预留未来平台 |
| `external_id` | 页面可获得的岗位 ID，可为空 |
| `canonical_key` | 去重键，唯一索引 |
| `title/company/location/salary` | 结构化展示字段 |
| `description` | 清洗后的 JD |
| `source_url` | 正常可见的岗位链接，可为空 |
| `raw_payload_json` | 必要的原始结构化信息，不存整页 HTML |
| `first_seen_at/last_seen_at` | 首次与最近捕捉时间 |
| `availability` | `available/contacted/closed/unknown` |

岗位去重优先级：

1. 使用页面正常暴露的稳定岗位 ID；
2. 使用规范化后的岗位 URL 标识；
3. 最后使用 `company + title + location + normalized JD hash`。

`canonical_key` 算法必须带版本，例如 `v1:boss:<hash>`，未来调整算法时可迁移。

### 6.3 `evaluations`

| 字段 | 说明 |
|---|---|
| `id/job_id/profile_id` | 关联字段 |
| `keyword_matches_json` | 命中关键词 |
| `keyword_passed` | 粗筛结果 |
| `score/reason` | LLM 分数与理由 |
| `degraded` | LLM 评分是否降级 |
| `model/prompt_version` | 可复现信息 |
| `created_at` | 生成时间 |

同一岗位可有多次 evaluation；UI 默认展示最新一次。

### 6.4 `drafts`

| 字段 | 说明 |
|---|---|
| `id/job_id/profile_id` | 关联字段 |
| `content` | 当前招呼语 |
| `original_content` | LLM 原始输出 |
| `validation_ok/reasons_json` | 安全校验结果 |
| `review_state` | `pending/approved/rejected` |
| `revision` | 编辑版本号 |
| `approved_at` | 批准时间 |
| `created_at/updated_at` | 时间戳 |

编辑已批准草稿会自动回到 `pending`，要求重新批准。

### 6.5 `outreach_attempts`

| 字段 | 说明 |
|---|---|
| `id/job_id/draft_id` | 关联字段 |
| `idempotency_key` | 唯一键，防止重复执行 |
| `state` | `started/sent/failed/unknown` |
| `error_code/error_detail` | 失败信息 |
| `started_at/finished_at` | 时间戳 |

规则：同一 profile + job 只能存在一个 `sent` 或 `unknown` 的有效联系记录。`unknown` 必须人工确认后才能重试。

### 6.6 `audit_events`

保存关键状态变化：捕捉、评分、草稿生成、编辑、批准、拒绝、开始发送、发送成功或失败。JSONL telemetry 保留用于模型成本分析，但业务真相源改为 SQLite。

## 7. 状态与幂等

不要用一个巨大的 `job_status` 表达所有维度。分别维护：

- evaluation：`not_evaluated/evaluated/skipped/degraded`
- review：`no_draft/pending/approved/rejected`
- outreach：`not_started/started/sent/failed/unknown`

允许的核心流程：

```text
captured
  → evaluated
  → draft pending
  → approved
  → outreach started
  → sent
```

异常流程：

```text
outreach started
  ├─ 明确未发送 → failed → 用户可再次批准重试
  ├─ 明确已发送 → sent
  └─ 无法判断     → unknown → 禁止自动重试
```

发送事务采用 intent-first：

1. 事务内校验 draft 已批准、岗位未联系、未超每日限额；
2. 插入唯一 `outreach_attempt(state=started)`；
3. 提交事务；
4. 执行浏览器发送；
5. 根据可验证结果更新为 `sent/failed/unknown`。

应用崩溃后残留的 `started` 在下次启动时转换为 `unknown`，而不是自动重发。

## 8. 三条核心工作流

### 8.1 Capture-only

```text
启动 Chrome → 用户登录检查 → 选择推荐标签 → 遍历可见岗位
→ 提取结构化 JobSnapshot → 计算 canonical_key → upsert jobs
→ 继续滚动 → 达到捕捉上限或 feed 结束 → 输出摘要
```

要求：

- 不点击“立即沟通”。
- 默认每轮最多捕捉 30 个岗位，可由用户调整。
- 已存在岗位只更新 `last_seen_at` 和可变展示信息。
- 页面字段缺失时保留岗位，但标记 `raw_quality`，不静默拼接错误字段。

### 8.2 Evaluate and draft

```text
读取未评估岗位 → 排除词过滤 → 关键词粗筛 → LLM 评分
→ 低分标记 skipped → 高分生成招呼语 → validate_letter
→ 写 evaluations + drafts(pending)
```

要求：

- LLM 评分失败时默认 `degraded`，不得自动进入发送。
- prompt 带版本号，便于后续比较效果。
- 已存在 pending/approved/sent 草稿时不自动覆盖。
- 可单条或批量生成草稿，但批量生成不等于批量批准。

### 8.3 Approve and send

```text
用户查看岗位 + 匹配理由 + 草稿 → 编辑/批准
→ 单条点击发送 → 再次确认页面岗位身份和按钮状态
→ intent-first 记录 → 发送 → 更新结果 → 返回审核队列
```

MVP 只支持单条发送。批量发送延后到实际使用验证稳定后，且仍只处理已批准草稿。

## 9. 浏览器适配层改造

新增结构化类型：

```python
@dataclass(frozen=True)
class JobSnapshot:
    external_id: str | None
    title: str
    company: str
    location: str
    salary: str
    description: str
    source_url: str | None
    raw_payload: dict[str, object]
```

将现有 `get_job_description_by_index` 扩展为或旁路新增：

```python
async def get_job_snapshot_by_index(index: int) -> JobSnapshot | None
```

新增发送接口：

```python
async def send_approved_message(
    expected_job: JobIdentity,
    message: str,
) -> SendResult
```

`SendResult` 必须区分：

- `sent`：有足够证据确认消息已发送；
- `failed`：明确未发送；
- `unknown`：点击或输入后页面状态异常，无法确认。

发送前重新读取当前岗位标题和公司，与数据库预期身份核对。不一致则失败，不发送。

## 10. 桌面端方案

沿用现有 React + Zustand + typed IPC。

### 10.1 页面

1. **发现**：选择求职配置、捕捉数量，开始/停止捕捉，展示新增和重复数量。
2. **待审核**：岗位卡片、匹配分、理由、JD、草稿编辑器；批准、跳过、发送。
3. **已联系**：发送时间、公司、岗位、实际消息和结果。
4. **历史**：失败、unknown、被过滤岗位和审计事件。
5. **设置**：简历、LLM、筛选条件、每日上限和 Chrome Profile。

### 10.2 新增 IPC

```text
capture_jobs(config)              -> task started
stop_capture()                    -> stopped/idle
list_jobs(filter, cursor, limit)  -> paged jobs
evaluate_job(job_id)              -> evaluation
generate_draft(job_id)            -> draft
update_draft(draft_id, content)   -> pending draft
review_draft(draft_id, decision)  -> approved/rejected
send_draft(draft_id)              -> sent/failed/unknown
get_dashboard_summary()           -> counts
resolve_unknown(attempt_id, state)-> sent/failed
```

所有列表必须分页，避免未来数据积累后一次把完整 JD 推到 WebView。

## 11. 配置与本地安全

- Chrome Profile、简历、SQLite、向量库和日志只存本机应用数据目录。
- `.env`、数据库、简历、Cookie 和日志继续保持在 `.gitignore`。
- UI 永远不回传 LLM API Key 明文。
- 业务日志不打印 Cookie、Authorization、完整 API Key。
- 个人 MVP 可延用 `.env`；可分发版本增加 `SecretStore` 接口，并接入系统 Keychain/Credential Manager。
- 提供数据导出与“清除本地数据”，但删除前明确展示范围并二次确认。

## 12. 限额策略

MVP 默认值：

- 每轮捕捉：30 个岗位；
- 每日发送：5 条；
- 单次操作：只发送 1 条；
- 发送时间窗口：默认 09:00–21:00，本地时区；
- `unknown`：0 次自动重试；
- 同一岗位：永不自动二次联系。

限额由 `OutreachPolicy` 在数据库事务内检查，不依赖 UI 禁用按钮。

## 13. 测试策略

### 13.1 自动测试

- `job_identity`：不同字段组合、规范化和 hash 版本。
- repository：upsert、唯一索引、分页和迁移。
- 状态迁移：所有允许与禁止的迁移。
- 幂等：重复点击发送只能创建一次 attempt。
- 限额：跨日、时区边界、unknown 和 sent 计数。
- draft：编辑后撤销批准、校验失败不可批准。
- application services：使用显式 fake adapter 测业务编排，不伪装真实浏览器 E2E。
- IPC contract：Pydantic camelCase 与 TypeScript 类型一致。

### 13.2 手工验证

按上游约束，浏览器改动必须通过真实页面 DRY_RUN：

1. 使用专用 Chrome Profile 手动扫码；
2. capture-only 捕捉 5 个岗位，确认没有触发沟通；
3. 第二次捕捉确认无重复；
4. 生成草稿但不发送；
5. 用测试岗位单条批准并发送；
6. 模拟返回列表失败，确认记录 sent 或 unknown 且不重复发送。

## 14. 分阶段交付

### Phase 0：建立工作副本与基线

- 从上游主骨架创建个人版仓库/分支。
- 保留 MIT notice 和上游 remote。
- 安装依赖，跑完整 pytest。
- 使用 DRY_RUN 完成一次真实页面基线验证。

验收：未改业务前，测试通过且可走到生成草稿。

### Phase 1：数据层与 Capture-only

- SQLAlchemy + migration。
- profiles/jobs/audit_events。
- `JobSnapshot` 和岗位唯一标识。
- CaptureService、数据库 upsert、发现页摘要。

验收：连续运行两次，第二次新增为 0 或只包含真正新岗位；全程不发消息。

### Phase 2：评分与审核队列

- evaluations/drafts。
- EvaluationService、DraftService、ReviewService。
- 待审核页面和草稿编辑。
- 现有 JSONL 历史只读兼容或一次性导入。

验收：岗位可被评分、生成草稿、编辑、批准或拒绝；没有发送入口绕过批准。

### Phase 3：可靠单条发送

- outreach_attempts 和 intent-first 幂等。
- 每日上限、时间窗口、岗位身份复核。
- 单条发送与 sent/failed/unknown 结果。
- 已联系和异常处理页面。

验收：重复点击不会重复发送；崩溃恢复不会自动重试 started/unknown。

### Phase 4：个人稳定版

- 数据导出、诊断报告、备份和迁移验证。
- macOS/Windows 安装包。
- 新用户配置引导与更新机制。
- 可选本地 MCP，只开放查询、草稿和显式批准后的发送工具。

验收：新机器可按引导完成安装、登录、捕捉、审核和发送。

## 15. 未来扩展边界

给更多人使用时优先保持“每个用户本地运行”：

- 增加多个本地 profile；
- 系统密钥存储；
- 自动更新与诊断；
- 配置/数据备份；
- 可选匿名 crash report，默认关闭。

只有明确需要跨设备同步时才新增云服务。云服务默认只同步非敏感配置和用户主动选择的数据，不上传 BOSS Cookie。若未来需要服务端代用户运行浏览器，应作为新产品重新进行平台条款、隐私、安全和架构评估，不从个人版直接开启远程 Cookie 托管。

## 16. 首个开发切片

第一个可合并切片控制在数据层，不碰真实发送：

1. 创建工作副本并跑基线测试；
2. 添加 SQLAlchemy、数据库初始化和 migration v1；
3. 实现 `Profile`、`Job`、`AuditEvent`；
4. 实现 `JobSnapshot` 和 `canonical_key v1`；
5. 为以上模块补齐单元测试；
6. 暂不接 UI，先通过 service/CLI 写入 3 条 fixture 验证去重。

完成后再接真实页面 capture-only，降低第一次改动同时触碰数据库、浏览器和 UI 的风险。
