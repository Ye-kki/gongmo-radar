"""Find post links on a board's list page."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

NAV_WORDS = {"로그인", "회원가입", "사이트맵", "이전", "다음", "처음", "마지막", "목록", "더보기", "검색",
             "공지사항", "자주묻는질문", "개인정보처리방침", "이용약관", "홈", "home", "next", "prev", "more"}
FILE_EXT = re.compile(r"\.(pdf|hwp|hwpx|docx?|xlsx?|zip|jpg|jpeg|png|gif)(\?|$)", re.I)


def _site(netloc: str) -> str:
    parts = netloc.lower().split(":")[0].split(".")
    if parts and parts[0] in ("www", "m"):
        parts = parts[1:]
    return ".".join(parts[-3:]) if len(parts) >= 3 and parts[-2] in ("co", "or", "go", "ac", "ne", "re") else ".".join(parts[-2:])


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"^(NEW|N|새글|공지|HOT|D-\d+|D-day|마감임박|접수중|진행중)\s+", "", text, flags=re.I)
    return text


def extract_links(html: str, base_url: str, source: dict) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    base_site = _site(urlsplit(base_url).netloc)
    link_re = re.compile(source["link_regex"]) if source.get("link_regex") else None
    onclick = source.get("onclick")
    oc_re = re.compile(onclick["regex"]) if onclick else None
    out, seen = [], set()
    for a in soup.find_all("a"):
        title = _clean(a.get_text(" ", strip=True) or a.get("title", ""))
        if not title:
            # a link wrapping only an image or icon: use row text
            row = a.find_parent(["tr", "li", "div"])
            title = _clean(row.get_text(" ", strip=True)) if row else ""
        href = (a.get("href") or "").strip()
        url = None
        if oc_re:
            m = oc_re.search((a.get("onclick") or "") + " " + href)
            if m:
                from urllib.parse import quote
                g = [quote(x, safe="") for x in m.groups()]
                url = onclick["template"].format(id=g[0], id2=g[1] if len(g) > 1 else "", id3=g[2] if len(g) > 2 else "")
        if url is None:
            if not href or href.startswith(("#", "mailto:", "tel:")) or href.lower().startswith("javascript"):
                continue
            url = urljoin(base_url, href)
        if not url.startswith("http") or FILE_EXT.search(url):
            continue
        if not link_re and _site(urlsplit(url).netloc) != base_site:
            continue
        if link_re and not link_re.search(url):
            continue
        if len(title) < 6 or title.lower() in NAV_WORDS or len(title) > 300:
            continue
        key = url.split("#")[0]
        if key in seen or key.rstrip("/") == base_url.rstrip("/"):
            continue
        seen.add(key)
        out.append({"title": title[:200], "url": key})
    return out


def keyword_match(title: str, keywords: list[str]) -> bool:
    t = title.lower()
    return any(k.lower() in t for k in keywords)
