# 라벨 기반 정확도 검증 결과 (골든셋 3계층 eval)

> **본 문서는 평가 산출물(제출용)이다.** `eval/` 디렉터리의 러너 스크립트는 결과를 콘솔로만 출력하므로,
> 실행 결과를 사람이 읽을 수 있게 박제한 단일 진실 소스(single source of truth)다.
> 수치를 갱신할 때는 반드시 아래 "재현 방법"으로 다시 실행한 뒤 이 파일을 먼저 고치고, 다른 문서를 동기화한다.

- **측정일**: 2026-06-25
- **실행 환경**: 프로젝트 루트, 서버 미기동(인프로세스), `.venv` (Python 3.12.13)
- **데이터 규모**: corpus 67,023 청크 · 사전요약 1,188 (삼성전자 00126380 · 현대차 00164742)
- **합격 기준**: `severity=must` 케이스는 100% 통과해야 함(회귀 게이트). `watch`는 알려진 약점으로 추적만.

---

## 요약 — 3계층 한눈에

| 계층 | 러너 | 라벨셋(JSON) | 케이스 수 | 결과 | LLM |
|---|---|---|---|---|---|
| ① 검색 (retrieval) | `eval_retrieval.py` | `retrieval_set.json` | 15 (must 13 / watch 2) | **must 13/13 (100%)** · MRR **0.933** | 없음(무료·결정적) |
| ② 행동 (chat) | `eval_chat.py` | `chat_eval_set.json` | 11 (must 9 / watch 2) | **must 9/9** · watch 2/2 | 사용 |
| ③ 회귀 골든 (golden) | `run_golden_inproc.py` | `chat_golden_set.json` | 20 (must 18 / watch 2) | **must 18/18** · watch 2/2 | 사용 |

검색 세부: **hit@1 85% (13/15) · hit@3 100% · hit@5 100% (must 13/13)** · MRR 0.933.

---

## 재현 방법

프로젝트 루트(`gongsitoktok-pydantic/`)에서 가상환경으로 실행. ②③은 LLM(OpenAI) 호출이 필요하므로 `.env`에 `OPENAI_API_KEY` 등이 설정돼 있어야 한다. ①은 임베딩+BM25만 쓰는 무료·결정적 평가다.

```bash
# ① 검색 — hit@k / MRR (무료·결정적, LLM 없음)
PYTHONPATH=. .venv/bin/python -m eval.eval_retrieval --k 5 --show

# ② 행동 — 멀티턴·스코프·거시결합·되묻기·숫자신선도
PYTHONPATH=. .venv/bin/python -m eval.eval_chat

# ③ 회귀 골든셋 — 인텐트·정확수치·스코프·기간·기수·회사명 환각 가드
PYTHONPATH=. .venv/bin/python -m eval.run_golden_inproc
```

종료코드 규약: must 전부 통과 `0` / must 미통과 `1` / (HTTP 변형 한정) 서버 호출 실패 `2` → CI 게이트로 사용 가능.

---

## ① 검색 (retrieval) — must 13/13 · MRR 0.933

LLM 없이 임베딩(벡터) ∪ BM25 합집합을 RRF로 융합한 하이브리드 검색의 정답 청크 회수율을 측정. 결정적이라 비용 0·재현성 100%.

```
=== 검색 평가 15케이스 · hit@5 ===

  [PASS hit@1 ] ss-ret-income-revenue  연결 손익계산서 매출액
  [PASS hit@1 ] ss-ret-segment         사업부문별 매출 DX DS 반도체
  [PASS hit@1 ] ss-ret-business        주요 사업 메모리 반도체 DRAM NAND
  [PASS hit@1 ] ss-ret-harman          하만 전장 디지털 콕핏 카오디오
  [PASS hit@1 ] ss-ret-dividend        배당 정책 결산배당 배당성향
  [PASS hit@2 ] ss-ret-treasury        자기주식 취득 처분 현황
  [PASS hit@1 ] ss-ret-largest         최대주주 및 특수관계인 지분 현황
  [PASS hit@1 ] ss-ret-rnd             연구개발 실적 비용 조직
  [PASS hit@1 ] ss-ret-risk            사업위험 시장위험 재무위험관리 파생
  [PASS hit@1 ] ss-ret-region          지역별 매출 미주 유럽 아시아
  [PASS hit@1 ] hd-ret-business        주요 사업 자동차 제조 판매 차량
  [PASS hit@2 ] hd-ret-dividend        배당 정책 결산배당
  [PASS hit@1 ] hd-ret-rnd             연구개발 실적 친환경 전동화
  [PASS hit@1 ] ss-ret-fy-shares       주식의 총수 발행주식 보통주
  [PASS hit@1 ] ss-ret-fy-rnd          연구개발 실적 비용 조직

--- 결과 ---
must  hit@5: 13/13 (100%)
watch hit@5: 2/2 (알려진 약점)
MRR(전체): 0.933

✅ must 전부 회수
```

- hit@1 = 13/15(85%): 13건은 1위에 정답, `ss-ret-treasury`·`hd-ret-dividend`는 2위(hit@2)에서 회수 → MRR 0.933.
- `ss-ret-fy-*` 2건은 사업연도(bsns_year) 필터 가드 케이스로, 기간 질의 기능 추가 시 검색 회귀를 막기 위해 신설.

## ② 행동 (chat) — must 9/9 · watch 2/2

`handle_chat()`을 직접 호출해 라우팅·스코프·멀티턴·거시결합·되묻기·환각 방지 등 "동작"을 검증. LLM 사용.

```
=== 행동 평가 11케이스 (어려운 케이스 + 멀티턴) ===

  [PASS ] multiturn-anaphora     | 멀티턴 - 생략된 주어를 직전 맥락으로 해석
  [PASS ] macro-combine          | 거시 결합 - ECOS 스냅샷 노출
  [PASS ] table-segment          | 표 질의 - 부문 구분(표-인식)
  [PASS ] num-freshness-revenue  | 숫자 트랙 - 값 미고정(신선도, 재무결합 노드)
  [PASS ] smalltalk-thanks       | 스몰토크 - 근거 없이 짧게
  [PASS ] scope-compare          | 스코프 가드 - 타사 비교 차단
  [PASS ] clarify-ambiguous      | 되묻기 - '이익'(영업/순/총) 기준 모호
  [PASS ] unanswerable-future    | 미근거 - 미래 전망치는 공시에 단정 없음(환각 방지)
  [PASS ] scope-offdomain        | 스코프 가드 - 공시·회사 무관 일반질문(맛집·날씨 등) 차단
  [PASS ] scope-stock-self       | 스코프 가드(#16) - 자기회사 투자조언은 out_of_scope이되 detected_company는 None
  [PASS ] scope-stock-anaphora   | 스코프 가드(#16) - 지시어('이 회사')는 방 회사. history의 타사를 detected로 끌어오지 않음(None)

--- 결과 ---
must  : 9/9 통과
watch : 2/2 통과 (알려진 약점)

✅ must 전부 통과
```

## ③ 회귀 골든 (golden) — must 18/18 · watch 2/2

인프로세스 회귀 스모크. 인텐트·정확수치(exact-match)·스코프·기간(사업연도)·기수(제N기)·회사명 환각 가드를 20케이스로 회귀 검증. LLM 사용.

```
=== 챗 골든셋 20케이스 (인프로세스) ===

  [PASS ] ss-summary-overview        | 요약 트랙 - 회사 개요(서술)
  [PASS ] ss-summary-business        | 요약 트랙 - 사업 내용(서술)
  [PASS ] ss-num-revenue             | 숫자 트랙 - 매출(RAG exact-match)
  [PASS ] ss-num-opincome            | 숫자 트랙 - 영업이익(RAG exact-match)
  [PASS ] ss-num-assets              | 숫자 트랙 - 자산총계(RAG exact-match)
  [PASS ] ss-route-business-plain    | 라우팅 견고성 - '요약' 단어 없는 서술 질문
  [PASS ] ss-scope-other-company     | 스코프 가드 - 다른 회사 질문
  [PASS ] hd-summary-overview        | 요약 트랙 - 회사 개요(서술)
  [PASS ] hd-summary-business        | 요약 트랙 - 사업 내용(서술)
  [PASS ] hd-num-revenue             | 숫자 트랙 - 매출(RAG exact-match)
  [PASS ] hd-num-opincome            | 숫자 트랙 - 영업이익(RAG, 값 미고정)
  [PASS ] hd-num-liabilities         | 숫자 트랙 - 부채총계(RAG, 값 미고정)
  [PASS ] hd-route-business-plain    | 라우팅 견고성 - '요약' 단어 없는 서술 질문
  [PASS ] hd-scope-other-company     | 스코프 가드 - 다른 회사 질문
  [PASS ] ss-period-shares           | 기간 한정 질문 - 사업연도 필터 적용해도 corpus 근거 유지(E2E)
  [PASS ] ss-fy-financial            | 기간 한정 재무 - 재무 트랙이 요청 사업연도(FY2023) 조회(최신연도 아님)
  [PASS ] ss-fy-summary              | 기간 한정 요약 - summary 트랙도 사업연도 필터 존중(회귀 없음)
  [PASS ] ss-gisu-shares             | 기수 질의 - 제N기를 사업연도로 환산해 필터(삼성 제57기=FY2025)
  [PASS ] hd-company-no-mention      | 회사명 환각 가드 - 방 회사 근거로 답하되 타사명 금지(#15)
  [PASS ] ss-gisu-56-opincome        | 기수 코드변환 - 제56기=FY2024, off-by-one 가드(#13)

--- 결과 ---
must  : 18/18 통과
watch : 2/2 통과 (알려진 약점)

✅ must 전부 통과
```

> 참고: 골든셋 실행 로그에 `retrieve[corpus] 실패(graceful): ... input cannot be an empty string` 경고가 1건 나오나, 빈 쿼리 입력을 graceful-degrade로 흡수하는 정상 동작이며 모든 must 케이스 통과에 영향 없음.

---

## 라벨셋(정답 기준) 파일

| 계층 | 라벨 파일 | 비고 |
|---|---|---|
| ① 검색 | `eval/retrieval_set.json` | 쿼리 → 기대 청크 식별자 + severity |
| ② 행동 | `eval/chat_eval_set.json` | 질문(±history) → assertion(intent·out_of_scope·macro_used·has_number 등) |
| ③ 골든 | `eval/chat_golden_set.json` | 질문 → contains_any·intent·exact-match 등 회귀 기대값 |

기준·케이스 매트릭스 상세는 `eval/EVAL_README.md`·`eval/CHAT_GOLDEN_README.md` 참조.
