# threads-skill

Eleven Claude skills that run a Threads account. Free, MIT, no signup, no API key, nothing to connect.
Korean-first, with English support in every tool.

**Nothing gets posted until you post it.** These skills write. You post.

[한국어 README](README.md)

## Why

The well-known Instagram pack ([instagram-agent-skill](https://github.com/Jakeschincariol/instagram-agent-skill))
has no Threads equivalent of similar reach, and its scoring tools are English-only: a hook that scores 85 in
English scored 38 when translated to Korean. This pack adapts its structure to Threads (500-character posts,
chains, one topic tag, replies) and rebuilds the tools to read Korean.

## Install

```
https://github.com/D-Sup/threads-skill
Install this skill, then confirm /th-post works.
```

or

```bash
git clone https://github.com/D-Sup/threads-skill.git
cp -r threads-skill/skills/th-* ~/.claude/skills/
```

or `/plugin marketplace add D-Sup/threads-skill` then `/plugin install threads-skill`.

Then run `/th-voice` and paste a few of your own posts.

## The eleven

| command | what it does |
| --- | --- |
| `/th-voice` | Builds `~/.claude/threads/voice.md` (niche, voice, real numbers you can use). Every skill reads it. |
| `/th-post` | One idea into a post or a 3-6 part chain. Three hooks from 22 formulas, scored, then a 500-char check. |
| `/th-source` | Turns a link, doc, release note or your own work log into a useful post. Facts checked against the source, cited. |
| `/th-viral` | Finds what is working in your niche, ranked by multiple over each account's own median views. |
| `/th-plan` | The week, 1-2 posts a day by default, plus 10 accounts to reply to. |
| `/th-reply` | Triage and draft replies under your own post. |
| `/th-comment` | Replies on other people's posts, nine types, never "so true". |
| `/th-repurpose` | One long asset into a week of standalone posts. |
| `/th-profile` | Profile scored out of 100, rewrites in fix-first order. |
| `/th-audit` | Post-mortem on your posts. Optional read-only fetch from the official Threads API. |
| `/th-human` | Humanizer: strips stock phrases, em dashes and invisible characters, fixes Korean particles, scores five checks. |

## Credits

MIT. Adapted from Jake Schincariol's [instagram-agent-skill](https://github.com/Jakeschincariol/instagram-agent-skill) (MIT):
the pack structure, outlier-multiple research and the five-check scoring approach. The hook formulas, Korean scorers,
lexicon, Threads API fetcher, `/th-source` and `/th-voice` are new.
