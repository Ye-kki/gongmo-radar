"""Sources that publish a JSON API (need a free key, kept in GitHub secrets).

Each item becomes a candidate whose text is the item's own fields, so no page has to be opened.
Field names differ between APIs, so we look for the first field that exists from a list."""
from __future__ import annotations

import json
import os

LABELS = {  # field -> label shown to Claude (keeps the text readable)
    # 온통청년
    "plcyNm": "정책명", "plcyExplnCn": "설명", "plcySprtCn": "지원 내용", "lclsfNm": "대분류", "mclsfNm": "중분류",
    "aplyYmd": "신청 기간", "bizPrdBgngYmd": "사업 시작", "bizPrdEndYmd": "사업 종료", "sprtTrgtMinAge": "최소 나이",
    "sprtTrgtMaxAge": "최대 나이", "sprvsnInstCdNm": "주관 기관", "operInstCdNm": "운영 기관", "plcyAplyMthdCn": "신청 방법",
    "addAplyQlfcCndCn": "추가 자격", "ptcpPrpTrgtCn": "참여 제한", "earnCndSeCd": "소득 조건", "zipCd": "지역 코드",
    "aplyUrlAddr": "신청 주소", "refUrlAddr1": "참고 주소", "plcyKywdNm": "키워드",
    # 기업마당
    "pblancNm": "공고명", "bsnsSumryCn": "사업 요약", "reqstBeginEndDe": "신청 기간", "jrsdInsttNm": "소관 기관",
    "excInsttNm": "수행 기관", "trgetNm": "지원 대상", "pldirSportRealmLclasCodeNm": "지원 분야", "hashtags": "태그",
    "reqstMthPapersCn": "신청 방법", "pblancUrl": "공고 주소", "creatPnttm": "등록일",
}


def _items(obj):
    """Find the longest list of dicts anywhere in the response."""
    best = []
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, list):
            if o and all(isinstance(x, dict) for x in o) and len(o) > len(best):
                best = o
            stack.extend(o)
        elif isinstance(o, dict):
            stack.extend(o.values())
    return best


def _first(it: dict, keys):
    for k in keys:
        v = it.get(k)
        if v not in (None, "", []):
            return str(v).strip()
    return ""


def fetch_api(fetcher, src: dict) -> tuple[list[dict], str]:
    """Returns (candidates, problem). problem is '' when fine."""
    api = src["api"]
    key = os.getenv(api["env"], "").strip()
    if not key:
        return [], f"API 키 필요: GitHub secret {api['env']}"
    try:
        page = fetcher.get(api["url"].format(key=key), robots=False)
        data = json.loads(page.text.strip().lstrip("\ufeff"))
    except Exception as e:  # never let the key reach health.json (public)
        return [], f"{type(e).__name__}: {str(e).replace(key, '***')}"[:200]
    out = []
    for it in _items(data):
        title = _first(it, api["title"])
        link = _first(it, api["link"])
        if link and not link.startswith("http"):
            link = api.get("link_prefix", "") + link
        if not link and api.get("link_template"):
            link = api["link_template"].format(**{k: it.get(k, "") for k in api.get("link_fields", [])})
        if not title or not link.startswith("http"):
            continue
        text = "\n".join(f"{LABELS.get(k, k)}: {str(v).strip()}" for k, v in it.items()
                         if v not in (None, "", []) and len(str(v)) < 3000)
        out.append({"title": title, "url": link, "pasted_text": text, "api_only": True})
    return out, ""
