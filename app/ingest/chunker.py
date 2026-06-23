"""표-인식 청킹 — Block 리스트 → 검색 단위 Chunk 리스트.

원칙:
  - 본문(text): 섹션 경계 유지 + 슬라이딩 윈도우(chunk_size/overlap).
  - 표(table): 통째로 1청크. 너무 크면 **헤더 행을 매 조각에 반복**하며 행 단위 분할
    (각 조각이 열 의미를 잃지 않게 — 표 RAG의 핵심).
  - 모든 청크에 Contextual 문맥 줄을 붙여 임베딩 대상 text 를 만든다.

원문(raw_text)은 인용·표시용으로 따로 보관하고, text(=문맥+원문)는 임베딩/BM25용.
"""
from __future__ import annotations

from app.config import get_settings
from app.ingest.contextual import apply_context, build_context_line
from app.schemas.ingest import Block, Chunk, ChunkMeta


def chunk_blocks(blocks: list[Block], base_meta: dict) -> list[Chunk]:
    """Block 리스트를 메타데이터와 결합해 Chunk 리스트로.

    base_meta: corp_code, corp_name, rcept_no, report_nm, rcept_dt, pblntf_ty
    """
    s = get_settings()
    chunks: list[Chunk] = []
    order = 0
    rcept = base_meta["rcept_no"]

    for block in blocks:
        section = " > ".join(block.section_path)
        pieces = (
            _split_table(block.text, s.table_max_chars)
            if block.kind == "table"
            else _window(block.text, s.chunk_size, s.chunk_overlap)
        )
        for piece in pieces:
            meta = ChunkMeta(
                corp_code=base_meta["corp_code"],
                corp_name=base_meta["corp_name"],
                rcept_no=rcept,
                report_nm=base_meta["report_nm"],
                rcept_dt=base_meta["rcept_dt"],
                pblntf_ty=base_meta.get("pblntf_ty", "A"),
                section_title=section,
                kind=block.kind,
                order=order,
            )
            ctx = build_context_line(meta, block)
            chunks.append(
                Chunk(
                    chunk_id=f"{rcept}-{order:04d}",
                    text=apply_context(piece, ctx),
                    raw_text=piece,
                    context_line=ctx,
                    meta=meta,
                )
            )
            order += 1
    return chunks


def _window(text: str, size: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    step = max(size - overlap, 1)
    out: list[str] = []
    for start in range(0, len(text), step):
        piece = text[start : start + size].strip()
        if piece:
            out.append(piece)
        if start + size >= len(text):
            break
    return out


def _split_table(md: str, max_chars: int) -> list[str]:
    """Markdown 표를 행 단위로 분할(필요할 때만).

    - 헤더가 충분히 작을 때만 매 조각에 반복(열 의미 유지). 헤더가 비정상적으로
      크면(레이아웃표·거대셀) 반복하지 않는다 — 안 그러면 청크가 폭증한다.
    - 한 행이 예산보다 길면 그 행을 하드 윈도우로 쪼갠다.
    - 어떤 조각도 임베딩 한계를 넘지 않게 절대 상한을 둔다.
    """
    md = md.strip()
    if len(md) <= max_chars:
        return [md]
    lines = md.splitlines()
    if len(lines) < 3:
        return _hard_wrap(md, max_chars)

    header, sep, body = lines[0], lines[1], lines[2:]
    repeat_header = len(header) <= max_chars // 3   # 작은 헤더만 반복
    prefix = f"{header}\n{sep}\n" if repeat_header else ""
    budget = max(max_chars - len(prefix), 200)

    # 긴 행은 미리 하드 윈도우로 분해(한 행이 예산 초과 방지)
    rows: list[str] = []
    for row in (body if repeat_header else lines):
        rows.extend(_hard_wrap(row, budget) if len(row) > budget else [row])

    out: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for row in rows:
        if cur and cur_len + len(row) + 1 > budget:
            out.append(prefix + "\n".join(cur))
            cur, cur_len = [], 0
        cur.append(row)
        cur_len += len(row) + 1
    if cur:
        out.append(prefix + "\n".join(cur))
    return out


def _hard_wrap(text: str, size: int) -> list[str]:
    """오버랩 없는 고정 폭 분할(거대 행/셀 안전장치)."""
    return [text[i : i + size] for i in range(0, len(text), size)] or [text]
