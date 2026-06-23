# 평가(eval) 가이드 — 3계층

기존 골든셋(회귀 스모크) 위에 **검색 평가**와 **어려운 행동 평가**를 더해, 재구축의
핵심 개선(표파싱·하이브리드·Contextual)과 까다로운 동작을 실제로 검증한다.

## 3계층 한눈에
| 계층 | 파일 | 무엇을 보나 | 비용 | 실행 |
|---|---|---|---|---|
| ① 검색 | `eval_retrieval.py` + `retrieval_set.json` | 정답 청크 회수율 hit@k·MRR (표파싱·하이브리드·Contextual 직접 측정) | **무료**(임베딩+BM25, LLM 없음)·결정적 | `python -m eval.eval_retrieval --show` |
| ② 행동 | `eval_chat.py` + `chat_eval_set.json` | 멀티턴·거시결합·표질의·되묻기·스코프비교·숫자신선도 | LLM(턴당) | `python -m eval.eval_chat` |
| ③ 회귀 | `run_golden_inproc.py` + `chat_golden_set.json` | 기존 14케이스 회귀 스모크(인텐트·정확수치·스코프) | LLM(턴당) | `python -m eval.run_golden_inproc` |

> 모두 프로젝트 루트에서 `PYTHONPATH=. .venv/bin/python -m eval.<모듈>` 로 실행. 서버 불필요.

## ① 검색 평가 (가장 싸고 핵심)
- 정제된 query로 `store.search`만 호출 → top-k에 `expect_any`(섹션명·구별 문구)가 있으면 hit.
- 라우터/writer를 안 거쳐 **검색 품질만 격리**. LLM 비용 0, 결정적이라 자주 돌려도 됨.
- 현재: **must 11/11 hit@5(100%)·MRR 0.923**. terse 질의 약점은 watch로 명시(쿼리분해 개선거리).

## ② 행동 평가 (어려운 케이스)
- `handle_chat`을 직접 호출. 기존 골든이 안 보던 것:
  - **멀티턴**(history로 '그럼 매출은?' 해석), **거시결합**(macro_used), **표질의**(부문),
    **스코프 비교**('삼성 vs SK하이닉스'), **스몰토크**, **되묻기**, **미래전망 환각방지**.
- **숫자 신선도**: 값을 하드코딩하지 않고 `has_number`+`verdict`로 검증 → 보고서 갱신에도 안 썩음.
- 이 평가가 **비교-스코프 버그를 잡아내** 라우터를 고쳤다(이 계층의 효용 증명).

## ③ 회귀 골든 (기존)
- 재구축 전후 같은 잣대. 회귀 게이트로 유지. 단 얕은 키워드 매칭·하드코딩 수치라 품질 증명용으론 ①②로 보강.

## assert 종류(행동 평가)
`intent · history · contains_any · has_number · verdict_not · out_of_scope · macro_used · needs_clarification · no_citations`

## 확장 방법
- 검색: `retrieval_set.json`에 `{query, corp, expect_any, severity}` 추가.
- 행동: `chat_eval_set.json`에 `{company, question, history?, expect, severity}` 추가.
- 새 회사·표질의·기간필터 등으로 늘리면 커버리지가 올라간다.
