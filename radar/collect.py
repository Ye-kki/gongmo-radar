"""Find post links on a board's list page."""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urljoin, urlsplit

from bs4 import BeautifulSoup

NAV_WORDS = {"로그인", "회원가입", "사이트맵", "이전", "다음", "처음", "마지막", "목록", "더보기", "검색",
             "공지사항", "자주묻는질문", "개인정보처리방침", "이용약관", "홈", "home", "next", "prev", "more"}
POST_ID_RX = re.compile(r"(\d{3,}|[?&](idx|seq|no|id|num|nttId|bbsId|articleNo|wr_id|uid)=\w+)", re.I)
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
        if source.get("post_like") and not POST_ID_RX.search(url.split("#")[0][len(urlsplit(url).scheme) + 3:].split("/", 1)[-1]):
            continue  # auto-found boards: keep only links that carry a post number
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


BOARD_WORD_RX = re.compile(r"(공지|공모|모집|공고|새\s*소식|알림|지원\s*사업|재단\s*소식|입주\s*작가)")
BOARD_SKIP_RX = re.compile(r"(결과|채용|입찰|계약|FAQ|자주|정보\s*공개|감사|민원|칭찬|고객|규정|경영|인권|윤리|청렴|보도|언론|뉴스레터|갤러리|사진|영상|자료실)")
BOARD_RANK = ["공모소식", "지원사업공모", "사업공모", "지원사업공고", "입주작가공모", "공모사업", "공모안내", "공모", "모집공고",
              "공모·모집", "공모/모집", "지원사업", "공고", "일반공고", "공지사항", "공지", "알림마당", "알림", "새소식", "재단소식", "모집"]
SCRIPT_URL_RX = re.compile(r"""['"]((?:https?://|/)[^'"\s]+|[\w./-]+\.(?:do|php|jsp|asp|aspx|html?)(?:\?[^'"\s]*)?)['"]""")


def _script_url(a) -> str:
    """URL from href, or from onclick / javascript: href like goPage('/notice/list.do')."""
    href = (a.get("href") or "").strip()
    if href and not href.startswith("#") and not href.lower().startswith("javascript"):
        return href
    m = SCRIPT_URL_RX.search((a.get("onclick") or "") + " " + href)
    return m.group(1) if m else ""


def board_candidates(html: str, base_url: str, limit: int = 6) -> list[tuple[str, str]]:
    """Links on an institution page that look like notice / open-call board menus, best first."""
    soup = BeautifulSoup(html, "lxml")
    base_site = _site(urlsplit(base_url).netloc)
    found: dict[str, tuple[int, str]] = {}
    for a in soup.find_all("a"):
        name = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if not name or len(name) > 16 or not BOARD_WORD_RX.search(name) or BOARD_SKIP_RX.search(name):
            continue
        href = _script_url(a)
        if not href or href.startswith("mailto:"):
            continue
        url = urljoin(base_url, href).split("#")[0]
        if not url.startswith("http") or _site(urlsplit(url).netloc) != base_site or FILE_EXT.search(url):
            continue
        key = re.sub(r"\s+", "", name)
        rank = BOARD_RANK.index(key) if key in BOARD_RANK else len(BOARD_RANK) + (0 if "공모" in key else 5)
        if url not in found or rank < found[url][0]:
            found[url] = (rank, name)
    return [(u, n) for u, (r, n) in sorted(found.items(), key=lambda x: x[1][0])][:limit]


def find_boards(html: str, base_url: str, limit: int = 2) -> list[str]:
    """Back-compat: board menu URLs only (no scoring)."""
    return [u for u, _ in board_candidates(html, base_url)][:limit]


ID_PARAM_RX = re.compile(r"^(idx|seq|no|id|num|nttid|nttsn|wr_id|uid|bbsidx|bidx|bbidx|board_?no|article_?no|post_?no|"
                         r"brd_?idx|bno|b_?idx|list_?no|data_?id|pk|contentid|key)$", re.I)


def _signature(url: str):
    """Shape of a post URL: path with numbers wildcarded + the id parameter name."""
    p = urlsplit(url)
    path = re.sub(r"\d{2,}", "#", p.path)
    params = [k for k, _ in parse_qsl(p.query, keep_blank_values=True)]
    idp = next((k for k in params if ID_PARAM_RX.match(k)), None)
    if not idp and not re.search(r"/\d{3,}(/|$)", p.path):
        return None
    return (p.netloc, path, idp)


def score_board(html: str, url: str, exclude: set[str] = frozenset()) -> tuple[int, str]:
    """How many post-like links this page has, and a link_regex matching them."""
    soup = BeautifulSoup(html, "lxml")
    base_site = _site(urlsplit(url).netloc)
    groups: dict[tuple, set] = {}
    for a in soup.find_all("a"):
        title = _clean(a.get_text(" ", strip=True))
        if len(title) < 8 or len(title) > 200:
            continue
        href = _script_url(a)
        if not href:
            continue
        u = urljoin(url, href).split("#")[0]
        if not u.startswith("http") or _site(urlsplit(u).netloc) != base_site or u in exclude or FILE_EXT.search(u):
            continue
        sig = _signature(u)
        if sig:
            groups.setdefault(sig, set()).add(u)
    if not groups:
        return 0, ""
    sig, urls = max(groups.items(), key=lambda kv: len(kv[1]))
    _, path, idp = sig
    rx = re.escape(path).replace("\\#", "#").replace("#", r"\d+")
    rx = rx + (r"\?(?:.*&)?" + re.escape(idp) + r"=\w+" if idp else "")
    return len(urls), rx
