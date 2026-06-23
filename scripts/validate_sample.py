"""삼성 사업보고서 1건(20250311001085)으로 파싱→청킹→Contextual 설계 검증.

비용 0(임베딩/LLM 호출 없음). 표-인식 파싱과 청크/문맥 형식이 의도대로인지,
골든셋의 핵심 수치(매출 300,870,903 / 영업이익 32,725,961 등)가 검색 단위에
온전히 들어가는지 확인한다.

사용:  python scripts/validate_sample.py [rcept_no]
원문이 data/raw/<rcept>.xml 에 없으면 DART에서 받아 캐시한다.
"""
from __future__ import annotations

import os
import sys
from collections import Counter

from app.ingest import dart
from app.ingest.chunker import chunk_blocks
from app.ingest.parser import parse_document

RCEPT = sys.argv[1] if len(sys.argv) > 1 else "20250311001085"
BASE_META = {
    "corp_code": "00126380",
    "corp_name": "삼성전자",
    "rcept_no": RCEPT,
    "report_nm": "사업보고서 (2024.12)",
    "rcept_dt": "20250311",
    "pblntf_ty": "A",
}
# 골든셋에서 가져온 검증용 핵심 문구
GOLDEN_PHRASES = ["300,870,903", "32,725,961", "258,935,494", "반도체", "메모리"]


def _load_xml(rcept: str) -> str:
    path = f"data/raw/{rcept}.xml"
    if os.path.exists(path):
        return open(path, encoding="utf-8").read()
    xml = dart.fetch_document_xml(rcept)
    os.makedirs("data/raw", exist_ok=True)
    open(path, "w", encoding="utf-8").write(xml)
    return xml


def main() -> None:
    xml = _load_xml(RCEPT)
    print(f"■ 원문 {len(xml):,}자  (rcept={RCEPT})")

    blocks = parse_document(xml)
    bk = Counter(b.kind for b in blocks)
    print(f"\n■ 파싱: {len(blocks)}블록  text={bk['text']} table={bk['table']}")
    print(f"  텍스트 {sum(len(b.text) for b in blocks if b.kind=='text'):,}자 "
          f"/ 표 {sum(len(b.text) for b in blocks if b.kind=='table'):,}자")

    chunks = chunk_blocks(blocks, BASE_META)
    ck = Counter(c.meta.kind for c in chunks)
    sizes = [len(c.text) for c in chunks]
    print(f"\n■ 청킹: {len(chunks)}청크  text={ck['text']} table={ck['table']}")
    print(f"  크기(문맥포함) 평균 {sum(sizes)//len(sizes)}자 / 최대 {max(sizes)}자 / 최소 {min(sizes)}자")

    print("\n■ Contextual 문맥 줄 샘플 (text 2 · table 2):")
    shown = {"text": 0, "table": 0}
    for c in chunks:
        if shown[c.meta.kind] < 2:
            print(f"  · {c.context_line}")
            shown[c.meta.kind] += 1
        if all(v >= 2 for v in shown.values()):
            break

    print("\n■ 골든셋 핵심 문구가 어느 청크에 들어갔나:")
    for phrase in GOLDEN_PHRASES:
        hit = next((c for c in chunks if phrase in c.raw_text), None)
        if hit:
            print(f"  ✓ {phrase:14} → {hit.chunk_id} [{hit.meta.kind}] {hit.meta.section_title[:40]}")
        else:
            print(f"  ✗ {phrase:14} → 어느 청크에도 없음 (!)")

    print("\n■ 임베딩 대상 text 1건 전문(표 청크 예시):")
    tbl = next((c for c in chunks if c.meta.kind == "table" and "300,870,903" in c.raw_text), None)
    if tbl:
        print("  chunk_id:", tbl.chunk_id, "| 길이", len(tbl.text))
        print("  " + "\n  ".join(tbl.text.splitlines()[:10]))


if __name__ == "__main__":
    main()
