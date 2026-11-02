"""Offline tests: no network, no API. Run with `pytest -q`."""
from datetime import date
from pathlib import Path
import json

from radar import run as runmod
from radar.collect import extract_links, keyword_match
from radar.detail import page_text
from radar.fetch import Page, FetchError, decode
from radar.store import Store, normalize_url, title_key
from radar.validate import clean, date_in_text

LIST_HTML = """<html><body><nav><a href="/login">로그인</a></nav>
<table><tr><td><a href="/board/view.do?pblancId=PB001&page=2">2026 수원시 관광기념품 공모전 개최 안내</a></td></tr>
<tr><td><a href="javascript:void(0)" onclick="go_view(17777)">청년 디자인 창업 지원사업 모집</a></td></tr>
<tr><td><a href="/board/view.do?pblancId=PB002">2026년 하반기 시설 청소 용역 입찰</a></td></tr>
<tr><td><a href="https://other.example.com/x">외부 링크 배너 광고입니다</a></td></tr>
<tr><td><a href="/files/guide.pdf">첨부 공고문 다운로드</a></td></tr></table></body></html>"""

DETAIL_HTML = """<html><head><title>관광기념품 공모</title></head><body><header>메뉴</header>
<div class="board-view"><h2>2026 수원시 관광기념품 공모전</h2>
<p>접수기간: 2026. 11. 2.(월) ~ 2026. 11. 20.(금) 18:00까지</p>
<p>응모자격: 관광기념품을 개발·생산할 수 있는 개인 또는 사업자</p>
<p>시상: 대상 1점 300만원, 수상작 상품화 및 판로 지원. 결과발표 12월 4일 예정.</p>
<p>문의: 수원시 관광과</p>""" + "<p>세부 내용은 첨부 공고문을 참고하시기 바랍니다.</p>" * 3 + """
<a href="/files/notice.pdf">공고문.pdf</a></div><footer>copyright</footer></body></html>"""


def test_extract_links_filters_nav_external_files_and_builds_onclick():
    src = {"id": "t", "onclick": {"regex": r"go_view\((\d+)\)", "template": "https://site.go.kr/view?sn={id}"}}
    links = extract_links(LIST_HTML, "https://www.site.go.kr/board/list.do", src)
    urls = [l["url"] for l in links]
    assert "https://www.site.go.kr/board/view.do?pblancId=PB001&page=2" in urls
    assert "https://site.go.kr/view?sn=17777" in urls
    assert not any("login" in u or "other.example" in u or u.endswith(".pdf") for u in urls)


def test_link_regex_and_keyword_filter():
    links = extract_links(LIST_HTML, "https://www.site.go.kr/board/list.do", {"link_regex": r"pblancId="})
    assert len(links) == 2
    kws = ["공모", "모집", "지원"]
    kept = [l for l in links if keyword_match(l["title"], kws)]
    assert [l["title"] for l in kept] == ["2026 수원시 관광기념품 공모전 개최 안내"]


def test_page_text_picks_body_block():
    t = page_text(DETAIL_HTML)
    assert "접수기간" in t and "copyright" not in t and "메뉴" not in t


def test_decode_cp949():
    raw = '<meta charset="euc-kr"><p>공모전</p>'.encode("cp949")
    assert "공모전" in decode(raw, None, "text/html")


def test_date_in_text_formats():
    assert date_in_text(date(2026, 11, 20), "2026. 11. 20.(금) 18:00")
    assert date_in_text(date(2026, 11, 20), "11월 20일까지")
    assert date_in_text(date(2026, 12, 11), "Regular: 10 Oct – 11 December 2026")
    assert date_in_text(date(2026, 12, 11), "until Dec 11, 2026")
    assert not date_in_text(date(2026, 11, 21), "2026. 11. 20.(금)")


def _rec(**kw):
    base = {"is_open_call": True, "relevance": 3, "title": "2026 수원시 관광기념품 공모전", "org": "수원시",
            "cats": ["goods", "local"], "region": "경기", "start_date": "2026-11-02", "deadline": "2026-11-20",
            "deadline_evidence": "2026. 11. 20.(금) 18:00까지", "announce_date": "2026-12-04",
            "support": ["prize", "commercial"], "fit": ["pixel"], "summary": "관광기념품 공모", "confidence": "high"}
    base.update(kw)
    return base


def test_clean_accepts_matching_deadline():
    out, problems = clean(_rec(), page_text(DETAIL_HTML), date(2026, 10, 30))
    assert problems == [] and out["deadline"] == "2026-11-20" and out["announceDate"] == "2026-12-04"


def test_clean_flags_unsupported_deadline_and_bad_values():
    out, problems = clean(_rec(deadline="2026-11-25", deadline_evidence="없는 문장", region="화성", cats=["x"]),
                          page_text(DETAIL_HTML), date(2026, 10, 30))
    assert out["needsCheck"] and "마감일 원문 대조 실패" in problems
    assert out["region"] == "전국" and out["cats"] == []
    out, problems = clean(_rec(deadline=None), "본문", date(2026, 10, 30))
    assert "마감일 없음" in problems


def test_store_dedupes_by_url_and_title(tmp_path):
    s = Store(tmp_path)
    a = {"title": "2026 수원시 관광기념품 공모전", "org": "수원시", "url": "https://www.a.kr/v?id=1&utm_source=x",
         "deadline": "2026-11-20", "needsCheck": True}
    assert s.upsert(dict(a), "2026-10-30") == "new"
    assert s.upsert(dict(a, url="https://a.kr/v?id=1"), "2026-10-31") in ("same", "updated")
    b = dict(a, title="[공고] 제3회 2026년 수원시 관광기념품 공모전", url="https://news.kr/1", needsCheck=False)
    assert s.upsert(b, "2026-10-31") == "updated"
    assert len(s.calls) == 1
    only = next(iter(s.calls.values()))
    assert only["url"] == "https://news.kr/1" and only["foundAt"] == "2026-10-30"
    assert normalize_url("https://WWW.a.kr/v/?b=2&a=1&utm_x=1#f") == "https://a.kr/v?a=1&b=2"
    assert title_key("2026년 관광 공모(연장)") == title_key("관광 공모")


class FakeFetcher:
    pages = {
        "https://www.site.go.kr/board/list.do": LIST_HTML,
        "https://www.site.go.kr/board/view.do?pblancId=PB001&page=2": DETAIL_HTML,
    }

    def get(self, url, max_bytes=0):
        if url in self.pages:
            return Page(url=url, text=self.pages[url], content_type="text/html", content=b"")
        raise FetchError("404")


class FakeAI:
    def __init__(self, *a):
        from radar.ai import Usage
        self.usage = Usage()
        self.seen = []

    def extract(self, post, hint):
        self.seen.append(post["url"])
        if "관광기념품" in post["text"]:
            return _rec()
        return {"is_open_call": False, "relevance": 0, "skip_reason": "무관"}

    def discover(self, q, n):
        return []


def test_full_run_offline(tmp_path, monkeypatch):
    cfg = {"title_keywords": ["공모", "모집"], "sources": [
        {"id": "site", "name": "테스트 기관", "url": "https://www.site.go.kr/board/list.do", "cats": ["local"],
         "region": "경기", "filter": True,
         "onclick": {"regex": r"go_view\((\d+)\)", "template": "https://site.go.kr/view?sn={id}"}}]}
    real_load = runmod.load
    monkeypatch.setattr(runmod, "load", lambda n: cfg if n == "sources.yaml" else real_load(n))
    fake = FakeAI()
    rc = runmod.main(["--no-discover"], ai_factory=lambda p, t: fake, fetcher=FakeFetcher(), data_dir=tmp_path)
    assert rc == 0
    data = json.loads((tmp_path / "calls.json").read_text("utf-8"))
    assert len(data["calls"]) == 1 and data["calls"][0]["sources"] == ["테스트 기관"]
    health = json.loads((tmp_path / "health.json").read_text("utf-8"))
    assert health["sources"][0]["status"] == "ok" and health["counts"]["read_failed"] == 1
    # second run: nothing new is read again
    fake2 = FakeAI()
    runmod.main(["--no-discover"], ai_factory=lambda p, t: fake2, fetcher=FakeFetcher(), data_dir=tmp_path)
    assert fake2.seen == []


def test_parse_date_accepts_datetime_prefix():
    from radar.validate import parse_date
    assert parse_date("2026-11-20T18:00:00+09:00") == date(2026, 11, 20)
    assert parse_date("2026-11-20") == date(2026, 11, 20)
    assert parse_date("2026-02-30") is None and parse_date("11월 20일") is None


def test_manual_links_are_read_first(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "manual.yaml").write_text(
        "urls:\n  - https://www.site.go.kr/board/view.do?pblancId=PB001&page=2\n", "utf-8")
    monkeypatch.setattr(runmod, "load", lambda n: {"title_keywords": [], "sources": []} if n == "sources.yaml"
                        else runmod.yaml.safe_load((runmod.ROOT / "config" / n).read_text("utf-8")))
    fake = FakeAI()
    runmod.main(["--no-discover"], ai_factory=lambda p, t: fake, fetcher=FakeFetcher(), data_dir=tmp_path / "data")
    data = json.loads((tmp_path / "data" / "calls.json").read_text("utf-8"))
    assert data["calls"][0]["sources"] == ["직접 추가"]


def test_robots_longest_match():
    from radar.fetch import parse_robots, robots_allows
    rules = parse_robots("User-agent: *\nDisallow: /\nAllow: /community/\n")
    assert robots_allows(rules, "/community/ko/notice/1") and not robots_allows(rules, "/member")
    only_named = parse_robots("User-Agent : *\nDisallow : /\n\nUser-Agent : Yeti\nAllow : /\n")
    assert not robots_allows(only_named, "/sub04/board01_view.htm")


def test_prefilter():
    from radar.prefilter import looks_like_call, date_fingerprint
    assert looks_like_call("2026 굿즈 공모전", "접수기간: 11.1~11.20")[0]
    assert not looks_like_call("2026 굿즈 공모전 결과 발표", "수상작 안내")[0]
    assert not looks_like_call("[연합뉴스] 재단 표창", "기사 본문")[0]
    assert not looks_like_call("정기 종합감사 안내", "감사 기간 11월")[0]
    assert looks_like_call("입주작가 모집", "")[0]
    a = date_fingerprint("접수 2026. 11. 2.(월) ~ 2026. 11. 20.(금) 조회수 81")
    b = date_fingerprint("접수 2026. 11. 2.(월) ~ 2026. 11. 20.(금) 조회수 95")
    c = date_fingerprint("접수 2026. 11. 2.(월) ~ 2026. 11. 27.(금) 조회수 95")
    assert a == b and a != c and a


class BatchAI(FakeAI):
    def __init__(self, *a):
        super().__init__()
        self.batches = []

    def extract_batch(self, items):
        self.batches.append(len(items))
        return {j: (_rec() if "관광기념품" in p["text"] else {"is_open_call": False, "relevance": 0})
                for j, (p, c) in enumerate(items)}


def test_batch_recheck_and_first_run(tmp_path, monkeypatch):
    pages = dict(FakeFetcher.pages)
    list_html = "".join(f'<a href="/board/view.do?pblancId=X{i}">2026 시설 안내 게시글 {i}번</a>' for i in range(20))
    pages["https://www.site.go.kr/new/list.do"] = list_html
    for i in range(20):
        pages[f"https://www.site.go.kr/board/view.do?pblancId=X{i}"] = "<div class='view'>" + "<p>일반 안내 글입니다. 신청 내용 없음.</p>" * 5 + "</div>"

    class F(FakeFetcher):
        def get(self, url, max_bytes=0):
            if url in pages:
                return Page(url=url, text=pages[url], content_type="text/html", content=b"")
            raise FetchError("404")

    cfg = {"title_keywords": ["공모", "모집", "안내"], "sources": [
        {"id": "site", "name": "테스트 기관", "url": "https://www.site.go.kr/board/list.do", "filter": True},
        {"id": "newsite", "name": "새 기관", "url": "https://www.site.go.kr/new/list.do", "filter": True}]}
    real_load = runmod.load
    monkeypatch.setattr(runmod, "load", lambda n: cfg if n == "sources.yaml" else real_load(n))
    ai = BatchAI()
    runmod.main(["--no-discover"], ai_factory=lambda p, t: ai, fetcher=F(), data_dir=tmp_path)
    health = json.loads((tmp_path / "health.json").read_text("utf-8"))
    c = health["counts"]
    # site.go.kr was never seen -> both boards are first runs: newsite keeps 12, baselines 8; all 12 filtered in code
    assert c["baseline"] == 8 and c["filtered"] == 12 and ai.batches == [1]
    data = json.loads((tmp_path / "calls.json").read_text("utf-8"))
    assert data["calls"][0]["fp"] and data["calls"][0]["board"] == "art"

    # deadline edited on the page -> re-read once and the date replaced
    pages["https://www.site.go.kr/board/view.do?pblancId=PB001&page=2"] = DETAIL_HTML.replace("11. 20.(금)", "11. 27.(금)")
    ai2 = BatchAI()
    ai2.extract_batch = lambda items: {0: _rec(deadline="2026-11-27", deadline_evidence="2026. 11. 27.(금) 18:00까지")}
    runmod.main(["--no-discover"], ai_factory=lambda p, t: ai2, fetcher=F(), data_dir=tmp_path)
    health = json.loads((tmp_path / "health.json").read_text("utf-8"))
    assert health["counts"]["changed"] == 1
    data = json.loads((tmp_path / "calls.json").read_text("utf-8"))
    assert data["calls"][0]["deadline"] == "2026-11-27"


def test_find_boards_and_post_like():
    from radar.collect import extract_links, find_boards
    home = ('<a href="/brd/board/314/L/menu/282">공지사항</a><a href="/brd/board/337/L/menu/284">사업공모</a>'
            '<a href="/x/result">공모결과</a><a href="https://other.kr/x">공지</a>')
    assert find_boards(home, "https://www.kcdf.or.kr/main") == [
        "https://www.kcdf.or.kr/brd/board/337/L/menu/284", "https://www.kcdf.or.kr/brd/board/314/L/menu/282"]
    board = ('<a href="/about/intro">재단 소개 페이지 안내</a>'
             '<a href="/board/view?idx=1234">2027 공예 공모전시 참여작가 모집</a>'
             '<a href="/notice/5821">입주작가 정기공모 안내</a>')
    links = extract_links(board, "https://www.ex.or.kr/board/list", {"post_like": True})
    assert [l["url"] for l in links] == ["https://www.ex.or.kr/board/view?idx=1234", "https://www.ex.or.kr/notice/5821"]


def test_life_prefilter_title():
    from radar.prefilter import looks_like_call
    assert looks_like_call("2026년 청년 월세 지원 2차 신청 안내", "", "life")[0]
    assert not looks_like_call("2026년 청년 월세 지원 2차 신청 안내 결과 발표", "", "life")[0]


def test_api_source(monkeypatch):
    import json as _j
    from radar.apisrc import fetch_api

    class P:
        def __init__(self, t): self.text = t

    class F:
        def get(self, url, robots=True):
            assert "SECRET" in url and robots is False
            return P(_j.dumps({"result": {"youthPolicyList": [
                {"plcyNo": "20250101", "plcyNm": "청년 월세 지원", "aplyYmd": "20261101 ~ 20261130", "aplyUrlAddr": ""},
                {"plcyNm": "", "plcyNo": "x"}]}}))
    src = {"api": {"env": "TEST_KEY", "url": "https://x/api?k={key}", "title": ["plcyNm"], "link": ["aplyUrlAddr"],
                   "link_template": "https://y/{plcyNo}", "link_fields": ["plcyNo"]}}
    assert fetch_api(F(), src)[1].startswith("API 키 필요")
    monkeypatch.setenv("TEST_KEY", "SECRET")
    items, problem = fetch_api(F(), src)
    assert problem == "" and len(items) == 1
    assert items[0]["url"] == "https://y/20250101" and "신청 기간: 20261101 ~ 20261130" in items[0]["pasted_text"]

    class Bad:
        def get(self, url, robots=True):
            raise RuntimeError("HTTP 500: " + url)
    assert "SECRET" not in fetch_api(Bad(), src)[1]
