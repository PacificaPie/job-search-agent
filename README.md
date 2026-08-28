# Reachout 测评体系

> 建于 2026-08-27。设计原则：测评先于重构——任何 pipeline 改动必须先过这里。

## 为什么分层

业界对 agent 的测评通用做法是按「确定性 → 单步 LLM → 端到端」分层，每层用不同手段：

| 层 | 被测对象 | 方法 | 状态 |
|---|---|---|---|
| **L0 契约** | 平台 → Campaign → action strategy | Golden 精确断言；未知来源必须显式失败 | ✅ 4/4 |
| **L1 过滤** | `domain/job_filter.py`、`domain/linkedin_filter.py` | Golden set 精确断言 + 真实 DB 全量回归快照 | ✅ 20/20 |
| **L2 打分** | Campaign-specific LLM 匹配评分 | 人工/合成分数带 + 关键点覆盖；直接 import app 生产 prompt/parser | ✅ 国内 7/7 + 海外 4/4 |
| **L3 生成物** | 海外定制简历 / outreach | LLM-as-judge + 事实溯源 + 一票否决制 rubric | ⏸ rubric 已写，harness 未接 |
| （远期）E2E | 全链路 | 北极星指标：回复率/约面率，从 applications 表自动统计 | 待投递数据积累 |

## 怎么跑

```bash
cd evals
python3 run_evals.py               # L0 Campaign 契约 + L1 过滤，当前 24/24
python3 run_evals.py --regression  # 真实 DB 回归，只比较快照，不会自动覆盖
python3 run_evals.py --update-regression  # 仅在人工解释分布变化后显式更新快照

# L2：从 app/.env 读端点即可（base_url 带不带 /v1 都兼容）
set -a && . ../app/.env && set +a && ../app/.venv/bin/python run_evals.py --l2

# 端点偶发 503 时只重跑失败 case，避免重复付费
../app/.venv/bin/python run_evals.py --l2 --case G02 --case G04
```

> ⚠️ 用 `../app/.venv/bin/python` 而不是系统 `python3`：机器上的 anaconda python
> 走 `urllib` 连 api.anthropic.com 会抛 `SSL: UNEXPECTED_EOF_WHILE_READING`，
> venv 里的解释器正常。L1/--regression 不联网，用哪个都行。

## 首轮发现（2026-08-27）与处理结果

1. **B10 = 真实 bug，已修**（`fix(filter)` commit）。
   **修正首轮结论**：README 初版写「30/95 被误杀」是高估。实测 30 条「不在目标城市范围」里
   **25 条是真·乌鲁木齐岗位（正确过滤）**，只有 **5 条是 location 为空导致的误杀**——
   这 5 条正文里都有「工作地址 北京…」。
   修法：location 为空才回退正文找城市；仍找不到降级 needs_review；排除词/岗位方向仍先杀
   以免灌满审核队列；location 有值但不匹配的照旧硬杀。
   回归影响：filtered 47→46、needs_review 43→44（1 条「高级数据产品经理」转入人工队列），
   「不在目标城市范围」30→25。

2. **L10 = 误杀模式，已修**（同一 commit）。
   **修正首轮结论**：真实 5 条 LinkedIn 岗位里那 2 条被杀的**不是误杀**——它们确实写着
   `Qualifications 8+ years` / `Ideal Experience 3+ years`。真正的误杀风险来自两类同形表述：
   导师背景（`mentored by leaders with 10+ years`）和公司宣传（`we've been innovating for 40 years`），
   后者在真实数据里确实命中了。
   修法：按句切分，豁免语境（导师/团队/公司历史）优先于要求语境（require/qualification/minimum…），
   并把命中原句写进理由。回归分布不变（那 2 条本来就该杀）。

3. **判定分布基线**：boss 46 filtered / 44 needs_review / 5 eligible。needs_review 占 46%——
   「未找到校招标识」的岗位太多，人工审核台会被灌满，可考虑对 needs_review 也跑 L2 打分做二次排序。

4. **L2 首次跑通，两个坑都在输入/输出格式上，不在打分能力**：
   - golden 里 S02–S07 的 `resume_summary` 字面写着「同 S01」，以前被原样塞进 prompt，
     模型收到四个字当然只能回「请提供候选人背景」。已在 harness 加引用解析（`resolve_resume_refs`）。
   - 模型爱把 JSON 包在 ```json 围栏里，且 `reason` 里嵌半角双引号 → 解析失败 2/7。
     已迭代 `rubrics/match_scoring_prompt.md`（禁围栏、禁半角双引号、引用改用「」），
     **未动任何 golden 标签**。
   - 修完连跑两次都是 **7/7 band 命中、0 解析失败**，must_mention 关键点全覆盖。
     分数很稳（S01 82、S03 91、S06 22），说明 rubric 的硬规则（外包 ≤40、硬门槛 ≤45）真的在起作用。

5. **Campaign 架构进入 L0 与回归快照**：`campaign_contract.jsonl` 固定平台路由、
   action strategy 和是否需要生成材料。真实 DB 回归同时输出 `by_platform` 与
   `by_campaign`，未知平台进入 `unassigned`，不能静默混队列。

6. **L2 prompt 漂移已结构性消除**：生产 prompt 与 parser 的唯一来源是
   `app/src/boss_zhipin/models/match_scoring.py`；harness 直接 import，不再读取一份
   evals 私有 prompt。国内/海外各有版本号，写入 evaluation 便于回放。

7. **BOSS 固定招呼语不再作为 L3 生成任务**：L3 优先评海外定制简历和英文
   outreach。BOSS 的测评重点是路由正确、无逐岗位生成、无系统自动发送。

8. **海外 L2 首批 4 条已跑通**（claude-sonnet-4-6）：标准正例 82、明确不支持
   Sponsorship 28、Senior + 5 年门槛 38、签证未说明 62，全部落在标注 band，
   硬门槛理由覆盖无遗漏。端点期间多次 503/断连，因此 harness 增加 `--case` 定点
   重跑和逐 case 错误隔离；网络失败会让本轮失败，但不会中断后续 case。

## 标注约定

- golden 标签编码**期望行为**而非当前实现——红灯是功能不是事故。
- 每条 case 带 `note` 说明设计意图；已知保守取舍（如 B09 否定语境）标 green 但注明。
- L2 国内分数带来自 2026-08-20 的 5 条人工标注，海外首批为 Campaign 硬门槛合成集；
  扩充时必须填写 `campaign_key`。同一 Campaign 内保持同一 resume summary 以保证可比，
  文件里可写 `"resume_summary": "同 S01"` / `"同 G01"`，harness 会自动解析。

## 同步维护协议

| app 改动 | 必须同步的 eval |
|---|---|
| 新增/修改来源平台或 Campaign action strategy | `golden/campaign_contract.jsonl`（L0） |
| 修改确定性召回/过滤规则 | 对应 L1 golden；再跑 `--regression`，解释分布变化 |
| 修改匹配 prompt、parser 或硬门槛 | 改 app 的 `models/match_scoring.py` + 对应 Campaign L2 case；禁止在 evals 复制 prompt |
| 修改海外简历/outreach 生成 | 先补 L3 case/rubric，再改生成链 |
| 修改 applications 状态或反馈定义 | 更新 E2E 指标口径与历史兼容说明 |

Golden 标签不能为了变绿而改。只有产品期望确实变化时才修改标签，并在 case `note`
和变更记录中说明原因。回归快照也不再自动写入，必须使用 `--update-regression` 显式确认。

## 这是一个独立的仓

`evals/` 有自己的 git 仓，**不并进 `app/`**——`app/` 是有 upstream 的 fork，
测评是私货，混进去以后往上游提 PR 很难拆。

但"独立"不等于"不依赖 app"：L1 **故意直接 import `app` 里的真实规则函数**，
而不是抄一份副本过来。抄副本就会跟 app 漂移，测的东西就不再是线上跑的东西。
所以依赖是真的，只是被显式化了：

```bash
# 默认按 ../app、./app、../reachout/app 依次找；找不到就报错告诉你怎么指
REACHOUT_APP_PATH=~/Desktop/项目/reachout/app python3 run_evals.py

# --regression 要一个真实的 reachout.db，默认取 <app>/data/reachout.db
REACHOUT_DB_PATH=/path/to/reachout.db python3 run_evals.py --regression
```

| 环境变量 | 作用 | 默认 |
|---|---|---|
| `REACHOUT_APP_PATH` | 被测 app 的根目录 | `../app` → `./app` → `../reachout/app` |
| `REACHOUT_DB_PATH` | 回归测评用的真实库 | `<app>/data/reachout.db` |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | L2 用的端点 | 无，未配则 `--l2` 跳过 |
