#!/usr/bin/env python3
"""
rank.py - 모아 온 쓰레드 글을 '그 계정 평소보다 몇 배 나왔나'로 순위 매기고,
첫 줄이 어떤 훅 공식인지 이름 붙여 스와이프 파일(따라 쓸 구조 모음)을 만든다.

이 스크립트가 바로잡는 것 하나: 조회수 자체는 증거가 아니다. 팔로워 50만 계정의
조회수 10만은 평범한 날이다. 팔로워 3천 계정의 조회수 10만은 뭔가를 찾은 것이고,
그 뭔가는 따라 할 수 있다. 그래서 그 계정의 최근 중앙값 대비 배수로 순위를 낸다.

쓰레드는 남의 글 조회수도 공개라서(글을 누르면 보인다) 이 방법이 그대로 먹힌다.
조회수가 없으면 좋아요로 대신 계산한다(덜 정확하다고 표시한다).

입력: 탭으로 나눈 파일. 첫 줄은 열 이름.
    account  followers  median  views  likes  replies  reposts  hook
    @someone 4200       3100    41000  820    96       40       서버비 40만 원을 날린 이유는...

  - median: 그 계정 최근 글 12개쯤의 조회수 가운데 값 (없으면 followers로 대신)
  - likes_median 열이 있으면 조회수 대신 좋아요 배수를 계산할 때 쓴다
  - hook: 글 첫 줄, 원문 그대로

사용법
  python3 rank.py captured.tsv
  python3 rank.py captured.tsv --out ~/.claude/threads/swipe.md
  python3 rank.py captured.tsv --json
"""

import argparse
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.join(HERE, "..", "th-post", "hooks.json")
sys.path.insert(0, os.path.join(HERE, "..", "th-post"))
try:
    from hookscore import run as score_hook  # noqa: E402
except Exception:
    score_hook = None


def load_formulas(path=HOOKS):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    by_id = {h["id"]: h for h in d["hooks"]}
    order = d.get("classify_order") or sorted(by_id)
    return [(i, by_id[i]["name"], re.compile(by_id[i]["match"], re.I)) for i in order if i in by_id]


def classify(hook, formulas):
    if not formulas:
        return None, "분류 안 됨"
    for fid, name, pat in formulas:
        if pat.search(hook):
            return fid, name
    return None, "분류 안 됨"


def num(v):
    """'4.1만', '12,300', '3.2K' 같은 표기를 숫자로."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    m = re.match(r"^([\d.]+)\s*(만|천|억|k|K|m|M)?", s)
    if not m:
        return None
    n = float(m.group(1))
    mult = {"만": 1e4, "천": 1e3, "억": 1e8, "k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6}.get(m.group(2), 1)
    return int(n * mult)


def read_rows(path):
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    lines = [l for l in raw.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        return []
    head = [c.strip().lower() for c in lines[0].split("\t")]
    rows = []
    for line in lines[1:]:
        cells = [c.strip() for c in line.split("\t")]
        cells += [""] * (len(head) - len(cells))
        r = dict(zip(head, cells))
        for k in ("followers", "median", "views", "likes", "replies", "reposts", "likes_median"):
            r[k] = num(r.get(k))
        if r.get("hook") and (r.get("views") or r.get("likes")):
            rows.append(r)
    return rows


def analyse(rows, formulas):
    for r in rows:
        if r.get("views") and (r.get("median") or r.get("followers")):
            base = r.get("median") or r.get("followers")
            r["outlier"], r["basis"] = round(r["views"] / base, 2), ("조회수/중앙값" if r.get("median") else "조회수/팔로워")
        elif r.get("likes") and r.get("likes_median"):
            r["outlier"], r["basis"] = round(r["likes"] / r["likes_median"], 2), "좋아요/좋아요 중앙값"
        else:
            r["outlier"], r["basis"] = None, "기준 없음"
        r["reply_rate"] = round(r["replies"] * 1000 / r["views"], 1) if r.get("replies") and r.get("views") else None
        r["formula_id"], r["formula"] = classify(r["hook"], formulas)
        r["chars"] = len(re.sub(r"\s", "", r["hook"]))
        if score_hook:
            _, overall, verdict, _ = score_hook(r["hook"])
            r["hook_score"], r["hook_verdict"] = round(overall, 1), verdict
        else:
            r["hook_score"], r["hook_verdict"] = None, None
    ranked = sorted(rows, key=lambda r: -(r["outlier"] or 0))
    third = max(1, len(ranked) // 3)
    top, bottom = ranked[:third], ranked[-third:]

    def med(items, key):
        vals = [i[key] for i in items if i.get(key) is not None]
        return round(statistics.median(vals), 1) if vals else None

    top_counts, bottom_counts = {}, {}
    for r in top:
        top_counts[r["formula"]] = top_counts.get(r["formula"], 0) + 1
    for r in bottom:
        bottom_counts[r["formula"]] = bottom_counts.get(r["formula"], 0) + 1
    bases = {r["basis"] for r in ranked}
    return {
        "n": len(ranked),
        "accounts": len({r.get("account", "") for r in ranked}),
        "basis": ", ".join(sorted(bases)),
        "posts": ranked,
        "top_formulas": sorted(top_counts.items(), key=lambda kv: -kv[1]),
        "bottom_formulas": bottom_counts,
        "top_hook_score": med(top, "hook_score"), "bottom_hook_score": med(bottom, "hook_score"),
        "top_chars": med(top, "chars"), "bottom_chars": med(bottom, "chars"),
        "top_reply_rate": med(top, "reply_rate"), "bottom_reply_rate": med(bottom, "reply_rate"),
        "unclassified": [r for r in ranked if r["formula"] == "분류 안 됨"],
    }


def confidence(n, accounts):
    if n >= 30 and accounts >= 5:
        return "주장할 만함"
    if n >= 15:
        return "방향 정도만"
    return "표본이 작다. 결론 내리지 말 것"


def render(a, out=sys.stdout):
    head = f"SWIPE · 글 {a['n']}개 · 계정 {a['accounts']}개 · 기준: {a['basis']} · 신뢰도: {confidence(a['n'], a['accounts'])}"
    print("\n" + head, file=out)
    print("=" * 78, file=out)
    print("\n배수 순위", file=out)
    for r in a["posts"]:
        mult = f"{r['outlier']:>5.1f}x" if r["outlier"] else "    ?"
        hs = f"{r['hook_score']:.0f}" if r["hook_score"] is not None else "-"
        fid = f"#{r['formula_id']}" if r["formula_id"] else "-"
        hook = r["hook"] if len(r["hook"]) <= 34 else r["hook"][:33] + "…"
        print(f"  {mult}  훅{hs:>3}  {fid:<4} {r.get('account', ''):<12} [{r['formula']}] {hook}", file=out)
    print("\n위 1/3에 많이 나온 공식", file=out)
    for name, c in a["top_formulas"]:
        bc = a["bottom_formulas"].get(name, 0)
        print(f"  {name:<12} 위 {c}개 / 아래 {bc}개", file=out)
    print("\n위 1/3 vs 아래 1/3", file=out)
    print(f"  훅 점수 중앙값   {a['top_hook_score']} vs {a['bottom_hook_score']}", file=out)
    print(f"  첫 줄 글자 수    {a['top_chars']} vs {a['bottom_chars']}", file=out)
    print(f"  천 조회당 답글   {a['top_reply_rate']} vs {a['bottom_reply_rate']}", file=out)
    print(f"\n분류 안 됨 ({len(a['unclassified'])}개) - 직접 읽어볼 것. 새 공식일 수 있다.", file=out)
    for r in a["unclassified"][:8]:
        print(f"  {r['outlier'] or '?'}x  {r['hook']}", file=out)
    print("", file=out)


def to_markdown(a):
    lines = [f"# 스와이프 파일", "", f"- 글 {a['n']}개, 계정 {a['accounts']}개, 기준 {a['basis']}",
             f"- 신뢰도: {confidence(a['n'], a['accounts'])}", "", "## 배수 순위", "",
             "| 배수 | 공식 | 계정 | 첫 줄 |", "|---|---|---|---|"]
    for r in a["posts"]:
        lines.append(f"| {r['outlier'] or '?'}x | {r['formula']} | {r.get('account', '')} | {r['hook']} |")
    lines += ["", "## 위 1/3에 많이 나온 공식", ""]
    lines += [f"- {n}: 위 {c}개 / 아래 {a['bottom_formulas'].get(n, 0)}개" for n, c in a["top_formulas"]]
    lines += ["", "## 내 버전 (th-viral이 채운다)", "", "- ", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="모아 온 쓰레드 글을 계정 평소 대비 배수로 순위 매긴다.")
    ap.add_argument("input", nargs="?", default="-")
    ap.add_argument("--out", help="스와이프 파일(markdown) 저장 위치")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = read_rows(args.input)
    if not rows:
        print("읽을 줄이 없다. 첫 줄에 열 이름(account, median, views, hook ...)이 있는지 확인", file=sys.stderr)
        sys.exit(2)
    a = analyse(rows, load_formulas())
    if args.json:
        print(json.dumps(a, ensure_ascii=False, indent=2))
    else:
        render(a)
    if args.out:
        path = os.path.expanduser(args.out)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(to_markdown(a))
        print(f"저장: {path}")


if __name__ == "__main__":
    main()
