#!/usr/bin/env python3
"""
audit.py - 내가 이미 올린 쓰레드 글을 돌아본다. 무엇이 진짜 잘 됐고, 무엇을 그만할지.

조회수 자체는 덜 쓸모 있다. 대부분 팔로워 수가 정하기 때문이다. 대신 이렇게 본다:
  - 배수: 조회수 / 내 글 조회수 중앙값    (평범한 날인지 진짜 터진 건지)
  - 천 조회당 답글                       (대화가 붙었는지. 쓰레드에서 가장 중요한 신호)
  - 천 조회당 퍼감 = 리포스트+인용+공유     (남이 자기 이름을 걸고 퍼뜨렸는지)
  - 천 조회당 좋아요

입력 (셋 중 아무거나):
  1. fetch_insights.py 가 만든 JSON (공식 API, 가장 정확)
  2. CSV/TSV: date, text(또는 hook), views, likes, replies, reposts, quotes, shares 열
  3. 손으로 적은 TSV (views와 text만 있어도 첫 분석은 된다)

사용법
  python3 audit.py ~/.claude/threads/posts.json
  python3 audit.py my_posts.tsv
  python3 audit.py my_posts.csv --json
"""

import argparse
import csv
import io
import json
import os
import re
import statistics
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "th-post"))
sys.path.insert(0, os.path.join(HERE, "..", "th-viral"))
try:
    from hookscore import run as score_hook  # noqa: E402
except Exception:
    score_hook = None
try:
    from rank import load_formulas, classify, num  # noqa: E402
except Exception:
    load_formulas = lambda: None  # noqa: E731
    classify = lambda h, f: (None, "분류 안 됨")  # noqa: E731

    def num(v):
        try:
            return int(str(v).replace(",", "")) if str(v).strip() else None
        except ValueError:
            return None

FIELDS = ("views", "likes", "replies", "reposts", "quotes", "shares")


def read_posts(path):
    raw = sys.stdin.read() if path == "-" else open(os.path.expanduser(path), encoding="utf-8").read()
    s = raw.lstrip()
    if s.startswith("[") or s.startswith("{"):
        data = json.loads(raw)
        posts = data["posts"] if isinstance(data, dict) else data
    else:
        delim = "\t" if "\t" in raw.splitlines()[0] else ","
        posts = list(csv.DictReader(io.StringIO(raw), delimiter=delim))
    out = []
    for p in posts:
        p = {str(k).strip().lower(): v for k, v in p.items()}
        text = (p.get("text") or p.get("hook") or "").strip()
        row = {"text": text, "hook": text.splitlines()[0].strip() if text else "",
               "date": p.get("timestamp") or p.get("date") or "", "permalink": p.get("permalink", ""),
               "is_chain": str(p.get("is_chain", p.get("type", ""))).lower() in ("true", "1", "chain", "연결글")}
        for f in FIELDS:
            row[f] = num(p.get(f))
        if row["hook"] and row["views"]:
            out.append(row)
    return out


def per_k(a, b):
    return round(a * 1000 / b, 1) if a is not None and b else None


def hour_of(ts):
    """'2026-11-13T00:00:06+0000' 같은 시각을 내 컴퓨터 시간대의 '시'로."""
    s = str(ts).strip().replace("Z", "+00:00")
    s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo:
        d = d.astimezone()
    return d.hour if ("T" in s or " " in s) else None


def analyse(posts):
    formulas = load_formulas()
    med_views = statistics.median([p["views"] for p in posts])
    for p in posts:
        p["outlier"] = round(p["views"] / med_views, 2) if med_views else None
        spread = sum(p[f] or 0 for f in ("reposts", "quotes", "shares"))
        p["reply_k"] = per_k(p["replies"], p["views"])
        p["spread_k"] = per_k(spread, p["views"]) if any(p[f] is not None for f in ("reposts", "quotes", "shares")) else None
        p["like_k"] = per_k(p["likes"], p["views"])
        p["formula_id"], p["formula"] = classify(p["hook"], formulas)
        p["chars"] = len(re.sub(r"\s", "", p["text"]))
        p["hour"] = hour_of(p["date"]) if p["date"] else None
        p["hook_score"] = round(score_hook(p["hook"])[1], 1) if score_hook else None
    ranked = sorted(posts, key=lambda p: (-(p["outlier"] or 0), -(p["reply_k"] or 0)))
    k = min(5, max(1, len(ranked) // 3))
    top, bottom = ranked[:k], ranked[-k:]

    def mean(items, key):
        vals = [i[key] for i in items if i.get(key) is not None]
        return round(statistics.mean(vals), 1) if vals else None

    def group(key_fn):
        g = {}
        for p in posts:
            g.setdefault(key_fn(p), []).append(p["outlier"] or 0)
        return {k2: (round(statistics.mean(v), 2), len(v)) for k2, v in g.items() if k2 is not None}

    findings = []
    hs_t, hs_b = mean(top, "hook_score"), mean(bottom, "hook_score")
    if hs_t is not None and hs_b is not None and hs_t - hs_b >= 10:
        findings.append(f"첫 줄 차이가 크다: 위 {k}개 훅 점수 평균 {hs_t}, 아래 {k}개 {hs_b}. 훅부터 고친다.")
    rk_t, rk_b = mean(top, "reply_k"), mean(bottom, "reply_k")
    if rk_t is not None and rk_b is not None:
        findings.append(f"천 조회당 답글: 위 {rk_t} vs 아래 {rk_b}. 답글이 붙은 글이 더 멀리 갔는지 본다.")
    by_formula = group(lambda p: p["formula"])
    best = sorted(((f, m, n) for f, (m, n) in by_formula.items() if n >= 2 and f != "분류 안 됨"), key=lambda x: -x[1])
    if best:
        f, m, n = best[0]
        findings.append(f"가장 잘 된 공식: {f} (평균 {m}x, {n}개).")
        if len(best) > 1:
            f2, m2, n2 = best[-1]
            findings.append(f"가장 안 된 공식: {f2} (평균 {m2}x, {n2}개).")
    if "분류 안 됨" in by_formula:
        m, n = by_formula["분류 안 됨"]
        findings.append(f"공식에 안 맞는 첫 줄 {n}개, 평균 {m}x. 직접 읽어보고 새 공식인지, 훅이 없는 건지 가른다.")
    by_len = group(lambda p: "짧음(~150자)" if p["chars"] <= 150 else ("중간(~350자)" if p["chars"] <= 350 else "김(350자~)"))
    if len(by_len) > 1:
        findings.append("길이별 평균 배수: " + ", ".join(f"{k2} {m}x({n})" for k2, (m, n) in sorted(by_len.items())))
    by_chain = group(lambda p: "연결글" if p["is_chain"] else "단독")
    if len(by_chain) > 1:
        findings.append("형식별: " + ", ".join(f"{k2} {m}x({n})" for k2, (m, n) in by_chain.items()))
    return {"n": len(posts), "median_views": med_views, "top": top, "bottom": bottom,
            "findings": findings, "by_hour": group(lambda p: p["hour"]), "posts": ranked}


def render(a, out=sys.stdout):
    conf = "패턴을 말할 수 있다" if a["n"] >= 30 else ("방향 정도만" if a["n"] >= 12 else "표본이 작다. 결론 금지")
    print(f"\nAUDIT · 글 {a['n']}개 · 조회수 중앙값 {a['median_views']:,} · 신뢰도: {conf}", file=out)
    print("=" * 78, file=out)

    def line(p):
        hook = p["hook"] if len(p["hook"]) <= 30 else p["hook"][:29] + "…"
        rk = p["reply_k"] if p["reply_k"] is not None else "-"
        sk = p["spread_k"] if p["spread_k"] is not None else "-"
        return f"  {p['outlier']:>5.1f}x  {p['views']:>7,}회  답글 {rk:>5}/천  퍼감 {sk:>5}/천  [{p['formula']}] {hook}"

    print("\n위", file=out)
    for p in a["top"]:
        print(line(p), file=out)
    print("\n아래", file=out)
    for p in a["bottom"]:
        print(line(p), file=out)
    print("\n데이터가 말하는 것", file=out)
    for i, f in enumerate(a["findings"], 1):
        print(f"  {i}. {f}", file=out)
    if a["by_hour"]:
        hours = ", ".join(f"{h}시 {m}x({n})" for h, (m, n) in sorted(a["by_hour"].items()))
        print(f"\n  시간대(맨 마지막에 볼 것, 대부분 원인이 아니다): {hours}", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="내 쓰레드 글 성과를 돌아본다.")
    ap.add_argument("input", nargs="?", default="-")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    posts = read_posts(args.input)
    if not posts:
        print("읽을 글이 없다. text(또는 hook)와 views 열이 있는지 확인", file=sys.stderr)
        sys.exit(2)
    a = analyse(posts)
    if args.json:
        print(json.dumps(a, ensure_ascii=False, indent=2, default=str))
    else:
        render(a)


if __name__ == "__main__":
    main()
