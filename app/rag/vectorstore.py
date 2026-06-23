"""Chroma 벡터스토어 + BM25 하이브리드 검색.

컬렉션 규칙(확정): **회사 1곳 = 1 코퍼스 컬렉션 `corpus_<corp_code>`**.
공시 여러 건을 한 컬렉션에 적재하고 rcept_no/rcept_dt 메타로 필터링한다.
(사전요약은 별도 `summary_<corp_code>` — 본 모듈 범위 밖)

하이브리드(진짜): 벡터(의미) top-K **와** 전체 코퍼스 BM25(키워드) top-K를 각각
독립으로 뽑아 **합집합**을 만든 뒤 RRF(순위 융합)로 정렬. 정답이 한쪽 후보에만
있어도 살아남는다(이전의 '벡터 후보 안 BM25 재랭킹'은 정답이 벡터 밖이면 유실).
이어 리랭킹(중복제거·최신우선)으로 마무리(보고서 §2·§5 발견).
"""
from __future__ import annotations

import re

import chromadb
from chromadb.config import Settings as ChromaSettings
from rank_bm25 import BM25Okapi

from app.config import get_settings
from app.rag.embedder import get_embedder
from app.rag.rerank import rerank
from app.schemas.disclosure import Citation
from app.schemas.ingest import Chunk

_RRF_K = 60  # RRF 상수(표준값) — 순위가 낮아도 0이 되지 않게 완충


def corpus_collection(corp_code: str) -> str:
    return f"corpus_{corp_code}"


def summary_collection(corp_code: str) -> str:
    return f"summary_{corp_code}"


def _tokenize(text: str) -> list[str]:
    # 한글/영숫자 토큰 + 콤마 포함 숫자(300,870,903)를 한 토큰으로 보존
    return re.findall(r"[0-9][0-9,]*[0-9]|[0-9]|[가-힣]+|[A-Za-z]+", text.lower())


def _match_where(meta: dict, where: dict) -> bool:
    """BM25 후보에 chroma where 필터를 동일하게 적용(우리가 쓰는 연산자 부분집합)."""
    if "$and" in where:
        return all(_match_where(meta, c) for c in where["$and"])
    for field, cond in where.items():
        val = meta.get(field)
        if isinstance(cond, dict):
            for op, target in cond.items():
                if op == "$gte" and not (val is not None and str(val) >= str(target)):
                    return False
                if op == "$lte" and not (val is not None and str(val) <= str(target)):
                    return False
                if op == "$eq" and val != target:
                    return False
        elif val != cond:
            return False
    return True


class VectorStore:
    def __init__(self) -> None:
        s = get_settings()
        self.client = chromadb.PersistentClient(
            path=s.chroma_dir,
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
        self.embedder = get_embedder()
        # 컬렉션별 전체 코퍼스 BM25 인덱스 캐시(지연 로드·재사용)
        self._bm25: dict[str, dict] = {}

    # ── 적재 ────────────────────────────────────────────
    def index_chunks(self, corp_code: str, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        # cosine: OpenAI 임베딩은 정규화돼 있어 점수 해석이 깨끗하다(1=동일, 0=무관)
        coll = self.client.get_or_create_collection(
            corpus_collection(corp_code), metadata={"hnsw:space": "cosine"}
        )
        embeddings = self.embedder.embed_documents([c.text for c in chunks])
        coll.add(
            ids=[c.chunk_id for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=embeddings,
            metadatas=[
                {
                    "raw_text": c.raw_text,
                    "section_title": c.meta.section_title,
                    "kind": c.meta.kind,
                    "rcept_no": c.meta.rcept_no,
                    "report_nm": c.meta.report_nm,
                    "rcept_dt": c.meta.rcept_dt,
                    "order": c.meta.order,
                }
                for c in chunks
            ],
        )
        self._bm25.pop(corpus_collection(corp_code), None)  # 캐시 무효화(재적재 반영)
        return len(chunks)

    def has_disclosure(self, corp_code: str, rcept_no: str) -> bool:
        try:
            coll = self.client.get_collection(corpus_collection(corp_code))
        except Exception:
            return False
        return coll.get(where={"rcept_no": rcept_no}, limit=1).get("ids", []) != []

    # ── 사전요약(summary_<corp>) ─────────────────────────
    def index_summaries(self, corp_code: str, chunks: list[Chunk]) -> int:
        """사전요약 Chunk(kind='summary')를 summary_<corp> 컬렉션에 적재."""
        if not chunks:
            return 0
        coll = self.client.get_or_create_collection(
            summary_collection(corp_code), metadata={"hnsw:space": "cosine"}
        )
        embeddings = self.embedder.embed_documents([c.text for c in chunks])
        coll.add(
            ids=[c.chunk_id for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=embeddings,
            metadatas=[
                {
                    "raw_text": c.raw_text, "section_title": c.meta.section_title,
                    "kind": "summary", "rcept_no": c.meta.rcept_no,
                    "report_nm": c.meta.report_nm, "rcept_dt": c.meta.rcept_dt,
                    "order": c.meta.order,
                }
                for c in chunks
            ],
        )
        return len(chunks)

    def has_summary(self, corp_code: str, rcept_no: str) -> bool:
        try:
            coll = self.client.get_collection(summary_collection(corp_code))
        except Exception:
            return False
        return coll.get(where={"rcept_no": rcept_no}, limit=1).get("ids", []) != []

    def search_summaries(self, corp_code: str, query: str, top_k: int | None = None) -> list[Citation]:
        """사전요약 컬렉션에서 의미검색(벡터). 요약은 이미 간결·서술이라 벡터만으로 충분."""
        s = get_settings()
        k = top_k or s.summary_top_k
        try:
            coll = self.client.get_collection(summary_collection(corp_code))
        except Exception:
            return []
        q_emb = self.embedder.embed_query(query)
        res = coll.query(query_embeddings=[q_emb], n_results=k)
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        out: list[Citation] = []
        for cid, doc, m, dist in zip(ids, docs, metas, dists):
            m = m or {}
            out.append(
                Citation(
                    chunk_id=cid, section_title=m.get("section_title") or None,
                    quote=m.get("raw_text") or doc,
                    score=round(1 - float(dist), 4) if dist is not None else None,
                    kind="summary", rcept_no=m.get("rcept_no"),
                    report_nm=m.get("report_nm"), rcept_dt=m.get("rcept_dt"),
                )
            )
        return out

    # ── 전체 코퍼스 BM25 인덱스(지연 로드·캐시) ──────────────
    def _corpus_index(self, corp_code: str) -> dict | None:
        name = corpus_collection(corp_code)
        if name in self._bm25:
            return self._bm25[name]
        try:
            coll = self.client.get_collection(name)
        except Exception:
            return None
        g = coll.get(include=["documents", "metadatas"])
        ids = g.get("ids", [])
        docs = g.get("documents", [])
        metas = g.get("metadatas", [])
        if not ids:
            return None
        idx = {
            "ids": ids,
            "metas": metas,
            "docs": docs,
            "bm25": BM25Okapi([_tokenize(d) for d in docs]),
            "pos": {cid: i for i, cid in enumerate(ids)},
        }
        self._bm25[name] = idx
        return idx

    # ── 검색 (진짜 하이브리드: 벡터 ∪ 전체BM25 → RRF → 리랭킹) ──
    def search(
        self,
        corp_code: str,
        query: str,
        *,
        top_k: int | None = None,
        where: dict | None = None,
        prefer_recent: bool = False,
    ) -> list[Citation]:
        s = get_settings()
        k = top_k or s.top_k
        ck = s.candidate_k
        try:
            coll = self.client.get_collection(corpus_collection(corp_code))
        except Exception:
            return []

        # 1) 벡터 후보 (chroma where 필터 적용)
        q_emb = self.embedder.embed_query(query)
        vres = coll.query(query_embeddings=[q_emb], n_results=ck, where=where or None)
        vec_ids = vres.get("ids", [[]])[0]

        # 2) BM25 후보 — 전체 코퍼스에서 독립으로(정답이 벡터 밖이어도 포착)
        idx = self._corpus_index(corp_code)
        bm25_ids: list[str] = []
        if idx:
            scores = idx["bm25"].get_scores(_tokenize(query))
            order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            for i in order:
                cid = idx["ids"][i]
                if scores[i] <= 0:
                    break
                if where and not _match_where(idx["metas"][i], where):
                    continue
                bm25_ids.append(cid)
                if len(bm25_ids) >= ck:
                    break

        # 3) RRF 융합 (가중: bm25_weight)
        w = s.bm25_weight
        fused: dict[str, float] = {}
        for rank, cid in enumerate(vec_ids):
            fused[cid] = fused.get(cid, 0.0) + (1 - w) / (_RRF_K + rank)
        for rank, cid in enumerate(bm25_ids):
            fused[cid] = fused.get(cid, 0.0) + w / (_RRF_K + rank)
        if not fused:
            return []

        ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[: ck]
        # 표시용 score를 0~1로 정규화: RRF 미세값(~0.01)을 최댓값 기준 상대 점수로
        # (상위=1.0). 계약상 sources[].score가 의미있는 0~1이 되게 한다(재무결합 1.0과 정합).
        top = ranked[0][1] if ranked else 1.0
        citations = [
            self._to_citation(corp_code, cid, round(score / top, 4) if top else 0.0)
            for cid, score in ranked
        ]
        citations = [c for c in citations if c is not None]

        # 4) 리랭킹: 중복 제거 + (옵션)최신 우선 → 상위 k
        return rerank(citations, prefer_recent=prefer_recent, top_k=k)

    def _to_citation(self, corp_code: str, cid: str, score: float) -> Citation | None:
        idx = self._corpus_index(corp_code)
        if not idx or cid not in idx["pos"]:
            return None
        m = idx["metas"][idx["pos"][cid]] or {}
        return Citation(
            chunk_id=cid,
            section_title=m.get("section_title") or None,
            quote=m.get("raw_text") or idx["docs"][idx["pos"][cid]],
            score=score,
            kind=m.get("kind", "text"),
            rcept_no=m.get("rcept_no"),
            report_nm=m.get("report_nm"),
            rcept_dt=m.get("rcept_dt"),
        )


_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store
