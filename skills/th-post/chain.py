#!/usr/bin/env python3
"""
chain.py - 쓰레드에 붙여넣기 전에 단독 글이나 연결글을 검사한다.

연결글은 `---` 만 있는 줄로 나눈다. 글마다:
  - 글자 수 (한도 500자)
  - 주제 태그 개수 (글 하나에 하나만 붙는다)
  - 링크, 이모지, 빈 줄 없는 긴 덩어리
  - 1번 글의 첫 줄을 hookscore.py로 채점
  - "1/3" 같은 번호가 실제 개수와 맞는지

글자 수 세는 법:  기본은 눈에 보이는 글자(유니코드 문자) 수다. 일부 외부 도구
문서에 '이모지는 더 많이 센다'는 말이 있지만 Meta 공식 문서로는 확인하지 못했다.
그래서 --strict 를 주면 이모지 하나를 UTF-8 바이트 수(보통 4)로 세는 보수적인
계산도 같이 보여준다. 한도에 바짝 붙은 글은 strict 기준으로 맞추면 안전하다.

사용법
  python3 chain.py draft.txt
  python3 chain.py draft.txt --strict
  pbpaste | python3 chain.py -
  python3 chain.py draft.txt --json
"""

import argparse
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from hookscore import run as score_hook  # noqa: E402
except Exception:  # chain.py만 따로 복사한 경우
    score_hook = None

LIMIT = 500
NEAR = 20
MAX_PARTS = 10
SEP_RE = re.compile(r"^\s*-{3,}\s*$", re.M)
TAG_RE = re.compile(r"(?:^|\s)#[^\s#]+")
URL_RE = re.compile(r"https?://\S+|www\.\S+")
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
NUMBERING_RE = re.compile(r"(?:^|\s)\(?(\d{1,2})\s*/\s*(\d{1,2})\)?")


def count_chars(text, strict=False):
    text = unicodedata.normalize("NFC", text)
    n = len(text)
    if strict:
        for e in EMOJI_RE.findall(text):
            n += len(e.encode("utf-8")) - 1
    return n


def first_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def check_part(i, total, text, strict):
    issues = []
    n = count_chars(text)
    ns = count_chars(text, strict=True)
    limit_n = ns if strict else n
    if limit_n > LIMIT:
        issues.append(("FAIL", f"{limit_n - LIMIT}자 초과. 문장을 줄이거나 다음 글로 넘긴다"))
    elif limit_n > LIMIT - NEAR:
        issues.append(("WARN", f"한도까지 {LIMIT - limit_n}자. 수정하다 넘치기 쉽다"))
    tags = TAG_RE.findall(text)
    if len(tags) > 1:
        issues.append(("FAIL", f"주제 태그 {len(tags)}개. 쓰레드는 글 하나에 하나만 붙는다"))
    urls = URL_RE.findall(text)
    if urls and i == 1 and total > 1:
        issues.append(("WARN", "1번 글에 링크. 링크는 마지막 글이나 답글로 옮기는 편이 읽기 좋다"))
    if len(EMOJI_RE.findall(text)) > max(3, n // 100):
        issues.append(("WARN", f"이모지 {len(EMOJI_RE.findall(text))}개. 장식보다 문장부호처럼 쓴다"))
    blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    if any(count_chars(b) > 220 for b in blocks):
        issues.append(("WARN", "빈 줄 없이 220자 넘는 덩어리. 모바일에서 벽처럼 보인다"))
    m = NUMBERING_RE.search(first_line(text)) or NUMBERING_RE.search(text[-12:])
    if m and total > 1:
        a, b = int(m.group(1)), int(m.group(2))
        if a != i or b != total:
            issues.append(("WARN", f"번호 {a}/{b}가 실제 위치 {i}/{total}와 다르다"))
    return {"part": i, "chars": n, "chars_strict": ns, "tags": len(tags), "links": len(urls),
            "first_line": first_line(text), "issues": issues}


def run(raw, strict=False):
    parts = [p.strip() for p in SEP_RE.split(raw) if p.strip()]
    total = len(parts)
    rows = [check_part(i, total, p, strict) for i, p in enumerate(parts, 1)]
    general = []
    if total > MAX_PARTS:
        general.append(("WARN", f"연결글 {total}개. 대부분 3~6개에서 끝난다. 둘로 나눌 수 있는지 본다"))
    tags_total = sum(r["tags"] for r in rows)
    if total > 1 and tags_total > 1:
        general.append(("WARN", "여러 글에 태그를 붙였다. 1번 글에 하나만 두는 편이 깔끔하다"))
    hook = None
    if rows and score_hook:
        line = NUMBERING_RE.sub(" ", rows[0]["first_line"]).strip()
        _, overall, verdict, flags = score_hook(line)
        hook = {"line": line, "score": round(overall, 1), "verdict": verdict, "flags": flags}
        if overall < 50:
            general.append(("WARN", f"첫 줄 훅 {overall:.0f}점 {verdict}. /th-post 로 훅부터 다시"))
    fails = sum(1 for r in rows for lvl, _ in r["issues"] if lvl == "FAIL")
    status = "READY" if not fails else "FIX"
    return {"parts": rows, "total": total, "chars_total": sum(r["chars"] for r in rows),
            "general": general, "hook": hook, "status": status, "strict": strict}


def render(a, out=sys.stdout):
    kind = "단독 글" if a["total"] == 1 else f"연결글 {a['total']}개"
    print(f"\n{kind} · 총 {a['chars_total']}자" + (" · strict(이모지 바이트) 기준" if a["strict"] else ""), file=out)
    print("=" * 72, file=out)
    for r in a["parts"]:
        shown = r["chars_strict"] if a["strict"] else r["chars"]
        lvl = "FAIL" if any(l == "FAIL" for l, _ in r["issues"]) else ("WARN" if r["issues"] else "OK")
        line = r["first_line"] if len(r["first_line"]) <= 34 else r["first_line"][:33] + "…"
        print(f"  {r['part']}/{a['total']}  {shown:>3}/{LIMIT}  {lvl:<4}  {line}", file=out)
        for l, msg in r["issues"]:
            print(f"              - {msg}", file=out)
    if a["hook"]:
        h = a["hook"]
        print(f"\n  첫 줄 훅: {h['score']:.0f}점 {h['verdict']}", file=out)
        for f in h["flags"]:
            print(f"    감점: {f}", file=out)
    for l, msg in a["general"]:
        print(f"  {l}: {msg}", file=out)
    print(f"\n  상태: {a['status']}" + ("  (붙여넣어도 된다)" if a["status"] == "READY" else "  (FAIL부터 고친다)"), file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="쓰레드 글/연결글을 붙여넣기 전에 검사한다.")
    ap.add_argument("input", nargs="?", default="-")
    ap.add_argument("--strict", action="store_true", help="이모지를 UTF-8 바이트 수로 세는 보수적 계산")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    if not raw.strip():
        print("검사할 내용이 없다", file=sys.stderr)
        sys.exit(2)
    a = run(raw, strict=args.strict)
    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(a)
    sys.exit(0 if a["status"] == "READY" else 1)


if __name__ == "__main__":
    main()
