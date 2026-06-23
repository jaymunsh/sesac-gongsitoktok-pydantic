"""검색 후처리 — 중복 제거 + 최신 우선 + 도메인 가중.

하이브리드 융합(vectorstore) 다음 단계. 정기보고서 16건엔 같은 표(재무위험관리 등)가
반복 적재돼 있어, 중복을 걷어내지 않으면 상위 결과를 잠식한다.
"""
from __future__ import annotations

import re

from app.schemas.disclosure import Citation


def _signature(text: str) -> str:
    """근사 중복 판별용 시그니처 — 숫자/공백 제거한 앞부분(표는 헤더가 같아도
    값이 다르면 다른 청크로 보존되도록 숫자는 남기되 길이를 늘려 구분)."""
    norm = re.sub(r"\s+", "", text)
    return norm[:160]


def dedup(citations: list[Citation]) -> list[Citation]:
    """근사 중복 청크 제거(높은 점수 우선 유지)."""
    seen: set[str] = set()
    out: list[Citation] = []
    for c in citations:
        sig = _signature(c.quote)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(c)
    return out


def rerank(
    citations: list[Citation],
    *,
    prefer_recent: bool = False,
    top_k: int = 5,
) -> list[Citation]:
    """중복 제거 → (옵션)최신 가중 → 상위 top_k.

    citations는 이미 하이브리드 융합 점수(score)로 정렬돼 들어온다고 가정.
    prefer_recent면 rcept_dt 최신일수록 소폭 가점해 동점·근소차를 최신으로 정렬.
    """
    items = dedup(citations)
    if prefer_recent:
        dates = [c.rcept_dt or "" for c in items if c.rcept_dt]
        newest = max(dates) if dates else ""
        oldest = min(dates) if dates else ""
        span = (int(newest) - int(oldest)) if (newest and oldest and newest != oldest) else 0

        def boosted(c: Citation) -> float:
            base = c.score or 0.0
            if span and c.rcept_dt:
                recency = (int(c.rcept_dt) - int(oldest)) / span  # 0~1
                return base + 0.1 * recency
            return base

        items = sorted(items, key=boosted, reverse=True)
    return items[:top_k]
