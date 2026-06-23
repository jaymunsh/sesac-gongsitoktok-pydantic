"""v2.0 계약 ↔ 내부 스키마 변환 어댑터 (finance_v2 드롭인 호환).

요청: v2.0(roomId/companyContext/messages) → 내부 ChatRequest
응답: 내부 ChatResponse → v2.0(camelCase, sourceContent/sources/macroSnapshot/error)
명세: 연동 명세서 v2.0. 내부 파이프라인은 그대로 두고 껍데기만 번역한다.
"""
from __future__ import annotations

from app.schemas.disclosure import ChatRequest, ChatResponse, ChatTurn, Citation
from app.schemas.external import (
    ChatV2Request,
    ChatV2Response,
    ErrorOut,
    SourceItem,
    VerificationOut,
)
from app.services import macro

_MAX_HISTORY = 10  # 단기 메모리 안전 상한
_DART_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="


def _dart_url(rcept_no: str | None) -> str | None:
    return f"{_DART_VIEWER}{rcept_no}" if rcept_no else None


def to_internal(req: ChatV2Request) -> ChatRequest:
    """v2.0 요청 → 내부 ChatRequest. 마지막 user 메시지=질문, 나머지=history."""
    msgs = req.messages
    question = msgs[-1].content if msgs else ""
    history = [ChatTurn(role=m.role, content=m.content) for m in msgs[:-1]][-_MAX_HISTORY:]
    return ChatRequest(
        corp_code=req.companyContext.corpCode,
        company_name=req.companyContext.corpName,
        question=question,
        history=history,
        session_id=str(req.roomId),
    )


def _format_source_content(corp_name: str, cits: list[Citation]) -> str:
    """sources → '[접수번호 / 기업명 공시명]\\n인용' 을 빈 줄로 구분한 텍스트."""
    blocks = []
    for c in cits:
        head = f"[{c.rcept_no or '-'} / {corp_name} {c.report_nm or '-'}]"
        blocks.append(f"{head}\n{c.quote}")
    return "\n\n".join(blocks)


def to_v2(room_id: int, corp_name: str, r: ChatResponse) -> ChatV2Response:
    """내부 ChatResponse → v2.0 응답."""
    # 완전 실패(답 자체 생성 불가)만 error 로 올린다. 부분 실패(검증/거시/재무)는 로그만.
    if r.error and "qa_failed" in r.error:
        return ChatV2Response(
            roomId=room_id,
            intent=r.intent.value if r.intent else None,
            answerText=None,
            error=ErrorOut(code="INTERNAL_ERROR", message=r.error, retriable=True),
        )

    sources = [
        SourceItem(
            rceptNo=c.rcept_no, reportNm=c.report_nm, rceptDt=c.rcept_dt,
            sectionTitle=c.section_title, quote=c.quote, score=c.score,
            dartUrl=_dart_url(c.rcept_no),
        )
        for c in r.citations
    ] or None
    source_content = _format_source_content(corp_name, r.citations) or None
    macro_snapshot = macro.format_macro(r.macro) if (r.macro_used and r.macro) else None
    verification = (
        VerificationOut(verdict=r.verification.verdict.value, groundedScore=r.verification.grounded_score)
        if r.verification else None
    )
    return ChatV2Response(
        roomId=room_id,
        intent=r.intent.value if r.intent else None,
        answerText=r.answer or None,
        sourceContent=source_content,
        macroSnapshot=macro_snapshot,
        sources=sources,
        outOfScope=r.out_of_scope,
        detectedCompany=r.detected_company,
        needsClarification=r.needs_clarification,
        verification=verification,
        error=None,
    )
