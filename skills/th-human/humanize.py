#!/usr/bin/env python3
"""
humanize.py - 초안에서 기계가 쓴 흔적을 지운다.

자동으로 고치는 것 (slop.json 기준):
  1. 보이지 않는 문자: 폭 없는 공백, 단어 연결자, BOM 등은 지우고, 특수 공백은 일반 공백으로.
  2. 문장부호: 긴 줄표(—)는 쉼표로, 둥근 따옴표는 곧은 따옴표로, …는 ...로.
  3. 상투어: '결론적으로', '함께 알아볼까요?', '혁신적인' 같은 말을 쉬운 말로 바꾸거나 지운다.

자동으로 고치지 않는 것:
  문장 구조('단순히 X가 아니라 Y', '첫째 둘째 셋째', 이모지 글머리 등)는 표시만 한다.
  문장 모양을 바꾸려면 판단이 필요해서다. 표시된 줄은 직접 고친다.

URL 안은 건드리지 않는다.

사용법
  python3 humanize.py draft.txt --report          # 고친 결과 + 바뀐 내용
  python3 humanize.py draft.txt -o clean.txt --report
  pbpaste | python3 humanize.py - --report
"""

import argparse
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
LEX = os.path.join(HERE, "slop.json")
URL_RE = re.compile(r"https?://\S+|www\.\S+")


def load():
    return json.load(open(LEX, encoding="utf-8"))


def protect_urls(text):
    urls = []

    def keep(m):
        urls.append(m.group(0))
        return f"\x00{len(urls) - 1}\x00"

    return URL_RE.sub(keep, text), urls


def restore_urls(text, urls):
    return re.sub(r"\x00(\d+)\x00", lambda m: urls[int(m.group(1))], text)


def strip_invisible(text, lex, log):
    for item in lex["invisible"]:
        ch = chr(int(item["cp"][2:], 16))
        n = text.count(ch)
        if n:
            text = text.replace(ch, item.get("to", ""))
            log.append(("보이지 않는 문자", f"{item['name']} x{n}"))
    # 이름 없는 서식 문자(Cf)도 지운다. 단, 줄바꿈·탭·URL 자리표시는 남긴다.
    extra = [c for c in text if unicodedata.category(c) == "Cf" and c not in "\x00"]
    if extra:
        for c in set(extra):
            text = text.replace(c, "")
        log.append(("보이지 않는 문자", f"기타 서식 문자 x{len(extra)}"))
    return text


def fix_typography(text, lex, log):
    for item in lex["typographic"]:
        n = text.count(item["from"])
        if n:
            text = text.replace(item["from"], item["to"])
            log.append(("문장부호", f"{item['name']} x{n}"))
    # 줄표를 쉼표로 바꾸며 생긴 ", ," / " ," / ",." 정리
    text = re.sub(r"\s*,\s*,", ",", text)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r",\s*([.!?])", r"\1", text)
    text = re.sub(r"([!?.])\s*,", r"\1", text)
    text = re.sub(r"^,\s*", "", text, flags=re.M)
    return text


PARTICLES = {"을": ("을", "를"), "를": ("을", "를"), "이": ("이", "가"), "가": ("이", "가"),
             "은": ("은", "는"), "는": ("은", "는"), "과": ("과", "와"), "와": ("과", "와"),
             "으로": ("으로", "로"), "로": ("으로", "로")}


def has_batchim(word):
    """마지막 글자에 받침이 있는지. 한글이 아니면 None."""
    for ch in reversed(word.strip()):
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            return code % 28 != 0, code % 28 == 8   # (받침 있음, 받침이 ㄹ)
        if ch.isalnum():
            return None
    return None


def fit_particle(rep, particle):
    """바꾼 말의 받침에 맞게 조사를 고른다. 배운 점+를 -> 배운 점을."""
    if not particle or particle not in PARTICLES:
        return particle or ""
    info = has_batchim(rep)
    if info is None:
        return particle
    batchim, rieul = info
    with_b, without_b = PARTICLES[particle]
    if with_b == "으로":
        return "로" if (not batchim or rieul) else "으로"
    return with_b if batchim else without_b


def swap_lexicon(text, lex, log):
    items = sorted(lex["phrases"] + lex["words"], key=lambda x: -len(x["find"]))
    for item in items:
        find, rep = item["find"], item["replace"]
        if re.search(r"[A-Za-z]", find):
            pat = re.compile(r"\b" + re.escape(find) + r"\b", re.I)
            hits = pat.findall(text)
            if hits:
                text = pat.sub(rep, text)
        else:
            pat = re.compile(re.escape(find) + r"(으로|로|을|를|이|가|은|는|과|와)?")
            hits = pat.findall(text)
            if hits:
                text = pat.sub(lambda m: rep + (fit_particle(rep, m.group(1)) if rep else (m.group(1) or "")), text)
        if hits:
            log.append(("상투어", f"'{find}' -> " + (f"'{rep}'" if rep else "삭제") + (f" x{len(hits)}" if len(hits) > 1 else "")))
    # 지운 자리에 남은 공백·문장부호 정리
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([,.!?])", r"\1", text)
    text = re.sub(r"(?m)^[ \t]+", "", text)
    text = re.sub(r"(?m)^[,.]\s*", "", text)
    text = re.sub(r"([!?.])\s*,", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def find_structures(text, lex):
    flags = []
    for s in lex["structures"]:
        for m in re.finditer(s["regex"], text):
            snippet = m.group(0).strip().replace("\n", " ")
            flags.append((s["name"], snippet[:50], s["fix"]))
    return flags


def humanize(text, lex=None):
    lex = lex or load()
    log = []
    text, urls = protect_urls(text)
    text = strip_invisible(text, lex, log)
    text = fix_typography(text, lex, log)
    text = swap_lexicon(text, lex, log)
    text = restore_urls(text, urls).strip() + "\n"
    return text, log, find_structures(text, lex)


def main():
    ap = argparse.ArgumentParser(description="초안에서 AI 흔적을 지운다.")
    ap.add_argument("input", nargs="?", default="-")
    ap.add_argument("-o", "--out")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    clean, log, flags = humanize(raw)
    if args.json:
        print(json.dumps({"text": clean, "changes": log, "flags": flags}, ensure_ascii=False, indent=2))
        return
    if args.out:
        open(args.out, "w", encoding="utf-8").write(clean)
    else:
        sys.stdout.write(clean)
    if args.report:
        err = sys.stderr
        print("\nHUMANIZE 보고", file=err)
        print("=" * 60, file=err)
        if log:
            for kind, what in log:
                print(f"  고침   [{kind}] {what}", file=err)
        else:
            print("  자동으로 고칠 것 없음", file=err)
        if flags:
            print("\n  직접 고칠 문장 구조:", file=err)
            for name, snip, fix in flags:
                print(f"  - {name}: \"{snip}\"", file=err)
                print(f"      -> {fix}", file=err)
        print("", file=err)


if __name__ == "__main__":
    main()
