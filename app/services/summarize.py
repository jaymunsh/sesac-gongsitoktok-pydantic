"""사전요약 빌더 — 공시 Block 리스트 → 섹션별 서술 요약(Chunk, kind='summary').

기준(criteria):
  ① 단위: 섹션(목차)별. micro-섹션은 ~target_chars 묶음으로 합쳐 LLM 호출 폭증 방지.
  ② 가중: 분석 가치 높은 섹션 우선(사업의 내용·경영진단·위험·주석…), 형식 섹션은 후순위.
  ③ takeaway 지시: 핵심 사업/전략/리스크 위주, 메타설명·수치 나열 금지(수치는 RAG/재무결합).

산출물은 summary_<corp_code> 컬렉션에 적재된다(vectorstore.index_summaries).
변화탐지·이벤트트리거(직전 공시 대비 새 소식)는 추후 고급 단계(개선점).
"""
from __future__ import annotations

import asyncio

from app.agents.agents import section_summary_agent
from app.config import get_settings
from app.schemas.ingest import Block, Chunk, ChunkMeta

# 섹션 가중(부분일치). 높을수록 우선 요약.
_PRIORITY = {
    "사업의 내용": 9, "경영진단": 9, "위험": 9, "주요계약": 7, "연구개발": 7,
    "재무에 관한 사항": 6, "주석": 6, "배당": 6, "주주": 5, "회사의 개요": 4,
}
_DEMOTE = ("정관", "임원", "직원", "계열회사", "대주주", "상세표", "확인", "감사보고서")
_MAX_CONCURRENCY = 8


def _weight(section: str) -> int:
    if any(k in section for k in _DEMOTE):
        return 0
    for key, w in _PRIORITY.items():
        if key in section:
            return w
    return 3  # 기본


def _section_label(b: Block) -> str:
    return " > ".join(b.section_path[:2]) if b.section_path else "(기타)"


def _bundles(blocks: list[Block]) -> list[tuple[str, str]]:
    """블록을 섹션별로 모아 ~target_chars 묶음으로. 가중 높은 섹션 우선, max_sections 상한."""
    s = get_settings()
    target, min_chars, max_sec = (
        s.summary_section_target_chars, s.min_section_chars, s.summary_max_sections,
    )
    # 1) 섹션별 텍스트 누적(문서 순서 유지)
    by_sec: dict[str, list[str]] = {}
    for b in blocks:
        if b.kind == "table":  # 요약은 서술 위주 → 표는 제외(수치는 RAG/재무 담당)
            continue
        by_sec.setdefault(_section_label(b), []).append(b.text)
    # 2) 섹션 텍스트를 target 단위 묶음으로 쪼갬
    bundles: list[tuple[str, str, int]] = []  # (section, text, weight)
    for sec, parts in by_sec.items():
        w = _weight(sec)
        if w == 0:
            continue
        buf = ""
        for part in parts:
            buf = f"{buf}\n{part}".strip() if buf else part
            if len(buf) >= target:
                bundles.append((sec, buf[:target], w))
                buf = ""
        if len(buf) >= min_chars:
            bundles.append((sec, buf, w))
    # 3) 가중 높은 순 → max_sections 상한
    bundles.sort(key=lambda t: t[2], reverse=True)
    return [(sec, text) for sec, text, _ in bundles[:max_sec]]


async def build_summary_chunks(blocks: list[Block], base_meta: dict) -> list[Chunk]:
    """Block 리스트 → 사전요약 Chunk 리스트(kind='summary'). LLM 병렬 호출."""
    bundles = _bundles(blocks)
    if not bundles:
        return []
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _summarize(section: str, text: str) -> str:
        async with sem:
            prompt = f"[섹션] {section}\n\n[섹션 본문]\n{text}"
            return (await section_summary_agent.run(prompt)).output.strip()

    summaries = await asyncio.gather(*[_summarize(sec, txt) for sec, txt in bundles])

    rcept = base_meta["rcept_no"]
    corp_name, report_nm = base_meta["corp_name"], base_meta["report_nm"]
    chunks: list[Chunk] = []
    for i, ((section, _), summary) in enumerate(zip(bundles, summaries)):
        if not summary:
            continue
        ctx = f"[{corp_name} · {report_nm} · {section} · 요약]"
        meta = ChunkMeta(
            corp_code=base_meta["corp_code"], corp_name=corp_name, rcept_no=rcept,
            report_nm=report_nm, rcept_dt=base_meta["rcept_dt"],
            pblntf_ty=base_meta.get("pblntf_ty", "A"), section_title=section,
            kind="summary", order=i,
        )
        chunks.append(
            Chunk(chunk_id=f"sum-{rcept}-{i:03d}", text=f"{ctx}\n{summary}",
                  raw_text=summary, context_line=ctx, meta=meta)
        )
    return chunks
