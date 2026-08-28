# Goal：海内外求职一条龙系统蓝图

状态：v2（2026-08-28，Campaign 架构已确认并开始落地）
目标：**可用、不累赘**的「岗位抓取 → 简历制作 → 打招呼 → 投递 → 动态监控」闭环，海内外双线。

---

## 1. 先回答：这是系统项目还是 agent 项目

**现状是系统项目**：reachout 是一条确定性流水线，LLM 只在两处被当函数调用（打分、生成文案），没有循环决策、没有工具选择、没有记忆演化。诚实地说，把它叫 agent 是名不符实的。

**但它有一条清晰的 agent 化路径**，而且第一块拼图（测评集）今天已经落地：

| Agent 项目的要件 | 现状 | 差距 |
|---|---|---|
| 工具集（tools） | 已有：capture / score / draft / query DB，都是干净的函数 | 缺统一的 tool 接口封装 |
| 决策循环 | 无——每步固定顺序 | 核心待建：一个「求职操盘 agent」按当日情况决定先干什么（今天抓哪条路由？needs_review 积压了先清哪些？谁值得定制简历？） |
| 记忆 | archive.md（静态）+ SQLite（事务） | 缺：投递反馈回流（哪类岗位回复率高→调整打分权重） |
| 人机协作边界 | ✅ 已经很好：发送/提交全部人工门禁 | 保持 |
| **测评** | ✅ 今天建了三层测评集（evals/），L1 已跑通并抓出 2 个真实 bug | L2/L3 待配 API key 激活 |

**建议叙事**：不要把「流水线」硬包装成 agent——面试官一问决策循环就穿帮。正确说法是「human-in-the-loop 求职 agent：确定性工具层 + LLM 决策层 + 测评驱动迭代」，其中测评先行恰恰是最专业的 agent 工程姿态（先有可回归的测评，再敢让 LLM 接管决策）。你的 prd-stress-test、LLM 评测经历和这套 evals 可以串成同一条方法论主线。

---

## 2. 外部对标（学什么、不学什么）

| 项目/产品 | 形态 | 学 | 不学 |
|---|---|---|---|
| [AutoApply](https://github.com/Liam-Frost/AutoApply)（117★，PolyForm 非商用） | 最接近我们的 local-first 全链路：discovery→fit scoring→materials→human-gated submit→tracking | ①「story bank + bullet pool」= 我们 archive.md 思路的工程化验证；②evidence-grounded 生成（每句可溯源到 profile 事实）；③dead-letter 队列处理卡死任务；④文档结构（DECISIONS.md/PHASE_HISTORY.md） | Postgres+Redis+Celery+Vue 的重栈——个人自用是累赘，我们 SQLite+Tauri 够了 |
| [AIHawk](https://github.com/feder-cr/jobs_applier_ai_agent_aihawk)（数万★） | LinkedIn Easy Apply 全自动海投 | 反面教材的价值：早期版本会往简历里塞假资历；海投触发平台风控与雇主反感 | 全自动投递。你 brief 里「投递不做全自动」的决策被它的争议完整验证，别推翻 |
| [ApplyPilot](https://github.com/ibarrajo/ApplyPilot) | 7 阶段自主管线，6+ job boards | 多源发现的阶段划分 | 自动提交 |
| Huntr / Teal / Simplify | 商业投递追踪器 | ①Huntr 的 kanban 状态机（Wishlist→Applied→Interview→Offer→Rejected）+ 联系人 CRM 层；②Teal 的「追踪器和简历定制长在同一张记录上」；③Simplify 的浏览器扩展自动填表（到提交前一步） | 不自建 web SaaS |
| 简历定制有效性 | 行业数据：定制简历回调率显著高于通用简历（各来源口径 40%~200% 提升） | 证明「按 JD 定制」这条主线值得做重 | 对具体数字存疑（多为厂商口径），用自己的 applications 表算真实回调率 |

---

## 3. 目标架构：统一生命周期，不强行统一召回

国内 BOSS 校招和海外 New Grad 的召回条件、打分口径、后续动作都不同。两条线不应
共用一份 targeting 配置，也不应把分数直接混排。系统统一的是岗位被发现之后的
生命周期，而不是搜索范围。

```
  国内 Campaign ──▶ BOSS 发现器 ──┐
                                   ├─▶ jobs（客观岗位，跨来源去重）
  海外 Campaign ──▶ LinkedIn/官网 ─┘             │
                                                 ▼
                              job_campaign_matches（为什么召回它）
                                      │ 各 Campaign 内过滤/打分
                                      ▼
                                   人工选择
                                  ╱        ╲
        BOSS：打开岗位，本人在平台沟通          海外：定制简历 + outreach
        （使用 BOSS 固定招呼语）                （本人手动提交/发送）
                                  ╲        ╱
                                      ▼
                              applications（统一跟踪）
```

四个核心概念：

- `profile`：候选人是谁，保存经历事实与通用材料；
- `search_campaign`：正在找什么，如「国内 2027 AI 产品校招」；
- `job`：岗位本身的客观信息；
- `job_campaign_match`：岗位在哪条 Campaign 被发现、按哪套规则判断、在该方向内排第几。

**合并决策**：
- 简历自动化 brief 里的 `jds` 表不建，复用 `jobs`；`resume_versions`/`applications` 直接建在 reachout.db 里（改变上轮"分库"倾向——单人单机，分库的写隔离收益 < 跨库 join 的麻烦，audit_events 已经提供了完整变更审计）。
- 简历渲染链复用 design-extractor 的 Playwright 能力：HTML 模板 → PDF。
- 召回范围属于 `search_campaign`，不再继续塞进唯一的 active profile；迁移期保留
  `profile_preferences`，等 Campaign 审核台接通后再移除重复配置。
- 排名只在同一个 Campaign 内比较。顶层操盘层按时间预算、队列积压和真实回复效果
  在 Campaign 之间分配精力，不比较含义不同的裸分数。
- BOSS 固定招呼语以平台设置为实际来源。本地可保存备忘/版本，但不再为每个 BOSS
  岗位生成一条个性化 draft，也不通过系统点击「立即沟通」。

## 4. Campaign 与投递监控数据模型

新增搜索方向与岗位关联：

```sql
CREATE TABLE search_campaigns (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES profiles(id),
  campaign_key TEXT NOT NULL,
  name TEXT NOT NULL,
  source_platforms_json TEXT NOT NULL,
  targeting_config_json TEXT NOT NULL,
  action_strategy TEXT NOT NULL, -- boss_fixed_greeting / tailored_application
  is_active INTEGER NOT NULL,
  UNIQUE(profile_id, campaign_key)
);

CREATE TABLE job_campaign_matches (
  campaign_id TEXT NOT NULL REFERENCES search_campaigns(id),
  job_id TEXT NOT NULL REFERENCES jobs(id),
  source_route TEXT NOT NULL,
  rule_state TEXT NOT NULL,
  rule_reasons_json TEXT NOT NULL,
  score INTEGER,
  score_reason TEXT NOT NULL,
  evaluation_policy_version TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY(campaign_id, job_id)
);
```

`jobs` 不带唯一求职方向：同一个岗位可以被多个 Campaign 召回，但只保存一次。
`job_campaign_matches` 保存不同方向下的判断结果，避免拿国内校招的 80 分和海外
New Grad 的 80 分直接比较。

新增两张表（在现有 7 张表基础上）：

```sql
CREATE TABLE resume_versions (
  id TEXT PRIMARY KEY,
  job_id TEXT REFERENCES jobs(id),          -- NULL = 通用母版
  archive_entry_ids TEXT,                    -- JSON: 用了 archive.md 哪几条经历（A1,B2...）
  lang TEXT CHECK (lang IN ('zh','en')),
  html_path TEXT, pdf_path TEXT,
  created_at TEXT
);

CREATE TABLE applications (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  campaign_id TEXT REFERENCES search_campaigns(id),
  resume_version_id TEXT REFERENCES resume_versions(id),
  draft_id TEXT REFERENCES drafts(id),       -- BOSS 线用
  channel TEXT,                              -- boss_chat / linkedin_easy / company_site / referral
  status TEXT NOT NULL DEFAULT 'preparing',
  -- 状态机: preparing → ready → submitted → screening → interview_1..n → offer / rejected / ghosted / withdrawn
  status_history TEXT,                       -- JSON [{status, at, note}]
  submitted_at TEXT, first_response_at TEXT, -- 回调率与响应时长的原始数据
  next_action TEXT, next_action_due TEXT,    -- 跟进提醒
  notes TEXT, created_at TEXT, updated_at TEXT
);
```

要点：`status_history` 留全轨迹（回调率、各阶段转化率、响应时长都从这算，这就是 E2E 测评的北极星指标来源）；`ghosted` 是独立状态（投后 14 天无响应自动标记，别让它们混在 submitted 里看不见）。

## 5. 飞书多维表格的定位：只做看板，不做主库

| | 结论 |
|---|---|
| 主数据库 | **SQLite（reachout.db）**。pipeline 高频读写、join、迁移都在本地；多维表格 API 走网络+token，做主库会让每步 capture 都依赖外网 |
| 飞书多维表格 | **只读镜像看板**：手机上看进度、kanban 拖视图、到期跟进提醒。单向同步（SQLite→bitable，`batch_create/update`，500 条/次够用），**永不反向写** |
| 迭代方式 | 现有表格不用改结构，新建一个由脚本维护的 base；旧表格手工数据一次性导入 applications 后退役 |
| 何时可以砍 | Tauri 审核台若加一个 applications kanban 页，飞书层可整体移除——同步脚本单独一个文件，保持可弃 |

## 6. 测评体系（已落地，见 evals/）

- L0 Campaign 契约：4/4。固定平台 → Campaign → action strategy，以及是否需要生成材料；未知来源必须显式失败。
- L1 过滤 golden：20/20；真实 DB 回归同时记录 `by_platform` 与 `by_campaign`，快照只比较、不自动覆盖。
- L2 打分：国内 7/7、海外 4/4。harness 直接 import app 的生产 prompt builder/parser，`cn-match-v2` 与 `global-match-v1` 分开版本化，避免「eval 测一份、线上跑另一份」。
- L3 生成物 rubric：一票否决制（编造事实/语言不匹配/隐私）+ 五维打分；优先用于海外定制简历和 outreach。BOSS 固定招呼语不再要求逐 JD 个性化，因此不拿「岗位针对性」考核每一条 BOSS 沟通。
- E2E：applications 表落地后自动产出回调率/转化率，成为唯一不可作弊的指标。
- **纪律：改 filter/prompt 前先跑 `python3 evals/run_evals.py --regression`，改后分布变化必须能解释。**
- 同步协议：改来源/Campaign → L0；改规则 → L1 + regression；改 prompt/parser → 对应 Campaign L2；改生成链 → 先补 L3。

## 7. 路线图（每期独立可验收）

| 期 | 内容 | 验收 |
|---|---|---|
| P0 | 跑 commit_pending_work.sh 保护现有工作；修 B10（location 回退正文）+ L10（经验正则语境）两个 bug | L1 20/20 绿；回归分布中「不在目标城市」大幅下降 |
| P1 | .env 配上 LLM key；archive.md 填完 `[待填]`（人工）；archive.md 替代 PDF 接入打分 | L2 band 命中 ≥6/7 |
| P2 | applications + resume_versions 建表迁移；审核台"批准"动作落 applications 记录 | 状态机流转有 audit 记录 |
| P3 | Campaign 化：新增 search_campaigns / job_campaign_matches；两条 daily 链路写入各自 Campaign；审核台分 Campaign 展示 | 两套召回与判断不再依赖同一个 active profile，旧数据仍可读 |
| P4 | BOSS 线：审核动作改为「值得沟通/跳过/打开岗位」；使用平台固定招呼语，不生成逐岗位草稿 | 全流程无自动发送；入选岗位可进入 application 跟踪 |
| P5 | 海外线：JD→选 archive 条目→HTML→PDF（复用 design-extractor）+ 英文 outreach | 3 份真实定制简历人工验收 |
| P6 | 飞书看板单向同步 + ghosted 自动标记 + 跟进提醒 | 手机可看全 pipeline |
| P7 | Campaign-aware agent：按各方向状态决定今日动作与时间分配；测评反馈回流 | agent 决策日志可回放，E2E 指标不劣于人工排程 |

## 8. 红线（不因任何迭代妥协）

1. 发送/提交永远人工门禁（AIHawk 的教训 + 平台 ToS + brief 既有决策）。
2. 不编造：生成物每句可溯源到 archive.md 条目 ID（学 AutoApply 的 evidence-grounding）。
3. 每日触达限额（现 12/天）保留；发送状态不确定禁止自动重试。
4. 不做多用户/云端/商业化——「不累赘」的第一含义。
