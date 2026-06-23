"""FastAPI 진입점 — 공시분석 챗 + 과제형 보관/조회.

  uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.observability import setup_observability
from app.storage import db


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()  # 보관 테이블 생성
    yield


app = FastAPI(
    title="gongsitoktok-pydantic",
    description="PydanticAI 기반 공시분석 — 요약·근거 QA·보관·조회",
    version="0.1.0",
    lifespan=lifespan,
)
setup_observability(app)  # OBSERVABILITY=console 일 때만 활성(콘솔 trace)
app.include_router(router)
