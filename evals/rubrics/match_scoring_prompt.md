# L2 匹配打分契约说明

生产 prompt 与响应 parser 的唯一事实源：

`app/src/boss_zhipin/models/match_scoring.py`

`run_evals.py --l2` 直接 import 以下生产函数，不在 evals 仓复制 prompt：

- `build_match_scoring_prompt`
- `match_scoring_policy`
- `parse_match_scoring_response`

当前版本：

| Campaign | prompt version | 核心硬门槛 |
|---|---|---|
| `cn-2027-ai-product` | `cn-match-v2` | 外包/劳务派遣、年限/行业门槛、2027 校招属性 |
| `global-2027-ai-product` | `global-match-v1` | 资深/3+ 年限、Sponsorship、2027/New Grad 属性 |

修改 prompt 时只改 app 中的生产文件，同时补对应 Campaign 的
`golden/match_scoring.jsonl` case。不要在本文件粘贴 prompt 副本。
