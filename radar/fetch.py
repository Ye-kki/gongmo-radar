"""HTTP fetching with polite defaults: robots.txt, per-host delay, retries, Korean encodings."""
from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

UA = "GongmoRadar/1.0 (personal open-call tracker; once a day)"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class FetchError(Exception):
    pass


class RobotsBlocked(FetchError):
    pass


@dataclass
class Page:
    url: str
    text: str
    content_type: str
    content: bytes


class Fetcher:
    def __init__(self, delay: float = 2.0, timeout: float = 20.0, retries: int = 2):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": BROWSER_UA, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
                               "From": UA})
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _allowed(self, url: str) -> bool:
        p = urlsplit(url)
        root = f"{p.scheme}://{p.netloc}"
        if root not in self._robots:
            rules = None
            try:
                r = self.s.get(root + "/robots.txt", timeout=10)
                if r.status_code == 200 and "text/html" not in r.headers.get("content-type", ""):
                    rules = parse_robots(r.text)
            except requests.RequestException:
                pass
            self._robots[root] = rules
        rules = self._robots[root]
        path = p.path or "/"
        if p.query:
            path += "?" + p.query
        return True if rules is None else robots_allows(rules, path)

    def _wait(self, host: str):
        last = self._last.get(host)
        if last is not None:
            gap = time.monotonic() - last
            if gap < self.delay:
                time.sleep(self.delay - gap)
        self._last[host] = time.monotonic()

    def get(self, url: str, max_bytes: int = 8_000_000, robots: bool = True) -> Page:
        # robots=False only for official open APIs used with an issued key
        if robots and not self._allowed(url):
            raise RobotsBlocked(f"robots.txt가 수집을 막음: {url}")
        host = urlsplit(url).netloc
        err: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait(host)
            try:
                r = self.s.get(url, timeout=self.timeout, stream=True)
                content = r.raw.read(max_bytes + 1, decode_content=True)
                if len(content) > max_bytes:
                    raise FetchError(f"파일이 너무 큼: {url}")
                if r.status_code >= 500 or r.status_code == 429:
                    raise FetchError(f"HTTP {r.status_code}")
                if r.status_code >= 400:
                    raise FetchError(f"HTTP {r.status_code}: {url}")
                ctype = r.headers.get("content-type", "")
                return Page(url=r.url, text=decode(content, r.encoding, ctype), content_type=ctype, content=content)
            except (requests.RequestException, FetchError) as e:
                err = e
                if isinstance(e, FetchError) and "HTTP 4" in str(e):
                    break
                time.sleep(2 * (attempt + 1))
        raise FetchError(str(err))


def decode(content: bytes, declared: str | None, ctype: str) -> str:
    """Decode bytes, handling the euc-kr/cp949 pages common on Korean public sites."""
    if "html" not in ctype and "text" not in ctype and ctype:
        return ""
    head = content[:3000].decode("ascii", "ignore").lower()
    candidates = []
    for marker in ("charset=", 'charset="', "charset='"):
        i = head.find(marker)
        if i != -1:
            cs = head[i + len(marker):].split('"')[0].split("'")[0].split(";")[0].split(">")[0].strip()
            if cs:
                candidates.append(cs)
    if declared and declared.lower() != "iso-8859-1":
        candidates.append(declared)
    candidates += ["utf-8", "cp949"]
    for cs in candidates:
        cs = {"euc-kr": "cp949", "ks_c_5601-1987": "cp949"}.get(cs, cs)
        try:
            return content.decode(cs)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", "replace")


def parse_robots(text: str) -> list[tuple[str, str]]:
    """Return the (allow|disallow, path) rules that apply to a generic crawler (User-agent: *)."""
    groups, agents, rules, in_rules = [], [], [], False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, val = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if in_rules:
                groups.append((agents, rules))
                agents, rules, in_rules = [], [], False
            agents.append(val.lower())
        elif key in ("allow", "disallow"):
            in_rules = True
            if val or key == "allow":
                rules.append((key, val))
    groups.append((agents, rules))
    picked = [r for a, r in groups if "*" in a]
    return [x for r in picked for x in r]


def _rule_match(pattern: str, path: str) -> bool:
    import re as _re
    if not pattern:
        return False
    rx = _re.escape(pattern).replace(r"\*", ".*")
    if rx.endswith(r"\$"):
        rx = rx[:-2] + "$"
    return _re.match(rx, path) is not None


def robots_allows(rules: list[tuple[str, str]], path: str) -> bool:
    """Longest matching rule wins; Allow wins a tie (RFC 9309)."""
    best_len, allowed = -1, True
    for kind, pat in rules:
        if _rule_match(pat, path):
            n = len(pat)
            if n > best_len or (n == best_len and kind == "allow"):
                best_len, allowed = n, kind == "allow"
    return allowed


class Renderer:
    """Opens a page in a real (headless) browser, for boards whose list is drawn by JavaScript.
    Started only when first needed; silently unavailable if Playwright is not installed."""

    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher
        self._pw = self._browser = None
        self.broken = False
        self.used = 0

    def get(self, url: str, wait_ms: int = 2500) -> Page | None:
        if self.broken or self.used >= 40:  # keep runs short
            return None
        if not self.fetcher._allowed(url):
            raise RobotsBlocked(f"robots.txt가 수집을 막음: {url}")
        try:
            if self._browser is None:
                from playwright.sync_api import sync_playwright
                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch()
            self.fetcher._wait(urlsplit(url).netloc)
            page = self._browser.new_page(user_agent=BROWSER_UA, locale="ko-KR")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(wait_ms)
                html, final = page.content(), page.url
            finally:
                page.close()
            self.used += 1
            return Page(final, html, "text/html", html.encode())
        except RobotsBlocked:
            raise
        except Exception:
            self.broken = self._browser is None  # cannot start at all → stop trying
            return None

    def close(self):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
