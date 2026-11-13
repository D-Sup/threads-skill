#!/usr/bin/env python3
"""도구들이 실제로 돌아가고, 한국어를 제대로 읽는지 확인한다.  python3 tests/test_scripts.py"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "skills")


def run(script, *args, stdin=None):
    p = subprocess.run([sys.executable, "-I", os.path.join(S, script), *args],
                       input=stdin, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def tmp(text, suffix=".txt"):
    f = tempfile.NamedTemporaryFile("w", delete=False, suffix=suffix, encoding="utf-8")
    f.write(text)
    f.close()
    return f.name


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def hook(line):
    _, out, _ = run("th-post/hookscore.py", "--hook", line, "--json")
    return json.loads(out)


class HookScore(unittest.TestCase):
    def test_korean_strong_beats_weak(self):
        strong = hook("서버비 40만 원을 날린 이유는 캐시 설정 한 줄이었다.")
        weak = hook("요즘 AI가 정말 많이 발전하고 있는 것 같습니다")
        self.assertGreaterEqual(strong["score"], 70)
        self.assertLess(weak["score"], 50)

    def test_korean_matches_english_counterpart(self):
        # 원본(영어 전용)에서는 한국어 번역이 38점이었다. 이제 영어와 비슷해야 한다.
        ko = hook("아무도 안 알려주는데, 첫 글 30개는 반응 없는 게 정상이에요")
        en = hook("Nobody tells you that your first 30 posts are supposed to flop.")
        self.assertLess(abs(ko["score"] - en["score"]), 15)

    def test_greeting_and_preamble_are_dealbreakers(self):
        r = hook("안녕하세요 여러분 오늘은 콘텐츠 전략에 대해 이야기해볼게요")
        self.assertEqual(r["verdict"], "WEAK")
        self.assertGreaterEqual(len(r["flags"]), 2)

    def test_clickbait_flagged(self):
        self.assertTrue(hook("충격!! 이거 모르면 무조건 손해 🔥🔥")["flags"])


class Chain(unittest.TestCase):
    def test_over_limit_fails(self):
        code, out, _ = run("th-post/chain.py", tmp("첫 줄\n" + "가" * 520))
        self.assertEqual(code, 1)
        self.assertIn("초과", out)

    def test_two_tags_fail_and_numbering(self):
        text = "빌드 12분이 2분 됐다. 1/2\n---\n2/3 바꾼 건 한 줄. #개발 #빌드"
        code, out, _ = run("th-post/chain.py", tmp(text), "--json")
        a = json.loads(out)
        self.assertEqual(a["total"], 2)
        msgs = " ".join(m for p in a["parts"] for _, m in p["issues"])
        self.assertIn("태그 2개", msgs)
        self.assertIn("2/3", msgs)

    def test_clean_post_ready(self):
        code, _, _ = run("th-post/chain.py", tmp("서버비 40만 원을 날린 이유는 캐시 설정 한 줄이었다.\n\n원인은 TTL 0. #백엔드"))
        self.assertEqual(code, 0)

    def test_dash_line_inside_code_block_does_not_split(self):
        text = "SKILL.md 맨 위는 이렇게 생겼다.\n\n```\n---\nname: th-post\n---\n```\n\n이 세 줄이 전부다."
        _, out, _ = run("th-post/chain.py", tmp(text), "--json")
        self.assertEqual(json.loads(out)["total"], 1)

    def test_date_is_not_numbering(self):
        text = "11/9에 나온 업데이트 하나만 보면 된다.\n---\n바뀐 건 11/9 버전부터다.\n---\n그래서 11/16 전에 올려 둔다."
        _, out, _ = run("th-post/chain.py", tmp(text), "--json")
        a = json.loads(out)
        msgs = " ".join(m for p in a["parts"] for _, m in p["issues"])
        self.assertNotIn("번호", msgs)
        self.assertIn("11/9", a["hook"]["line"])

    def test_date_at_line_start_is_not_numbering(self):
        cases = [
            "3/5 회의에서 정한 것 하나.\n---\n둘째 글.\n---\n셋째 글.",
            "3/5 회의 메모.\n---\n3/7 출시 메모.\n---\n정리.",
            "1/3 첫 글.\n---\n3/5 회의에서 바뀐 것. 2/3\n---\n끝. 3/3",
            "1/3 출시된 기능 하나.\n---\n둘째 글.\n---\n셋째 글.",
            "첫 글.\n---\n둘째 글.\n---\n3/3 회의에서 정했다.",
        ]
        for text in cases:
            _, out, _ = run("th-post/chain.py", tmp(text), "--json")
            a = json.loads(out)
            msgs = " ".join(m for p in a["parts"] for _, m in p["issues"])
            self.assertNotIn("번호", msgs, text)
        self.assertIn("3/5", json.loads(run("th-post/chain.py", tmp(cases[0]), "--json")[1])["hook"]["line"])
        # 위치와 우연히 맞는 날짜(1/3, 연결글 3개)도 첫 줄 채점에서 지우지 않는다
        self.assertIn("1/3", json.loads(run("th-post/chain.py", tmp(cases[3]), "--json")[1])["hook"]["line"])
        # 진짜 번호가 여러 글에 있으면 첫 줄 채점에서 번호를 지운다
        numbered = "1/2 빌드가 12분에서 2분이 됐다.\n---\n2/2 바꾼 건 한 줄."
        self.assertNotIn("1/2", json.loads(run("th-post/chain.py", tmp(numbered), "--json")[1])["hook"]["line"])

    def test_real_numbering_mismatch_still_warns(self):
        text = "1/3 첫 글.\n---\n3/3 둘째 글.\n---\n2/3 셋째 글."
        _, out, _ = run("th-post/chain.py", tmp(text), "--json")
        msgs = " ".join(m for p in json.loads(out)["parts"] for _, m in p["issues"])
        self.assertIn("3/3가 실제 위치 2/3", msgs)  # 순서가 섞인 번호
        text = "1/4 첫 글.\n---\n2/4 둘째 글.\n---\n3/4 끝."
        _, out, _ = run("th-post/chain.py", tmp(text), "--json")
        msgs = " ".join(m for p in json.loads(out)["parts"] for _, m in p["issues"])
        self.assertIn("1/4", msgs)

    def test_more_number_and_fence_shapes(self):
        def check(text):
            _, out, _ = run("th-post/chain.py", tmp(text), "--json")
            a = json.loads(out)
            return a, " ".join(m for p in a["parts"] for _, m in p["issues"]), " ".join(m for _, m in a["general"])
        a, msgs, _ = check("5/12 출시 소식\n---\n6/12 패치 소식\n---\n정리")
        self.assertNotIn("번호", msgs)
        a, msgs, _ = check("[1/3] 첫\n---\n[3/3] 둘\n---\n[2/3] 셋")
        self.assertIn("3/3가 실제 위치 2/3", msgs)
        a, msgs, _ = check("첫 1/3.\n---\n둘 3/3.\n---\n셋 2/3.")
        self.assertIn("3/3가 실제 위치 2/3", msgs)
        a, _, gen = check("첫\n```\ncode\n---\n둘\n---\n셋")
        self.assertEqual(a["total"], 3)
        self.assertIn("닫히지 않았다", gen)
        a, _, _ = check("첫\n~~~\n---\n~~~\n끝")
        self.assertEqual(a["total"], 1)

    def test_tags_links_code_and_unsplit_chain(self):
        def part(text):
            _, out, _ = run("th-post/chain.py", tmp(text), "--json")
            a = json.loads(out)
            return a, a["parts"][0], " ".join(m for _, m in a["parts"][0]["issues"])
        _, p, _ = part("#1 실수는 이거였다. #개발")
        self.assertEqual(p["tags"], 1)  # 순번 #1은 태그가 아니다
        _, p, _ = part("코드\n```\n#include <stdio.h>\n#define A 1\n```\n끝 #C언어")
        self.assertEqual(p["tags"], 1)  # 코드 안 #은 태그가 아니다
        _, p, msgs = part("github.com/D-Sup/threads-skill 에 올렸다. Next.js 썼다.")
        self.assertEqual(p["links"], 1)
        self.assertIn("첫 답글", msgs)  # 단독 글 링크도 알려준다
        _, _, msgs = part("1/3 첫 글\n\n2/3 둘째\n\n3/3 셋째")
        self.assertIn("--- 줄이 없다", msgs)
        a, _, _ = part("첫 글. 1/2\n#개발\n---\n둘째 글. 2/2")
        self.assertFalse([m for q in a["parts"] for _, m in q["issues"] if "번호" in m])

    def test_bom_and_missing_file(self):
        _, out, _ = run("th-post/chain.py", tmp("\ufeff1/2 첫\n---\n2/2 둘"), "--json")
        a = json.loads(out)
        self.assertEqual(a["parts"][0]["chars"], 5)
        self.assertEqual(a["hook"]["line"], "첫")
        code, _, err = run("th-post/chain.py", "/없는/파일.txt")
        self.assertEqual(code, 2)
        self.assertIn("못 읽었다", err)

    def test_strict_counts_emoji_bigger(self):
        _, out, _ = run("th-post/chain.py", tmp("🔥" * 10), "--json")
        p = json.loads(out)["parts"][0]
        self.assertGreater(p["chars_strict"], p["chars"])


class Human(unittest.TestCase):
    AI = ("급변하는 시대에 혁신적인 도구가 필요합니다 — 결론적으로 인사이트를 얻을 수 있습니다.\n"
          "✅ 첫째\n✅ 둘째\n도움이 되셨기를 바랍니다!! https://example.com/a—b #AI #생산성 #업무")

    def test_humanize_fixes_and_particles(self):
        _, out, err = run("th-human/humanize.py", "-", "--report", stdin=self.AI)
        self.assertNotIn("결론적으로", out)
        self.assertNotIn("혁신적인", out)
        self.assertIn("배운 점을", out)          # 인사이트를 -> 배운 점을 (조사 맞춤)
        self.assertNotIn("배운 점를", out)
        self.assertIn("https://example.com/a—b", out)   # URL은 건드리지 않는다
        self.assertIn("이모지 글머리", err)
        self.assertIn("태그 벽", err)

    def test_humanize_keeps_code_emoji_and_grammar(self):
        text = ("개발자 👨‍💻 입니다. 이 도구를 활용해요. 활용해 보세요. 인사이트이다.\n"
                "```\n  x = \"—결론적으로\"\n```\n`a—b` leverage를 쓴다.")
        _, out, _ = run("th-human/humanize.py", "-", stdin=text)
        self.assertIn("👨\u200d💻", out)          # 이모지 ZWJ는 남긴다
        self.assertIn("써요", out)
        self.assertIn("써 보세요", out)
        self.assertIn("배운 점이다", out)           # '이다'의 '이'는 조사가 아니다
        self.assertIn('  x = "—결론적으로"', out)  # 코드 블록은 그대로
        self.assertIn("`a—b`", out)
        self.assertIn("use를", out)

    def test_detect_sentence_and_first_person(self):
        sys.path.insert(0, os.path.join(S, "th-human"))
        import detect
        self.assertEqual(len(detect.sentences("빌드가 3.5배 빨라졌다. github.com 에 있다!")), 2)
        self.assertFalse(detect.FIRST_PERSON.search("제도를 바꿨다"))
        self.assertTrue(detect.FIRST_PERSON.search("제가 했다"))

    def test_detect_separates(self):
        human = ("주간 보고서 쓰는 데 매주 3시간씩 쓰고 있었다.\n\n지난달에 Claude한테 슬랙 기록 붙여넣고 "
                 "초안만 뽑게 바꿨더니 15분이면 끝난다. 숫자 확인은 내가 한다. 이건 절대 맡기면 안 됨.\n\n"
                 "처음 2주는 오히려 더 오래 걸렸어요. 프롬프트를 계속 고쳐야 해서.")
        _, out_h, _ = run("th-human/detect.py", tmp(human), "--json")
        _, out_a, _ = run("th-human/detect.py", tmp(self.AI * 2), "--json")
        self.assertGreater(json.loads(out_h)[0]["score"], json.loads(out_a)[0]["score"] + 25)


class RankAndAudit(unittest.TestCase):
    def test_rank_outlier_and_formula(self):
        tsv = ("account\tfollowers\tmedian\tviews\thook\n"
               "@a\t3000\t2000\t4.1만\t서버비 40만 원을 날린 이유는 캐시 한 줄이었다.\n"
               "@a\t3000\t2000\t1800\t요즘 개발 트렌드 정리\n")
        _, out, _ = run("th-viral/rank.py", tmp(tsv), "--json")
        a = json.loads(out)
        top = a["posts"][0]
        self.assertEqual(top["outlier"], 20.5)
        self.assertEqual(top["formula"], "비용 고백")

    def test_rank_bad_numbers_and_small_sample(self):
        tsv = "account\tmedian\tviews\thook\n@a\t100\t1.2.3\t첫 줄 | 파이프\n"
        code, out, _ = run("th-viral/rank.py", tmp(tsv, ".tsv"), "--json")
        a = json.loads(out)
        self.assertEqual(a["n"], 1)
        md = tmp("", ".md")
        run("th-viral/rank.py", tmp(tsv, ".tsv"), "--out", md)
        self.assertIn("첫 줄 \\| 파이프", read(md))  # 표가 깨지지 않게

    def test_audit_without_views_uses_likes_and_skips_reposts(self):
        data = {"posts": [
            {"id": "1", "text": "서버비 40만 원을 날렸다", "likes": 40, "replies": 3},
            {"id": "2", "text": "캐시 한 줄", "likes": 10, "replies": 1},
            {"id": "3", "text": "남의 글", "media_type": "REPOST_FACADE", "likes": 999},
        ]}
        code, out, _ = run("th-audit/audit.py", tmp(json.dumps(data, ensure_ascii=False), ".json"), "--json")
        a = json.loads(out)
        self.assertEqual(a["n"], 2)
        self.assertIn("좋아요 기준", a["findings"][0])
        self.assertFalse({p["text"] for p in a["top"]} & {p["text"] for p in a["bottom"]})  # 위·아래 안 겹침

    def test_audit_reads_api_json(self):
        posts = [{"text": f"서버비 {i}0만 원을 날린 이유\n본문", "timestamp": "2026-11-13T00:00:06+0000",
                  "views": 1000 * (i + 1), "likes": 10, "replies": i, "reposts": 1, "quotes": 0, "shares": 1}
                 for i in range(6)]
        _, out, err = run("th-audit/audit.py", tmp(json.dumps({"posts": posts}), ".json"), "--json")
        self.assertEqual(json.loads(out)["n"], 6, err)


class Files(unittest.TestCase):
    def test_every_skill_has_frontmatter(self):
        for d in sorted(os.listdir(S)):
            p = os.path.join(S, d, "SKILL.md")
            self.assertTrue(os.path.exists(p), d)
            head = read(p).split("---")[1]
            self.assertIn(f"name: {d}", head)
            self.assertIn("description:", head)

    def test_hooks_regex_compiles(self):
        import re
        d = json.loads(read(os.path.join(S, "th-post", "hooks.json")))
        ids = {h["id"] for h in d["hooks"]}
        self.assertEqual(set(d["classify_order"]), ids)
        for h in d["hooks"]:
            re.compile(h["match"])

    def test_rubric_totals_100(self):
        d = json.loads(read(os.path.join(S, "th-profile", "rubric.json")))
        self.assertEqual(sum(i["points"] for i in d["items"]), 100)


if __name__ == "__main__":
    unittest.main(verbosity=1)
