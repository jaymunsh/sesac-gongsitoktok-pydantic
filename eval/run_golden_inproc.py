"""챗 골든셋 인프로세스 실행기 — handle_chat()을 직접 호출(서버 불필요).

chat_golden_set.json의 expect(intent/contains_any/verdict_not/out_of_scope/has_number)를
ChatResponse(answer + citations.quote)와 대조해 통과율 집계.

실행 (프로젝트 루트):
    PYTHONPATH=. .venv/bin/python -m eval.run_golden_inproc
    PYTHONPATH=. .venv/bin/python -m eval.run_golden_inproc --only ss-   # id 접두 필터
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from app.schemas.disclosure import ChatRequest
from app.services.chat import handle_chat

NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+")


def _text_of(resp) -> str:
    parts = [resp.answer or ""]
    parts += [c.quote for c in resp.citations]
    if resp.detected_company:
        parts.append(resp.detected_company)
    return " ".join(parts)


def evaluate(case: dict, resp) -> tuple[bool, list[str]]:
    exp = case.get("expect", {})
    reasons: list[str] = []
    text = _text_of(resp)
    intent = resp.intent.value if hasattr(resp.intent, "value") else resp.intent

    if "intent" in exp and intent != exp["intent"]:
        reasons.append(f"intent={intent} (기대 {exp['intent']})")
    if exp.get("out_of_scope") is True and not resp.out_of_scope:
        reasons.append("outOfScope=false (기대 true)")
    if "verdict_not" in exp and resp.verification:
        v = resp.verification.verdict.value
        if v == exp["verdict_not"]:
            reasons.append(f"verdict={v} (금지)")
    if "contains_any" in exp and not any(s in text for s in exp["contains_any"]):
        reasons.append(f"contains_any 미충족 {exp['contains_any']}")
    if "contains_none" in exp:
        hit = [s for s in exp["contains_none"] if s in text]
        if hit:
            reasons.append(f"금지어 포함 {hit}")
    if exp.get("has_number") and not NUM_RE.search(text):
        reasons.append("숫자 토큰 없음")
    if resp.error:
        reasons.append(f"error={resp.error}")
    return (not reasons), reasons


async def run(cases: list[dict]) -> int:
    must_total = must_pass = watch_total = watch_pass = 0
    for c in cases:
        sev = c.get("severity", "must")
        req = ChatRequest(
            corp_code=c["company"]["corpCode"],
            company_name=c["company"]["corpName"],
            question=c["question"],
        )
        try:
            resp = await handle_chat(req)
            ok, reasons = evaluate(c, resp)
        except Exception as e:  # 파이프라인 예외도 케이스 실패로 기록
            ok, reasons = False, [f"예외: {type(e).__name__}: {e}"]
        if sev == "must":
            must_total += 1
            must_pass += ok
        else:
            watch_total += 1
            watch_pass += ok
        tag = "PASS" if ok else ("FAIL" if sev == "must" else "WATCH")
        line = f"  [{tag:5}] {c['id']:26} | {c['behavior']}"
        if not ok:
            line += f"\n          ↳ {'; '.join(reasons)}"
        print(line)

    print("\n--- 결과 ---")
    print(f"must  : {must_pass}/{must_total} 통과")
    print(f"watch : {watch_pass}/{watch_total} 통과 (알려진 약점)")
    ok_all = must_pass == must_total
    print("\n" + ("✅ must 전부 통과" if ok_all else "❌ must 미통과 있음"))
    return 0 if ok_all else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=str(Path(__file__).with_name("chat_golden_set.json")))
    ap.add_argument("--only", default=None, help="id 접두 필터")
    args = ap.parse_args()
    data = json.loads(Path(args.set).read_text(encoding="utf-8"))
    cases = [c for c in data["cases"] if not args.only or c["id"].startswith(args.only)]
    print(f"=== 챗 골든셋 {len(cases)}케이스 (인프로세스) ===\n")
    return asyncio.run(run(cases))


if __name__ == "__main__":
    sys.exit(main())
