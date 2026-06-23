"""AI ↔ 백엔드 계약(contract) 스키마.

모든 답변에는 근거 문단(Citation)이 붙어 출처를 추적한다(RFP 2.1).
PydanticAI 에이전트의 `output_type` 으로 그대로 재사용된다 — 결과가 이 모델로
검증되고, 실패 시 자동 재시도된다(보고서 §3).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ============================================================
# 근거 / 출처
# ============================================================
class Citation(BaseModel):
    """답변·요약의 근거가 된 공시 문단 출처."""

    chunk_id: str = Field(..., description="청크 식별자")
    section_title: Optional[str] = Field(None, description="해당 문단이 속한 섹션 제목")
    quote: str = Field(..., description="근거가 된 원문 인용")
    score: Optional[float] = Field(None, description="검색 유사도 점수")
    kind: Literal["text", "table", "summary"] = Field("text", description="원문 종류(본문/표/사전요약)")
    # 어느 공시에서 나온 근거인지 (코퍼스 검색 시 채워짐) — RFP 2.1 출처 추적
    rcept_no: Optional[str] = Field(None, description="출처 공시 접수번호")
    report_nm: Optional[str] = Field(None, description="출처 공시명")
    rcept_dt: Optional[str] = Field(None, description="출처 공시 접수일(YYYYMMDD)")


# ============================================================
# Router (매 턴 맨 앞 분류)
# ============================================================
class ChatIntent(str, Enum):
    SMALLTALK = "smalltalk"        # 인사·잡담 → 근거 불필요
    QA = "qa"                      # 특정 사실/수치 질문
    SUMMARY = "summary"            # 요약·개요·동향
    OUT_OF_SCOPE = "out_of_scope"  # 방 회사가 아닌 다른 회사 → 안내


class RouterResult(BaseModel):
    """라우터 에이전트 결과."""

    intent: ChatIntent
    needs_evidence: bool = Field(True, description="공시 근거(출처)가 필요한 질문인지")
    financial_relevant: bool = Field(
        False, description="매출·영업이익 등 정형 재무 수치/실적 질문인지"
    )
    macro_relevant: bool = Field(False, description="환율·금리 등 거시 결합이 도움되는지")
    out_of_scope: bool = Field(False, description="방 회사가 아닌 다른 회사가 주제인지")
    detected_company: Optional[str] = Field(None, description="out_of_scope일 때 감지된 회사명")
    reply: Optional[str] = Field(None, description="smalltalk일 때 짧은 답변")
    search_query: Optional[str] = Field(
        None, description="검색용 정제 키워드(회사명·말투 제거). qa/summary일 때만"
    )
    date_from: Optional[str] = Field(None, description="기간 시작 YYYYMMDD")
    date_to: Optional[str] = Field(None, description="기간 끝 YYYYMMDD")
    prefer_recent: bool = Field(False, description="'최근/요즘' 등 최신 우선 여부")


# ============================================================
# Writer / Summary
# ============================================================
class QAResult(BaseModel):
    """QA(writer) 에이전트 결과."""

    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    answerable: bool = Field(True, description="공시 내 근거로 답변 가능했는지")
    needs_clarification: bool = Field(
        False, description="기준(당기/누적·연결/별도 등)이 모호해 되물어야 하는지"
    )


class SummaryResult(BaseModel):
    """요약 에이전트 결과."""

    headline: str = Field(..., description="한 줄 핵심")
    key_points: list[str] = Field(default_factory=list, description="핵심 bullet")
    summary: str = Field(..., description="본문 요약")
    citations: list[Citation] = Field(default_factory=list)


# ============================================================
# Verification
# ============================================================
class VerificationVerdict(str, Enum):
    PASS = "pass"          # 근거에 부합
    PARTIAL = "partial"    # 일부만 근거 있음
    FAIL = "fail"          # 근거 없음 / 환각 의심


class VerificationResult(BaseModel):
    """검증 에이전트 결과."""

    target: str = Field(..., description="검증 대상 (summary | 질문 텍스트)")
    verdict: VerificationVerdict
    grounded_score: float = Field(..., ge=0, le=1, description="근거 충실도 0~1")
    reason: str = Field(..., description="판정 근거")
    issues: list[str] = Field(default_factory=list, description="발견된 문제점")


# ============================================================
# 챗 요청/응답 (기업 단위 방 + 라우터)
# ============================================================
class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    corp_code: str = Field(..., description="방의 회사 DART corp_code")
    company_name: str = Field(..., description="방의 회사명")
    question: str
    history: list[ChatTurn] = Field(default_factory=list, description="단기 메모리(세션 내)")
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    corp_code: str
    session_id: Optional[str] = None
    intent: ChatIntent
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    verification: Optional[VerificationResult] = None
    out_of_scope: bool = False
    detected_company: Optional[str] = None
    macro_used: bool = False
    macro: Optional[dict] = None
    needs_clarification: bool = False
    error: Optional[str] = None


# ============================================================
# 과제형(RFP 필수): 보관 / 조회
# ============================================================
class AnalysisStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class AnalysisResult(BaseModel):
    """분석 1건 전체 결과 (저장 / 상세 조회 단위)."""

    analysis_id: str
    status: AnalysisStatus = AnalysisStatus.DONE
    corp_code: Optional[str] = None
    company_name: Optional[str] = None
    title: Optional[str] = None
    rcept_no: Optional[str] = None
    summary: Optional[SummaryResult] = None
    qa: list[QAResult] = Field(default_factory=list)
    verifications: list[VerificationResult] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AnalysisListItem(BaseModel):
    analysis_id: str
    company_name: Optional[str] = None
    title: Optional[str] = None
    headline: Optional[str] = None
    status: AnalysisStatus
    created_at: datetime


class AnalysisListResponse(BaseModel):
    items: list[AnalysisListItem]
    total: int
