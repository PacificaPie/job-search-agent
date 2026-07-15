---
name: apply
description: 求职投递全流程编排：给定一个具体岗位（用户粘贴的链接/JD，或管线推送卡里的岗位），走完「抓JD → 从 career-archive 取对口经历 → 多agent评审循环生成 ATS 友好简历 → 浏览器填官网申请表到提交前」。触发："/apply <岗位链接或描述>"、"投这个岗"、"帮我申请 X 公司的 Y 岗"、"按这个JD出简历并投递"。投递永远 human-in-the-loop：填到提交前，用户审核后自己点提交。
---

# apply — 简历定制 + 投递工作流

六个阶段顺序执行。铁律（不可被任何阶段绕过）：
- **不造假**：每条 bullet 的每个事实/数字必须能落到 archive.md 的某张事实卡（E-ID）；标了"待确认"的数字不得使用；没有出处的写法一律降级为过程性描述。
- **不自动提交**：表单填到提交前为止；签证/薪资/通勤/身份类决策题一律留空并列清单交用户。
- **发现矛盾先报告**：JD 硬性要求与用户画像冲突（如年限 8-10 年、必须 onsite 到不可通勤的城市）时，先摊开事实给用户拍板，不闷头执行（先例：Figma AI Platform 岗）。

## 阶段 1 · 抓 JD

输入可能是：URL（Greenhouse/Lever/Ashby/LinkedIn/公司官网）、粘贴的 JD 文本、或推送卡里的公司+岗位名。
- Greenhouse 板：优先 `https://boards-api.greenhouse.io/v1/boards/<board>/jobs/<id>?questions=true`（JSON 含表单字段）；页面 WebFetch 兜底。
- LinkedIn 链接：headless `claude -p --mcp-config .mcp.json` 调 `mcp__linkedin__get_job_details`。
- 落盘 `data/jd_<公司小写>_<YYYYMMDD>.md`：JD 全文 + 申请表单字段清单。
- 产出「JD 要点解析」：硬性要求逐条、加分项逐条、公司/岗位的叙事钩子（它反复强调什么）。

## 阶段 2 · 取材（career-archive）

```bash
cd ~/career-archive && git pull --rebase
```
读 `archive.md`（全部事实卡 + 能力索引）。按 JD 要点选卡：
- 输出选材清单：每张选中的卡 → 命中 JD 的哪条要求（可回溯）；
- 明确列出"JD 要求但库里证据薄弱"的缺口（诚实呈现，不硬凑）；
- WORKLOG 有而 archive 还没入卡的新素材 → 提示用户先跑增量 organize，不直接引用未过审的材料。

## 阶段 3 · 生成（ATS 友好）

以 `resume_master_EN.html`（或对应语言母版）的版式为基底生成定制版：
- ATS 规则：单栏、标准节名（Summary/Education/Skills/Experience/Projects）、无表格/图标/多栏、bullet 用动词开头、JD 关键词自然融入（不堆砌）、文件名 `Resume.pdf`。
- Summary 按该 JD 的叙事钩子重写；bullet 按"JD 要求 → 证据"逐条对齐。
- **边界表述规范**（用户明确要求）：产品形态/初代算法/交互 = "我先 propose → 团队校验 → 协同开发"；实现 = "借助 AI 结对交付（我定方向、判断与验收）"。
- 同时产出 sidecar 文件 `data/bullets_map_<公司>_<日期>.md`：每条 bullet → 引用的 E-ID 列表（评审用，不进简历）。

## 阶段 4 · 多 agent 评审循环（最多 2 轮）

用 Agent 工具并行拉起三个评审（一次消息内并发）：
1. **事实核查**（给它 archive.md + 简历 + bullets_map）：逐条核对 E-ID 存在、内容一致、数字与卡上完全相同、没有使用"待确认"数字、边界表述未夸大。输出：每条 PASS/FAIL+理由。
2. **JD 匹配**（给它 JD + 简历）：硬性要求覆盖率、关键词缺口、哪条 bullet 弱/冗余、Summary 是否回应叙事钩子。输出：覆盖率表 + 修改建议。
3. **ATS/语言**（给它简历 HTML）：格式合规、动词强度、每条长度、可量化处是否量化、拼写。输出：逐条建议。

主循环汇总 → 修订 → 若有 FAIL 再跑一轮事实核查。两轮后仍有 FAIL 的条目直接删除或降级，不带病投递。

## 阶段 5 · 产出与转档

- 简历 HTML 存项目根 `resume_<公司>_<岗位简称>_EN.html`；
- 转 PDF：`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu --no-pdf-header-footer --print-to-pdf=<路径>/Resume.pdf "file://<HTML绝对路径>"`；
- `cp` 一份到 `~/Downloads/`（表单上传沙盒不允许 agent 传文件，用户从下载文件夹手动 Attach）；
- 用户要 cover letter 才写（一页、直面 JD、不虚构经历，先例 `cover_letter_IXL_APM_EN.html`）。
- 交付摘要：选材理由 / 评审结论 / 遗留 `[待填]` / 与 JD 的已知差距。

## 阶段 6 · 官网填表（到提交前）

Chrome MCP（工具若未加载先 ToolSearch 批量拉取）：
- `tabs_context_mcp` → 用户已开着申请页就用那个 tab，否则 `navigate`；
- `find`/`read_page` 定位字段 → `form_input` 填：姓名 <YOUR_NAME> / 邮箱 <YOUR_EMAIL> / 电话 <YOUR_PHONE> / 地点 <YOUR_LOCATION> / LinkedIn <YOUR_LINKEDIN> / GitHub <YOUR_GITHUB> / 个人站 <YOUR_SITE>；
- 开放题（编码经验/项目描述类）：从事实卡取材现写，风格与阶段 3 一致；
- **留空并列清单**：工作许可、sponsorship、通勤承诺、薪资确认、性别/族裔/退伍/残障等自愿披露题；
- **绝不点 Submit / 不碰 CAPTCHA**；截图核验已填内容。
- 交接清单格式：✅已填项 / 📎用户动作（上传简历→审开放题→答决策题→点提交）/ ⚠️风险提示（如毕业时间 vs 岗位 start date）。

## 收尾 · 投递台账

追加 `data/applications.json`：`{date, company, role, jd_file, resume_file, status: "filled_pending_submit", url, notes}`。用户确认提交后把 status 更新为 `submitted`。台账后续供反馈闭环（推送准度调优）使用。
