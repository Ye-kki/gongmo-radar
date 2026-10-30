"""Daily run: collect board posts and web-search finds, read them, extract with Claude, validate, save.

Usage:
  python -m radar.run                  # full run
  python -m radar.run --dry-run        # list new candidate posts only, no AI calls
  python -m radar.run --only bizinfo   # one source
  python -m radar.run --discover       # force web-search discovery today
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .collect import extract_links, keyword_match
from .detail import read_post
from .fetch import Fetcher, FetchError, RobotsBlocked
from .store import Store, normalize_url
from .validate import clean

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


def load(name):
    return yaml.safe_load((ROOT / "config" / name).read_text("utf-8"))


def main(argv=None, ai_factory=None, fetcher=None, data_dir=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--no-discover", action="store_true")
    ap.add_argument("--max-new", type=int, default=80, help="하루에 AI로 읽을 최대 게시글 수 (비용 상한)")
    ap.add_argument("--budget-min", type=float, default=35, help="이 시간(분)이 지나면 읽기를 멈추고 저장")
    args = ap.parse_args(argv)

    started = time.monotonic()
    now = datetime.now(KST)
    today = now.date()
    sources_cfg, profile, disc = load("sources.yaml"), load("profile.yaml"), load("discovery.yaml")
    store = Store(Path(data_dir) if data_dir else ROOT / "data")
    fetcher = fetcher or Fetcher()
    health = {"runAt": now.strftime("%Y-%m-%d %H:%M"), "sources": [], "discovery": [], "counts": {}}

    # 1) collect candidates from boards
    candidates: list[dict] = []
    for src in sources_cfg["sources"]:
        if src.get("enabled") is False or (args.only and src["id"] != args.only):
            continue
        h = {"id": src["id"], "name": src["name"], "url": src["url"], "status": "ok", "links": 0, "new": 0}
        try:
            page = fetcher.get(src["url"])
            links = extract_links(page.text, page.url, src)
            h["links"] = len(links)
            if not links:
                h["status"] = "empty"
                h["detail"] = "목록에서 게시글 링크를 찾지 못함. 자바스크립트로 그리는 페이지이거나 link_regex 확인 필요"
            for ln in links:
                if src.get("filter") and not keyword_match(ln["title"], sources_cfg["title_keywords"]):
                    continue
                if store.is_seen(ln["url"]):
                    continue
                h["new"] += 1
                candidates.append({**ln, "source_id": src["id"], "source_name": src["name"],
                                   "cats": src.get("cats", []), "region": src.get("region", "전국")})
        except RobotsBlocked as e:
            h["status"], h["detail"] = "robots", str(e)
        except FetchError as e:
            h["status"], h["detail"] = "error", str(e)[:200]
        except Exception as e:  # parsing bug in one source must not stop the run
            h["status"], h["detail"] = "error", f"{type(e).__name__}: {e}"[:200]
        health["sources"].append(h)
        print(f"[{h['status']:>6}] {src['id']}: links={h['links']} new={h['new']}", file=sys.stderr)

    # 1b) links added by hand in config/manual.yaml
    manual_path = (Path(data_dir).parent if data_dir else ROOT) / "config" / "manual.yaml"
    if manual_path.exists() and (not args.only or args.only == "manual"):
        for u in (yaml.safe_load(manual_path.read_text("utf-8")) or {}).get("urls") or []:
            text = ""
            if isinstance(u, dict):
                u, text = u.get("url", ""), (u.get("text") or "")
            if isinstance(u, str) and u.startswith("http") and not store.is_seen(u):
                candidates.insert(0, {"title": "", "url": u.strip(), "source_id": "manual",
                                      "source_name": "직접 추가", "cats": [], "region": "전국",
                                      "pasted_text": text.strip()})

    if args.dry_run:
        for c in candidates:
            print(f"{c['source_id']}\t{c['title']}\t{c['url']}")
        return 0

    ai = (ai_factory or _make_ai)(profile, today.isoformat())

    # 2) discovery by web search on chosen weekdays
    run_disc = args.discover or (not args.no_discover and not args.only and today.weekday() in disc.get("weekdays", []))
    if run_disc:
        for q in disc["queries"]:
            found = ai.discover(q, disc.get("max_searches_per_query", 3))
            n_new = 0
            for f in found:
                if store.is_seen(f["url"]) or any(normalize_url(c["url"]) == normalize_url(f["url"]) for c in candidates):
                    continue
                n_new += 1
                candidates.append({"title": f["title"], "url": f["url"], "source_id": f"search:{q['id']}",
                                   "source_name": "웹 검색", "cats": q.get("cats", []), "region": "전국",
                                   "search_hint": f})
            health["discovery"].append({"id": q["id"], "found": len(found), "new": n_new})

    # 3) read and extract
    counts = {"candidates": len(candidates), "read": 0, "same": 0, "new": 0, "updated": 0, "skipped": 0,
              "read_failed": 0, "over_limit": 0}
    fails = 0
    for c in candidates:
        if counts["read"] >= args.max_new or time.monotonic() - started > args.budget_min * 60:
            counts["over_limit"] += 1
            continue
        try:
            post = read_post(fetcher, c["url"])
            if c.get("pasted_text") and len(post["text"]) < 400:
                post["text"] = (post["text"] + "\n\n[직접 붙여넣은 공고 내용]\n" + c["pasted_text"]).strip()
        except (FetchError, Exception) as e:
            if c.get("pasted_text"):
                post = {"url": c["url"], "text": c["pasted_text"], "attachments": [], "attachment_text": ""}
            else:
                counts["read_failed"] += 1
                health.setdefault("read_errors", []).append(f"{c['source_name']}: {c['url'][:90]} → {str(e)[:120]}")
                health["read_errors"] = health["read_errors"][:30]
                # board posts: try again tomorrow; search finds: forget after one failure
                if c["source_id"].startswith("search:"):
                    store.mark_seen(c["url"], "failed", str(e), today.isoformat())
                continue
        if len(post["text"]) < 80 and not post.get("attachment_text"):
            counts["read_failed"] += 1
            store.mark_seen(c["url"], "skipped", "본문이 비어 있음", today.isoformat())
            continue
        counts["read"] += 1
        rec = ai.extract(post, c)
        if rec is None:
            # API error: not marked seen, retried next run. Stop early if AI is down (e.g. bad token).
            fails += 1
            if fails >= 5:
                counts["aborted"] = "AI 호출이 연속 5번 실패해 중단 (토큰·키 확인 필요)"
                break
            continue
        fails = 0
        if not rec.get("is_open_call") or (rec.get("relevance") or 0) < 2:
            counts["skipped"] += 1
            store.mark_seen(c["url"], "skipped", rec.get("skip_reason") or "관련 낮음", today.isoformat())
            continue
        source_text = post["text"] + "\n" + post.get("attachment_text", "")
        out, _ = clean(rec, source_text, today)
        if not out["cats"]:
            out["cats"] = c.get("cats", [])
        out["url"] = post["url"] if c["source_id"].startswith("search:") else c["url"]
        out["sources"] = [c["source_name"]]
        out["relevance"] = rec.get("relevance")
        result = store.upsert(out, today.isoformat())
        counts[result] += 1
        store.mark_seen(c["url"], "kept", out["title"], today.isoformat())
        if counts["read"] % 10 == 0:
            print(f"  read {counts['read']}: new={counts['new']} skipped={counts['skipped']}", file=sys.stderr, flush=True)
        time.sleep(0.2)

    store.prune(today)
    health["counts"] = counts
    health["ai"] = ai.usage.as_dict()
    health["ai"]["mode"] = getattr(ai, "mode", "api")
    store.save(now.strftime("%Y-%m-%d %H:%M"), health)
    print(f"done: {counts} ai={health['ai']}", file=sys.stderr)
    return 0


def _make_ai(profile, today):
    from .ai import make_ai
    return make_ai(profile, today)


if __name__ == "__main__":
    sys.exit(main())
