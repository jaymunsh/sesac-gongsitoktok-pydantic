"""Logfire 관찰성 — PydanticAI 에이전트·HTTP 호출 추적.

토큰 없이 **콘솔 출력 모드**로 동작(send_to_logfire=False). 환경변수로 on/off:
    OBSERVABILITY=console  → 콘솔에 trace 출력 (라우터→검색→writer→verifier 타임라인)
    (미설정)               → 비활성(기본) — 골든 실행 등 로그 스팸 방지

켜는 순간 모든 PydanticAI 에이전트 run이 자동 계측된다(에이전트 코드 변경 없음).
"""
from __future__ import annotations

import os
from contextlib import nullcontext

_configured = False


def observability_enabled() -> bool:
    return os.environ.get("OBSERVABILITY", "").lower() in ("console", "1", "true", "on")


def setup_observability(app=None) -> bool:
    """콘솔 모드 Logfire 구성. app을 주면 FastAPI 요청까지 계측. 반환=활성여부."""
    global _configured
    if not observability_enabled():
        return False
    if _configured:
        if app is not None:
            import logfire

            logfire.instrument_fastapi(app)
        return True

    import logfire

    logfire.configure(
        send_to_logfire=False,                 # 토큰 불필요 — 콘솔만
        service_name="gongsitoktok-pydantic",
    )
    logfire.instrument_pydantic_ai()           # 라우터/writer/verifier 자동 계측
    logfire.instrument_httpx()                 # DART/ECOS/OpenAI HTTP 호출 추적
    if app is not None:
        logfire.instrument_fastapi(app)
    _configured = True
    return True


def request_span(name: str, **attributes):
    """요청 1건을 감싸는 루트 span (관찰성 off면 no-op).

    백엔드의 X-Trace-Id를 attributes로 박으면, 그 아래 에이전트 호출(router→
    writer→verifier)이 자식 span으로 묶여 백엔드 trace_id로 AI 내부까지 추적된다.
    """
    if not _configured:
        return nullcontext()
    import logfire

    # None 속성은 제거(검색 노이즈 방지)
    attrs = {k: v for k, v in attributes.items() if v is not None}
    return logfire.span(name, **attrs)
