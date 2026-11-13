#!/usr/bin/env python3
"""
detect.py - 초안이 얼마나 기계가 쓴 것처럼 보이는지 다섯 가지로 채점한다.

무엇인가:  공개된 AI 탐지기들이 보는 신호를 본뜬 다섯 가지 휴리스틱이다.
문장 길이 변화, 구체성, 상투어, 문장부호 흔적, 말투. 전부 내 컴퓨터에서
글자만 보고 계산한다. 아무것도 업로드하지 않는다.

무엇이 아닌가:  GPTZero, 카피킬러 같은 탐지 서비스가 아니고, 그 결과를 약속하지
못한다. 같은 신호를 보기 때문에 여기서 고친 것이 그쪽 점수도 움직이는 경향이
있을 뿐이다. "탐지 안 된다"고 말하면 안 된다.

한국어 기준으로 만들었고 영어 글도 읽는다. 원본 instagram-agent-skill의
detect.py(영어 전용)를 바탕으로 한국어 어절·어미를 읽도록 다시 썼다.

각 기준은 '사람 같음' 점수 0~100. 높을수록 좋다.

사용법
  python3 detect.py draft.txt
  python3 detect.py before.txt after.txt     # 두 초안 비교
  pbpaste | python3 detect.py -
  python3 detect.py draft.txt --json
"""

import argparse
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LEX = os.path.join(HERE, "slop.json")

# 문장 끝: . ! ? 。 뒤에 공백·줄끝이 올 때만. "3.5배", "github.com" 의 점에서 자르지 않는다.
SENT_RE = re.compile(r"[^\n]+?(?:[.!?。]+(?=\s|$)|$)", re.M)
URL_RE = re.compile(r"https?://\S+|www\.\S+")
CODE_RE = re.compile(r"^[ \t]*(```|~~~)[^\n]*\n.*?^[ \t]*\1[^\n]*$|`[^`\n]+`", re.M | re.S)
TOKEN_RE = re.compile(r"\S+")
NUMBERS = re.compile(r"\d[\d,.]*\s*(%|원|만|억|배|시간|분|초|일|주|개월|년|명|개|번)?")
PROPER = re.compile(r"\b[A-Z][A-Za-z0-9]+\b|\b[A-Z]{2,}\b")
QUOTED = re.compile(r"[\"“'‘][^\"”'’]{2,40}[\"”'’]")
# 조사 뒤가 끊겨야 1인칭이다. '제도', '나가서', '전에'는 1인칭이 아니다.
FIRST_PERSON = re.compile(r"(^|\s)(나|내가|내|저는|제가|제|저|우리|저희|난|전)(는|가|의|도|한테)?(?=\s|$|[.,!?])"
                          r"|\b(i|my|me|we|our)\b", re.I)
SECOND_PERSON = re.compile(r"(당신|너|니가|네가|여러분|\byou\b|\byour\b)", re.I)
CASUAL_END = re.compile(r"(요|죠|네|지|음|함|임|듯|ㅋ+|ㅎ+|다|어|야|까|걸|데)[.!?~]*$")
FORMAL_END = re.compile(r"(니다|습니다|십시오)[.!?]*$")


def clamp(n):
    return max(0.0, min(100.0, n))


def scale(value, human, machine):
    if human == machine:
        return 50.0
    return clamp((value - machine) / (human - machine) * 100)


def load():
    return json.load(open(LEX, encoding="utf-8"))


def sentences(text):
    return [s.strip() for s in SENT_RE.findall(text) if len(s.strip()) >= 6]


def tokens(text):
    return TOKEN_RE.findall(text)


def check_burstiness(text):
    """사람은 문장 길이를 크게 흔든다. 모델은 고르게 쓴다."""
    lens = [len(re.sub(r"\s", "", s)) for s in sentences(text)]
    if len(lens) < 4:
        return 50.0, "문장이 적어 판단 보류"
    mean = statistics.mean(lens)
    cv = statistics.pstdev(lens) / mean if mean else 0
    return scale(cv, human=0.65, machine=0.20), f"문장 길이 변화 {cv:.2f}, 문장 {len(lens)}개 (0.5 이상이 좋다)"


def check_specificity(text):
    """숫자, 이름, 인용. AI 글은 추상적이다."""
    t = tokens(text)
    if len(t) < 15:
        return 50.0, "글이 짧아 판단 보류"
    hits = len(NUMBERS.findall(text)) + len(set(PROPER.findall(text))) + len(QUOTED.findall(text))
    density = hits * 100 / len(t)
    return scale(density, human=8.0, machine=0.5), f"100어절당 구체 표지 {density:.1f}개 (5 이상이 좋다)"


def slop_hits(text, lex):
    hits = []
    for item in lex["phrases"] + lex["words"]:
        f = item["find"]
        pat = (re.compile(r"(?<![A-Za-z])" + re.escape(f) + r"(?![A-Za-z])", re.I)
               if re.search(r"[A-Za-z]", f) else re.compile(re.escape(f)))
        n = len(pat.findall(text))
        if n:
            hits.append((f, n))
    return hits


def check_slop(text, lex):
    """상투어 밀도."""
    t = tokens(text)
    if not t:
        return 50.0, "비어 있음"
    hits = slop_hits(text, lex)
    n = sum(c for _, c in hits)
    per100 = n * 100 / len(t)
    words = ", ".join(f for f, _ in hits[:4])
    return scale(per100, human=0.0, machine=4.0), f"100어절당 상투어 {per100:.1f}개" + (f": {words}" if words else "")


def check_fingerprint(text, lex):
    """보이지 않는 문자, 긴 줄표, 둥근 따옴표. 키보드로는 잘 안 나오는 것들."""
    n_chars = max(1, len(text))
    inv = sum(text.count(chr(int(i["cp"][2:], 16))) for i in lex["invisible"])
    dash = text.count("—")
    curly = sum(text.count(c) for c in "“”‘’")
    per1k = (inv * 3 + dash * 2 + curly) * 1000 / n_chars
    detail = f"보이지 않는 문자 {inv}, 긴 줄표 {dash}, 둥근 따옴표 {curly}"
    return scale(per1k, human=0.0, machine=6.0), detail


def check_voice(text, lex):
    """말투: 끝맺음이 섞이는지, 사람이 말하는지, AI식 문장 구조가 있는지."""
    sents = sentences(text)
    if len(sents) < 3:
        base = 60.0
        mix = "문장이 적음"
    else:
        formal = sum(1 for s in sents if FORMAL_END.search(s))
        casual = sum(1 for s in sents if CASUAL_END.search(s) and not FORMAL_END.search(s))
        share_formal = formal / len(sents)
        # '~니다'로만 끝나는 글은 보도자료처럼 읽힌다. 섞이면 사람 같다.
        base = 100.0 if 0 < share_formal < 0.8 or casual >= 2 else (55.0 if share_formal >= 0.8 else 75.0)
        mix = f"'~니다' 끝맺음 {formal}/{len(sents)}문장"
    person = bool(FIRST_PERSON.search(text) or SECOND_PERSON.search(text))
    if not person:
        base -= 15
    structs = sum(len(re.findall(s["regex"], text)) for s in lex["structures"])
    base -= structs * 12
    return clamp(base), f"{mix}, 사람 {'있음' if person else '없음'}, AI식 구조 {structs}개"


CHECKS = ["BURSTINESS", "SPECIFICITY", "SLOP", "FINGERPRINT", "VOICE"]
NAMES = {"BURSTINESS": "문장 리듬", "SPECIFICITY": "구체성", "SLOP": "상투어", "FINGERPRINT": "흔적 문자", "VOICE": "말투"}


def run(text, lex=None):
    lex = lex or load()
    # 코드와 링크는 사람이 쓴 문장이 아니라서 빼고 잰다.
    text = URL_RE.sub(" ", CODE_RE.sub(" ", text.lstrip("\ufeff")))
    res = {
        "BURSTINESS": check_burstiness(text),
        "SPECIFICITY": check_specificity(text),
        "SLOP": check_slop(text, lex),
        "FINGERPRINT": check_fingerprint(text, lex),
        "VOICE": check_voice(text, lex),
    }
    scores = [res[c][0] for c in CHECKS]
    overall = statistics.mean(scores) * 0.6 + min(scores) * 0.4
    verdict = "PASS" if overall >= 70 and min(scores) >= 55 else ("REVIEW" if overall >= 50 else "FAIL")
    return res, overall, verdict


def bar(score, width=24):
    filled = round(score / 100 * width)
    return "#" * filled + "." * (width - filled)


def render(name, res, overall, verdict, out=sys.stdout):
    print(f"\nDETECT · {name}", file=out)
    print("=" * 64, file=out)
    for c in CHECKS:
        s, d = res[c]
        print(f"  {NAMES[c]:<6} {bar(s)} {s:5.1f}", file=out)
        print(f"  {'':<6} {d}", file=out)
    print("-" * 64, file=out)
    print(f"  {'사람다움':<6} {bar(overall)} {overall:5.1f}   {verdict}", file=out)
    if verdict != "PASS":
        weakest = min(CHECKS, key=lambda c: res[c][0])
        print(f"\n  가장 약한 기준: {NAMES[weakest]}. 그것부터 고친다.", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="초안의 AI 티를 다섯 기준으로 채점한다.")
    ap.add_argument("inputs", nargs="*", default=["-"])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    lex = load()
    results = []
    if len(args.inputs) > 2:
        print("한 번에 두 개까지만 비교한다. 앞의 두 개만 본다.", file=sys.stderr)
    for path in args.inputs[:2]:
        try:
            text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8-sig").read()
        except OSError as e:
            print(f"파일을 못 읽었다: {e}", file=sys.stderr)
            sys.exit(2)
        res, overall, verdict = run(text, lex)
        results.append((path, res, overall, verdict))
    if args.json:
        print(json.dumps([{"file": p, "score": round(o, 1), "verdict": v,
                           "checks": {k: {"score": round(r[k][0], 1), "detail": r[k][1]} for k in CHECKS}}
                          for p, r, o, v in results], ensure_ascii=False, indent=2))
        return
    for p, r, o, v in results:
        render(p, r, o, v)
    if len(results) == 2:
        delta = results[1][2] - results[0][2]
        print(f"  변화: {results[0][2]:.1f} -> {results[1][2]:.1f} ({delta:+.1f})\n")
    sys.exit(0 if results[-1][3] == "PASS" else 1)


if __name__ == "__main__":
    main()
