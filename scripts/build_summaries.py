"""사전요약 빌드 — 정기보고서별 섹션 요약을 생성해 summary_<corp>에 적재.

corpus 적재와 독립. 빌드 타임 1회(gpt-4o-mini, ~$1-2). 이미 요약된 공시는 스킵.

  python scripts/build_summaries.py --dry-run            # 대상 목록만
  python scripts/build_summaries.py --corp 삼성전자       # 삼성만
  python scripts/build_summaries.py                       # 삼성+현대
"""
from __future__ import annotations

import argparse
import asyncio
import os

from app.ingest import dart
from app.ingest.parser import parse_document
from app.ingest.pipeline import list_periodic
from app.rag.vectorstore import get_vector_store, summary_collection
from app.services.summarize import build_summary_chunks

COMPANIES = {"삼성전자": "00126380", "현대자동차": "00164742"}


def _load_xml(rcept: str) -> str:
    path = f"data/raw/{rcept}.xml"
    if os.path.exists(path):
        return open(path, encoding="utf-8").read()
    xml = dart.fetch_document_xml(rcept)
    os.makedirs("data/raw", exist_ok=True)
    open(path, "w", encoding="utf-8").write(xml)
    return xml


async def build_company(code: str, name: str, bgn: str, end: str, dry: bool) -> None:
    targets = list_periodic(code, bgn, end)
    print(f"\n=== {name} ({code}) 정기보고서 {len(targets)}건 ===")
    if dry:
        for t in targets:
            print(f"   {t['rcept_dt']} {t['rcept_no']} {t['report_nm'].strip()}")
        return
    store = get_vector_store()
    done = skip = total = 0
    for i, t in enumerate(targets, 1):
        rcept = t["rcept_no"]
        if store.has_summary(code, rcept):
            skip += 1
            print(f"  [{i}/{len(targets)}] skip {rcept} (이미 요약)")
            continue
        try:
            blocks = parse_document(_load_xml(rcept))
            base_meta = {
                "corp_code": code, "corp_name": name, "rcept_no": rcept,
                "report_nm": t["report_nm"].strip(), "rcept_dt": t["rcept_dt"], "pblntf_ty": "A",
            }
            chunks = await build_summary_chunks(blocks, base_meta)
            n = store.index_summaries(code, chunks)
            total += n
            done += 1
            print(f"  [{i}/{len(targets)}] {t['report_nm'].strip()[:28]} → 요약 {n}개 (누적 {total})")
        except Exception as e:
            print(f"  [{i}/{len(targets)}] 실패 {rcept}: {type(e).__name__}: {e}")
    print(f"  ✅ {name}: 신규 {done} / 스킵 {skip} / 총 요약 {total}개 (collection={summary_collection(code)})")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bgn", default="20220101")
    ap.add_argument("--end", default="20260101")
    ap.add_argument("--corp", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    items = [(args.corp, dart.find_corp_code(args.corp)[0]["corp_code"])] if args.corp else \
        [(n, c) for n, c in COMPANIES.items()]
    for name, code in items:
        await build_company(code, name, args.bgn, args.end, args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
