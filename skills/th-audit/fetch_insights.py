#!/usr/bin/env python3
"""
fetch_insights.py - 쓰레드 공식 API로 '내 글'과 글별 성과를 읽어서 audit.py가 읽는 JSON으로 저장한다.

읽기만 한다. 글을 올리거나, 지우거나, 답글을 달지 않는다.

필요한 것 (한 번만):
  1. https://developers.facebook.com 에서 앱을 만들고 'Threads API' 사용 사례를 추가
  2. 권한 threads_basic, threads_manage_insights 로 사용자 토큰 발급 (내 계정)
  3. 장기 토큰(60일)으로 바꿔 두면 편하다
  4. 토큰은 환경변수 THREADS_TOKEN 에 넣는다. 파일이나 저장소에 넣지 않는다.

공식 문서:
  글 목록   GET /me/threads?fields=id,text,timestamp,permalink,media_type,is_quote_post,topic_tag
  글 성과   GET /{media-id}/insights?metric=views,likes,replies,reposts,quotes,shares
  (문서 예시는 graph.threads.com, 예전 예시는 graph.threads.net. 앞에 것이 안 되면 뒤에 것으로 다시 시도한다.)
  views, shares 는 문서에 '개발 중'으로 표시돼 있어 값이 비어 올 수 있다.

사용법
  THREADS_TOKEN=... python3 fetch_insights.py                    # 최근 50개
  THREADS_TOKEN=... python3 fetch_insights.py --limit 100 --since 2026-10-01
  python3 fetch_insights.py --out ~/.claude/threads/posts.json   # 기본 저장 위치
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HOSTS = ["https://graph.threads.com/v1.0", "https://graph.threads.net/v1.0"]
FIELDS = "id,text,timestamp,permalink,media_type,is_quote_post,topic_tag"
METRICS = "views,likes,replies,reposts,quotes,shares"


def get(url, params, token):
    q = dict(params, access_token=token)
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(q), headers={"User-Agent": "threads-skill/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def pick_host(token):
    last = None
    for host in HOSTS:
        try:
            get(host + "/me", {"fields": "id,username"}, token)
            return host
        except urllib.error.HTTPError as e:
            last = f"{host}: HTTP {e.code} {e.read().decode('utf-8', 'ignore')[:200]}"
        except Exception as e:  # 네트워크 등
            last = f"{host}: {e}"
    sys.exit(f"API 연결 실패. 토큰과 권한(threads_basic)을 확인한다.\n{last}")


def fetch_posts(host, token, limit, since=None):
    params = {"fields": FIELDS, "limit": min(limit, 100)}
    if since:
        params["since"] = since
    url, posts = host + "/me/threads", []
    while url and len(posts) < limit:
        data = get(url, params, token)
        posts += data.get("data", [])
        nxt = data.get("paging", {}).get("next")
        if not nxt:
            break
        url, params = nxt.split("?")[0], dict(urllib.parse.parse_qsl(nxt.split("?", 1)[1]))
        params.pop("access_token", None)
    return posts[:limit]


def fetch_metrics(host, token, media_id):
    try:
        data = get(f"{host}/{media_id}/insights", {"metric": METRICS}, token)
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    out = {}
    for m in data.get("data", []):
        vals = m.get("values") or []
        if vals:
            out[m["name"]] = vals[0].get("value")
        elif "total_value" in m:
            out[m["name"]] = m["total_value"].get("value")
    return out


def main():
    ap = argparse.ArgumentParser(description="쓰레드 공식 API로 내 글 성과를 읽어 저장한다(읽기 전용).")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--since", help="YYYY-MM-DD 이후 글만")
    ap.add_argument("--out", default="~/.claude/threads/posts.json")
    args = ap.parse_args()
    token = os.environ.get("THREADS_TOKEN")
    if not token:
        sys.exit("THREADS_TOKEN 환경변수가 없다. 파일 맨 위 설명대로 토큰을 만든다.")
    host = pick_host(token)
    posts = fetch_posts(host, token, args.limit, args.since)
    print(f"글 {len(posts)}개를 찾았다. 성과를 읽는 중...", file=sys.stderr)
    for i, p in enumerate(posts, 1):
        p.update(fetch_metrics(host, token, p["id"]))
        if i % 10 == 0:
            print(f"  {i}/{len(posts)}", file=sys.stderr)
        time.sleep(0.2)   # 요청 한도를 넉넉히 지킨다
    out = os.path.expanduser(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "host": host, "posts": posts},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"저장: {out}\n다음: python3 audit.py {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
