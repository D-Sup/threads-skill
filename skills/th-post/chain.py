#!/usr/bin/env python3
"""
chain.py - 쓰레드에 붙여넣기 전에 단독 글이나 연결글을 검사한다.

연결글은 `---` 만 있는 줄로 나눈다. 코드 블록(```) 안의 `---` 는 글 내용으로 본다. 글마다:
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
# 주제 태그. "#1", "#5" 같은 숫자만 있는 건 순번이라 뺀다.
TAG_RE = re.compile(r"(?:^|(?<=\s))#(?!\d+(?:\s|$|[.,!?)]))[^\s#]+")
# 링크. http(s)·www 말고 "github.com/..." 처럼 맨 도메인도 쓰레드가 링크로 바꾼다.
URL_RE = re.compile(r"https?://\S+|www\.\S+|(?<![\w@.])[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*"
                    r"\.(?:com|net|org|io|dev|app|ai|co|kr|me|so|gg|xyz|page|site|link|ly|sh)(?:/\S*)?(?![\w])")
# 이모지: 그림 문자, 국기, 기호 문자, 별·화살표 기호
EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF]")
FENCE_BODY_RE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$", re.M | re.S)
# 연결글 번호는 줄 맨 앞("1/4 ...")이나 줄 맨 끝("... (1/4)")에 따로 있는 것만 본다.
# 문장 가운데 날짜("11/9에 나온")나 앞 숫자가 뒤보다 큰 것("11/9")은 번호가 아니다.
# 1/4, (1/4), [1/4] 와 뒤에 붙는 마침표·쌍점까지 번호로 본다.
NUM_HEAD_RE = re.compile(r"^\s*[(\[]?(\d{1,2})\s*/\s*(\d{1,2})[)\]]?[.:]?(?=\s|$)\s*")
NUM_TAIL_RE = re.compile(r"(?:^|\s+)[(\[]?(\d{1,2})\s*/\s*(\d{1,2})[)\]]?[.]?\s*$")
NEAR_POS = 2  # 진짜 번호는 앞 숫자가 실제 위치에서 둘 넘게 벗어나지 않는다
MAX_NUMBERED = 30


def split_parts(raw):
    """`---` 줄로 나누되, 코드 블록(``` 또는 ~~~) 안의 줄은 나누지 않는다.
    돌려주는 값: (글 목록, 코드 블록이 안 닫혔는지)."""
    def split(fence_aware):
        parts, cur, fence = [], [], None
        for line in raw.splitlines():
            mark = line.lstrip()[:3]
            if fence_aware and mark in ("```", "~~~"):
                if fence is None:
                    fence = mark
                elif mark == fence:
                    fence = None
            if fence is None and SEP_RE.match(line):
                parts.append("\n".join(cur))
                cur = []
            else:
                cur.append(line)
        parts.append("\n".join(cur))
        return [p.strip() for p in parts if p.strip()], fence is not None

    parts, unclosed = split(True)
    if unclosed:
        # 닫는 표시를 빠뜨린 것이다. 뒤 글이 통째로 붙어 버리지 않게 코드 블록을 무시하고 나눈다.
        parts, _ = split(False)
    return parts, unclosed


def only_tags_links(line):
    """태그나 링크만 있는 줄 (번호가 그 앞줄 끝에 붙는 경우가 많다)."""
    rest = URL_RE.sub(" ", TAG_RE.sub(" ", line))
    return line.strip() != "" and rest.strip() == ""


def without_code(text):
    """코드 블록 안은 태그·링크·이모지 검사에서 뺀다(#include, 예시 주소 등)."""
    return FENCE_BODY_RE.sub("", text)


def unsplit_chain(text):
    """--- 없이 '1/3 ... 2/3 ...' 처럼 번호만 붙여 한 덩어리로 쓴 연결글."""
    heads = []
    for line in text.splitlines():
        m = NUM_HEAD_RE.match(line)
        if m:
            heads.append((int(m.group(1)), int(m.group(2))))
    nums = [a for a, _ in heads]
    return len(heads) >= 2 and len({b for _, b in heads}) == 1 and nums == sorted(set(nums)) and nums[0] == 1


def candidates(text):
    """번호처럼 생긴 것: {'head': (a, b), 'tail': (a, b)} 중 있는 것만.
    head는 첫 줄 맨 앞, tail은 마지막 줄 맨 끝. 날짜와 모양이 같을 수 있어서
    이것만으로는 번호라고 정하지 않는다(numbered_chain 참고)."""
    lines = [l for l in text.splitlines() if l.strip()]
    out = {}
    if not lines:
        return out
    body = [l for l in lines if not only_tags_links(l)] or lines
    for pos, m in (("head", NUM_HEAD_RE.match(lines[0])), ("tail", NUM_TAIL_RE.search(body[-1]))):
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 1 <= a <= b <= MAX_NUMBERED and b >= 2:
                out[pos] = (a, b)
    return out


def numbered_chain(cands, total):
    """연결글이 실제로 번호를 쓰는지, 쓴다면 글마다 어느 번호를 볼지 정한다.

    "3/5 회의에서" 같은 날짜는 번호와 모양이 똑같다. 그래서 한 글만 보고 정하지 않고
    연결글 전체를 본다:
      - 번호처럼 생긴 게 한 글에만 있으면 번호로 보지 않는다. 날짜와 구분할 수 없고,
        번호였더라도 한 글만 보고는 어긋났다고 말할 근거가 없다.
      - 두 글 이상에 있으면, 뒤 숫자가 모두 같거나(1/3, 3/3, 2/3: 순서가 섞인 번호)
        글 순서대로 앞 숫자가 커질 때만 번호다(3/5, 3/7은 둘 다 아니라서 날짜다).
      - 앞 숫자가 실제 위치에서 둘 넘게 벗어나면 날짜다(5/12, 6/12).
      - 다른 글들이 한 자리(맨 앞 또는 맨 끝)만 쓰면 그 자리만 본다.
    돌려주는 값: {글 번호: (a, b)}. 번호를 안 쓰면 빈 dict."""
    if total < 2:
        return {}

    def pick(i, c, others_pos):
        if (i, total) in c.values():
            return (i, total)
        if len(others_pos) == 1:
            pos = next(iter(others_pos))
            if pos in c:
                return c[pos]
        return c.get("head") or c.get("tail")

    has = {i: c for i, c in enumerate(cands, 1) if c}
    if not has:
        return {}
    chosen = {}
    for i, c in has.items():
        others = {pos for j, cj in has.items() if j != i for pos in cj}
        v = pick(i, c, others)
        if v:
            chosen[i] = v
    if len(chosen) < 2:
        # 한 글에만 있으면 날짜인지 번호인지 알 수 없다. 위치가 맞으면 경고할 것도 없고,
        # 날짜일 수도 있으니 번호로 보지 않는다(첫 줄 채점에서도 지우지 않는다).
        return {}
    if any(abs(a - i) > NEAR_POS for i, (a, _) in chosen.items()):
        # 5/12, 6/12처럼 앞 숫자가 위치와 동떨어지면 날짜다
        return {}
    nums = [chosen[i][0] for i in sorted(chosen)]
    dens = {chosen[i][1] for i in chosen}
    increasing = all(a < b for a, b in zip(nums, nums[1:]))
    if not increasing and len(dens) > 1:
        return {}
    return chosen


def strip_numbering(line, num):
    """첫 줄에서 연결글 번호 num=(a, b)만 지운다. 날짜는 남긴다."""
    if not num:
        return line.strip()
    for rx in (NUM_HEAD_RE, NUM_TAIL_RE):
        m = rx.search(line)
        if m and (int(m.group(1)), int(m.group(2))) == num:
            line = line[:m.start()] + " " + line[m.end():]
    return line.strip()


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


def check_part(i, total, text, strict, num=None):
    issues = []
    n = count_chars(text)
    ns = count_chars(text, strict=True)
    limit_n = ns if strict else n
    if limit_n > LIMIT:
        issues.append(("FAIL", f"{limit_n - LIMIT}자 초과. 문장을 줄이거나 다음 글로 넘긴다"))
    elif limit_n > LIMIT - NEAR:
        issues.append(("WARN", f"한도까지 {LIMIT - limit_n}자. 수정하다 넘치기 쉽다"))
    plain = without_code(text)
    tags = TAG_RE.findall(plain)
    if len(tags) > 1:
        issues.append(("FAIL", f"주제 태그 {len(tags)}개. 쓰레드는 글 하나에 하나만 붙는다"))
    urls = URL_RE.findall(plain)
    if urls and i == 1:
        where = "마지막 글이나 첫 답글" if total > 1 else "첫 답글"
        issues.append(("WARN", f"1번 글에 링크. 읽기 전에 나간다. {where}로 옮긴다"))
    emojis = len(EMOJI_RE.findall(plain))
    if emojis > max(3, n // 100):
        issues.append(("WARN", f"이모지 {emojis}개. 장식보다 문장부호처럼 쓴다"))
    if total == 1 and unsplit_chain(text):
        issues.append(("WARN", "번호(1/N, 2/N)는 있는데 --- 줄이 없다. 연결글이면 글 사이에 --- 줄을 넣는다"))
    blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    if any(count_chars(b) > 220 for b in blocks):
        issues.append(("WARN", "빈 줄 없이 220자 넘는 덩어리. 모바일에서 벽처럼 보인다"))
    if num:
        a, b = num
        if a != i or b != total:
            issues.append(("WARN", f"번호 {a}/{b}가 실제 위치 {i}/{total}와 다르다"))
    return {"part": i, "chars": n, "chars_strict": ns, "tags": len(tags), "links": len(urls),
            "first_line": first_line(text), "issues": issues}


def run(raw, strict=False):
    parts, unclosed = split_parts(raw)
    total = len(parts)
    nums = numbered_chain([candidates(p) for p in parts], total)
    rows = [check_part(i, total, p, strict, nums.get(i)) for i, p in enumerate(parts, 1)]
    general = []
    if unclosed:
        general.append(("WARN", "코드 블록(``` 또는 ~~~)이 닫히지 않았다. 닫는 줄을 넣는다"))
    if total > MAX_PARTS:
        general.append(("WARN", f"연결글 {total}개. 대부분 3~6개에서 끝난다. 둘로 나눌 수 있는지 본다"))
    tags_total = sum(r["tags"] for r in rows)
    if total > 1 and tags_total > 1:
        general.append(("WARN", "여러 글에 태그를 붙였다. 1번 글에 하나만 두는 편이 깔끔하다"))
    hook = None
    if rows and score_hook:
        line = strip_numbering(rows[0]["first_line"], nums.get(1))
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
    try:
        raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8-sig").read()
    except OSError as e:
        print(f"파일을 못 읽었다: {e}", file=sys.stderr)
        sys.exit(2)
    raw = raw.lstrip("\ufeff")
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
