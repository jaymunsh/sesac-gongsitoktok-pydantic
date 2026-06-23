"""에이전트 의존성 주입(deps) — PydanticAI Agent에 타입 안전하게 주입.

retrieve-then-read 관용구(보고서 §3): 검색은 오케스트레이션(코드)이 끝내고,
근거를 프롬프트로 넣어 에이전트는 output_type 생성에 집중한다. deps는 방(회사)
컨텍스트와 벡터스토어 핸들을 담는다.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.rag.vectorstore import VectorStore


@dataclass
class Deps:
    corp_code: str
    company_name: str
    store: VectorStore
