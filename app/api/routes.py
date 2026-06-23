"""HTTP API — 챗 + 과제형 보관/조회 (RFP 1급 흐름).

  POST /api/v1/chat          : 챗 한 턴(요약/근거 QA) → 응답 + 자동 보관
  GET  /api/analyses         : 보관된 분석 목록(마이페이지)
  GET  /api/analyses/{id}    : 분석 상세(근거·검증 포함)
  GET  /health               : 헬스체크
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Response

from app.observability import request_span
from app.schemas.disclosure import AnalysisListResponse
from app.schemas.external import ChatV2Request, ChatV2Response
from app.services import contract
from app.services.chat import handle_chat
from app.storage import db

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/api/v1/chat", response_model=ChatV2Response)
async def chat(
    req: ChatV2Request,
    response: Response,
    x_trace_id: str | None = Header(default=None),
) -> ChatV2Response:
    """백엔드 연동 계약 v2.0 — finance_v2(Spring) 드롭인 호환.

    v2.0 요청 → 내부 ChatRequest 번역 → handle_chat → v2.0 응답 변환.
    근거 있는 답(qa/summary)만 보관한다. X-Trace-Id 는 그대로 echo.
    """
    if x_trace_id:
        response.headers["X-Trace-Id"] = x_trace_id
    internal_req = contract.to_internal(req)
    # 백엔드 X-Trace-Id를 루트 span에 박아 AI 내부(router→writer→verifier)까지 端-to-端 추적
    with request_span(
        "chat", trace_id=x_trace_id, room_id=req.roomId,
        corp_code=req.companyContext.corpCode,
    ):
        internal_resp = await handle_chat(internal_req)
    if internal_resp.citations:
        db.save_chat(internal_req.question, internal_resp, company_name=req.companyContext.corpName)
    return contract.to_v2(req.roomId, req.companyContext.corpName, internal_resp)


@router.get("/api/analyses", response_model=AnalysisListResponse)
def list_analyses(
    corp_code: str | None = Query(None, description="회사 필터(corp_code)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AnalysisListResponse:
    return db.list_analyses(corp_code, limit=limit, offset=offset)


@router.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> dict:
    rec = db.get_analysis(analysis_id)
    if not rec:
        raise HTTPException(status_code=404, detail="analysis not found")
    return rec
