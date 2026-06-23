"""SQLite 보관소 — 챗 분석 결과를 영속화(RFP 과제형: 보관/조회).

각 챗 턴의 결과(질문·답·근거·검증)를 한 레코드로 저장하고, 목록/상세로 조회한다.
보고서 §1의 '요약→근거 QA→보관→조회' 흐름을 1급으로 구현.
표준 라이브러리 sqlite3만 사용(추가 의존성 없음).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.schemas.disclosure import (
    AnalysisListItem,
    AnalysisListResponse,
    AnalysisStatus,
    ChatResponse,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    analysis_id   TEXT PRIMARY KEY,
    corp_code     TEXT NOT NULL,
    company_name  TEXT,
    title         TEXT,
    question      TEXT,
    intent        TEXT,
    answer        TEXT,
    citations     TEXT,   -- JSON
    verification  TEXT,   -- JSON
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analyses_corp ON analyses(corp_code, created_at DESC);

CREATE TABLE IF NOT EXISTS macro_cache (
    as_of     TEXT PRIMARY KEY,   -- YYYYMMDD
    snapshot  TEXT NOT NULL       -- JSON
);
"""


def _conn() -> sqlite3.Connection:
    path = get_settings().sqlite_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(_SCHEMA)


def save_chat(
    question: str,
    resp: ChatResponse,
    *,
    company_name: str | None = None,
    title: str | None = None,
) -> str:
    """챗 응답 1건을 보관하고 analysis_id 반환."""
    aid = uuid.uuid4().hex[:12]
    with _conn() as conn:
        conn.execute(
            """INSERT INTO analyses
               (analysis_id, corp_code, company_name, title, question, intent,
                answer, citations, verification, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                aid,
                resp.corp_code,
                company_name,
                title or (question[:40] if question else None),
                question,
                resp.intent.value,
                resp.answer,
                json.dumps([c.model_dump() for c in resp.citations], ensure_ascii=False),
                json.dumps(resp.verification.model_dump(), ensure_ascii=False)
                if resp.verification
                else None,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return aid


def list_analyses(
    corp_code: str | None = None, *, limit: int = 50, offset: int = 0
) -> AnalysisListResponse:
    """보관된 분석 목록(마이페이지 카드)."""
    where = "WHERE corp_code = ?" if corp_code else ""
    params: tuple = (corp_code,) if corp_code else ()
    with _conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM analyses {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT analysis_id, company_name, title, answer, created_at
                FROM analyses {where} ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()
    items = [
        AnalysisListItem(
            analysis_id=r["analysis_id"],
            company_name=r["company_name"],
            title=r["title"],
            headline=(r["answer"] or "")[:60] or None,
            status=AnalysisStatus.DONE,
            created_at=datetime.fromisoformat(r["created_at"]),
        )
        for r in rows
    ]
    return AnalysisListResponse(items=items, total=total)


def get_macro_cache(as_of: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT snapshot FROM macro_cache WHERE as_of = ?", (as_of,)
        ).fetchone()
    return json.loads(row["snapshot"]) if row else None


def set_macro_cache(as_of: str, snapshot: dict) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO macro_cache (as_of, snapshot) VALUES (?, ?)",
            (as_of, json.dumps(snapshot, ensure_ascii=False)),
        )


def get_analysis(analysis_id: str) -> dict | None:
    """상세 조회 — 저장된 원본 레코드(근거·검증 포함)."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM analyses WHERE analysis_id = ?", (analysis_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["citations"] = json.loads(d["citations"]) if d["citations"] else []
    d["verification"] = json.loads(d["verification"]) if d["verification"] else None
    return d
