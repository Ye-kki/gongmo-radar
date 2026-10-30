"""Daily run.

1. Collect new post links from boards (code only).
2. Optionally discover calls by web search (Claude, chosen weekdays).
3. Open each new post and drop the ones that are clearly not open calls (code only).
4. Re-open live calls and re-read only those whose dates changed (code only to detect).
5. Send the remaining posts to Claude in small batches, validate, save.

Usage:
  python -m radar.run                  # full run
  python -m radar.run --dry-run        # list new candidate posts only, no AI calls
  python -m radar.run --only bizinfo   # one source ("manual" = only config/manual.yaml)
  python -m radar.run --discover       # force web-search discovery today
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from .collect import extract_links, find_boards, keyword_match
from .detail import read_post
from .fetch import Fetcher, FetchError, RobotsBlocked
from .prefilter import date_fingerprint, looks_like_call
from .store import Store, normalize_url
from .validate import clean

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
BATCH = 6
FIRST_RUN_TAKE = 12      # a newly added board: read only its newest posts, mark the rest as seen
RECHECK_LIMIT = 60       # live calls re-opened per day to look for changed dates


def load(name):
    return yaml.safe_load((ROOT / "config" / name).read_text("utf-8"))


def main(argv=None, ai_factory=None, fetcher=None, data_dir=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--no-discover", action="store_true")
    ap.add_argument("--max-new", type=int, default=150, help="하루에 Claude에게 보낼 최대 게시글 수 (사용량 상한)")
    ap.add_argument("--max-fetch", type=int, default=500, help="하루에 열어볼 최대 게시글 수")
    ap.add_argument("--budget-min", type=float, default=45, help="이 시간(분)이 지나면 멈추고 저장")
    ap.add_argument("--no-recheck", action="store_true")
    args = ap.parse_args(argv)

    started = time.monotonic()
    over_time = lambda: time.monotonic() - started > args.budget_min * 60  # noqa: E731
    now = datetime.now(KST)
    today = now.date()
    sources_cfg, profile, disc = load("sources.yaml"), load("profile.yaml"), load("discovery.yaml")
    store = Store(Path(data_dir) if data_dir else ROOT / "data")
    fetcher = fetcher or Fetcher()
    health = {"runAt": now.strftime("%Y-%m-%d %H:%M"), "sources": [], "discovery": [], "counts": {}}
    counts = {"candidates": 0, "fetched": 0, "filtered": 0, "sent": 0, "same": 0, "new": 0, "updated": 0,
              "skipped": 0, "read_failed": 0, "over_limit": 0, "baseline": 0, "rechecked": 0, "changed": 0}

    # 1) board links
    candidates: list[dict] = []
    for src in sources_cfg["sources"]:
        if src.get("enabled") is False or (args.only and src["id"] != args.only):
            continue
        h = {"id": src["id"], "name": src["name"], "url": src["url"], "status": "ok", "links": 0, "new": 0,
             "board": src.get("board", "art")}
        try:
            _scan_board(src, src["url"], fetcher, store, sources_cfg, candidates, counts, h, today)
        except RobotsBlocked as e:
            h["status"], h["detail"] = "robots", str(e)
        except FetchError as e:
            h["status"], h["detail"] = "error", str(e)[:200]
        except Exception as e:  # parsing bug in one source must not stop the run
            h["status"], h["detail"] = "error", f"{type(e).__name__}: {e}"[:200]
        health["sources"].append(h)
        print(f"[{h['status']:>6}] {src['id']}: links={h['links']} new={h['new']}", file=sys.stderr)

    # 1a) institution homepages: find their notice boards automatically
    for org in _load_orgs(data_dir):
        if org.get("enabled") is False or (args.only and args.only not in (org["id"], "orgs")):
            continue
        if time.monotonic() - started > args.budget_min * 60 * 0.4:  # leave most of the time for reading posts
            health["sources"].append({"id": org["id"], "name": org["name"], "url": org["home"], "status": "skipped",
                                      "links": 0, "new": 0, "board": "art", "kind": "org", "detail": "시간 부족으로 오늘은 건너뜀"})
            continue
        src = {"id": org["id"], "name": org["name"], "cats": ["art", "local"] if org.get("type") == "기초" else ["art"],
               "region": org.get("region", "전국"), "filter": True, "board": "art", "post_like": True, "first_take": 5}
        h = {"id": org["id"], "name": org["name"], "url": org["home"], "status": "ok", "links": 0, "new": 0,
             "board": "art", "kind": "org"}
        try:
            boards = [org["board_url"]] if org.get("board_url") else _org_boards(org, fetcher, store, today)
            if not boards:
                h["status"], h["detail"] = "empty", "홈페이지에서 공지·공모 게시판을 찾지 못함. orgs.yaml에 board_url을 적어주세요"
            for b in boards:
                _scan_board(src, b, fetcher, store, sources_cfg, candidates, counts, h, today)
            if boards:
                h["url"] = boards[0]
        except RobotsBlocked as e:
            h["status"], h["detail"] = "robots", str(e)
        except FetchError as e:
            h["status"], h["detail"] = "error", str(e)[:200]
        except Exception as e:
            h["status"], h["detail"] = "error", f"{type(e).__name__}: {e}"[:200]
        health["sources"].append(h)
        print(f"[{h['status']:>6}] {org['id']}: links={h['links']} new={h['new']}", file=sys.stderr)

    # 1b) links added by hand
    manual_path = (Path(data_dir).parent if data_dir else ROOT) / "config" / "manual.yaml"
    if manual_path.exists() and (not args.only or args.only == "manual"):
        for u in (yaml.safe_load(manual_path.read_text("utf-8")) or {}).get("urls") or []:
            text, board = "", "art"
            if isinstance(u, dict):
                u, text, board = u.get("url", ""), (u.get("text") or ""), (u.get("board") or "art")
            if isinstance(u, str) and u.startswith("http") and not store.is_seen(u):
                candidates.insert(0, {"title": "", "url": u.strip(), "source_id": "manual", "board": board,
                                      "source_name": "직접 추가", "cats": [], "region": "전국",
                                      "pasted_text": text.strip()})

    if args.dry_run:
        for c in candidates:
            print(f"{c['source_id']}\t{c['title']}\t{c['url']}")
        return 0

    ai = (ai_factory or _make_ai)(profile, today.isoformat())

    # 2) discovery by web search
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
                                   "board": q.get("board", "art"), "search_hint": f})
            health["discovery"].append({"id": q["id"], "found": len(found), "new": n_new})
    counts["candidates"] = len(candidates)

    # 3) open posts, filter in code
    queue: list[tuple[dict, dict]] = []
    for c in candidates:
        if len(queue) >= args.max_new or counts["fetched"] >= args.max_fetch or over_time():
            counts["over_limit"] += 1
            continue
        try:
            post = read_post(fetcher, c["url"])
            counts["fetched"] += 1
            if c.get("pasted_text") and len(post["text"]) < 400:
                post["text"] = (post["text"] + "\n\n[직접 붙여넣은 공고 내용]\n" + c["pasted_text"]).strip()
        except Exception as e:
            if c.get("pasted_text"):
                post = {"url": c["url"], "text": c["pasted_text"], "attachments": [], "attachment_text": ""}
            else:
                counts["read_failed"] += 1
                health.setdefault("read_errors", []).append(f"{c['source_name']}: {c['url'][:90]} → {str(e)[:120]}")
                health["read_errors"] = health["read_errors"][:30]
                if c["source_id"].startswith("search:"):
                    store.mark_seen(c["url"], "failed", str(e), today.isoformat())
                continue
        full = post["text"] + "\n" + post.get("attachment_text", "")
        if len(full.strip()) < 80:
            counts["read_failed"] += 1
            store.mark_seen(c["url"], "skipped", "본문이 비어 있음", today.isoformat())
            continue
        if c["source_id"] not in ("manual",) and not c["source_id"].startswith("search:"):
            ok, why = looks_like_call(c.get("title", ""), full)
            if not ok:
                counts["filtered"] += 1
                store.mark_seen(c["url"], "filtered", why, today.isoformat())
                continue
        c["fp"] = date_fingerprint(full)
        queue.append((post, c))

    # 4) live calls whose dates may have changed
    if not args.no_recheck and not args.only:
        live = [x for x in store.calls.values()
                if x.get("fp") and (not x.get("deadline") or x["deadline"] >= today.isoformat())
                and "직접 추가" not in (x.get("sources") or [])]
        live.sort(key=lambda x: x.get("deadline") or "9999")
        for x in live[:RECHECK_LIMIT]:
            if over_time() or len(queue) >= args.max_new:
                break
            try:
                post = read_post(fetcher, x["url"])
            except Exception:
                continue
            counts["rechecked"] += 1
            fp = date_fingerprint(post["text"] + "\n" + post.get("attachment_text", ""))
            if fp and fp != x["fp"]:
                counts["changed"] += 1
                queue.append((post, {"title": x["title"], "url": x["url"], "source_id": "recheck",
                                     "source_name": (x.get("sources") or ["재확인"])[0], "cats": x.get("cats", []),
                                     "region": x.get("region", "전국"), "board": x.get("board", "art"),
                                     "fp": fp, "recheck": True}))

    # 5) Claude, in batches
    fails = 0
    for i in range(0, len(queue), BATCH):
        if over_time():
            counts["over_limit"] += len(queue) - i
            break
        chunk = queue[i:i + BATCH]
        results = _judge(ai, chunk)
        if results is None:
            fails += 1
            if fails >= 3:
                counts["aborted"] = "AI 호출이 연속 3번 실패해 중단 (토큰·키 확인 필요)"
                break
            continue
        fails = 0
        counts["sent"] += len(chunk)
        for j, (post, c) in enumerate(chunk):
            rec = results.get(j)
            if rec is None:
                continue  # not answered: tried again next run
            _apply(rec, post, c, store, today, counts)
        print(f"  sent {counts['sent']}: new={counts['new']} skipped={counts['skipped']}", file=sys.stderr, flush=True)

    store.prune(today)
    health["counts"] = counts
    health["ai"] = ai.usage.as_dict()
    health["ai"]["mode"] = getattr(ai, "mode", "api")
    store.save(now.strftime("%Y-%m-%d %H:%M"), health)
    print(f"done: {counts} ai={health['ai']}", file=sys.stderr)
    return 0


def _scan_board(src, url, fetcher, store, sources_cfg, candidates, counts, h, today):
    page = fetcher.get(url)
    links = extract_links(page.text, page.url, src)
    h["links"] += len(links)
    if not links and h["status"] == "ok":
        h["status"] = "empty"
        h["detail"] = "목록에서 게시글 링크를 찾지 못함. 자바스크립트로 그리는 페이지이거나 link_regex 확인 필요"
    elif links and h["status"] == "empty":
        h["status"] = "ok"
        h.pop("detail", None)
    state_key = src["id"]
    first_run = state_key not in store.sources_state and not (links and store.known_host(links[0]["url"]))
    taken = 0
    for ln in links:
        if src.get("filter") and not keyword_match(ln["title"], src.get("title_keywords") or sources_cfg["title_keywords"]):
            continue
        if store.is_seen(ln["url"]) or any(c["url"] == ln["url"] for c in candidates):
            continue
        if first_run and taken >= src.get("first_take", FIRST_RUN_TAKE):
            store.mark_seen(ln["url"], "baseline", "첫 실행 이전 글", today.isoformat())
            counts["baseline"] += 1
            continue
        taken += 1
        h["new"] += 1
        candidates.append({**ln, "source_id": src["id"], "source_name": src["name"],
                           "cats": src.get("cats", []), "region": src.get("region", "전국"),
                           "board": src.get("board", "art")})
    if links:
        store.sources_state.setdefault(state_key, {})["since"] = store.sources_state.get(state_key, {}).get(
            "since", today.isoformat())


def _org_boards(org, fetcher, store, today):
    st = store.sources_state.setdefault(org["id"], {})
    checked = st.get("boards_checked")
    if st.get("boards") and checked and (today - date.fromisoformat(checked)).days < 14:
        return st["boards"]
    page = fetcher.get(org["home"])
    boards = find_boards(page.text, page.url)
    st["boards"], st["boards_checked"] = boards, today.isoformat()
    return boards


def _load_orgs(data_dir):
    path = (Path(data_dir).parent if data_dir else ROOT) / "config" / "orgs.yaml"
    if not path.exists():
        return []
    return (yaml.safe_load(path.read_text("utf-8")) or {}).get("orgs") or []


def _judge(ai, chunk):
    if hasattr(ai, "extract_batch"):
        return ai.extract_batch(chunk)
    out = {}
    for j, (post, c) in enumerate(chunk):  # simple backends (tests) without batching
        rec = ai.extract(post, c)
        if rec is None:
            return None
        out[j] = rec
    return out


def _apply(rec: dict, post: dict, c: dict, store: Store, today: date, counts: dict):
    if c.get("recheck"):
        if not rec.get("is_open_call"):
            return
    elif not rec.get("is_open_call") or (rec.get("relevance") or 0) < 2:
        counts["skipped"] += 1
        store.mark_seen(c["url"], "skipped", rec.get("skip_reason") or "관련 낮음", today.isoformat())
        return
    source_text = post["text"] + "\n" + post.get("attachment_text", "")
    out, _ = clean(rec, source_text, today)
    if not out["cats"]:
        out["cats"] = c.get("cats", [])
    out["url"] = post["url"] if c["source_id"].startswith("search:") else c["url"]
    out["sources"] = [c["source_name"]]
    out["relevance"] = rec.get("relevance")
    out["board"] = c.get("board", "art")
    out["fp"] = c.get("fp", "")
    result = store.upsert(out, today.isoformat(), force=bool(c.get("recheck")))
    counts[result] += 1
    if c.get("recheck") and result == "updated":
        counts["changed_applied"] = counts.get("changed_applied", 0) + 1
    store.mark_seen(c["url"], "kept", out["title"], today.isoformat())


def _make_ai(profile, today):
    from .ai import make_ai
    return make_ai(profile, today)


if __name__ == "__main__":
    sys.exit(main())
