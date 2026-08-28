# 接手清单 · Job Search Agent / Reachout v2

状态日期：2026-08-28

## 1. 这是什么

一个个人、local-first、human-in-the-loop 的求职系统：

> 多来源发现岗位 → 在各自 Search Campaign 内过滤与打分 → 人工选择 →
> 准备对应渠道的下一步 → 本人手动沟通/投递 → 统一跟踪反馈。

失败代价不对称：抓错一个岗位只是多审核一次，发错消息或误提交不可撤回。因此
发送、投递和不确定状态重试永远不进入 Agent 工具箱。

## 2. 起手验证

```bash
cd app && uv run pytest -q                 # 期望 315 passed
cd ../evals && python3 run_evals.py         # 期望 L0 4/4 + L1 20/20 = 24/24
```

真实 DB 回归默认寻找 `app/data/reachout.db`。新 clone 没有私人数据库时，用显式路径：

```bash
cd evals
REACHOUT_DB_PATH=/path/to/reachout.db python3 run_evals.py --regression
```

L2 会调用付费模型端点：

```bash
cd evals
set -a && . ../app/.env && set +a
../app/.venv/bin/python run_evals.py --l2

# 端点偶发 503 时只重跑失败项
../app/.venv/bin/python run_evals.py --l2 --case G02
```

## 3. 红线

1. 不新增自动发送、自动提交或不确定外部动作的自动重试。
2. 不写提速、并发触达、绕反爬、验证码规避。
3. 不把 AI 工具写进新 commit 的 `Co-Authored-By`；使用 Pacifica 的署名。
4. 不改 golden 标签只为变绿；期望行为真的变化时必须在 case note 解释。
5. 不碰或提交 `.env`、真实 DB、浏览器 profile、vectorstores、logs、私人简历/事实库。
6. migration 必须先在真实 DB 副本验证；只读命令不能顺手迁移。

## 4. 当前验证基线

| 项目 | 状态 |
|---|---|
| App 单测 | 315 passed |
| L0 Campaign 契约 | 4/4 |
| L1 过滤 | BOSS 10/10 + LinkedIn 10/10 |
| L2 国内 | 7/7，`cn-match-v2` |
| L2 海外 | 4/4，`global-match-v1` |
| L3 | 海外 outreach rubric 已更新，harness 未接 |
| E2E | applications 状态机已建，尚无足够投递反馈数据 |

生产 prompt/parser 的唯一事实源是
`app/src/boss_zhipin/models/match_scoring.py`。eval harness 直接 import，不保留副本。

## 5. Campaign 模型

| Campaign | 来源 | action strategy |
|---|---|---|
| `cn-2027-ai-product` | BOSS | `boss_fixed_greeting`：系统筛选，本人在 BOSS 使用平台固定招呼语沟通 |
| `global-2027-ai-product` | LinkedIn；未来公司官网 | `tailored_application`：准备定制简历/outreach，本人提交 |

核心表：

- `jobs`：岗位客观事实，跨来源去重；
- `search_campaigns`：搜索意图、来源和后续动作；
- `job_campaign_matches`：岗位为什么进入某 Campaign、规则状态、分数与 policy version；
- `applications`：跨渠道统一状态跟踪；
- `resume_versions`：定制材料与事实引用。

migration 5 新增 Campaign 两张表。原工作数据库仍停在 migration 4；代码已经在其副本上
验证 migration 5，100 条 jobs 迁移前后完整保留。不要因为看到 pending 就擅自迁移真库。

## 6. 仓库结构

```text
job-search-agent/
├── app/                    # 工作应用；从原 app 仓以非 squash subtree 导入
├── evals/                  # 测评体系；从原 evals 仓以非 squash subtree 导入
├── docs/                   # v2 蓝图、Agent 路线和原技术方案
├── skills/                 # career archive / resume tailor / apply 编排规格
├── integrations/          # 尚未接入主 app 的来源适配器候选
├── legacy/v1-prompts/      # 原 prompt-only 发现/富化方案，只作历史参考
├── AGENTS.md
└── HANDOFF.md
```

旧 `job-search-agent` 的一笔 v1 历史、app 的完整上游与本地历史、evals 的完整历史都在
本仓保留。不要再把 app/evals 拆回嵌套 Git 仓。

## 7. 下一步（按顺序）

### P3.2 · Campaign-aware 审核台

1. 设计旧岗位 backfill：在 DB 副本上按 platform 归入默认 Campaign，未知来源进
   `unassigned`，不得静默丢弃。
2. `ReviewService.list_jobs` 增加 `campaign_id`，读取 `job_campaign_matches` 的规则状态。
3. UI 国内/海外分栏，各 Campaign 内打分排序，不跨 Campaign 比裸分。
4. BOSS 动作改为「值得沟通 / 跳过 / 打开岗位」，不生成逐岗位招呼语。
5. 修改前先补对应 L0/L1/服务层测试，修改后跑 regression。

### P4 · 海外材料链

把 `skills/career-archive.md`、`resume-tailor.md` 的事实溯源原则接入数据模型：
JD → 选择事实卡 → HTML/PDF 简历 + 英文 outreach。先接 L3 harness，再批量生成。

### P5 · Campaign-aware planner

现有 `DailyState` 仍把平台聚合成一个 eligible/needs_review。下一版改成
`campaign_states`，先做确定性 planner 与 L4 快照，再评估 LLM planner；不得让 LLM
获得发送或提交工具。

## 8. Eval 同步协议

| 改动 | 必须同步 |
|---|---|
| 来源平台或 Campaign action strategy | L0 `campaign_contract.jsonl` |
| 确定性召回/过滤 | L1 golden + `--regression` |
| 打分 prompt/parser/硬门槛 | 对应 Campaign L2 case |
| 海外材料生成 | L3 case + 事实性 rubric |
| applications/反馈口径 | E2E 指标与历史兼容说明 |

`--regression` 只比较快照。只有人工解释并确认分布变化后才运行
`--update-regression`，禁止让 harness 自动接受新基线。

## 9. 关键文件

| 目标 | 文件 |
|---|---|
| Campaign 规格 | `app/src/boss_zhipin/domain/campaign.py` |
| 生产 L2 prompt/parser | `app/src/boss_zhipin/models/match_scoring.py` |
| Schema/migration | `app/src/boss_zhipin/persistence/schema.py`、`migrations.py` |
| 审核服务 | `app/src/boss_zhipin/application/review_service.py` |
| Agent 工具/排程 | `app/src/boss_zhipin/agent/tools.py`、`planner.py` |
| Eval harness/golden | `evals/run_evals.py`、`evals/golden/` |
| 整体蓝图 | `docs/goal-一条龙系统蓝图.md` |
| Agent 路线 | `docs/agent化改造方案.md` |
