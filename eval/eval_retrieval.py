"""검색(retrieval) 평가 — corpus 하이브리드 검색의 정답 회수율(hit@k).

표-인식 파싱·하이브리드(벡터∪BM25 RRF)·Contextual의 실효를 LLM 없이 직접 측정한다.
정제된 query로 store.search만 호출하므로 **무비용·결정적**(임베딩+BM25). writer/verifier
를 안 거쳐 검색 품질만 격리해서 본다.

실행 (프로젝트 루트):
    PYTHONPATH=. .venv/bin/python -m eval.eval_retrieval
    PYTHONPATH=. .venv/bin/python -m eval.eval_retrieval --k 5 --show
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.rag.vectorstore import get_vector_store


def _hit(citations, expect_any: list[str]) -> tuple[bool, int]:
    """top-k 중 expect_any가 처음 등장한 순위(1-based) 반환. 없으면 (False, 0)."""
    for rank, c in enumerate(citations, 1):
        hay = f"{c.section_title or ''} {c.quote}"
        if any(p in hay for p in expect_any):
            return True, rank
    return False, 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=str(Path(__file__).with_name("retrieval_set.json")))
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--show", action="store_true", help="미스 케이스의 top-1 출력")
    args = ap.parse_args()

    data = json.loads(Path(args.set).read_text(encoding="utf-8"))
    cases = data["cases"]
    store = get_vector_store()

    must_tot = must_hit = watch_tot = watch_hit = 0
    rr_sum = 0.0  # MRR(평균 역순위)
    print(f"=== 검색 평가 {len(cases)}케이스 · hit@{args.k} ===\n")
    for c in cases:
        cits = store.search(c["corp"], c["query"], top_k=args.k)
        hit, rank = _hit(cits, c["expect_any"])
        rr_sum += (1.0 / rank) if hit else 0.0
        sev = c.get("severity", "must")
        if sev == "must":
            must_tot += 1; must_hit += hit
        else:
            watch_tot += 1; watch_hit += hit
        tag = f"hit@{rank}" if hit else "MISS "
        mark = "PASS" if hit or sev == "watch" else "FAIL"
        print(f"  [{mark:4} {tag:6}] {c['id']:22} {c['query'][:30]}")
        if not hit and args.show:
            top = cits[0] if cits else None
            print(f"         ↳ 기대 {c['expect_any']} / top1: {(top.section_title or '—') if top else '없음'}")

    n = len(cases)
    print("\n--- 결과 ---")
    print(f"must  hit@{args.k}: {must_hit}/{must_tot}" + (f" ({must_hit/must_tot*100:.0f}%)" if must_tot else ""))
    print(f"watch hit@{args.k}: {watch_hit}/{watch_tot} (알려진 약점)")
    print(f"MRR(전체): {rr_sum/n:.3f}")
    ok = must_hit == must_tot
    print("\n" + ("✅ must 전부 회수" if ok else f"❌ must {must_tot-must_hit}건 미회수"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
