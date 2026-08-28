#!/usr/bin/env python3
"""Reachout 测评 harness。

L1（确定性过滤）：离线可跑，python3.10+ 均可（内置 StrEnum shim）。
L2（匹配打分）/ L3（草稿质量）：需要 OpenAI 兼容端点，设 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL。

用法：
  python3 run_evals.py                 # 跑 L1 golden 集
  python3 run_evals.py --regression    # 用真实 DB + 真实用户偏好跑全量回归快照
  python3 run_evals.py --l2            # 跑 L2 打分测评（需 API key）
"""
from __future__ import annotations

import argparse
import enum
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

# --- py<3.11 兼容 shim：app 代码用了 enum.StrEnum ---
if not hasattr(enum, "StrEnum"):
    class _StrEnum(str, enum.Enum):
        def __str__(self) -> str:  # 与 3.11 语义对齐
            return self.value
    enum.StrEnum = _StrEnum  # type: ignore[attr-defined]

HERE = Path(__file__).resolve().parent

# --- 被测代码的位置 ---------------------------------------------------------
# 这个仓是独立的，但它**故意**直接 import app 里的真实规则函数，而不是抄一份副本过来：
# 抄副本就会跟 app 漂移，测的东西就不再是线上跑的东西。所以依赖是真的，只是把它显式化
# ——路径可用 REACHOUT_APP_PATH 覆盖，找不到时报错要能照着做。
_APP_CANDIDATES = ("../app", "./app", "../reachout/app")


def _resolve_app_path() -> Path:
    configured = os.environ.get("REACHOUT_APP_PATH", "").strip()
    candidates = (
        [Path(configured).expanduser()]
        if configured
        else [HERE / c for c in _APP_CANDIDATES]
    )
    for candidate in candidates:
        if (candidate / "src" / "boss_zhipin").is_dir():
            return candidate.resolve()
    tried = "\n  ".join(str(c) for c in candidates)
    raise SystemExit(
        "找不到 app 源码（需要 <app>/src/boss_zhipin/）。已尝试：\n  "
        + tried
        + "\n\n用 REACHOUT_APP_PATH 指过去，例如：\n"
        "  REACHOUT_APP_PATH=~/Desktop/项目/reachout/app python3 run_evals.py"
    )


APP = _resolve_app_path()
sys.path.insert(0, str(APP / "src"))


def default_db_path() -> Path:
    """回归测评用的真实库。独立部署时用 REACHOUT_DB_PATH 指过去。"""

    configured = os.environ.get("REACHOUT_DB_PATH", "").strip()
    return Path(configured).expanduser() if configured else APP / "data" / "reachout.db"


from boss_zhipin.domain.job_filter import JobFilterConfig, evaluate_job_rules  # noqa: E402
from boss_zhipin.domain.linkedin_filter import (  # noqa: E402
    DEFAULT_LINKEDIN_FILTER,
    evaluate_linkedin_job_rules,
)


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_user_prefs(db: Path) -> JobFilterConfig:
    conn = sqlite3.connect(db)
    row = conn.execute(
        "select target_cities_json, target_roles_json, employment_types_json,"
        " title_excludes_json, content_excludes_json from profile_preferences limit 1"
    ).fetchone()
    conn.close()
    if row is None:
        raise SystemExit("profile_preferences 为空，无法构造真实配置")
    c, r, e, te, ce = (tuple(json.loads(x)) for x in row)
    return JobFilterConfig(c, r, e, te, ce)


def run_golden(name: str, cases: list[dict], fn) -> tuple[int, int, list[str]]:
    passed, failures = 0, []
    for case in cases:
        result = fn(
            title=case["title"],
            location=case["location"],
            description=case["description"],
        )
        got = str(result.state)
        if got == case["expected_state"]:
            passed += 1
        else:
            failures.append(
                f"  ✗ [{case['id']}] {case['title'][:30]} | 期望 {case['expected_state']}"
                f" 实际 {got} | 理由 {'; '.join(result.reasons)} | 备注 {case.get('note','')}"
            )
    return passed, len(cases), failures


def cmd_l1() -> int:
    total_pass = total = 0
    for fname, fn in (
        ("boss_filter.jsonl", lambda **kw: evaluate_job_rules(config=BOSS_CFG, **kw)),
        (
            "linkedin_filter.jsonl",
            lambda **kw: evaluate_linkedin_job_rules(config=DEFAULT_LINKEDIN_FILTER, **kw),
        ),
    ):
        cases = load_jsonl(HERE / "golden" / fname)
        p, n, fails = run_golden(fname, cases, fn)
        total_pass += p
        total += n
        print(f"[{fname}] {p}/{n} 通过")
        for f in fails:
            print(f)
    print(f"\nL1 合计：{total_pass}/{total}")
    return 0 if total_pass == total else 1


def cmd_regression() -> int:
    db = default_db_path()
    if not db.exists():
        raise SystemExit(
            f"找不到数据库：{db}\n"
            "回归测评需要一个真实的 reachout.db。用 REACHOUT_DB_PATH 指过去，"
            "或先在 app 里跑一次 capture 生成它。"
        )
    prefs = load_user_prefs(db)
    conn = sqlite3.connect(db)
    dist: dict[str, dict[str, int]] = {}
    reason_top: dict[str, dict[str, int]] = {}
    for platform, title, location, desc in conn.execute(
        "select platform, title, location, description from jobs"
    ):
        if platform == "linkedin":
            m = evaluate_linkedin_job_rules(title=title, location=location, description=desc)
        else:
            m = evaluate_job_rules(title=title, location=location, description=desc, config=prefs)
        dist.setdefault(platform, {}).setdefault(str(m.state), 0)
        dist[platform][str(m.state)] += 1
        key = m.reasons[0] if m.reasons else "?"
        reason_top.setdefault(platform, {}).setdefault(key, 0)
        reason_top[platform][key] += 1
    conn.close()
    print("=== 真实 DB 全量回归（判定分布） ===")
    print(json.dumps(dist, ensure_ascii=False, indent=2))
    print("=== 首要理由 Top ===")
    for platform, reasons in reason_top.items():
        top = sorted(reasons.items(), key=lambda kv: -kv[1])[:6]
        print(platform, json.dumps(dict(top), ensure_ascii=False, indent=2))
    snapshot = HERE / "regression_snapshot.json"
    baseline = json.loads(snapshot.read_text()) if snapshot.exists() else None
    snapshot.write_text(json.dumps(dist, ensure_ascii=False, indent=2))
    if baseline is not None and baseline != dist:
        print("\n⚠️ 判定分布相对上次快照发生变化，检查是否为预期改动")
        return 1
    return 0


_RESUME_REF_RE = re.compile(r"^同\s*(S\d+)$")


def resolve_resume_refs(cases: list[dict]) -> None:
    """把 ``resume_summary: "同 S01"`` 这类引用替换成被引用 case 的真实简历摘要。

    golden 集里所有 case 共用同一份简历摘要（见 README「标注约定」），文件里
    为了不重复就写成引用。以前这段字面量被原样塞进 prompt，模型收到的是
    「同 S01」四个字 —— 于是除 S01 外全部输出「请提供候选人背景」而非 JSON。
    """
    by_id = {case["id"]: case for case in cases}
    for case in cases:
        match = _RESUME_REF_RE.match(str(case.get("resume_summary", "")).strip())
        if not match:
            continue
        target = by_id.get(match.group(1))
        if target is None or _RESUME_REF_RE.match(str(target["resume_summary"]).strip()):
            raise SystemExit(f"[{case['id']}] resume_summary 引用 {match.group(1)} 无法解析")
        case["resume_summary"] = target["resume_summary"]


def cmd_l2() -> int:
    key = os.environ.get("LLM_API_KEY")
    if not key:
        print("L2 需要 LLM_API_KEY（OpenAI 兼容端点）。当前未配置，跳过。")
        print("配好后：LLM_API_KEY=... LLM_BASE_URL=... LLM_MODEL=... python3 run_evals.py --l2")
        return 2
    import urllib.request

    # base_url 两种写法都要能跑：app/.env 里给 openai SDK 用的是带 /v1 的完整前缀
    # （如 https://api.anthropic.com/v1/），README 示例给的是不带 /v1 的裸域名。
    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com").rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    cases = load_jsonl(HERE / "golden" / "match_scoring.jsonl")
    resolve_resume_refs(cases)
    rubric = (HERE / "rubrics" / "match_scoring_prompt.md").read_text()
    errors, band_hits = [], 0
    for case in cases:
        prompt = rubric.format(jd=case["jd"], resume=case["resume_summary"])
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            }
        ).encode()
        req = urllib.request.Request(
            f"{base}/v1/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            content = json.load(resp)["choices"][0]["message"]["content"]
        try:
            got = json.loads(content.strip().removeprefix("```json").removesuffix("```"))
            score = float(got["score"])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"[{case['id']}] 输出不可解析: {exc}")
            continue
        lo, hi = case["expected_score_band"]
        ok = lo <= score <= hi
        band_hits += ok
        flag = "✓" if ok else "✗"
        print(f"{flag} [{case['id']}] score={score} 期望带 [{lo},{hi}] | {case['title']}")
        must = case.get("must_mention", [])
        missing = [m for m in must if m not in json.dumps(got, ensure_ascii=False)]
        if missing:
            print(f"   ⚠️ 理由未覆盖关键点: {missing}")
    print(f"\nL2 band 命中：{band_hits}/{len(cases)}；解析失败 {len(errors)}")
    for e in errors:
        print(" ", e)
    return 0 if band_hits == len(cases) and not errors else 1


if __name__ == "__main__":
    BOSS_CFG = JobFilterConfig(
        target_cities=("北京", "上海", "深圳", "广州"),
        target_roles=(
            "AI产品经理", "AI 产品经理", "大模型产品经理", "AIGC产品经理",
            "Agent产品经理", "智能体产品经理", "策略产品经理", "商业产品经理",
            "数据产品经理", "产品经理",
        ),
        employment_types=("2027校招",),
        title_excludes=("外包", "销售", "运营", "实施", "驻场"),
        content_excludes=("外包", "劳务派遣", "人力外包", "驻场", "外派"),
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--regression", action="store_true")
    ap.add_argument("--l2", action="store_true")
    args = ap.parse_args()
    if args.regression:
        raise SystemExit(cmd_regression())
    if args.l2:
        raise SystemExit(cmd_l2())
    raise SystemExit(cmd_l1())
