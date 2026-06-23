"""정기보고서 코퍼스 적재 CLI.

  python scripts/ingest_corpus.py --dry-run                # 목록만(무료·빠름)
  python scripts/ingest_corpus.py --corp 삼성전자           # 삼성만 적재
  python scripts/ingest_corpus.py                          # 삼성+현대 적재
"""
from __future__ import annotations

import argparse

from app.ingest import dart
from app.ingest.pipeline import ingest_company

COMPANIES = {"삼성전자": "00126380", "현대자동차": "00164742"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bgn", default="20220101")
    ap.add_argument("--end", default="20260101")
    ap.add_argument("--corp", default=None, help="회사명(없으면 전체)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.corp:
        cands = dart.find_corp_code(args.corp)
        items = [(args.corp, cands[0]["corp_code"])] if cands else []
    else:
        items = list(COMPANIES.items())

    for name, code in items:
        ingest_company(code, name, args.bgn, args.end, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
