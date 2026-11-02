"""Cheap checks done in code before any Claude call."""
from __future__ import annotations

import hashlib
import re

# Words in a body that show people can apply for something.
APPLY_RX = re.compile(
    r"(접수\s*기간|신청\s*기간|모집\s*기간|공모\s*기간|응모\s*기간|접수\s*일정|접수\s*마감|신청\s*마감|제출\s*기한|"
    r"지원\s*자격|신청\s*자격|응모\s*자격|참가\s*자격|모집\s*대상|지원\s*대상|공모\s*요강|모집\s*요강|제출\s*서류|"
    r"신청\s*방법|접수\s*방법|응모\s*방법|"
    r"deadline|submission|eligib|how to apply|open call|call for)", re.I)

# Titles that are not open calls.
NOT_CALL_TITLE_RX = re.compile(
    r"(채용|입찰|계약직|기간제|공무직|직원\s*모집|인턴\s*모집|"
    r"결과\s*(발표|안내|공고|알림)|선정\s*(결과|자\s*발표|작\s*발표|자\s*명단|자\s*공고)|합격자|당선작|수상작|심사\s*결과|"
    r"최종\s*선정|선정\s*안내|명단\s*공개|"
    r"관람\s*안내|공연\s*안내|프로그램북|티켓|예매|휴관|휴무|운영\s*시간|"
    r"보도자료|\[?(연합뉴스|뉴스|기사)\]|언론|감사\s*안내|정기\s*종합감사|사례집|"
    r"개인정보|처리방침|청렴|윤리|부패|이해충돌|"
    r"대관\s*(안내|신청|공고)|정기대관)")


LIFE_TITLE_RX = re.compile(r"(모집|신청|지원|입주자|공급|청약|접수|수당|바우처|대출|월세|전세|임대)")


def looks_like_call(title: str, body: str, board: str = "art") -> tuple[bool, str]:
    """True if the post is worth sending to Claude. Second value is the reason when skipped."""
    t = title or ""
    if NOT_CALL_TITLE_RX.search(t):
        return False, "제목상 모집 공고 아님"
    text = (body or "")[:15000]
    if APPLY_RX.search(text) or APPLY_RX.search(t):
        return True, ""
    if re.search(r"(공모|모집|지원\s*사업|레지던시|입주|open call|competition|award)", t, re.I):
        return True, ""  # title clearly says it, body may be in an image or attachment
    if board == "life" and LIFE_TITLE_RX.search(t):
        return True, ""  # housing / youth notices often put everything in an attached file
    return False, "본문에 신청·접수 관련 내용 없음"


DATE_RX = re.compile(
    r"(20\d\d\s*[.\-/년]\s*\d{1,2}\s*[.\-/월]\s*\d{1,2}\s*일?|"
    r"(?<!\d)\d{1,2}\s*월\s*\d{1,2}\s*일|"
    r"(?<![\d.])\d{1,2}\s*\.\s*\d{1,2}\s*\.?\s*\((?:월|화|수|목|금|토|일)\)|"
    r"\d{1,2}\s*:\s*\d{2}\s*까지|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+20\d\d)")


def date_fingerprint(text: str) -> str:
    """Hash of the date expressions in a page. Ignores view counters and other noise,
    changes when a deadline, period or schedule in the notice is edited."""
    found = sorted({re.sub(r"\s+", "", m.group(0)) for m in DATE_RX.finditer(text or "")})
    return hashlib.sha1("|".join(found).encode()).hexdigest()[:16] if found else ""
