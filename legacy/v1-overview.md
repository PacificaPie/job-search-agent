# Job-Search Agent — an unattended, human-in-the-loop AI pipeline

> 一个每天自动运行的求职系统：多信源发现岗位 → 画像筛选 → LLM agent 富化（找官方入口、抓 JD、判匹配度）→ 飞书推送 → 定制简历 → **人工审核后投递**。
> Running unattended since June 2026. Designed and owned by me; implementation pair-built with AI.

**Live case study:** [pacificapie.github.io/work/jobagent](https://pacificapie.github.io/work/jobagent.html)

## Why

校招信息散落在聚合表、招聘平台和公司官网里，跟踪它们是纯粹的重复劳动。我给自己定的产品指标只有一个：**从"新岗位出现"到"完成投递"的每日循环摩擦 ≤ 10 分钟**。个人工具的核心指标不是功能数量，是循环摩擦。

## Architecture

```
┌─ 信源层 ────────────────────────────────────────────┐
│  结构化聚合表(bitable API) · 招聘平台 MCP(只读/低频)   │
│  关注公司板扫描(Greenhouse/Ashby/Lever 公开 JSON API) │
└──────────────┬──────────────────────────────────────┘
               ▼
┌─ 筛选层 ─────────────────────────────────────────────┐
│  画像关键词/届次过滤 · 内容哈希去重 · 已投岗位跨渠道抑制 │
└──────────────┬──────────────────────────────────────┘
               ▼
┌─ 富化层(headless LLM agent) ─────────────────────────┐
│  搜官方投递入口 · 抓具体岗位 JD · 匹配度判定+理由       │
└──────────────┬──────────────────────────────────────┘
               ▼
┌─ 推送层 ─────────────────────┐   ┌─ 报警轨(独立凭证) ──┐
│  每日两班飞书卡片(仅新增)      │   │  任何环节失败即通知   │
└──────────────┬──────────────┘   └─────────────────────┘
               ▼
┌─ 投递层(human-in-the-loop) ──────────────────────────┐
│  简历定制(多agent评审:事实核查/JD匹配/ATS) → 填表到提交前│
│  → 人工审核点击提交 → 台账回流抑制                      │
└──────────────────────────────────────────────────────┘
```

## Design decisions I'd defend

1. **Human-in-the-loop 是产品设计不是技术妥协**：投递永不自动提交；简历每个数字必须可溯源到事实台账（bullet 引用事实卡 ID，让 AI 事实核查从模糊检索变成机械核对）。
2. **报警通道与数据通道凭证分离**：数据通道的用户授权会过期，报警通道用不过期的应用凭证——管线挂掉时，报警永远活着。"没消息"和"没命中"必须可区分，这是无人值守系统的底线。
3. **确定性优先于智能**：能用公开 JSON API 直读的（关注公司板扫描）绝不用 LLM；LLM 只花在真正需要判断的地方（匹配度、JD 提炼）。
4. **去重键是产品决策**：裸公司名去重会永久吞掉同一公司的新批次；改为 公司|届次|批次|内容哈希 后，真实漏岗被找回。
5. **已投抑制跨渠道生效**：投递台账反哺所有发现渠道，同岗位换链接重发也会被拦——投过的岗位第二天就该闭嘴。

## What's in this repo

| 文件 | 说明 |
|---|---|
| `scripts/watchlist_scan.py` | 关注公司板扫描：直读 Greenhouse/Ashby/Lever 公开 API，标题级筛选 + 已投抑制（可直接运行） |
| `prompts/discovery_prompt.md` | 岗位发现 agent 的任务提示词（资历过滤 + 去重 + 控频规则） |
| `prompts/enrich_prompt.md` | 富化 agent 的任务提示词（官方入口优先级 + 匹配度标尺 + 反编造铁律） |
| `skills/` | 编排层的三个自研 Claude Code skill（见下节） |


## Agent Skills (the orchestration layer, as real files)

这套系统的编排层由三个自研 Claude Code skill 构成——skill 文件本身就是产品规格：

| Skill | 职责 | 设计要点 |
|---|---|---|
| [`skills/career-archive.md`](skills/career-archive.md) | 经历库:捕获(/capture)+整理(/organize)双模式 | 审核闸不可跳过;WORKLOG 只追加、archive 可重组;不造假铁律 |
| [`skills/resume-tailor.md`](skills/resume-tailor.md) | 按 JD 从经历库取材裁剪 | 只用事实卡素材;无出处的数字写 [待填] 不编造 |
| [`skills/apply.md`](skills/apply.md) | 投递六阶段编排(已脱敏) | 三评审 agent 并行(事实核查/JD匹配/ATS);表单填到提交前,Submit 永远由人点 |

Skill 设计遵循的原则(在更大的团队项目中打磨出来的):**薄皮 skill**——只承担触发词、执行序和中止条件,知识正文放单一权威位置;**规则/地图/手册/剧本四层分离**——会话会结束,跟着 git 走的知识才是资产。

## What's deliberately excluded

个人身份信息、任何凭证与 token、公司内部数据源配置、简历事实库。本仓库展示的是**架构与产品判断**，不是可一键复制的求职外挂——铁律部分（不造假、不自动提交）恰恰是它最不该被去掉的部分。

## Evaluation

- 运行监控：全链路故障报警（曾靠它发现并修复三类环境故障：PATH/代理/凭证）
- 推送质量：投递台账的行为数据回流筛选层（投了/略过），推送准度随使用变准
- 简历质量：三评审 agent 并行（事实核查/JD 匹配/ATS），两轮不过的内容删除而非带病投递
