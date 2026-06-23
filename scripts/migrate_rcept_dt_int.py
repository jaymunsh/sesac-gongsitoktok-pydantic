"""일회성 마이그레이션 — Chroma 메타데이터 rcept_dt 를 문자열 → int 로 변환.

배경: rcept_dt가 문자열로 저장돼 있어 Chroma 숫자 범위필터($gte/$lte)가
'Expected ... int or float'로 거부 → 기간 질문이 corpus 0건이 되는 버그(보고서 §12-5).
임베딩/문서는 그대로 두고 **메타데이터만** update 한다(재적재·재임베딩 없음).

실행:
    PYTHONPATH=. .venv/bin/python scripts/migrate_rcept_dt_int.py            # 실제 변환
    PYTHONPATH=. .venv/bin/python scripts/migrate_rcept_dt_int.py --dry-run  # 미리보기
"""
from __future__ import annotations

import argparse

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings

_BATCH = 1000


def _to_int(v):
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return None  # 변환 불가는 건너뜀(원본 유지)


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

        up_ids, up_metas, already, skipped = [], [], 0, 0
        for cid, m in zip(ids, metas):
            m = m or {}
            cur = m.get("rcept_dt")
            if isinstance(cur, int):
                already += 1
                continue
            iv = _to_int(cur)
            if iv is None:
                skipped += 1
                continue
            nm = dict(m)
            nm["rcept_dt"] = iv
            up_ids.append(cid)
            up_metas.append(nm)

        print(
            f"[{col.name}] 총 {len(ids)} · 변환대상 {len(up_ids)} · "
            f"이미 int {already} · 스킵 {skipped}"
        )
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
