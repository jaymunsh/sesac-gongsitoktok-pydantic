"""재무 결합 노드 — DART 정형 재무(fnlttSinglAcnt)를 근거(Citation)로 변환.

배경(인제스트_설계확정 §6 발견): 정확한 재무 라인아이템(매출·영업이익)은 RAG로
집기 어렵다(같은 단어 청크가 수십 개). 정형 API가 그 값을 결정적으로 준다 → 1급 근거.
사업보고서는 당기/전기/전전기를 함께 주므로 한 번 호출로 3개년 비교가 가능하다.
"""
from __future__ import annotations

import asyncio
import datetime

from app.ingest import dart
from app.schemas.disclosure import Citation

# 표시할 핵심 계정(account_nm 부분일치)
_KEY_ACCOUNTS = ["매출액", "영업이익", "당기순이익", "자산총계", "부채총계", "자본총계"]


def _pick_year(corp_code: str) -> tuple[str | None, list[dict]]:
    """데이터 있는 최신 사업연도(사업보고서)를 찾는다."""
    cur = datetime.date.today().year
    for y in (cur, cur - 1, cur - 2):
        rows = dart.fetch_financials(corp_code, str(y), "11011")
        if rows:
            return str(y), rows
    return None, []


def fetch_financial_citations(corp_code: str) -> list[Citation]:
    """핵심 계정을 연결재무제표(CFS) 기준으로 Citation 화."""
    year, rows = _pick_year(corp_code)
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


async def fetch_financial_citations_async(corp_code: str) -> list[Citation]:
    """asyncio 병렬용 — 블로킹 httpx 호출을 스레드로."""
    return await asyncio.to_thread(fetch_financial_citations, corp_code)
