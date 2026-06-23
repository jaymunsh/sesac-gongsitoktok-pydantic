"""인제스트 오케스트레이션 — 회사별 정기보고서를 corpus_<corp_code>에 적재.

흐름(공시 1건): DART 목록 → 원문 raw XML → 표-인식 파싱 → 청킹+Contextual → 임베딩 → 색인.
정기보고서(pblntf_ty='A')만 대상(데이터 범위: 삼성·현대 정기보고서).
"""
from __future__ import annotations

from app.ingest import dart
from app.ingest.chunker import chunk_blocks
from app.ingest.parser import parse_document
from app.rag.vectorstore import corpus_collection, get_vector_store


def list_periodic(corp_code: str, bgn: str, end: str) -> list[dict]:
    """정기보고서(A) 전체 목록(페이지네이션, rcept_no 중복 제거)."""
    seen: set[str] = set()
    out: list[dict] = []
    page = 1
    while True:
        d = dart.list_disclosures(
            corp_code=corp_code, bgn_de=bgn, end_de=end,
            pblntf_ty="A", page_no=page, page_count=100,
        )
        for r in d.get("list", []):
            if r["rcept_no"] not in seen:
                seen.add(r["rcept_no"])
                out.append(r)
        if page >= int(d.get("total_page", 1) or 1):
            break
        page += 1
    return sorted(out, key=lambda r: r["rcept_dt"])


def ingest_company(corp_code: str, corp_name: str, bgn: str, end: str, *, dry_run: bool) -> None:
    targets = list_periodic(corp_code, bgn, end)
    print(f"\n=== {corp_name} ({corp_code}) {bgn}~{end} ===")
    print(f"  정기보고서 {len(targets)}건")
    for t in targets:
        print(f"    {t['rcept_dt']} {t['rcept_no']} {t['report_nm'].strip()}")
    if dry_run:
        return

    store = get_vector_store()
    coll = corpus_collection(corp_code)
    done = skipped = total_chunks = 0
    failed: list[str] = []
    for i, t in enumerate(targets, 1):
        rcept = t["rcept_no"]
        if store.has_disclosure(corp_code, rcept):
            skipped += 1
            print(f"  [{i}/{len(targets)}] skip {rcept} (이미 적재)")
            continue
        try:
            xml = dart.fetch_document_xml(rcept)
            blocks = parse_document(xml)
            base_meta = {
                "corp_code": corp_code, "corp_name": corp_name, "rcept_no": rcept,
                "report_nm": t["report_nm"].strip(), "rcept_dt": t["rcept_dt"], "pblntf_ty": "A",
            }
            chunks = chunk_blocks(blocks, base_meta)
            n = store.index_chunks(corp_code, chunks)
            total_chunks += n
            done += 1
            print(f"  [{i}/{len(targets)}] {t['report_nm'].strip()[:28]} → {n}청크 (누적 {total_chunks})")
        except Exception as e:
            failed.append(f"{rcept}({e})")
            print(f"  [{i}/{len(targets)}] 실패 {rcept}: {e}")
    print(f"  ✅ {corp_name}: 신규 {done} / 스킵 {skipped} / 총 {total_chunks}청크 (collection={coll})")
    if failed:  # 실패가 조용히 묻히지 않게 끝에서 한 번 더 경고(적재 누락 가시화)
        print(f"  ⚠️  {corp_name}: {len(failed)}건 적재 실패 — {', '.join(failed)}")
