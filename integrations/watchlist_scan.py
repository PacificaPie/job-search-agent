#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重点公司关注list扫描:直读 Greenhouse/Ashby/Lever 的公开 JSON API(确定性,无爬虫无LLM),
筛出「应届可投的产品/AI岗」新增项,推飞书。每日随 overseas_daily.sh 跑。

命中规则(标题级):
  A. 明确早期通道: new grad / university / early career / campus / apm
  B. 产品岗 且 无资深信号: (product manager|product|apm) - (senior|staff|principal|...)
去重: data/watchlist_seen.json(岗位URL集合)。命中0新增则静默。

用法: python3 scripts/watchlist_scan.py [--dry-run] [--baseline(只记台账不推送)]
"""
import argparse, datetime, json, os, re, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
DATA = os.path.join(PROJ, "data")

EARLY = re.compile(r"new\s*grad|university|early\s*career|campus|\bapm\b|associate product", re.I)
PRODUCT = re.compile(r"product manager|product management|\bapm\b|associate product", re.I)
SENIOR = re.compile(r"senior|staff|principal|director|head of|\blead\b|\bvp\b|group|\bsr\.?\b|manager,?\s*(ii|iii|2|3)", re.I)
FUNC = re.compile(r"product|strateg|analy|data|\bai\b|research|business|operation", re.I)   # 早期通道须职能相关
EXCL = re.compile(r"engineer|recruit|sales|account exec|counsel|designer|marketing|support", re.I)

def fetch(url, retries=2):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if i == retries: raise

def jobs_of(c):
    ats, bid = c["ats"], c["board_id"]
    out = []
    if ats == "greenhouse":
        d = fetch(f"https://boards-api.greenhouse.io/v1/boards/{bid}/jobs")
        for j in d.get("jobs", []):
            out.append((j.get("title",""), (j.get("location") or {}).get("name",""), j.get("absolute_url","")))
    elif ats == "ashby":
        d = fetch(f"https://api.ashbyhq.com/posting-api/job-board/{bid}")
        for j in d.get("jobs", []):
            out.append((j.get("title",""), j.get("location",""), j.get("jobUrl","") or j.get("applyUrl","")))
    elif ats == "lever":
        d = fetch(f"https://api.lever.co/v0/postings/{bid}?mode=json")
        for j in d:
            out.append((j.get("text",""), (j.get("categories") or {}).get("location",""), j.get("hostedUrl","")))
    return out

def matches(title):
    if PRODUCT.search(title) and not SENIOR.search(title):
        return "产品岗·无资深信号"
    if EARLY.search(title) and FUNC.search(title) and not EXCL.search(title):
        return "早期通道"
    return None

def applied_index():
    """投递台账 → (公司小写, 岗位词集合) 列表。台账里有的岗位不再推送(同岗位换链接重发也拦得住)。"""
    f = os.path.join(DATA, "applications.json")
    if not os.path.exists(f): return []
    try: apps = json.load(open(f, encoding="utf-8"))
    except Exception: return []
    idx = []
    for a in apps:
        toks = set(re.findall(r"[a-z]+", (a.get("role") or "").lower())) - {"the", "of", "and", "a"}
        idx.append(((a.get("company") or "").lower(), toks))
    return idx

def is_applied(company, title, idx):
    toks = set(re.findall(r"[a-z]+", title.lower()))
    for comp, atoks in idx:
        if comp and comp in company.lower() and atoks and len(atoks & toks) / len(atoks) >= 0.5:
            return True
    return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--baseline", action="store_true", help="只把当前命中记入台账,不推送(首跑用)")
    args = ap.parse_args()

    wl = json.load(open(os.path.join(DATA, "watchlist.json"), encoding="utf-8"))["companies"]
    seen_f = os.path.join(DATA, "watchlist_seen.json")
    seen = set()
    if os.path.exists(seen_f):
        try: seen = set(json.load(open(seen_f, encoding="utf-8")))
        except Exception: pass

    applied = applied_index()
    hits, errors, suppressed = [], [], 0
    for c in wl:
        try:
            for title, loc, url in jobs_of(c):
                why = matches(title)
                if not (why and url) or url in seen:
                    continue
                if is_applied(c["name"], title, applied):
                    seen.add(url); suppressed += 1; continue   # 已投递岗位:进台账不进推送
                hits.append((c["name"], c["tier"], title, loc, url, why))
        except Exception as e:
            errors.append(f"{c['name']}: {type(e).__name__}")
    if suppressed:
        print(f"watchlist: {suppressed} 条与投递台账重合,已抑制")

    if errors:
        print("拉取失败:", "; ".join(errors), file=sys.stderr)

    if not hits:
        if suppressed and not args.dry_run:
            json.dump(sorted(seen), open(seen_f, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=0)
        print("watchlist: 无新增命中"); return

    today = datetime.date.today()
    L = [f"# 关注公司速查 · {today} · 新岗 {len(hits)}\n"]
    for name, tier, title, loc, url, why in sorted(hits, key=lambda h: h[1]):
        tag = "🎯" if tier == "head" else "💎"
        L.append(f"{tag} **{title} · {name}** — {loc or '地点见链接'}〔{why}〕\n[查看/投递]({url})\n")
    body = "\n".join(L)

    out_f = os.path.join(DATA, f"watchlist_push_{today.strftime('%Y%m%d')}.md")
    open(out_f, "w", encoding="utf-8").write(body)

    if args.dry_run:
        print(body); return

    seen |= {h[4] for h in hits}
    json.dump(sorted(seen), open(seen_f, "w", encoding="utf-8"), ensure_ascii=False, indent=0)

    if args.baseline:
        print(f"watchlist: 基线建立,{len(hits)} 条入台账未推送"); return

    import subprocess
    r = subprocess.run([sys.executable, os.path.join(HERE, "feishu_notify.py"),
                        "--send-file", out_f], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"推送失败: {r.stderr.strip()}", file=sys.stderr); sys.exit(1)
    print(f"watchlist: 已推送 {len(hits)} 条新岗")

if __name__ == "__main__":
    main()
