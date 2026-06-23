"""삼성 1건 임베딩→하이브리드 검색 스모크 테스트 (비용 ~$0.01).

파싱→청킹→Contextual→임베딩→검색 전 구간을 1건으로 검증한다.
임시 컬렉션(별도 chroma dir)을 써서 본 데이터를 건드리지 않는다.
전체 33건 재적재가 아니라 '설계 검증'이 목적.
"""
from __future__ import annotations

import os

os.environ.setdefault("CHROMA_DIR", "./data/chroma_smoke")

from app.ingest.chunker import chunk_blocks  # noqa: E402
from app.ingest.parser import parse_document  # noqa: E402
from app.rag.vectorstore import get_vector_store  # noqa: E402

CORP = "00126380"
RCEPT = "20250311001085"
BASE_META = {
    "corp_code": CORP, "corp_name": "삼성전자", "rcept_no": RCEPT,
    "report_nm": "사업보고서 (2024.12)", "rcept_dt": "20250311", "pblntf_ty": "A",
}
QUERIES = [
    ("삼성전자 연간 매출액 얼마야?", "300,870,903"),
    ("영업이익 알려줘", "32,725,961"),
    ("삼성전자 사업 내용 요약", None),
    ("반도체 메모리 사업", None),
]


def main() -> None:
    store = get_vector_store()
    if not store.has_disclosure(CORP, RCEPT):
        xml = open(f"data/raw/{RCEPT}.xml", encoding="utf-8").read()
        chunks = chunk_blocks(parse_document(xml), BASE_META)
        print(f"임베딩 {len(chunks)}청크 …")
        store.index_chunks(CORP, chunks)
        print("적재 완료 (collection=corpus_%s)\n" % CORP)
    else:
        print("이미 적재됨 (재사용)\n")

    for q, want in QUERIES:
        hits = store.search(CORP, q, top_k=3)
        print(f"Q: {q}")
        for h in hits:
            mark = "★" if (want and want in h.quote) else " "
            sec = (h.section_title or "")[:34]
            print(f"  {mark}[{h.kind:5} score={h.score:.3f}] {sec} | {h.quote[:48].strip()}")
        if want:
            ok = any(want in h.quote for h in hits)
            print(f"  → 기대수치 {want} {'적중 ✓' if ok else '누락 ✗'}")
        print()


if __name__ == "__main__":
    main()
