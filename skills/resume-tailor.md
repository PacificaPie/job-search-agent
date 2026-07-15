---
name: resume-tailor
description: 经历裁剪层(与 career-archive 配对的下游 skill)。读 career-archive 里全部 WORKLOG + archive.md 这份中性事实池,输入一个 target(目标公司/岗位/行业/JD),输出面向该方向的简历 bullet、经历选择与面试故事框法——按 target 现推措辞,不锁死在互联网 PM。只要用户说"按这个 JD 裁简历""帮我把经历往 X 方向写""出一版投 Y 行业的简历""/resume""/tailor",就用本 skill。本 skill 只做"按方向重讲已有事实",绝不编造经历或指标——事实来自 career-archive,这里只换框法和语言。
---

# resume-tailor — 经历裁剪层(裁剪/措辞加工)

与 career-archive(捕获层)配对。career-archive 只如实记"做了什么"(方向无关);本 skill 拿那些中性事实,**按某个具体 target 重讲**成简历语言。两层分工不可混:捕获不加工,裁剪不造假。

## 数据从哪读(只读,不写经历库)

```
~/career-archive/                      ← 唯一事实源(career-archive skill 维护)
├── projects/<项目名>/WORKLOG.md        ← 贡献级原始记录(主要素材)
└── archive.md                          ← 跨项目蒸馏出的中性事实池(若已建)
```

- 开工先 `cd ~/career-archive && git pull --rebase` 拿最新(只读取,不在这里 commit 经历)。
- 若 `archive.md` 为空 → 先从 WORKLOG 现场提炼;提炼出的中性事实可建议回写给 career-archive,但**回写动作属于捕获层**,不在本 skill 里做。

## 铁律(与 career-archive 一致 + 本层特有)

1. **不造假**:bullet 里每个事实、每个数字都必须能在 WORKLOG/archive 里找到出处。WORKLOG 里标 `[待填]`/无硬指标的,输出时显式标出"待补真实数字",**绝不编**——投正式简历前由本人补真数或降级为过程性表述。
2. **忽略历史 tag**:老 WORKLOG 里残留的 `适用方向: [PM][数据][AI]` 是捕获层删 tag 之前写的,**不作数**。方向完全由本次 target 现推,别让历史标注限制选材。
3. **方向不锁死在互联网**:target 可以是任意行业(医药/临床/卫生经济/量化/咨询/政策评估…)。同一份事实换不同 target 应给出不同框法和语言,而不是只会写"互联网 PM"那套黑话。
4. **不泄密**:只用 WORKLOG 里已脱敏的可对外层面;不因为"要写简历"就把公司专有内容捞回来。
5. **human-in-the-loop**:输出是草稿,交本人定稿;不直接对接投递、不替本人提交。

## 工作流(/resume 或 /tailor)

1. **同步 + 读料**:`git pull --rebase` 后,读全部 `projects/*/WORKLOG.md`(+ archive.md 若有),建一个内存里的中性事实清单。
2. **解析 target**:从 JD/岗位/行业描述里抽出该方向真正看重的能力关键词与画像(不是套固定三桶)。
3. **选材打分**:按 target 关键词与每条经历的重合度排序,选最相关的几条;明确打出"为什么选这几条、命中哪些点"(可回溯)。
4. **跨行业重框**:把选中经历用 target 行业的语言重讲。示例映射(非穷举):
   - 面板 DID/随机化推断/稳健性检验 → 临床试验设计、卫生经济、政策因果评估、量化研究
   - 跨源去重/实体消歧/taxonomy → 医疗记录治理、金融/法务数据整合
   - 数据诚实性纪律(不静默吞错、跨边界先实测、对比口径独立算) → 任何受监管/循证环境的可信度论证
   - "我定方向+判断、AI/他人执行" → 通用的产品/项目领导力叙事
5. **出 bullet + 面试故事**:每条给 STAR 化的简历 bullet,并附一句"面试可展开点"。标出所有 `[待填]`。
6. **交付**:产物喂给简历工具(`generate.py` 的定制轨 / `简历工具.html` 的手动轨),由本人定稿、渲染、投递。

## 输出 schema(每条经历)

```
- 目标方向: <本次 target,如「临床数据科学家」>
- 选它的理由: 命中 target 的哪些点(可回溯)
- 简历 bullet: STAR 化、用 target 行业语言、动词开头
- 数字: 有真实数据则填;无则标 [待补真实数字],不编
- 面试可展开: 一句话钩子,指向 WORKLOG 里的细节
```

## 与项目其余部分的边界

- 事实的"写入"是 career-archive 的事;本 skill 只读。
- 确定性选材/打分,简历工具的 `generate.py` 已有一版;本 skill 负责其上"把经历重写成漂亮 bullet/面试故事"的语言层(README 里的 `/resume` LLM 润色环节)。
- 不碰投递状态机、不碰自动填表——那些在 pipeline 侧。
