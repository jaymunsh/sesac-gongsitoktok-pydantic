"""행동 평가 — handle_chat() 직접 호출(서버 불필요). 어려운 케이스 + 멀티턴 지원.

기존 run_golden_inproc 보다 넓은 assert: history(멀티턴)·macro_used·needs_clarification·
no_citations. 숫자 케이스는 값 미고정(has_number)으로 신선도 확보.

실행:
    PYTHONPATH=. .venv/bin/python -m eval.eval_chat
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from app.schemas.disclosure import ChatRequest, ChatTurn
from app.services.chat import handle_chat

NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+")


def _text(resp) -> str:
    return " ".join([resp.answer or ""] + [c.quote for c in resp.citations]
                    + ([resp.detected_company] if resp.detected_company else []))


def evaluate(case: dict, resp) -> tuple[bool, list[str]]:
    exp = case.get("expect", {})
    why: list[str] = []
    text = _text(resp)
    intent = resp.intent.value if hasattr(resp.intent, "value") else resp.intent

    if "intent" in exp and intent != exp["intent"]:
        why.append(f"intent={intent}≠{exp['intent']}")
    if exp.get("out_of_scope") and not resp.out_of_scope:
        why.append("outOfScope=false")
    if "verdict_not" in exp and resp.verification and resp.verification.verdict.value == exp["verdict_not"]:
        why.append(f"verdict={exp['verdict_not']}")
    if "contains_any" in exp and not any(s in text for s in exp["contains_any"]):
        why.append(f"contains_any 미충족 {exp['contains_any']}")
    if exp.get("has_number") and not NUM_RE.search(text):
        why.append("숫자 없음")
    if exp.get("macro_used") and not resp.macro_used:
        why.append("macro_used=false")
    if exp.get("needs_clarification") and not resp.needs_clarification:
        why.append("needs_clarification=false")
    if exp.get("no_citations") and resp.citations:
        why.append(f"citations={len(resp.citations)}(0 기대)")
    if exp.get("detected_none") and resp.detected_company:
        why.append(f"detected_company={resp.detected_company!r}(None 기대)")
    return (not why), why


async def run(cases: list[dict]) -> int:
    must_t = must_p = watch_t = watch_p = 0
    for c in cases:
        history = [ChatTurn(role=h["role"], content=h["content"]) for h in c.get("history", [])]
        req = ChatRequest(
            corp_code=c["company"]["corpCode"], company_name=c["company"]["corpName"],
            question=c["question"], history=history,
        )
        try:
            resp = await handle_chat(req)
            ok, why = evaluate(c, resp)
        except Exception as e:
            ok, why = False, [f"예외 {type(e).__name__}: {e}"]
        sev = c.get("severity", "must")
        if sev == "must":
            must_t += 1; must_p += ok
        else:
            watch_t += 1; watch_p += ok
        tag = "PASS" if ok else ("FAIL" if sev == "must" else "WATCH")
        line = f"  [{tag:5}] {c['id']:22} | {c['behavior']}"
        if not ok:
            line += f"\n          ↳ {'; '.join(why)}"
        print(line)

    print("\n--- 결과 ---")
    print(f"must  : {must_p}/{must_t} 통과")
    print(f"watch : {watch_p}/{watch_t} 통과 (알려진 약점)")
    ok_all = must_p == must_t
    print("\n" + ("✅ must 전부 통과" if ok_all else "❌ must 미통과 있음"))
    return 0 if ok_all else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=str(Path(__file__).with_name("chat_eval_set.json")))
    args = ap.parse_args()
    cases = json.loads(Path(args.set).read_text(encoding="utf-8"))["cases"]
    print(f"=== 행동 평가 {len(cases)}케이스 (어려운 케이스 + 멀티턴) ===\n")
    return asyncio.run(run(cases))


if __name__ == "__main__":
    sys.exit(main())
