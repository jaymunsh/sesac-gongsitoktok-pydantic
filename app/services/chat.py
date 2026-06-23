"""챗 오케스트레이션 — router → 검색(asyncio 병렬) → writer → verifier(샘플링).

보고서 §4-2 런타임 설계의 프로그램적 핸드오프. 검색은 코드가 끝내고(retrieve-then-read)
근거를 프롬프트로 넣는다. 부분 실패는 graceful(나머지 근거로 계속).
"""
from __future__ import annotations

import asyncio
import datetime
import hashlib
import logging

from app.agents.agents import (
    format_citations,
    qa_agent,
    router_agent,
    summary_agent,
    verifier_agent,
)
from app.config import get_settings
from app.schemas.disclosure import (
    ChatIntent,
    ChatRequest,
    ChatResponse,
    Citation,
    QAResult,
    RouterResult,
    SummaryResult,
    VerificationResult,
    VerificationVerdict,
)
from app.services import macro
from app.services.financials import fetch_financial_citations_async
from app.rag.vectorstore import get_vector_store

log = logging.getLogger(__name__)


async def _retrieve(
    corp_code: str, r: RouterResult, *, summary: bool = False
) -> list[Citation]:
    """corpus 검색 + (필요시) 재무 결합을 asyncio 병렬로. 부분 실패 graceful.

    summary 트랙은 서술 prose가 필요하므로 본문(text) 청크를 우선한다
    (회사/사업 개요 질의가 빈약한 수치 표에 끌려가는 것 방지).
    """
    s = get_settings()
    store = get_vector_store()
    query = r.search_query or ""
    where = _date_where(r)  # 사업연도(bsns_year) 필터

    async def corpus() -> list[Citation]:
        if summary:
            # 사전요약 트랙: summary_<corp>에서 '완성 요약'을 먼저 꺼낸다(기간 필터 동일 적용).
            sums = await asyncio.to_thread(
                store.search_summaries, corp_code, query, s.summary_top_k, where
            )
            if sums:
                return sums
            # 폴백: 사전요약이 아직 없으면 기존 실시간 corpus RAG(본문 청크 우선).
            w = {"$and": [where, {"kind": "text"}]} if where else {"kind": "text"}
            return await asyncio.to_thread(
                store.search, corp_code, query, top_k=s.summary_top_k, where=w
            )
        return await asyncio.to_thread(
            store.search, corp_code, query, top_k=s.top_k, where=where, prefer_recent=r.prefer_recent
        )

    tasks = [corpus()]
    if r.financial_relevant:
        # 재무도 같은 사업연도를 조회(미지정/미존재면 최신으로 graceful 폴백)
        tasks.append(fetch_financial_citations_async(corp_code, _target_fy(r)))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    corpus_cits = _ok(results[0], "corpus")
    fin_cits = _ok(results[1], "financials") if len(results) > 1 else []
    # 재무 정형수치(정확·authoritative)를 앞에 둔다 → used 상위에 항상 포함
    return list(fin_cits) + list(corpus_cits)


def _ok(result, label: str) -> list:
    """asyncio.gather 결과 언랩 — 예외는 [] 로 graceful 하되 **반드시 로깅**한다.

    (과거: 예외를 조용히 삼켜 날짜필터 버그가 0건으로 둔갑한 채 방치됐다. §12-5)
    """
    if isinstance(result, Exception):
        log.warning("retrieve[%s] 실패(graceful): %r", label, result)
        return []
    return result


def _date_where(r: RouterResult) -> dict | None:
    """기간 표현 → **사업연도(bsns_year)** 메타필터(Chroma where).

    '2024년 사업보고서'=FY2024 이므로 접수일(rcept_dt)이 아니라 사업연도로 거른다
    (접수일은 FY+1에 제출돼 의미가 어긋남). bsns_year는 int 저장 → $gte/$lte도 int.
    """
    conds = []
    if (lo := _fy_int(r.date_from)) is not None:
        conds.append({"bsns_year": {"$gte": lo}})
    if (hi := _fy_int(r.date_to)) is not None:
        conds.append({"bsns_year": {"$lte": hi}})
    if not conds:
        return None
    return conds[0] if len(conds) == 1 else {"$and": conds}


def _fy_int(v: str | None) -> int | None:
    """'YYYYMMDD'/'YYYY...' → 사업연도 int(앞 4자리). 비숫자/None이면 None."""
    if not v:
        return None
    try:
        return int(str(v)[:4])
    except (TypeError, ValueError):
        return None


def _target_fy(r: RouterResult) -> int | None:
    """재무 조회 대상 사업연도 — 기간 끝(없으면 시작) 연도. 미지정이면 None(최신)."""
    return _fy_int(r.date_to) or _fy_int(r.date_from)


def _verdict_of(score: float) -> VerificationVerdict:
    s = get_settings()
    if score >= s.verify_pass_min:
        return VerificationVerdict.PASS
    if score >= s.verify_partial_min:
        return VerificationVerdict.PARTIAL
    return VerificationVerdict.FAIL


def _should_verify(question: str) -> bool:
    """verifier 샘플링(보고서 §4-2-1b): 매 턴 아님. 질문 해시로 결정적 샘플."""
    s = get_settings()
    if s.verify_sample_rate >= 1.0:
        return True
    h = int(hashlib.sha1(question.encode()).hexdigest(), 16) % 100
    return h < int(s.verify_sample_rate * 100)


async def handle_chat(req: ChatRequest) -> ChatResponse:
    # 1) 라우팅
    r = (await router_agent.run(_router_prompt(req))).output

    if r.intent == ChatIntent.SMALLTALK:
        return ChatResponse(
            corp_code=req.corp_code, session_id=req.session_id,
            intent=r.intent,
            answer=r.reply or "안녕하세요. 공시에 대해 궁금한 점을 물어봐 주세요.",
        )
    if r.intent == ChatIntent.OUT_OF_SCOPE or r.out_of_scope:
        name = r.detected_company or "다른 회사"
        return ChatResponse(
            corp_code=req.corp_code, session_id=req.session_id,
            intent=ChatIntent.OUT_OF_SCOPE, out_of_scope=True, detected_company=r.detected_company,
            answer=f"이 방은 {req.company_name} 전용입니다. {name} 관련 질문은 해당 방에서 해주세요.",
        )

    # 2) 검색 + 거시 결합(병렬)
    retrieve_task = _retrieve(req.corp_code, r, summary=r.intent == ChatIntent.SUMMARY)
    if r.macro_relevant:
        macro_snap, citations = await asyncio.gather(
            macro.get_macro_async(_macro_date(r)), retrieve_task
        )
    else:
        macro_snap, citations = None, await retrieve_task
    macro_used = bool(macro_snap and macro.has_value(macro_snap))

    evidence = format_citations(citations)
    if macro_used:  # 거시지표를 작성 근거에 합침
        evidence += "\n\n[거시지표(ECOS)]\n" + macro.format_macro(macro_snap)

    # 3) 작성 (summary / qa 트랙)
    verification: VerificationResult | None = None
    if r.intent == ChatIntent.SUMMARY:
        out: SummaryResult = (
            await summary_agent.run(f"[질문]\n{req.question}\n\n[근거]\n{evidence}")
        ).output
        answer = out.summary
    else:  # QA
        qa: QAResult = (
            await qa_agent.run(f"[질문]\n{req.question}\n\n[근거]\n{evidence}")
        ).output
        answer = qa.answer

    # provenance는 코드가 검색한 '실제' 근거로 고정한다(에이전트 생성 인용은 환각 위험).
    used = citations[:5]

    # 4) 검증(샘플링/조건부) — 실제 근거에 대해 채점
    if used and _should_verify(req.question):
        verification = (
            await verifier_agent.run(f"[답]\n{answer}\n\n[근거]\n{evidence}")
        ).output
        # verdict는 문서화된 임계값으로 결정적으로 도출(모델 라벨 변동 방지, 보고서 §4-2-1b)
        verification.verdict = _verdict_of(verification.grounded_score)

    return ChatResponse(
        corp_code=req.corp_code, session_id=req.session_id, intent=r.intent,
        answer=answer, citations=used, verification=verification,
        macro_used=macro_used, macro=macro_snap if macro_used else None,
    )


def _macro_date(r: RouterResult) -> str:
    """거시 스냅샷 기준일 — 질문에 기간이 있으면 그 끝, 없으면 오늘(최신)."""
    return r.date_to or datetime.date.today().strftime("%Y%m%d")


def _router_prompt(req: ChatRequest) -> str:
    hist = "\n".join(f"{t.role}: {t.content}" for t in req.history[-4:])
    return (
        f"[방 회사] {req.company_name} (corp_code={req.corp_code})\n"
        f"[이전 대화]\n{hist or '(없음)'}\n\n[현재 질문]\n{req.question}"
    )
