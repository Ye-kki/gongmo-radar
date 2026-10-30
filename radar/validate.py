"""Check AI-extracted fields against the source text before they reach the page."""
from __future__ import annotations

import re
from datetime import date, timedelta

from .ai import CATS, FITS, REGIONS, SUPPORT


def parse_date(value) -> date | None:
    if not isinstance(value, str):
        return None
    m = re.match(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})(?:$|[T ]|\s)", value)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def date_in_text(d: date, text: str) -> bool:
    """True if the text mentions this month and day in a common Korean or numeric form."""
    t = _squash(text)
    m, dd = d.month, d.day
    pats = [
        rf"{m}월{dd}일", rf"0?{m}\.0?{dd}(?!\d)", rf"0?{m}/0?{dd}(?!\d)", rf"0?{m}-0?{dd}(?!\d)",
        rf"(?<!\d){d.year}{m:02d}{dd:02d}(?!\d)",
    ]
    if any(re.search(p, t) for p in pats):
        return True
    months = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
              "october", "november", "december"]
    name = months[m - 1]
    low = text.lower()
    return bool(re.search(rf"\b{name[:3]}[a-z]*\.?\s*{dd}(st|nd|rd|th)?\b", low)
                or re.search(rf"\b{dd}(st|nd|rd|th)?\s+{name[:3]}[a-z]*\b", low))


def clean(rec: dict, source_text: str, today: date) -> tuple[dict, list[str]]:
    """Normalize a record and return (record, problems). Problems mark the call as '확인 필요'."""
    problems: list[str] = []
    out = {
        "title": (rec.get("title") or "").strip()[:200],
        "org": (rec.get("org") or "").strip()[:100],
        "cats": [c for c in rec.get("cats") or [] if c in CATS],
        "region": rec.get("region") if rec.get("region") in REGIONS else "전국",
        "support": [s for s in rec.get("support") or [] if s in SUPPORT],
        "supportAmount": rec.get("support_amount"),
        "fit": [f for f in rec.get("fit") or [] if f in FITS],
        "individualOk": rec.get("individual_ok"),
        "ageLimit": rec.get("age_limit") or None,
        "eligibility": rec.get("eligibility"),
        "summary": (rec.get("summary") or "").strip()[:400],
        "deadlineNote": rec.get("deadline_note"),
        "confidence": rec.get("confidence", "low"),
    }
    lo, hi = today - timedelta(days=400), today + timedelta(days=550)

    for key, src in (("startDate", "start_date"), ("deadline", "deadline"), ("announceDate", "announce_date")):
        raw = rec.get(src)
        d = parse_date(raw)
        if raw and d is None:
            problems.append(f"{src} 형식 오류")
        if d and not (lo <= d <= hi):
            problems.append(f"{src} 범위 이상")
            d = None
        out[key] = d.isoformat() if d else None

    dl = parse_date(out["deadline"])
    if dl is None:
        problems.append("마감일 없음")
    else:
        ev = rec.get("deadline_evidence") or ""
        ev_ok = bool(ev) and _squash(ev)[:40] in _squash(source_text)
        if not (ev_ok and date_in_text(dl, ev)) and not date_in_text(dl, source_text):
            problems.append("마감일 원문 대조 실패")
    sd = parse_date(out["startDate"])
    if sd and dl and sd > dl:
        problems.append("시작일이 마감일보다 늦음")
    ad = parse_date(out["announceDate"])
    if ad and not date_in_text(ad, source_text):
        out["announceDate"] = None
    if out["confidence"] == "low":
        problems.append("AI 확신 낮음")
    if not out["title"]:
        problems.append("제목 없음")
    out["needsCheck"] = bool(problems)
    out["checkReasons"] = problems
    return out, problems
