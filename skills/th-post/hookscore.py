#!/usr/bin/env python3
"""
hookscore.py - 쓰레드 글 첫 줄(훅)을 다섯 가지 기준으로 채점하고, 여러 개를 순위로 비교한다.

무엇인가:  글자만 보고 내 컴퓨터에서 계산하는 다섯 가지 휴리스틱이다. 주의를
붙잡는 첫 줄이 공통으로 가진 성질을 잰다. 한눈에 읽히는 길이, 숫자나 이름 같은
구체적인 것, 걸려 있는 무언가(손해, 반전), 핵심이 앞에 있는지, 읽는 사람을
겨냥하는지.

무엇이 아닌가:  조회수 예측기가 아니다. 인사, 서론, 아무 내용 없는 첫 줄은
잘 잡아내지만, 괜찮은 두 문장 중 어느 쪽이 더 퍼질지는 알 수 없다. 그건 계정,
타이밍, 주제, 알고리즘이 정한다. 실제 성과(/th-audit)를 이 점수보다 믿는다.

한국어와 영어를 둘 다 읽는다. 원본 instagram-agent-skill의 hookscore.py(영어
전용)를 바탕으로 한국어 어절·어미·숫자 표현을 처리하도록 다시 썼다.

각 기준은 0~100점. 높을수록 좋다.

사용법
  python3 hookscore.py hooks.txt              # 한 줄에 하나씩, 순위
  python3 hookscore.py --hook "서버비 40만 원을 날린 이유는 캐시 한 줄이었다."
  pbpaste | python3 hookscore.py -
  python3 hookscore.py hooks.txt --json
"""

import argparse
import json
import re
import statistics
import sys

HANGUL_RE = re.compile(r"[가-힣]")
TOKEN_RE = re.compile(r"\S+")
LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")
HASHTAG_RE = re.compile(r"(?:^|(?<=\s))#(?!\d+(?:\s|$|[.,!?)]))[^\s#]+")  # "#1" 같은 순번은 태그 아님
EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF]")

# 숫자: 아라비아 숫자 + 단위, 한국어 수 표현
NUMBER_RE = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*(?:%|퍼센트|프로|만\s*원|억|원|만|천|배|x|X|시간|분|초|일|주|개월|달|년|명|개|번|줄|가지|단계|k|K)?"
)
KOREAN_NUMBER_WORDS = [
    "두 번", "세 번", "네 번", "다섯", "여섯", "일곱", "여덟", "아홉", "열 번",
    "스무", "서른", "마흔", "쉰", "백만", "천만", "수백", "수천", "수만", "절반",
    "두 배", "세 배", "열 배", "하루", "이틀", "사흘", "일주일", "한 달", "두 달",
]
SPOKEN_NUMBERS_EN = {
    "zero", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "twenty", "thirty", "hundred", "thousand", "million", "billion",
    "dozen", "half", "twice", "triple", "percent", "dollars", "grand",
}

# 긴장·손해·반전 표지. 하나도 없으면 그냥 사실 진술이다.
STAKES_KO = [
    "안 ", "못 ", "없", "실수", "망했", "망한", "손해", "날렸", "날린", "잃", "버렸",
    "그만", "절대", "하지 마", "틀렸", "틀린", "오해", "착각", "아무도", "누구도",
    "대신", "근데", "하지만", "그런데", "오히려", "사실은", "진짜", "끝났", "바뀌",
    "바뀐", "바꿨", "무료", "공짜", "비싼", "돈", "위험", "주의", "경고", "후회",
    "삭제", "차단", "금지", "몰랐", "모르", "숨겨", "비밀", "처음", "직접", "결국",
    "아직도", "벌써", "이제", "멈췄", "포기", "실패", "터졌", "빠졌", "줄었", "늘었",
    "반대", "아니라", "아닌", "왜 ", "?", "는데,", "었는데", "았는데", "했는데", "그때", "갑자기",
]
STAKES_EN = {
    "stop", "never", "wrong", "mistake", "lost", "lose", "cost", "broke", "failed",
    "nobody", "no", "not", "don't", "dont", "can't", "won't", "quit", "fired",
    "deleted", "killed", "replaced", "free", "paid", "saved", "worst", "hate",
    "wasted", "secret", "hidden", "truth", "but", "instead", "until", "only",
    "without", "vs", "actually", "still", "already", "before", "first",
}

# 첫 순간을 아무 말 없이 쓰는 시작
WEAK_OPENERS_KO = [
    "안녕하세요", "안녕", "여러분", "오늘은", "오늘 ", "혹시", "음 ", "음,", "자 ", "자,",
    "일단", "요즘", "다들", "제가 ", "저는 ", "이번에는", "이번에", "그래서", "그냥",
    "사실 저", "많은 분들", "많은 사람들", "우리는", "최근에", "드디어",
]
WEAK_OPENERS_EN = [
    "so", "ok", "okay", "hey", "hi", "hello", "guys", "welcome", "today", "basically",
    "honestly", "just", "i wanted", "i want", "in this", "in today", "this is",
]

DEALBREAKERS = [
    (re.compile(r"^\s*(안녕하세요|안녕|여러분 안녕|반갑습니다|hey |hi |hello )", re.I),
     "인사로 시작. 피드에 인사받으러 온 사람은 없다."),
    (re.compile(r"오늘은?\s*.{0,20}(에 대해|얘기|이야기|소개|알아보|공유해 ?보)|(알아보겠|알아볼게|소개해 ?드리|소개합니다)"),
     "준비 문장('오늘은 ~에 대해'). 지우고 핵심부터 쓴다."),
    (re.compile(r"(끝까지|마지막까지)\s*(읽|봐|보세요|봐주)|스크롤\s*(멈|내리지)|stop scrolling", re.I),
     "'끝까지 읽어주세요' 류. 주의를 달라고 하는 건 주의를 못 얻었다는 뜻이다."),
    (HASHTAG_RE,
     "첫 줄에 주제 태그. 태그는 글 끝이나 주제 칸에 하나만."),
    (re.compile(r"(충격|경악|소름|레전드|역대급|미쳤)"),
     "낚시성 표현. 한 번은 먹혀도 계정 신뢰를 깎는다."),
]


def clamp(n):
    return max(0.0, min(100.0, n))


def is_korean(text):
    letters = len(HANGUL_RE.findall(text)) + len(LATIN_WORD_RE.findall(text))
    return letters and len(HANGUL_RE.findall(text)) >= len(LATIN_WORD_RE.findall(text))


def tokens(text):
    return TOKEN_RE.findall(text.strip())


def visible_len(text):
    return len(re.sub(r"\s+", "", text))


def number_hits(text):
    hits = [m.group(0).strip() for m in NUMBER_RE.finditer(text) if m.group(0).strip()]
    hits += [w for w in KOREAN_NUMBER_WORDS if w in text]
    low = [w.lower() for w in LATIN_WORD_RE.findall(text)]
    hits += [w for w in low if w in SPOKEN_NUMBERS_EN]
    return hits


def proper_hits(text):
    """이름·제품명: 대문자로 시작하는 영어 단어, 따옴표 안 고유명, 영문 약어."""
    words = LATIN_WORD_RE.findall(text)
    first = words[0] if words and text.strip().startswith(words[0]) else None
    caps = {w for w in words if (w[0].isupper() and len(w) > 1 and w != first) or (w.isupper() and len(w) >= 2)}
    return sorted(caps)


def stakes_hits(text):
    low = text.lower() + " "
    hits = [s.strip() for s in STAKES_KO if s in low]
    hits += [w for w in (x.lower().strip("'’") for x in LATIN_WORD_RE.findall(text)) if w in STAKES_EN]
    if re.search(r"\d[\d,]*\s*(만\s*)?원|\$\s?\d", text):
        hits.append("금액")
    return sorted(set(h for h in hits if h))


def check_length(text):
    """피드에서 한 번에 읽혀야 한다. 한국어는 글자 수, 영어는 단어 수로 본다."""
    n_chars = visible_len(text)
    n_tok = len(tokens(text))
    if is_korean(text):
        if 12 <= n_chars <= 40:
            score = 100.0
        elif n_chars < 12:
            score = clamp(100 - (12 - n_chars) * 7)
        else:
            score = clamp(100 - (n_chars - 40) * 3.5)
        return score, f"{n_chars}자(공백 제외), {n_tok}어절 (좋은 범위 12~40자)"
    n = len(LATIN_WORD_RE.findall(text))
    if 5 <= n <= 14:
        score = 100.0
    elif n < 5:
        score = clamp(100 - (5 - n) * 20)
    else:
        score = clamp(100 - (n - 14) * 9)
    return score, f"{n} words (want 5-14)"


def check_specificity(text):
    """막연한 말 세 개보다 구체적인 것 하나."""
    nums = number_hits(text)
    propers = proper_hits(text)
    quoted = re.findall(r"[\"“'‘][^\"”'’]{2,40}[\"”'’]", text)
    hits = len(nums) + len(propers) + len(quoted)
    score = 15.0 if hits == 0 else clamp(45 + hits * 30)
    found = ", ".join((nums[:2] + propers[:2] + quoted[:1]))
    return score, (f"구체적인 표지 {hits}개" + (f": {found}" if found else " - 숫자도 이름도 없다"))


def check_stakes(text):
    """손해, 반전, 부정. 읽는 사람이 잃을 수 있는 것."""
    markers = stakes_hits(text)
    n = len(markers)
    score = {0: 20.0, 1: 70.0}.get(n, 100.0)
    detail = f"긴장 표지 {n}개" + (f": {', '.join(markers[:4])}" if markers else " - 걸려 있는 게 없다")
    return score, detail


def check_frontload(text):
    """흥미로운 말이 아홉 번째 어절에 있으면 늦다."""
    toks = tokens(text)
    if not toks:
        return 0.0, "비어 있음"
    stripped = text.strip()
    low = stripped.lower()
    penalty, hit = 0, None
    for weak in WEAK_OPENERS_KO:
        if stripped.startswith(weak):
            penalty, hit = 30, weak.strip()
            break
    if not hit:
        for weak in WEAK_OPENERS_EN:
            if low.startswith(weak + " ") or low == weak:
                penalty, hit = 30, weak
                break
    payload = None
    for i, tok in enumerate(toks):
        if number_hits(tok) or proper_hits(" x " + tok) or stakes_hits(tok + " ") or re.match(r"[\"“'‘]", tok):
            payload = i
            break
    if payload is None:
        base, where = 30.0, "핵심 단어가 없다"
    elif payload <= 2:
        base, where = 100.0, f"핵심이 {payload + 1}번째 어절"
    elif payload <= 5:
        base, where = 70.0, f"핵심이 {payload + 1}번째 어절, 더 앞으로"
    else:
        base, where = 40.0, f"핵심이 {payload + 1}번째 어절, 너무 늦다"
    return clamp(base - penalty), where + (f"; 약한 시작 \"{hit}\"" if hit else "")


def check_address(text):
    """한 사람에게 말하는가, 허공에 말하는가."""
    if re.search(r"(당신|너는|너의|네가|니가|여러분|\byou\b|\byour\b)", text, re.I):
        return 100.0, "읽는 사람을 부른다"
    if re.search(r"(하세요|마세요|해보세요|해 ?보세요|하지 ?마|해라|하자|해봐|쓰세요|가져가세요|드세요|보세요)", text):
        return 90.0, "권유·명령형 (읽는 사람에게 할 일을 준다)"
    if re.search(r"(라면|이라면|다면|하는 분|하는 사람|중이라면|중인 분)", text):
        return 90.0, "상황으로 읽는 사람을 지목한다"
    if re.search(r"(요|죠|네요|거든요|잖아요)[.!?…]*\s*$", text.strip()):
        return 80.0, "말하듯 건네는 어미(~요, ~죠)"
    if re.search(r"(^|\s)(나|내가|내|저는|제가|제|저|우리|저희)(\s|$|는|가|의|도)|\b(i|my|we|our)\b", text, re.I):
        return 70.0, "1인칭, 읽는 사람은 안 부름"
    # 한국어는 주어를 자주 뺀다. '~했다, ~써보니'는 숨은 1인칭 경험담이다.
    if re.search(r"(었다|았다|였다|했다|봤다|해보니|써보니|보니까|더라|었어|았어|했음|봤음)", text):
        return 70.0, "경험담 어미(숨은 1인칭), 읽는 사람은 안 부름"
    return 35.0, "3인칭, 아무도 부르지 않는다"


CHECKS = ["LENGTH", "SPECIFICITY", "STAKES", "FRONTLOAD", "ADDRESS"]
NAMES = {"LENGTH": "길이", "SPECIFICITY": "구체성", "STAKES": "긴장감", "FRONTLOAD": "핵심 위치", "ADDRESS": "말 거는 대상"}


def run(text):
    results = {
        "LENGTH": check_length(text),
        "SPECIFICITY": check_specificity(text),
        "STAKES": check_stakes(text),
        "FRONTLOAD": check_frontload(text),
        "ADDRESS": check_address(text),
    }
    flags = [msg for pattern, msg in DEALBREAKERS if pattern.search(text)]
    if len(EMOJI_RE.findall(text)) >= 2 or EMOJI_RE.match(text.strip()):
        flags.append("첫 줄에 이모지가 많거나 이모지로 시작. 글자 자리를 이모지가 먹는다.")
    scores = [results[c][0] for c in CHECKS]
    # 가장 약한 기준이 전체를 깎는다. 한 가지만 나빠도 엄지는 계속 내려간다.
    overall = statistics.mean(scores) * 0.6 + min(scores) * 0.4 - len(flags) * 15
    overall = clamp(overall)
    verdict = "STRONG" if overall >= 70 and min(scores) >= 55 and not flags else ("OK" if overall >= 50 else "WEAK")
    return results, overall, verdict, flags


def bar(score, width=24):
    filled = round(score / 100 * width)
    return "#" * filled + "." * (width - filled)


def render_one(text, results, overall, verdict, flags, out=sys.stdout):
    print("\nHOOK SCORE (훅 점수)", file=out)
    print("=" * 62, file=out)
    print(f"  \"{text.strip()}\"\n", file=out)
    for name in CHECKS:
        score, detail = results[name]
        print(f"  {NAMES[name]:<8} {bar(score)} {score:5.1f}", file=out)
        print(f"  {'':<8} {detail}", file=out)
    print("-" * 62, file=out)
    print(f"  {'합계':<8} {bar(overall)} {overall:5.1f}   {verdict}", file=out)
    for f in flags:
        print(f"\n  감점  {f}", file=out)
    if verdict != "STRONG":
        weakest = min(CHECKS, key=lambda c: results[c][0])
        print(f"\n  가장 약한 기준: {NAMES[weakest]}. 그것부터 고치고 다시 돌린다.", file=out)
    print("", file=out)


def render_table(rows, out=sys.stdout):
    print("\nHOOK RANKING (훅 순위)\n" + "=" * 78, file=out)
    for i, r in enumerate(rows, 1):
        mark = "->" if i == 1 else "  "
        hook = r["hook"] if len(r["hook"]) <= 50 else r["hook"][:47] + "..."
        print(f"{mark} {r['score']:5.1f} {r['verdict']:<7} {hook}", file=out)
        print(f"        약한 기준: {NAMES[r['weakest']]} ({r['checks'][r['weakest']]['score']:.0f})", file=out)
        for f in r["flags"]:
            print(f"        감점: {f}", file=out)
    print("\n1등을 쓴다. 1등이 50점 아래면 아직 훅이 없는 것이다.\n", file=out)


def score_payload(line):
    results, overall, verdict, flags = run(line)
    return {
        "hook": line,
        "checks": {k: {"score": round(v[0], 1), "detail": v[1]} for k, v in results.items()},
        "weakest": min(CHECKS, key=lambda c: results[c][0]),
        "flags": flags,
        "score": round(overall, 1),
        "verdict": verdict,
    }


def main():
    ap = argparse.ArgumentParser(description="쓰레드 첫 줄(훅)을 다섯 기준으로 채점한다.")
    ap.add_argument("input", nargs="?", default="-", help="한 줄에 훅 하나씩 적은 파일, 또는 -")
    ap.add_argument("--hook", help="훅 하나를 바로 채점")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.hook:
        lines = [args.hook]
    else:
        try:
            raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8-sig").read()
        except OSError as e:
            print(f"파일을 못 읽었다: {e}", file=sys.stderr)
            sys.exit(2)
        lines = [l.strip().lstrip("\ufeff") for l in raw.splitlines() if l.strip()]
    if not lines:
        print("채점할 내용이 없다", file=sys.stderr)
        sys.exit(2)

    payload = [score_payload(l) for l in lines]
    if args.json:
        print(json.dumps(payload if len(payload) > 1 else payload[0], indent=2, ensure_ascii=False))
        sys.exit(0 if max(p["score"] for p in payload) >= 70 else 1)
    if len(payload) == 1:
        render_one(lines[0], *run(lines[0]))
    else:
        render_table(sorted(payload, key=lambda r: -r["score"]))
    sys.exit(0 if max(p["score"] for p in payload) >= 70 else 1)


if __name__ == "__main__":
    main()
