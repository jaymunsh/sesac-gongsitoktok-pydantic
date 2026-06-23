"""Contextual 문맥 주입 — 청크 앞에 '기업·기간·공시명·섹션' 한 줄을 붙인다.

배경(Anthropic Contextual Retrieval): 고아 청크("매출 3% 증가")는 어느 회사·기간·
섹션인지 임베딩에 안 담겨 검색이 어긋난다. 청크 앞에 문맥 한 줄을 붙여 임베딩하면
검색 정밀도가 크게 오른다.

두 단계로 설계한다(비용 통제 — 보고서 §4-2-6):
  1) 결정적(무료·기본): 메타데이터로 문맥 줄을 '템플릿' 생성. 항상 적용.
  2) LLM 보강(선택·유료): gpt-4o-mini가 청크별 1문장 상황설명을 추가. 풀 빌드 전 확인.

확정 문맥 형식(결정적):
  [<회사> · <공시명> · <섹션경로> · <종류>]
  예) [삼성전자 · 사업보고서(2024.12) · II. 사업의 내용 > 1. 사업의 개요 · 본문]
      [삼성전자 · 사업보고서(2024.12) · 재무제표 > 연결 손익계산서 · 표]
"""
from __future__ import annotations

from app.schemas.ingest import Block, ChunkMeta

_KIND_KR = {"text": "본문", "table": "표"}


def build_context_line(meta: ChunkMeta, block: Block | None = None) -> str:
    """결정적 Contextual 문맥 한 줄 (LLM 불필요)."""
    section = " > ".join(meta.section_title.split(" > ")) if meta.section_title else ""
    parts = [meta.corp_name, _short_report(meta.report_nm)]
    if section:
        parts.append(section)
    # 표면 캡션(표 제목)도 문맥에 넣어 '무슨 표'인지 임베딩에 담음
    if block and block.kind == "table" and block.table_title:
        parts.append(block.table_title)
    parts.append(_KIND_KR.get(meta.kind, meta.kind))
    return "[" + " · ".join(p for p in parts if p) + "]"


def _short_report(report_nm: str) -> str:
    """'사업보고서 (2024.12)' → '사업보고서(2024.12)' 정도로 정리."""
    return report_nm.replace(" (", "(").strip()


def apply_context(raw_text: str, context_line: str) -> str:
    """임베딩/BM25 대상 텍스트 = 문맥 줄 + 원문. (raw_text는 인용용으로 따로 보관)"""
    return f"{context_line}\n{raw_text}"
