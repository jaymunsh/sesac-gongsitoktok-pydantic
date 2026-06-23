"""인제스트 파이프라인 데이터 모델 (파싱 → 청킹 → Contextual → 임베딩).

표-인식 파싱의 산출물(Block)과 검색 단위(Chunk) + 벡터스토어에 박히는
메타데이터 스키마(ChunkMeta)를 정의한다. 이 스키마가 "확정 산출물"이다(보고서 §6-1).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

BlockKind = Literal["text", "table"]


class Block(BaseModel):
    """표-인식 파서의 1차 산출물 — 본문 텍스트 덩어리 또는 표 1개.

    표는 plaintext로 뭉개지 않고 Markdown 표 문자열로 구조를 보존한다(행·열 유지).
    """

    kind: BlockKind
    text: str = Field(..., description="본문 텍스트 또는 Markdown 표")
    section_path: list[str] = Field(
        default_factory=list, description="섹션 경로(상위→하위), 예: ['II. 사업의 내용', '2. 매출']"
    )
    # 표 전용 부가정보
    table_title: Optional[str] = Field(None, description="표 바로 앞 캡션/제목(있으면)")
    n_rows: Optional[int] = None
    n_cols: Optional[int] = None


class ChunkMeta(BaseModel):
    """벡터스토어 청크에 박히는 메타데이터 (필터·랭킹·출처추적용).

    컬렉션은 회사별로 나뉘므로(corpus_<corp_code>) corp_code는 컬렉션 자체로도
    걸리지만, 교차 검증/디버깅을 위해 메타에도 남긴다.
    """

    corp_code: str
    corp_name: str
    rcept_no: str = Field(..., description="공시 접수번호(14자리)")
    report_nm: str = Field(..., description="공시명, 예: '사업보고서 (2024.12)'")
    rcept_dt: str = Field(..., description="접수일 YYYYMMDD — 날짜 메타필터 키")
    pblntf_ty: str = Field("A", description="공시유형 코드(A=정기 등)")
    section_title: str = Field("", description="섹션 경로를 ' > '로 이은 문자열")
    kind: BlockKind = "text"
    order: int = Field(0, description="문서 내 청크 순서")


class Chunk(BaseModel):
    """검색 단위. text는 '임베딩 대상'(=Contextual 문맥 + 본문)."""

    chunk_id: str
    text: str = Field(..., description="임베딩/BM25 대상 텍스트(Contextual 문맥 포함)")
    raw_text: str = Field(..., description="원문(인용·표시용, 문맥 줄 제외)")
    context_line: str = Field("", description="청크 앞에 붙인 Contextual 문맥 한 줄")
    meta: ChunkMeta
