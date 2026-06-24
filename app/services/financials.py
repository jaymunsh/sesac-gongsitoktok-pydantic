"""재무 결합 노드 — DART 정형 재무(fnlttSinglAcnt)를 근거(Citation)로 변환.

배경(인제스트_설계확정 §6 발견): 정확한 재무 라인아이템(매출·영업이익)은 RAG로
집기 어렵다(같은 단어 청크가 수십 개). 정형 API가 그 값을 결정적으로 준다 → 1급 근거.
사업보고서는 당기/전기/전전기를 함께 주므로 한 번 호출로 3개년 비교가 가능하다.
"""
from __future__ import annotations

import asyncio
import datetime
import re

from app.ingest import dart
from app.schemas.disclosure import Citation

# 표시할 핵심 계정(account_nm 부분일치)
_KEY_ACCOUNTS = ["매출액", "영업이익", "당기순이익", "자산총계", "부채총계", "자본총계"]

_anchor_cache: dict[str, tuple[int, int] | None] = {}


def fiscal_anchor(corp_code: str) -> tuple[int, int] | None:
    """(기수, 사업연도) 기준점을 **DART 정형재무에서 도출**해 캐시한다(회사당 1회).

    근거: `fnlttSinglAcnt` 응답의 `thstrm_nm`("제 57 기")와 그 사업연도가 함께 온다.
    여기서 (기수, 연도)를 얻으면 임의의 제M기 = year + (M - 기수)로 환산 가능.
    회사별 하드코딩 대신 공시에서 직접 얻으므로 회사 추가 시 코드 변경이 없다.
    데이터가 없으면 None(→ 기수 환산 미적용, graceful).
    """
    if corp_code in _anchor_cache:
        return _anchor_cache[corp_code]
    year, rows = _pick_year(corp_code)
    anchor = None
    if rows and year:
        m = re.search(r"\d+", rows[0].get("thstrm_nm") or "")  # "제 57 기" → 57
        if m:
            anchor = (int(m.group()), int(year))
    _anchor_cache[corp_code] = anchor
    return anchor


def _pick_year(corp_code: str, want: int | None = None) -> tuple[str | None, list[dict]]:
    """사업보고서(11011) 정형재무가 있는 사업연도를 찾는다.

    want(요청 사업연도)가 있으면 그 해를 먼저 시도하고, 데이터가 없으면(예: 아직
    미제출) 최신연도로 graceful 폴백한다 → 기간 질문은 그 해, 미지정은 최신.
    """
    cur = datetime.date.today().year
    candidates = ([want] if want else []) + [cur, cur - 1, cur - 2]
    seen = set()
    for y in candidates:
        if y is None or y in seen:
            continue
        seen.add(y)
        rows = dart.fetch_financials(corp_code, str(y), "11011")
        if rows:
            return str(y), rows
    return None, []


def fetch_financial_citations(corp_code: str, year: int | None = None) -> list[Citation]:
    """핵심 계정을 연결재무제표(CFS) 기준으로 Citation 화. year=요청 사업연도(없으면 최신)."""
    year, rows = _pick_year(corp_code, year)
    if not rows:
        return []
    out: list[Citation] = []
    for row in rows:
        if row.get("fs_div") != "CFS":  # 연결 우선
            continue
        nm = row.get("account_nm", "")
        if not any(k in nm for k in _KEY_ACCOUNTS):
            continue
        cur = row.get("thstrm_amount", "")
        prev = row.get("frmtrm_amount", "")
        # 실제 기수 명칭(예: '제 57 기')을 근거에 담아 writer가 기수를 추측하지 않게 한다.
        cur_nm = " ".join((row.get("thstrm_nm") or "당기").split())
        prev_nm = " ".join((row.get("frmtrm_nm") or "전기").split())
        quote = f"{nm}: {cur_nm} {cur} / {prev_nm} {prev} (단위 원, 연결, {year} 사업보고서 기준)"
        # 응답에 이미 든 rcept_no를 그대로 출처로 연결(추가 호출 없음) → 접수번호·DART 링크 생성.
        # 접수일은 접수번호 앞 8자리(YYYYMMDD).
        rcept = row.get("rcept_no") or None
        out.append(
            Citation(
                chunk_id=f"fin-{corp_code}-{nm}",
                section_title="정형 재무(DART)",
                quote=quote,
                score=1.0,
                kind="table",
                rcept_no=rcept,
                rcept_dt=rcept[:8] if rcept and len(rcept) >= 8 else None,
                report_nm=f"{year} 사업보고서 주요계정",
            )
        )
    return out


async def fetch_financial_citations_async(
    corp_code: str, year: int | None = None
) -> list[Citation]:
    """asyncio 병렬용 — 블로킹 httpx 호출을 스레드로."""
    return await asyncio.to_thread(fetch_financial_citations, corp_code, year)
