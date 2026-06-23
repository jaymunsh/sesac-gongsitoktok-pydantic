"""일회성 마이그레이션 — 기존 청크 메타데이터에 bsns_year(사업연도, int) 백필.

기간 질의를 접수일(rcept_dt)이 아니라 **사업연도**로 거르기 위함('2024년 사업보고서'=FY2024).
report_nm("사업보고서 (2024.12)")에 사업연도가 이미 들어 있어 **DART 호출·재임베딩 없이**
메타데이터만 update 한다. corpus·summary 모든 컬렉션에 적용(트랙 간 일관성).

실행:
    PYTHONPATH=. .venv/bin/python scripts/migrate_bsns_year.py            # 실제 변환
    PYTHONPATH=. .venv/bin/python scripts/migrate_bsns_year.py --dry-run  # 미리보기
"""
from __future__ import annotations

import argparse

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.rag.vectorstore import _bsns_year

_BATCH = 1000


def migrate(dry_run: bool) -> None:
    s = get_settings()
    client = chromadb.PersistentClient(
        path=s.chroma_dir,
        settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
    )
    for col in client.list_collections():
        coll = client.get_collection(col.name)
        g = coll.get(include=["metadatas"])
        ids = g.get("ids", [])
        metas = g.get("metadatas", []) or []

        up_ids, up_metas, unknown = [], [], 0
        for cid, m in zip(ids, metas):
            m = m or {}
            fy = _bsns_year(m.get("report_nm"))
            if fy == 0:
                unknown += 1
            if m.get("bsns_year") == fy:
                continue
            nm = dict(m)
            nm["bsns_year"] = fy
            up_ids.append(cid)
            up_metas.append(nm)

        print(f"[{col.name}] 총 {len(ids)} · 갱신 {len(up_ids)} · 미상(fy=0) {unknown}")
        if dry_run or not up_ids:
            continue
        for i in range(0, len(up_ids), _BATCH):
            coll.update(ids=up_ids[i : i + _BATCH], metadatas=up_metas[i : i + _BATCH])
        print(f"  → {len(up_ids)}건 update 완료")

    print("\n" + ("(dry-run) 변경 없음" if dry_run else "✅ 마이그레이션 완료"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    migrate(ap.parse_args().dry_run)
