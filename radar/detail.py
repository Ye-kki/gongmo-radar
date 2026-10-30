"""Read a post's body text and its PDF attachments."""
from __future__ import annotations

import io
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .fetch import Fetcher, FetchError

BODY_HINTS = re.compile(r"(view|content|cont|board|article|detail|post|bbs|txt|entry)", re.I)
ATTACH_RE = re.compile(r"\.(pdf|hwp|hwpx)(\b|$)", re.I)


def _norm(text: str) -> str:
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def page_text(html: str, limit: int = 12000) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "iframe", "svg"]):
        tag.decompose()
    best, best_len = None, 0
    for el in soup.find_all(["article", "main", "div", "section", "td"]):
        ident = " ".join(el.get("class", [])) + " " + (el.get("id") or "")
        if el.name in ("article", "main") or BODY_HINTS.search(ident):
            n = len(el.get_text(" ", strip=True))
            if n > best_len:
                best, best_len = el, n
    root = best if best is not None and best_len >= 200 else (soup.body or soup)
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = _norm(root.get_text("\n", strip=True))
    if title and title not in text[:300]:
        text = title + "\n" + text
    return text[:limit]


def attachments(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.find_all("a"):
        name = a.get_text(" ", strip=True)
        href = a.get("href") or ""
        if ATTACH_RE.search(name) or ATTACH_RE.search(href):
            url = urljoin(base_url, href) if href and not href.lower().startswith("javascript") else None
            out.append({"name": name[:120] or href[-60:], "url": url})
    return out[:10]


def pdf_text(data: bytes, pages: int = 8, limit: int = 8000) -> str:
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for p in reader.pages[:pages]:
            parts.append(p.extract_text() or "")
        return _norm("\n".join(parts))[:limit]
    except Exception:
        return ""


def read_post(fetcher: Fetcher, url: str) -> dict:
    """Return {'url', 'text', 'attachments', 'attachment_text'} for a post."""
    page = fetcher.get(url)
    if "pdf" in page.content_type:
        return {"url": page.url, "text": pdf_text(page.content), "attachments": [], "attachment_text": ""}
    text = page_text(page.text)
    atts = attachments(page.text, page.url)
    att_text = ""
    for att in atts:
        if att["url"] and (att["name"].lower().endswith(".pdf") or ".pdf" in att["url"].lower()):
            try:
                f = fetcher.get(att["url"])
                if f.content[:4] == b"%PDF":
                    att_text = pdf_text(f.content)
                    if att_text:
                        break
            except FetchError:
                continue
    return {"url": page.url, "text": text, "attachments": atts, "attachment_text": att_text}
