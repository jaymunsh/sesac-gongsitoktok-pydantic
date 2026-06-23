"""거시 결합 노드 — ECOS 거시지표를 질문 시점 기준으로 가져와 결합.

재무 결합(financials.py)과 같은 패턴: router가 macro_relevant를 켜면 이 노드가
환율·기준금리·KOSPI 스냅샷을 붙인다. 과거값은 불변이라 날짜당 1회 캐시(SQLite).
보조 데이터이므로 graceful — 실패해도 본 답변은 진행.
"""
from __future__ import annotations

import asyncio

from app.data import ecos
from app.storage import db

_LABELS = {
    "usd_krw": "원/달러 환율",
    "base_rate": "한국은행 기준금리",
    "market_rate": "시장금리(국고채 3년)",
    "kospi": "KOSPI",
}


def has_value(snapshot: dict) -> bool:
    inds = (snapshot or {}).get("indicators", {})
    return any(isinstance(v, dict) and v.get("value") is not None for v in inds.values())


def get_macro(as_of: str) -> dict:
    """as_of(YYYYMMDD) 기준 거시 스냅샷. 캐시 우선, 없으면 ECOS 호출 후 저장."""
    cached = db.get_macro_cache(as_of)
    if cached is not None:
        return cached
    snapshot = ecos.macro_snapshot(as_of)
    if has_value(snapshot):
        db.set_macro_cache(as_of, snapshot)
    return snapshot


async def get_macro_async(as_of: str) -> dict:
    """asyncio 병렬용 — 블로킹 호출을 스레드로."""
    return await asyncio.to_thread(get_macro, as_of)


def format_macro(snapshot: dict) -> str:
    """사람이 읽는/프롬프트용 거시지표 텍스트."""
    inds = (snapshot or {}).get("indicators", {})
    lines = []
    for key, label in _LABELS.items():
        v = inds.get(key)
        if isinstance(v, dict) and v.get("value") is not None:
            unit = v.get("unit", "") or ""
            lines.append(f"- {label}: {v['value']}{unit} (기준일 {v.get('time', '')})")
    return "\n".join(lines) or "(거시지표 조회 실패)"
