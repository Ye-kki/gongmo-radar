"""JSON files in data/: calls.json (what the page shows), seen.json (posts already judged), health.json."""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING = re.compile(r"^(utm_|fbclid|gclid|ref$|page$|pageIndex$|currentPage$|cpage$)", re.I)


def normalize_url(url: str) -> str:
    p = urlsplit(url.strip())
    q = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=False) if not TRACKING.match(k))
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return urlunsplit(("https", netloc, p.path.rstrip("/"), urlencode(q), ""))


def title_key(title: str) -> str:
    t = re.sub(r"\(.*?\)|\[.*?\]|<.*?>", " ", title or "")
    t = re.sub(r"20\d\d년?|제\s?\d+\s?회|\d+기", " ", t)
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", t).lower()


def call_id(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode()).hexdigest()[:12]


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.calls: dict[str, dict] = {c["id"]: c for c in self._load("calls.json", {"calls": []})["calls"]}
        self.seen: dict[str, dict] = self._load("seen.json", {})
        self.sources_state: dict[str, dict] = self._load("sources.json", {})

    def _load(self, name, default):
        p = self.root / name
        if p.exists():
            return json.loads(p.read_text("utf-8"))
        return default

    def _save(self, name, obj):
        (self.root / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", "utf-8")

    def is_seen(self, url: str) -> bool:
        return normalize_url(url) in self.seen

    def mark_seen(self, url: str, status: str, reason: str, today: str):
        self.seen[normalize_url(url)] = {"status": status, "reason": (reason or "")[:120], "date": today}

    def find_duplicate(self, rec: dict) -> dict | None:
        k = title_key(rec["title"])
        nurl = normalize_url(rec["url"])
        for c in self.calls.values():
            if normalize_url(c["url"]) == nurl:
                return c
            if k and difflib.SequenceMatcher(None, k, title_key(c["title"])).ratio() >= 0.88:
                if not rec.get("deadline") or not c.get("deadline") or rec["deadline"] == c["deadline"] \
                        or (rec.get("org") and rec.get("org") == c.get("org")):
                    return c
        return None

    def known_host(self, url: str) -> bool:
        host = urlsplit(normalize_url(url)).netloc
        return any(urlsplit(k).netloc == host for k in self.seen)

    def upsert(self, rec: dict, today: str, force: bool = False) -> str:
        """Add or merge a call. Returns 'new', 'updated' or 'same'.
        force=True (a re-read after the notice changed) lets the new values replace the old ones."""
        dup = self.find_duplicate(rec)
        if dup is None:
            rec["id"] = call_id(rec["url"])
            rec["foundAt"] = today
            rec["sources"] = rec.get("sources", [])
            self.calls[rec["id"]] = rec
            return "new"
        # Prefer the version that passed checks; keep first-seen date and id.
        changed = False
        better = force or (dup.get("needsCheck") and not rec.get("needsCheck")) or \
                 (not dup.get("deadline") and rec.get("deadline"))
        for k, v in rec.items():
            if k in ("id", "foundAt", "sources", "url"):
                continue
            if v in (None, "", []):
                continue
            if better or dup.get(k) in (None, "", []):
                if dup.get(k) != v:
                    dup[k] = v
                    changed = True
        for s in rec.get("sources", []):
            if s not in dup.setdefault("sources", []):
                dup["sources"].append(s)
        if better and not force and rec["url"] != dup["url"]:
            dup.setdefault("altUrls", []).append(dup["url"])
            dup["url"] = rec["url"]
        if changed:
            dup["updatedAt"] = today
        return "updated" if changed else "same"

    def prune(self, today: date, keep_days: int = 60):
        cut = (today - timedelta(days=keep_days)).isoformat()
        self.calls = {k: c for k, c in self.calls.items() if not c.get("deadline") or c["deadline"] >= cut}
        seen_cut = (today - timedelta(days=365)).isoformat()
        self.seen = {k: v for k, v in self.seen.items() if v.get("date", "") >= seen_cut}

    def save(self, updated_at: str, health: dict):
        calls = sorted(self.calls.values(), key=lambda c: (c.get("deadline") or "9999", c["title"]))
        self._save("calls.json", {"updatedAt": updated_at, "calls": calls})
        self._save("seen.json", self.seen)
        self._save("sources.json", self.sources_state)
        self._save("health.json", health)
