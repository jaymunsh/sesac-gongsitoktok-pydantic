# 공시톡톡 AI — PydanticAI 공시분석 시스템 종합 설명

> **한 줄 요약**: 한국 전자공시(DART) 원문을 표 구조까지 보존해 적재하고, 질문하면
> **근거(출처)와 함께 답하고 보관·조회**하는 PydanticAI 기반 RAG 챗봇.
>
> 본 문서는 현 프로젝트(AI 파트)를 처음 보는 사람도 바로 파악할 수 있게 정리한 종합 설명이며,
> 추후 *Spring + React + AI 종합보고서*에 그대로 활용할 소스다.
> 작성일 2026-06-23 · 대상 레포 `gongsitoktok-pydantic` · 관련 `docs/기술설명_상세.md`(CrewAI↔PydanticAI 비교 원본)

---

## 목차
1. [한눈에 — 무엇을 하는 시스템인가](#1-한눈에--무엇을-하는-시스템인가)
2. [서버 스펙 & 실행 방법](#2-서버-스펙--실행-방법)
3. [실무는 어떻게 하나 / 우리는 어떻게 구현했나](#3-실무는-어떻게-하나--우리는-어떻게-구현했나)
4. [청크 메타데이터 & 활용 ★](#4-청크-메타데이터--활용-)
5. [PydanticAI란 & 채택 이유 (vs LangGraph) ★](#5-pydanticai란--채택-이유-vs-langgraph-)
6. [파이프라인 상세 ★](#6-파이프라인-상세-)
7. [에이전트 영역 상세 ★핵심](#7-에이전트-영역-상세-핵심)
8. [요약은 어떻게 이뤄지고 활용되나 ★핵심](#8-요약은-어떻게-이뤄지고-활용되나-핵심)
9. [과제형 보관/조회 + v2.0 계약 연동](#9-과제형-보관조회--v20-계약-연동)
10. [데이터 규모 & 실측 수치](#10-데이터-규모--실측-수치)
11. [기존(CrewAI)에서 바꾼 결정적·합리적 이유](#11-기존crewai에서-바꾼-결정적합리적-이유)
12. [검증 — 3계층 eval](#12-검증--3계층-eval)
13. [API 절약 / 비용 로직](#13-api-절약--비용-로직)
14. [시연 강조 포인트](#14-시연-강조-포인트)
15. [추후 개선점](#15-추후-개선점)
16. [부록 — 구조·스키마·config·치트시트](#16-부록--구조스키마config치트시트)

---

## 1. 한눈에 — 무엇을 하는 시스템인가

**비유**: 회사의 공시 문서(사업보고서·분기보고서)를 잘게 잘라 "색인 카드"로 만들어 도서관에
꽂아두고, 사용자가 질문하면 **관련 카드를 찾아 그 근거 안에서만 답**하고, 그 답을 **보관**해
나중에 **목록·상세로 다시 꺼내보는** 시스템이다.

- **입력**: 기업 단위 채팅방에서의 자연어 질문 (예: "삼성전자 영업이익 알려줘", "사업 내용 요약해줘")
- **출력**: 근거(출처 공시·섹션·인용)와 함께 작성된 답변 + 근거 충실도 점수(정확도) + DART 원문 링크
- **핵심 가치**: ①표·숫자를 망가뜨리지 않는 적재 ②정확 수치는 RAG가 아니라 DART 정형 API로
  ③모든 답에 출처 추적(provenance) ④과제형(요약·근거·보관·조회) ⑤기존 백엔드와 드롭인 호환

### 전체 구성도
```
                    ┌─────────────── 데이터 소스 ───────────────┐
                    │ OpenDART(공시 원문·정형재무) · ECOS(거시) │
                    └──────────────────┬───────────────────────┘
   [인제스트(1회)]                     │                    [런타임(질문당)]
   표-인식 파싱→청킹→Contextual→임베딩   │     질문 → 라우터 → (검색+재무+거시 병렬) → 작성 → 검증
   └ +사전요약(섹션 가중·gpt-4o-mini)    │            (summary 질문은 summary_<회사>에서)
                    │                  │                         │
                    ▼                  ▼                         ▼
        corpus_<회사> · summary_<회사>  ┌──────────────┐         v2.0 응답 + SQLite 보관
              (Chroma)            │  FastAPI     │◀────────  Spring(finance_v2) ◀── React(gongsitoktok)
                                │ /api/v1/chat │
                                └──────────────┘
```

- **데이터**: 삼성전자·현대자동차 정기보고서 → 회사별 벡터 컬렉션(`corpus_<corp_code>`)
- **인제스트**(빌드 1회): 큰 비용이 여기 한 번. 표 보존·문맥 주입·임베딩.
- **런타임**(질문당): 라우터 분류 → 검색/재무/거시 병렬 결합 → 작성 → 검증. 푼돈.
- **연동**: React(프론트) ↔ Spring(백엔드 `finance_v2`) ↔ FastAPI(본 AI). v2.0 계약으로 통신.

### 1-2. 용어 한눈에 (Glossary)
이 문서에 자주 나오는 용어. 모르는 단어가 보이면 여기로.

| 용어 | 쉬운 뜻 |
|---|---|
| **RAG** (검색증강생성) | 질문에 맞는 근거를 **검색해서** 그 근거로 LLM이 답하는 방식. 환각↓·근거 기반. |
| **임베딩 / 벡터 검색** | 글을 숫자 벡터로 바꿔 **'뜻'이 비슷한 것**을 찾기. 개념·서술 질문에 강함. |
| **BM25** | 단어가 **글자 그대로 얼마나 잘 맞는지**로 순위를 매기는 고전 키워드 검색 알고리즘(검색엔진 표준). 티커·정확 수치·고유명사에 강함. |
| **하이브리드 검색** | 벡터(뜻) + BM25(단어)를 **함께** 써서 둘의 강점 결합. 공시는 개념+정확수치 둘 다 필요. |
| **RRF** (순위 융합) | 여러 검색의 **순위**를 합쳐 하나로 정렬(`1/(60+순위)` 합산). 점수 단위가 달라도 공정하게 섞임. |
| **리랭킹** | 검색 후보를 **더 정밀하게 재정렬**(여기선 중복제거·최신우선). |
| **Contextual Retrieval** | 청크 앞에 **출처 문맥 한 줄**을 붙여 임베딩 → 검색 정밀도↑(Anthropic). |
| **청크(Chunk)** | 긴 문서를 검색·요약하기 좋게 자른 **작은 조각**(색인 카드). |
| **메타데이터** | 청크에 붙는 **꼬리표**(회사·기간·섹션·종류) — 필터·출처추적·랭킹. |
| **provenance** (출처추적) | 답의 각 문장·수치가 **어느 공시·섹션에서 왔는지 끝까지 되짚는 것**. "이 숫자 어디서 났어?"에 답할 수 있게 함 → 환각 억제·감사(금융권 필수). 본 프로젝트는 출처를 코드가 고정하고 출처 카드+DART 링크로 보여줌. |
| **정형재무 / XBRL** | 매출·영업이익처럼 **표준 태그로 기계가 읽는** 재무 수치. DART API로 직접 획득(RAG 아님). |
| **retrieve-then-read** | 검색은 **코드가 끝내고** 그 근거를 LLM에 넣어 읽게 하는 패턴(환각·비용·비결정성↓). |
| **접수번호(rcept_no)** | DART 공시 1건의 **14자리 고유 식별자**(앞 8자리=접수일). 출처·원문 링크 기준. |
| **코사인 유사도** | 두 벡터가 **얼마나 같은 방향**인지(1=동일, 0=무관). 임베딩 검색의 거리 척도. |
| **groundedScore** (정확도) | 답이 근거에 **얼마나 충실한지**(0~1). 프론트 "정확도 %"로 표시. |
| **verdict** (판정) | 검증 결과 **pass/partial/fail**. groundedScore를 임계값(0.7/0.4)으로 코드가 확정. |

**시스템·데이터·평가 용어**

| 용어 | 쉬운 뜻 |
|---|---|
| **corpus** (코퍼스) | 회사별 공시 **원문 청크 저장소**(`corpus_<회사>`). 정확 사실·QA용. (사전요약은 별도 `summary_<회사>`) |
| **사전요약** (precompute summary) | 빌드때 섹션을 미리 요약해 `summary_<회사>`에 저장 → 요약 질문에 꺼내 씀(매번 안 만듦). |
| **인제스트** (ingest) | 공시 원문을 파싱·청킹·임베딩해 **적재하는 빌드 단계**(1회, 큰 비용은 여기). |
| **런타임** (runtime) | 질문이 들어와 답하는 **실행 단계**(질문당, 푼돈). |
| **Chroma** | 본 프로젝트가 쓰는 **벡터 데이터베이스**(임베딩 저장·검색). |
| **라우터** (router) | 질문의 **의도를 분류**하고 검색쿼리·플래그·기간을 정하는 첫 에이전트(gpt-4o-mini). |
| **intent** (의도) | 질문 종류: `qa`(사실·수치)/`summary`(요약)/`smalltalk`(잡담)/`out_of_scope`(다른 회사). |
| **eval** (평가) | 시스템이 잘 작동하는지 **자동 검증**하는 테스트 묶음. 본 프로젝트는 검색·행동·회귀 3계층. |
| **골든셋** (golden set) | 정답 기대값을 정해둔 **회귀 테스트 케이스** 모음(바뀌어도 안 깨지는지 확인). |
| **hit@k / MRR** | 검색 평가 지표 — hit@k=정답이 상위 k개 안에 있나, MRR=정답 순위의 역수 평균(1에 가까울수록 좋음). |
| **DART / OpenDART** | 금융감독원 **전자공시시스템** / 그 무료 **API**(공시 원문·정형재무). `fnlttSinglAcnt`=주요계정 재무 API. |
| **ECOS** | 한국은행 경제통계 **API**(환율·기준금리·국고채·KOSPI 등 거시지표). |
| **정기보고서** | 사업보고서·반기보고서·분기보고서(DART 공시유형 A). 본 프로젝트의 적재 대상. |
| **토큰** (token) | LLM이 글을 처리하는 단위(대략 단어 조각). 비용·길이 계산 기준. |
| **폴백** (fallback) | 주 경로가 안 되면 **대체 경로**로 처리(예: 사전요약 없으면 corpus RAG로). |
| **v2.0 계약** | 백엔드(Spring)와 합의한 **요청/응답 규격**(필드명·구조). 어댑터가 내부 스키마와 번역. |

**구현·기술 용어 (라이브러리·기법)**

| 용어 | 쉬운 뜻 |
|---|---|
| **asyncio / gather** | 파이썬 **비동기 동시 실행** 도구. 검색·재무·거시를 **동시에** 돌려 가장 느린 하나만 기다림(병렬). `gather`=여러 작업을 한 번에 모아 실행. |
| **병렬 / 동시성** | 여러 작업을 (거의) 동시에 처리해 **전체 시간을 줄임**. |
| **semaphore** (세마포어) | 동시에 도는 작업 수를 **제한**하는 장치(예: 요약 LLM 호출을 8개까지만). |
| **batch** (배치) | 여러 항목을 **묶어 한 번에** 처리(예: 임베딩 256개씩) → 호출 수·비용↓. |
| **output_type** | 에이전트 출력을 **정해진 스키마로 검증**(+실패 시 자동 재시도)하는 PydanticAI 기능. |
| **deps** (의존성 주입) | 에이전트에 벡터스토어·설정 등을 **타입 안전하게 넣어주는** 것. |
| **stateless** (무상태) | 서버가 상태를 안 가짐 → 같은 입력에 같은 출력. 대화이력은 백엔드가 보유해 매 요청에 넘김. |
| **graceful** (부분실패 처리) | 한 부분(예: 거시 결합)이 실패해도 **나머지로 계속** 진행해 답을 만든다. |
| **TTL** (time to live) | 캐시의 **유효 시간**. 지나면 새로 가져온다(예: 정형재무 캐시 개선안). |
| **FastAPI / uvicorn** | 파이썬 **웹 API 프레임워크** / 그 API를 띄우는 **서버**. |
| **BeautifulSoup / lxml** | HTML·XML을 **트리로 파싱**하는 라이브러리(표-인식 파싱에 사용). |
| **SQLite** | 파일 하나로 동작하는 **가벼운 데이터베이스**(분석 보관·거시 캐시). |
| **venv** | 파이썬 **가상환경** — 프로젝트별 의존성 격리. |
| **COLSPAN** | 표 셀이 **여러 열에 걸침**(병합). 파서가 빈 칸으로 패딩해 열 정렬을 유지. |

---

## 2. 서버 스펙 & 실행 방법

### 2-1. 런타임 요구 (기술 스택)
| 항목 | 값 |
|---|---|
| 언어/런타임 | **Python 3.12** (venv) |
| 에이전트 프레임워크 | **pydantic-ai 1.30.x** |
| 웹 | FastAPI 0.115 + uvicorn 0.34 |
| 벡터DB | Chroma 0.5 (로컬 영속, cosine) — 디스크 약 **~1GB**(67K 청크) |
| 키워드 검색 | rank-bm25 0.2 (인메모리 인덱스, 지연 캐시) |
| 임베딩/LLM | OpenAI (text-embedding-3-small / gpt-4o-mini / gpt-5.1 / o4-mini) |
| 파싱 | beautifulsoup4 4.12 + lxml 5 |
| 보관 | SQLite (stdlib `sqlite3`) — `data/app.db` |
| 관찰성 | Logfire 4 (콘솔 모드, 토큰 불필요) |
| 외부 API | OpenDART(공시·정형재무, 무료), 한국은행 ECOS(거시, 무료), OpenAI(유료) |
| 포트 | 8000 (백엔드 `finance_v2`가 `http://localhost:8000`로 호출) |

### 2-2. 모델 티어링 (역할별 모델 — `app/config.py`)
| 역할 | 모델 | 이유 |
|---|---|---|
| router (의도 분류) | gpt-4o-mini | 분류는 쉬운 작업 → 싼 모델 |
| summary (요약 작성) | gpt-4o-mini | 서술 요약은 싼 모델로 충분 |
| contextual (문맥 생성) | gpt-4o-mini | (현재 결정적 문맥 사용, LLM은 선택적) |
| macro (거시 결합) | gpt-4o-mini | |
| **writer/qa (답 작성)** | **gpt-5.1** | 답 품질이 핵심 → 상위 모델 |
| **verifier (검증)** | **o4-mini** | 근거 채점엔 추론형 |
| 임베딩 | text-embedding-3-small | 검색용 |

> 모델명은 전부 `.env`로 조정 가능. 비용 대부분은 writer(gpt-5.1)에 몰린다(Logfire로 확인).

### 2-3. 필수 환경변수 (`.env`, 깃 제외)
```
OPENAI_API_KEY=...      # 임베딩·LLM
DART_API_KEY=...        # OpenDART(무료 발급)
ECOS_API_KEY=...        # 한국은행 ECOS(무료 발급)
# 모델·임베딩·임계값·경로는 기본값 있음(config.py), 필요시 오버라이드
```

### 2-4. 실행 커맨드 (치트시트)
```bash
# 0) 환경 구성
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1) 코퍼스 적재 (빌드 1회) — 정기보고서
PYTHONPATH=. .venv/bin/python scripts/ingest_corpus.py --dry-run   # 목록만(무료)
PYTHONPATH=. .venv/bin/python scripts/ingest_corpus.py --corp 삼성전자   # 실제 적재

# 2) 서버 기동 (포트 8000)
PYTHONPATH=. .venv/bin/uvicorn app.main:app --port 8000
#   관찰성(콘솔 trace) 켜기:
OBSERVABILITY=console PYTHONPATH=. .venv/bin/uvicorn app.main:app --port 8000 --reload

# 3) 평가 (서버 불필요, 인프로세스)
PYTHONPATH=. .venv/bin/python -m eval.eval_retrieval     # 검색(무료·결정적)
PYTHONPATH=. .venv/bin/python -m eval.eval_chat          # 행동(어려운 케이스)
PYTHONPATH=. .venv/bin/python -m eval.run_golden_inproc  # 회귀(기존 골든)
```
- API 문서(Swagger): 서버 기동 후 `http://localhost:8000/docs`에서 폼으로 바로 테스트.

---

## 3. 실무는 어떻게 하나 / 우리는 어떻게 구현했나

현업 공시분석(AlphaSense·Hebbia 등)은 *"그냥 텍스트 청킹+벡터검색"이 아니다.* 7단계 production
파이프라인으로 돌아가며, 본 프로젝트는 그 축소·국내(DART)·대화형 버전을 구현했다.

| 단계 | 실무 production | 본 프로젝트 구현 | 파일 |
|---|---|---|---|
| ① 수집 | SEC/DART·실적콜·리서치 준실시간 | OpenDART 정기보고서 수집 | `ingest/dart.py` |
| ② 파싱 | 구조보존 + **표-인식** + XBRL | **표→Markdown 보존** 파서 | `ingest/parser.py` |
| ③ 청킹 | 표-인식 + 메타 + **Contextual** | 섹션·표 청킹 + 결정적 Contextual | `ingest/chunker.py`, `contextual.py` |
| ④ 인덱싱 | **벡터+BM25 하이브리드** | 벡터(Chroma)+전체 BM25 RRF | `rag/vectorstore.py` |
| ⑤ 검색 | 하이브리드+리랭킹+메타필터 | RRF 융합+dedup/최신우선+날짜필터 | `rag/vectorstore.py`, `rerank.py` |
| ⑥ 생성 | 근거內+숫자추론+인라인 인용 | 근거內 작성+provenance 고정 | `agents/agents.py`, `services/chat.py` |
| ⑦ 검증 | provenance·환각 억제 | verifier(추론형)+임계값 verdict | `agents/agents.py` |

- **추가 축**: 정형 재무(DART `fnlttSinglAcnt`)와 거시(ECOS)를 코드로 가져와 근거에 **결합** —
  실무의 "XBRL 정형 데이터 결합"을 국내 무료 API로 구현.
- **차별점**: 한국 DART는 PDF/HTML 비중이 커 **원문 파싱 부담이 큼**. 표·주석 추출 품질이 곧
  분석 품질이라, ② 표-인식 파싱이 가장 큰 품질 레버다(§6-1).

---

## 4. 청크 메타데이터 & 활용 ★

### 4-1. 청크 1개의 구성 (`app/schemas/ingest.py::Chunk`)
한 청크는 **"임베딩 대상 text"** 와 **"인용용 raw_text"** 를 분리 보관한다.
```
chunk_id     : "20250311001085-0025"   (=<접수번호>-<순서 4자리>)
text         : "[삼성전자 · 사업보고서(2024.12) · (첨부)연결재무제표 · 연결손익계산서 · 표]\n
                | 과목 | 주석 | 제 56 (당) 기 |  | 제 55 (전) 기 |  |\n
                | Ⅰ. 매출액 | 29 |  | 300,870,903 |  | 258,935,494 | ..."   ← 임베딩/BM25 대상(문맥줄+원문)
raw_text     : "| 과목 | ... | Ⅰ. 매출액 | ... 300,870,903 ..."                ← 화면 인용용(문맥줄 제외)
context_line : "[삼성전자 · 사업보고서(2024.12) · (첨부)연결재무제표 · 연결손익계산서 · 표]"
meta         : ChunkMeta(...)
```

### 4-2. 메타데이터 스키마 (`ChunkMeta`)
| 필드 | 예 | 활용 |
|---|---|---|
| `corp_code` / `corp_name` | `00126380` / `삼성전자` | 컬렉션·출처 |
| `rcept_no` | `20250311001085` | 공시 식별·중복적재 방지·**출처추적**·DART 링크 |
| `report_nm` | `사업보고서 (2024.12)` | 출처 표시 |
| `rcept_dt` | `20250311` | **날짜 메타필터 키**(기간 질의) |
| `pblntf_ty` | `A` | 공시유형(A=정기) |
| `section_title` | `II. 사업의 내용 > 1. 사업의 개요` | 섹션 경로(`>` 구분), 출처·랭킹 |
| `kind` | `text` / `table` | 본문/표 구분(요약은 text 우선) |
| `order` | `25` | 문서 내 순서 |

### 4-3. Contextual 문맥줄 (검색 정확도의 핵심)
**문제**: 고아 청크("매출 3% 증가")는 어느 회사·기간·섹션인지 임베딩에 안 담겨 검색이 어긋난다.
**해법**(Anthropic Contextual Retrieval): 청크 앞에 문맥 한 줄을 붙여 임베딩한다.
```
형식:  [<회사> · <공시명> · <섹션경로> · (표 제목) · <종류>]
예:    [삼성전자 · 사업보고서(2024.12) · II. 사업의 내용 > 1. 사업의 개요 · 본문]
       [삼성전자 · 사업보고서(2024.12) · (첨부)연결재무제표 · 연결손익계산서 · 표]
```
- **결정적(무료)**: 메타데이터로 템플릿 생성 → LLM 비용 0(`ingest/contextual.py::build_context_line`).
- DART는 섹션 계층(I~XII)이 명확해 `section_title`이 풍부하고, 표 캡션까지 문맥에 넣어 일반 문서보다 유리.

### 4-4. 메타 활용처 요약
- **컬렉션 분리**(`corpus_<corp_code>`) + `rcept_dt` 필터 → 기업·기간 혼동을 구조적으로 차단.
- **kind** → 요약 트랙은 `text` 청크 우선(빈약한 수치 표에 끌려가지 않게).
- **rcept_no/report_nm/rcept_dt** → 모든 답의 출처 카드(`sources[]`)와 DART 원문 링크(`dartUrl`) 생성.

---

## 5. PydanticAI란 & 채택 이유 (vs LangChain/LangGraph) ★

### 5-0. 짧은 역사 — 왜 프레임워크가 여러 개인가
LLM 앱 프레임워크는 "무엇이 어려운가"가 바뀌며 진화했다.
1. **LangChain (2022~)** — LLM에 검색·도구·메모리를 붙이는 **"부품 상자"**. RAG 붐을 이끌었으나 추상화 과다로 **무거움·추상화 누수** 비판.
2. **LangGraph (2024~)** — LangChain 팀의 **상태 그래프(노드·엣지)**. 순환·분기·롤백·휴먼인더루프 같은 **복잡 워크플로**에 강함.
3. **CrewAI/AutoGen (2024~)** — 역할극 멀티에이전트. 표현력↑이나 **단순 작업엔 과함**(기존이 이걸 단일 래퍼로 씀).
4. **PydanticAI (2024말~2025)** — Pydantic(파이썬 검증 표준) 팀. "에이전트=모델+**구조화 출력(검증)**+도구/의존성"으로 단순화. **가볍고 타입 안전**.

### 5-1. PydanticAI란 (상세)
Pydantic 팀의 **타입세이프 에이전트 프레임워크**(V1, 2025). FastAPI가 웹에서 한 일(타입·검증 1급)을 LLM 에이전트에서. 핵심:
- **구조화 출력 1급**: `Agent(output_type=Model)` → LLM 출력을 Pydantic으로 **검증, 안 맞으면 자동 재시도**.
- **deps(의존성 주입)**: 벡터스토어·설정을 타입 안전하게 주입(`RunContext`).
- **instructions/tools/model-agnostic**: 시스템 지시·도구·여러 provider를 동일 API로.
- **Logfire 관찰성 1급**(같은 팀) · **pydantic-graph**(복잡 흐름 확장).
- **경량·Pydantic-native**: 기존 스키마(RouterResult/QAResult)를 그대로 `output_type`으로 재사용.

### 5-2. 프레임워크 비교
| 프레임워크 | 한 줄 | 우리 적합도 |
|---|---|---|
| LangChain | 부품 상자(통합·RAG) | 부품엔 좋으나 무거움 |
| **LangGraph** | 순서도를 코드로(상태 그래프) | 흐름이 매우 복잡하면 ◎, **우리 규모엔 과함** |
| **PydanticAI** | 타입세이프 에이전트(구조화 출력) | **◎ Pydantic-native·경량·최소코드** |
| CrewAI(기존) | 역할극 팀 | 단일 래퍼로 전락 → 가치 0 |

### 5-3. 왜 PydanticAI인가 (LangGraph 대비)
- 우리 오케스트레이션은 `라우터→검색→작성→검증` + 병렬 결합으로, **분기·병렬이 평범한 파이썬
  (`if/else`, `asyncio.gather`)으로 충분히 표현된다.** LangGraph의 상태 그래프(노드·엣지 선언)는
  이 정도 흐름엔 **추상화 과잉**이다.
- 반면 우리가 매 단계 진짜로 원하는 것은 **"LLM 출력을 정해진 스키마로 안전하게 받기"** — 이게
  PydanticAI의 1급 기능(`output_type` 검증+재시도). 그래서 **흐름은 코드로, 각 호출은 PydanticAI로**가
  최소 코드·최대 타입안정의 조합이다.
- 기존이 Pydantic 결과를 쓰고 있었기에(RouterResult 등) **교체 비용이 가장 적다**.

> 더 복잡한 흐름(다단계 분기·롤백·휴먼인더루프)이 필요해지면 PydanticAI의 `pydantic-graph`로 확장 가능.

### 5-4. 프레임워크를 쓰는 명확한 이점 (Spring 비유) — 왜 체감이 "드라마틱"하진 않은가
**먼저 솔직히**: Spring을 써도 앱이 "하는 일"은 안 바뀐다. Spring은 **DI·트랜잭션·보일러플레이트 제거**로 **구조·안전성**을 준다. PydanticAI도 똑같다 — **"기능이 확 달라진" 체감이 없는 게 정상**이고, 대신 코드가 **안전·경량**해지고 실수를 프레임워크가 막는다. 진짜 품질 체감은 **인제스트(표파싱·Contextual)·검색(하이브리드)**에서 온다(§6). 프레임워크는 그 로직을 깔끔히 받치는 토대.

| PydanticAI가 공짜로 주는 것 | Spring 대응 | 우리 코드에서 쓴 곳 | 안 쓰면 직접 해야 할 일 |
|---|---|---|---|
| **구조화 출력 검증+자동 재시도**(`output_type`) | `@Valid`+바인딩 | Router/QA/Summary/Verification **전부** | LLM JSON 파싱·검증·재요청 루프를 **매번 수작업** |
| **의존성 주입**(`deps`) | DI(`@Autowired`) | `Deps`(벡터스토어·회사 컨텍스트) | 전역/수동 전달로 결합도↑ |
| **모델 추상화**(provider-agnostic) | JPA가 DB 가림 | `"openai:gpt-5.1"`→`.env` 한 줄 교체 | provider별 SDK 분기 |
| **관찰성 자동 계측**(Logfire) | Actuator/Micrometer | `instrument_pydantic_ai()` 한 줄→전 에이전트 trace | 호출마다 로깅·타이밍 수동 |
| **타입 안전·IDE 지원** | 정적 타입 체크 | `resp.intent`·`resp.citations` 자동완성 | `dict["키"]` 추측, 런타임 오류 |
| **정의 간결화** | Boot 오토컨피그 | 에이전트 5개=5줄 / 호출 1줄 | CrewAI식 보일러플레이트(§11-3) |

**장점**: LLM→**검증된 타입 객체** 보장(파싱·재시도 무료) · 모델 교체 자유 · 관찰성 무료 · 기존 스키마 재사용(교체비용 최소) · 호출당 객체 0(경량).
**단점·트레이드오프(정직)**: 프레임워크 의존(버전 추종) · 아주 단순한 1회 호출은 SDK 직접이 더 단순할 수도 · 복잡 그래프는 `pydantic-graph` 학습 · 비교적 신생(자료가 LangChain보다 적음).

---

## 6. 파이프라인 상세 ★

### 6-1. 인제스트 파이프라인 (빌드 1회)
```
OpenDART document.xml(ZIP)
   │  dart.fetch_document_xml — 태그 보존 raw XML로 (평문 변환 안 함)
   ▼
표-인식 파서 (parser.parse_document)         → list[Block]  (kind=text|table)
   │  · <TABLE> → Markdown 표(행·열·COLSPAN 패딩 보존)
   │  · <P> → 본문, <TITLE>/<SECTION-*> → 섹션 경로
   │  · 자간 라벨("매 출 액"→"매출액") 정규화
   ▼
청커 (chunker.chunk_blocks)                  → list[Chunk]
   │  · 본문: 섹션 유지 + 슬라이딩 윈도우(800/120)
   │  · 표: 통째 1청크, 크면 헤더 반복하며 행 분할(table_max_chars=2400)
   ▼
Contextual 주입 (contextual.build_context_line) → text = "[문맥]\n원문"
   ▼
임베딩 (embedder, text-embedding-3-small, batch 256)
   ▼
Chroma 색인 (vectorstore.index_chunks, corpus_<corp>, cosine)

  └─[사전요약 분기]─ 섹션 묶음(가중) → gpt-4o-mini 요약(takeaway) → 임베딩 → summary_<corp>
```

**표 보존 — before/after (가장 큰 품질 레버)**
```
[기존 CrewAI]  모든 태그를 공백 치환 → 표가 plaintext로 뭉개짐 (행·열 소실)
   "과목 주석 제56기 매출액 29 300,870,903 258,935,494 매출원가 ..."   ← 어느 숫자가 뭔지 깨짐

[재구축]       표를 표로 보존 (Markdown)
   | 과목 | 주석 | 제 56 (당) 기 |  | 제 55 (전) 기 |  |
   | Ⅰ. 매출액 | 29 |  | 300,870,903 |  | 258,935,494 |
   | Ⅳ. 영업이익 | 29 |  | 32,725,961 |  | 6,566,976 |        ← 행·열 의미 유지, 정확 수치 안착
```

### 6-2. 런타임 파이프라인 (질문 1턴)
```
ChatV2Request(v2.0)
   │ contract.to_internal
   ▼
[router_agent · gpt-4o-mini] ──▶ RouterResult(intent·search_query·기간·flag)
   ├── smalltalk / out_of_scope ──▶ 즉시 응답(근거 불필요)
   ├── summary ──▶ summary_<corp> 검색(완성 요약, 없으면 corpus 폴백) ──┐
   │ qa                                                                │
   ▼                                                                   │
   asyncio.gather (병렬, 부분실패 graceful) ─────────────────────────┐ │
     ├ corpus 하이브리드 검색 (vectorstore.search)                  │ │
     ├ 재무 결합 (financials, financial_relevant일 때)             │ │
     └ 거시 결합 (macro, macro_relevant일 때)                      │ │
   ◀───────────────────── 근거 합치기(재무 우선) ───────────────────┘ │
   ▼ ◀─────────────────────────────────────────────────────────────────┘
[writer qa_agent · gpt-5.1]  또는  [summary_agent · gpt-4o-mini]   ← 근거 안에서만 작성
   │  provenance = 코드가 검색한 실제 근거로 고정 (citations[:5])
   ▼
[verifier_agent · o4-mini] (샘플링 _should_verify) ──▶ grounded_score
   │  verdict = 임계값(0.7/0.4)으로 코드가 확정
   ▼
ChatResponse ── contract.to_v2 ──▶ ChatV2Response  +  storage.save_chat(보관)
```
| 노드 | 종류 | 모델 | 파일 |
|---|---|---|---|
| router | LLM | gpt-4o-mini | `agents/agents.py` |
| corpus 검색 | 코드 | 임베딩+BM25 | `rag/vectorstore.py` |
| 재무 결합 | 코드(API) | — | `services/financials.py` |
| 거시 결합 | 코드(API) | — | `services/macro.py` |
| writer | LLM | gpt-5.1 | `agents/agents.py` |
| summary | LLM | gpt-4o-mini | `agents/agents.py` |
| verifier | LLM | o4-mini | `agents/agents.py` |

### 6-3. 하이브리드 검색 (진짜 하이브리드)

**BM25는 어떻게 점수를 매기나** — "검색어가 이 문서에 얼마나 잘 맞나"를 세 가지로 계산:
1. **단어 빈도(TF)**: 검색어가 많이 나올수록 점수↑(단, 너무 많으면 포화).
2. **희소성(IDF)**: 흔한 단어("회사·것")는 가중치↓, 드문 단어(`300,870,903`·"하만")는 가중치↑.
3. **문서 길이 보정**: 긴 문서는 단어가 많은 게 당연 → 길이로 정규화.

→ 한마디로 **"드문 핵심어가 · 짧은 문서에 · 적당히 나오면"** 높은 점수. 그래서 **정확 수치·고유명사·티커**에 강하고, 벡터(뜻)가 놓치는 **글자 그대로 일치**를 잡는다. (벡터=뜻, BM25=글자 → 합친 게 하이브리드)

```python
# rag/vectorstore.py::VectorStore.search (요지)
vec_ids  = coll.query(query_embeddings=[q], n_results=candidate_k, where=...)  # 벡터 후보
bm25_ids = 전체 코퍼스 BM25 top-k (지연 캐시 인덱스, where 동일 적용)          # 정답이 벡터 밖이어도 포착
# RRF 융합 (bm25_weight=0.5, _RRF_K=60)
score[id] = (1-w)/(60+rank_vec) + w/(60+rank_bm25)
# 0~1 정규화(상위=1.0) → rerank(중복제거 + 최신우선) → top_k
```
- **이전(가짜 하이브리드)**: BM25가 벡터 후보 20개 *안에서만* 재랭킹 → 정답이 벡터 top-20 밖이면 유실.
- **현재(진짜)**: 벡터 top-k **와** 전체 코퍼스 BM25 top-k의 **합집합**을 RRF로 융합 → 한쪽에만 있어도 생존.
- 숫자 토큰(`300,870,903`)을 한 토큰으로 보존하는 토크나이저 + 날짜/kind 필터를 BM25에도 동일 적용.

### 6-4. End-to-End 워크스루 — 3가지 시나리오
한 질문이 들어와 답이 나가기까지 **실제 값으로** 따라간다. 질문 종류마다 **흐르는 길이 다르다.**

**시나리오 A — 정확 수치(재무 결합) · "삼성전자 영업이익 알려줘"**
1. **요청** — `{roomId, companyContext:{corpCode:"00126380",corpName:"삼성전자"}, messages:[{role:"user",content:"삼성전자 영업이익 알려줘"}]}` 도착. `X-Trace-Id` 있으면 Logfire 루트 span에 바인딩.
2. **라우터(gpt-4o-mini)** → `RouterResult(intent=qa, financial_relevant=true, search_query="영업이익", out_of_scope=false)`. "영업이익"이라 **재무 플래그 ON**.
3. **병렬 검색·결합**(`asyncio.gather`) — ⓐ corpus 하이브리드 검색, ⓑ 재무 결합이 DART `fnlttSinglAcnt(00126380)` 호출 → 연결 영업이익을 **score=1.0** citation으로 **맨 앞 배치**. quote: `"영업이익: 제 57 기 43,601,051,000,000 / 제 56 기 32,725,961,000,000 (단위 원, 연결, 2025 사업보고서 기준)"`, rcept_no=실제 접수번호.
4. **작성(writer gpt-5.1)** → `"삼성전자 영업이익은 제 57 기 43,601,051,000,000원, 제 56 기 32,725,961,000,000원입니다."` (페르소나·콤마표기·근거 기수 그대로).
5. **provenance 고정 + 검증** — 출처는 코드의 실제 근거(`citations[:5]`)로 고정. verifier(o4-mini) `grounded_score≈1.0` → 임계값으로 **verdict=pass**.
6. **응답·보관** — `contract.to_v2`가 `answerText`+`sources[]`(rceptNo·dartUrl)+`verification{verdict:"pass",groundedScore:1.0}`로 변환, SQLite 보관. 프론트는 "정확도 100%"와 출처 카드(+DART 링크) 표시.
> **A 흐름**: 질문 → 라우터(qa·재무ON) → **병렬**[corpus + DART 정형재무] → writer → 검증 → 응답. **정확 숫자는 정형 API가 책임.**

**시나리오 B — 요약(사전요약 트랙) · "삼성전자 사업 내용 요약해줘"**
1. **라우터** → `intent=summary`, `search_query="사업 내용 반도체 디스플레이"`. 재무·거시 플래그 **OFF**.
2. **사전요약 검색** — corpus·재무·거시 **안 탐**. `summary_<삼성>`에서 **완성 요약** top-8 의미검색("DX/DS/SDC/Harman 부문…"). *(없으면 corpus 실시간 RAG 폴백)*
3. **작성(summary gpt-4o-mini)** → 요약 조각 종합 → "삼성전자는 DX·DS·SDC·Harman 등 부문으로 구성되며…"
4. **검증·응답·보관** — 출처는 요약 조각(섹션·rcept_no·dartUrl), verdict=pass.
> **B 흐름**: 질문 → 라우터(summary) → **summary_<corp> 1번 검색** → writer → 응답. **병렬 결합 없이 빠르고 깔끔**(비싼 요약은 빌드때 끝).

**시나리오 C — 거시 결합 · "요즘 환율·금리 상황에서 삼성 실적 어때?"**
1. **라우터** → `intent=qa`, `financial_relevant=true`, **`macro_relevant=true`**, `search_query="실적 매출 영업이익"`.
2. **3중 병렬 결합**(`asyncio.gather`) — ⓐ corpus ⓑ 재무(DART) ⓒ **거시(ECOS)** 동시에. 거시 예: `환율 1,535원·기준금리 2.5%·국고채 3.81%·KOSPI…` (과거값 날짜 캐시).
3. **작성** — 공시 실적 + 거시 스냅샷을 **"같은 시점의 사실"**로 결합(인과 단정은 피함).
4. **응답** — **`macroSnapshot` 채워져** 거시 표가 함께 노출 + 출처 카드.
> **C 흐름**: 질문 → 라우터(qa·재무·**거시**ON) → **3중 병렬**[corpus + 재무 + **거시**] → writer → 응답. **거시 브랜치 추가** + `macroSnapshot` 노출.

---

## 7. 에이전트 영역 상세 ★핵심

에이전트는 이 프로젝트의 핵심이다. **5개 에이전트가 전부 `agents.py` 한 파일에 모듈 레벨로 정의**되고, 각각 **모델 · 출력 스키마(`output_type`) · 지시문(`instructions`)** 셋으로 설정된다. 말투는 공통 `_PERSONA` 공유.

| 에이전트 | 모델 | output_type | 지시문 요지 | _PERSONA |
|---|---|---|---|---|
| **router** | gpt-4o-mini | `RouterResult` | 의도 분류 + 검색쿼리 정제 + 재무·거시 플래그 + 기간 | 공유 |
| **writer(qa)** | **gpt-5.1** | `QAResult` | 근거 안에서만 답 · 수치 콤마표기 · 기준 모호하면 되묻기 | 공유 |
| **summary** | gpt-4o-mini | `SummaryResult` | 근거로 서술 요약 · 메타설명/추측 금지 | 공유 |
| **verifier** | o4-mini | `VerificationResult` | 답이 근거에 충실한지 `grounded_score` 채점 | 제외* |
| section_summary(빌드용) | gpt-4o-mini | (text) | 섹션 1묶음 → takeaway 요약(사전요약 빌드) | 공유 |

\* verifier는 답을 "쓰는" 게 아니라 "채점"만 해서 말투 페르소나 불필요. 모델·임계값은 전부 `.env`/`config.py`로 조정.

**실제 코드 — 공통 페르소나 + 지시문** (`agents.py`, 축약):
```python
# 모든 답변이 공유하는 말투 규칙 (한 곳에서 정의)
_PERSONA = "[역할·말투—공통] 정중한 존댓말 · 서론 없이 본론부터 · 이모지/느낌표 금지 · 사실 중심 …"

def _m(name): return f"openai:{name}"     # 모델명 → provider 경로 (키는 .env)

# ── 5개 에이전트: 모델 + output_type + (지시문 = _PERSONA + 고유지시) ──
router_agent = Agent(_m(_s.router_model),          # gpt-4o-mini
    output_type=RouterResult,
    instructions=_PERSONA + "너는 라우터다. 의도(qa/summary/…)·검색쿼리·플래그를 정한다 …")

qa_agent = Agent(_m(_s.qa_model),                  # gpt-5.1
    output_type=QAResult,
    instructions=_PERSONA + "너는 공시 분석가다. [근거]만 사용해 답한다. 수치는 콤마 표기 그대로 …")

verifier_agent = Agent(_m(_s.verification_model),  # o4-mini
    output_type=VerificationResult,
    instructions="너는 검증자다. 답이 근거에 충실한지 grounded_score를 매긴다 …")  # _PERSONA 없음(채점만)

# ── 호출 (services/chat.py) — 검색은 코드가 끝내고 근거를 프롬프트로 (retrieve-then-read) ──
qa = (await qa_agent.run(f"[질문]\n{q}\n\n[근거]\n{evidence}")).output   # → QAResult (검증·자동재시도)
```
→ `_PERSONA + "고유지시"` 한 줄로 말투를 공유하고, `output_type`이 결과를 스키마로 검증. 말투를 바꾸려면 `_PERSONA` 한 곳만.

### 7-1. 관용구 — "모듈 레벨 1회 정의 + retrieve-then-read"
```python
# agents/agents.py — 모듈 로드 시 1회 생성(재사용)
qa_agent = Agent("openai:gpt-5.1", output_type=QAResult, instructions=_PERSONA + "근거 안에서만 답…")

# services/chat.py — 검색은 코드가 끝내고(retrieve), 근거를 프롬프트로 넣어 읽게 함(read)
evidence = format_citations(citations)
qa = (await qa_agent.run(f"[질문]…[근거]\n{evidence}")).output   # 에이전트는 작성만
```
- **왜**: 에이전트에 "검색 툴"을 쥐여주면 (a)환각 (b)비용↑ (c)비결정성. 검색을 코드가 결정적으로
  끝내면 **근거가 고정**돼 재현 가능·저렴(실무 정확성-우선 RAG의 표준).

### 7-2. output_type — 검증 + 자동 재시도
`Agent(output_type=QAResult)`면 LLM 출력이 **QAResult로 검증**되고 **틀리면 자동 재시도**된다.
즉 "JSON 깨짐/필드 누락"을 프레임워크가 막는다.

### 7-3. provenance 고정 — 환각 차단
에이전트가 citations를 **지어내지 못하게**, 응답 출처는 **코드가 검색한 실제 근거**(`citations[:5]`)로 고정.
재무 정형수치는 앞에 배치돼 항상 상위 근거로 포함된다.

### 7-4. verifier — 샘플링 + 임계값
- `_should_verify`로 검증 빈도 제어(`verify_sample_rate`; 현재 1.0=매 턴 → 프론트 "정확도 %" 항상 표시).
- verifier는 `grounded_score`(0~1)만 잘 매기고, **verdict(pass/partial/fail)는 코드가 임계값(0.7/0.4)으로
  확정** → 모델 라벨 변동 제거(결정적).

### 7-5. 공통 페르소나 — 말투 일관성
4개 에이전트가 `_PERSONA`(정중한 존댓말, 차분한 전문가 톤, 이모지·느낌표·서론 금지, 사실 중심)를
공유해, 모델이 달라도(gpt-5.1·gpt-4o-mini) **한 사람이 말하는 것처럼** 일정하다. 수치는 출처의 콤마
표기를 그대로 쓰고(조/억 변환 금지), 기수는 근거에 적힌 명칭(제57기 등)을 그대로 쓴다.

**7-5-1. 페르소나(말투)는 어떻게 설정했나** — 말투가 제각각이던 문제를 하나의 공통 규칙으로 묶었다. `agents.py`의 `_PERSONA` 상수:
```
_PERSONA = (
  "[역할·말투 — 모든 답변 공통, 반드시 일관되게]
   너는 'gongsitoktok' 공시 분석 어시스턴트다. 출력 문체는 항상 동일하게 유지한다:
   - 정중한 존댓말. 서술='~합니다/입니다'체, 안내='~해 주세요'체로 통일.
   - 차분·간결한 전문가 톤. 인사말·사과·자기언급·서론 없이 본론부터.
   - 과장/홍보 수식어, 이모지, 구어체 감탄사('음','와','네!'), 느낌표 남발 금지.
   - 1인칭('저는')·2인칭 호칭 없이 사실 중심으로 서술."
)
```
1. **적용** — 각 에이전트 정의에서 지시문 앞에 붙인다: `instructions = _PERSONA + "(에이전트별 고유 지시)"`. router·writer(qa)·summary·section_summary가 공유(verifier는 채점만 해서 제외) → **모델이 달라도 같은 말투**.
2. **수치·기수 규칙(따로)** — writer/summary에 추가: "정확 수치는 **출처 콤마 표기 그대로**(43,601,051원), 조/억 변환 금지. 기수는 근거 명칭(제57기) 그대로." → 숫자 표기 흔들림도 고정.
3. **왜 한 곳에** — 말투·규칙을 바꾸려면 `_PERSONA` 한 곳만 고치면 전 에이전트 일괄 반영. (CrewAI는 backstory가 함수마다 흩어져 일관성 맞추기 어려웠음 — §11·§16-4)

### 7-6. 복합·멀티턴 질문은 어떻게 처리되나
"한 번에 2가지", "이전 질문 이어받기", "도중에 다른 트랙으로 전환"의 처리.
1. **복합 질문(한 번에 2가지)** — 라우터는 **intent 1개 + 플래그**(`financial_relevant`·`macro_relevant`)를 정한다. "매출 얼마고 환율 영향은?" → `intent=qa` + 재무 + 거시 → corpus·재무·거시 **병렬 결합**해 writer가 통합 답. **한계**: intent가 1개라 "요약+정확수치" 혼합이나 서로 다른 주제 2개 비교는 약함 → 추후 **에이전트 쿼리 분해**(시나리오 D, §15).
2. **멀티턴(이전 질문 이어받기)** — 최근 대화(history)를 **라우터·writer에 함께** 넘긴다. 생략된 주어·지시어("그럼 매출은?", "그거 더 자세히")를 직전 맥락으로 해석해 `search_query` 정제, writer도 "그거/방금"을 푼다. **행동 평가 멀티턴 케이스로 검증됨.**
3. **도중에 다른 트랙으로 전환** — 라우터는 **매 턴 새로 분류**. 같은 방에서 이전엔 요약, 지금은 정확수치를 물으면 intent·플래그가 그 턴에 맞게 바뀐다(summary→qa). 트랙은 **턴마다 독립 결정**, out_of_scope 가드도 매 턴 적용.
4. **상태는 누가 갖나** — AI는 **stateless**. 세션·대화이력은 백엔드가 소유하고 매 요청 `messages`로 넘김(마지막=현재 질문, 나머지=history 최근 10개) → 같은 입력에 같은 출력(재현 가능).

---

## 8. 요약은 어떻게 이뤄지고 활용되나 ★핵심

**핵심** — "비싼 요약은 **빌드때 1번**, 질의때는 **꺼내쓰기만**". 각 공시 섹션을 미리 요약해
`summary_<corp>` 컬렉션에 저장하고, summary 질문은 그 **완성 요약**을 검색한다(사전요약 트랙, **구현 완료**).

### 8-1. 무엇을 기준으로 요약하나 (criteria)
1. **단위 — 섹션(목차)별**: DART 섹션 계층 단위. micro-섹션은 ~6,000자 묶음으로 합치고 공시 1건당 ~40묶음 상한, 200자 미만 스킵.
2. **가중 — 분석 가치 높은 섹션 우선**: 사업의 내용·경영진단(MD&A)·위험·주석·주요계약·연구개발 ↑, 정관·임원명부·계열회사 제외/후순위(`summarize._weight`). 표는 제외(수치는 RAG/재무).
3. **takeaway 지시**: "실제 내용(사업·전략·리스크) 3~6문장, 목차식 메타설명 금지, 정밀 수치 망라 금지(대표 1~2개)" → 요약=서술, 정확수치=corpus/재무로 **역할 분리**.
> 현재는 **"기본"**(섹션+가중+takeaway). 변화탐지·이벤트트리거는 추후 고급(§15).

### 8-2. 데이터 흐름 — 빌드(생성) → 질의(소비)
```
[빌드 타임 · 1회 ~$1-2]  DART 원문 → 파서(Block) → 섹션 묶음(가중) → gpt-4o-mini 요약
                      → 임베딩 → summary_<corp> 컬렉션 저장 (corpus와 별개 저장소)
[질의 타임 · summary]   router(intent=summary) → summary_<corp> 벡터검색(완성 요약 top-k)
                      → summary_agent 종합 → 답 (출처 rcept_no·섹션·dartUrl 유지)
                      → 사전요약 없으면 기존 corpus 실시간 RAG로 자동 폴백
```
- 저장소 **2개 분리**: `corpus_<corp>`(원문·정확사실·QA) + `summary_<corp>`(사전요약·개요).
- **qa(정확수치)·재무·거시·verifier·v2.0 계약·보관은 그대로** — summary 트랙만 바뀐다. 폴백이 있어 점진 적용 안전.

#### 8-2-1. "corpus 폴백"이 정확히 하는 일 (상세)
summary 질문은 항상 `summary_<corp>`를 **먼저** 뒤지고, 결과가 안 나오면 corpus로 폴백한다.
1. **언제 발동(정확한 조건)** — `search_summaries()`가 **빈 리스트**를 돌려줄 때만 = `summary_<corp>` **컬렉션이 없거나(미빌드) 비었을 때**. 벡터 검색은 데이터만 있으면 어떤 질문이든 **항상 top-k를 반환**하므로, "질문이 안 맞아서"가 아니라 **"그 회사가 아직 사전요약 안 됨"**이 유일한 발동 조건.
2. **무엇을 하나** — `corpus_<corp>`에서 **원문 텍스트 청크**(`kind=text`) top-8 검색(완성 요약이 아닌 원문 그대로) → `summary_agent`에 [근거]로 넣어 **질의 시점에 요약 생성**(= 사전요약 도입 *전*의 '실시간 RAG 요약').
3. **왜 있나(안전장치)** — 점진 적용용. 새 회사 추가 후 `build_summaries` 전에도 요약이 **안 깨지고 동작**.
4. **현재 상태** — 삼성·현대 둘 다 빌드돼 **폴백은 실제로 안 탐**(항상 사전요약). 폴백은 "보험".
5. **트레이드오프** — 폴백은 **매 질의 재검색+재요약**이라 느리고 비쌈(사전요약 장점 사라짐). 정상 경로가 빠르고 안정적.

**두 경로의 차이 = `summary_agent`에 넣는 [근거]가 무엇이냐** (최종 답은 둘 다 summary_agent가 씀):

| | 정상(사전요약 트랙) | 폴백(corpus) |
|---|---|---|
| 근거 | 이미 만든 **완성 요약** 조각 | **원문 텍스트 청크**(요약 안 됨) |
| 요약 시점 | 빌드때(미리, 1회) | **질의때(즉석, 매번)** |
| summary_agent 역할 | 요약 조각 **종합·정리** | 원문에서 **요약 생성** |
| 속도·비용 | 빠름·쌈 | 느림·비쌈 |

### 8-3. 효과
| 항목 | 효과 |
|---|---|
| 요약 품질↑ | 섹션 전체를 보고 1번 정성껏 요약(우연히 집은 5청크가 아니라). 빈약한 수치 표에 끌려가던 문제 해소 |
| 질의 비용↓·속도↑ | 비싼 요약은 빌드때, 질의땐 꺼내기만 |
| 출처 유지 | 요약 조각도 rcept_no·섹션·dartUrl 유지 → provenance |

---

## 9. 과제형 보관/조회 + v2.0 계약 연동

### 9-1. 과제형(RFP 1급): 요약→근거 QA→**보관→조회**
RFP는 "단순 챗봇"이 아니라 **답을 저장하고 나중에 다시 꺼내보는 과제형**을 요구. 그래서 챗 답을 DB에 쌓고 목록·상세로 조회한다. (구현: `storage/db.py`+`api/routes.py`)

| 엔드포인트 | 하는 일 | 비유 |
|---|---|---|
| `POST /api/v1/chat` | 챗 처리 + **근거 있는 답을 SQLite(`analyses`)에 자동 저장** | 질문하면 답하고 **기록 남김** |
| `GET /api/analyses` | 저장된 분석 **목록**(id·회사·제목·요약 한 줄·시각) | "내 분석들" **목록 화면** |
| `GET /api/analyses/{id}` | 분석 1건 **상세**(질문·답·근거·검증) | 눌러서 **자세히 보기** |

> **"마이페이지 카드"** = 프론트(`gongsitoktok`)가 `GET /api/analyses` 결과를 카드 리스트로 보여주는 화면(프론트 영역). AI는 **저장·조회 API**만 제공.

### 9-2. v2.0 계약 (백엔드 `finance_v2` 드롭인 호환)
내부 스키마와 분리된 **camelCase 와이어 계약**을 `contract.py` 어댑터로 변환 → 백엔드 코드 수정 없이 연동.
```
요청  ChatV2Request : { roomId, userSeq, companyContext:{corpCode,corpName}, messages:[{role,content}] }
응답  ChatV2Response: { roomId, intent, answerText, sourceContent, macroSnapshot,
                        sources:[{rceptNo,reportNm,rceptDt,sectionTitle,quote,score,dartUrl}],
                        outOfScope, detectedCompany, needsClarification,
                        verification:{verdict,groundedScore}, error }
```
- `verification.groundedScore`(0~1) = 답변 1건의 **최종 정확도**(프론트 "정확도 %"로 표시).
- `sources[].score` = 출처별 검색 관련도(0~1 정규화). `dartUrl` = DART 원문 뷰어 링크.

### 9-3. X-Trace-Id 端-to-端 추적
백엔드가 보낸 `X-Trace-Id`를 **응답 헤더로 echo + Logfire 루트 span에 바인딩**한다. 그 아래 AI 내부
호출(router→검색→writer→verifier)이 자식 span으로 묶여, **백엔드 trace_id 하나로 AI 추론 과정까지
추적**된다(금융권 감사가능성). 관찰성 off면 no-op.

### 9-4. 실제 요청/응답 예시 (v2.0)
**요청 — `POST /api/v1/chat`** (헤더 `X-Trace-Id` 선택)
```json
{
  "roomId": 42, "userSeq": 1,
  "companyContext": { "corpCode": "00126380", "corpName": "삼성전자" },
  "messages": [ { "role": "user", "content": "삼성전자 영업이익 알려줘" } ]
}
```
**응답 — `ChatV2Response`** (발췌)
```json
{
  "roomId": 42, "intent": "qa",
  "answerText": "삼성전자 영업이익은 제 57 기 43,601,051,000,000원, 제 56 기 32,725,961,000,000원입니다.",
  "sourceContent": "[20260318001394 / 삼성전자 2025 사업보고서 주요계정]\n영업이익: 제 57 기 ...",
  "macroSnapshot": null,
  "sources": [
    { "rceptNo": "20260318001394", "reportNm": "2025 사업보고서 주요계정",
      "sectionTitle": "정형 재무(DART)", "quote": "영업이익: 제 57 기 43,601,051,000,000 / ...",
      "score": 1.0, "dartUrl": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260318001394" }
  ],
  "outOfScope": false, "detectedCompany": null, "needsClarification": false,
  "verification": { "verdict": "pass", "groundedScore": 1.0 },
  "error": null
}
```
> `-`가 아닌 **실제 접수번호**가 박혀 `dartUrl` 링크 생성(재무 인용도 클릭 시 DART 원문). 거시 질문이면 `macroSnapshot`, 다른 회사/비교면 `outOfScope:true`·`detectedCompany`가 채워진다.

---

## 10. 데이터 규모 & 실측 수치

| 항목 | 값 |
|---|---|
| 대상 기업 | 삼성전자 `00126380`, 현대자동차 `00164742` |
| 적재 공시 | 정기보고서 **32건** (삼성 16 + 현대 16, 2021.12~2025.11) |
| 총 청크 (corpus) | **67,023** (삼성 23,444 + 현대 43,579), cosine |
| 사전요약 (summary) | **1,188 요약** (삼성 380 + 현대 808), `summary_<corp_code>` |
| 검증 샘플(삼성 사업보고서 `20250311001085`, 원문 6.9M자) | 파싱 블록 2,288(text 395/table 1,893) → 청크 2,611(text 502/table 2,109), 평균 501자/최대 2,497자 |
| 골든 핵심 수치(구조보존 표 청크 안착) | 매출 **300,870,903** · 영업이익 **32,725,961** · 전기 258,935,494 |

> 참고: 일부 초기 문서·README는 "33건"으로 추정했으나, **실제 적재 로그 기준 32건**(삼성16+현대16)이다.

---

## 11. 기존(CrewAI)에서 바꾼 결정적·합리적 이유

### 11-1. 핵심 — 오케스트레이션은 같다, 진짜 바뀐 건 3가지
오케스트레이션(흐름)은 **두 버전 모두 `services/chat.py`(우리 코드)** 에 있고 프레임워크 독립적이다.
즉 "기존도 이미 아키텍처화돼 있었다." 진짜 바뀐 핵심:
1. **인제스트** — 표 plaintext 뭉갬 → **표-인식 보존 + Contextual**(가장 큰 품질 레버)
2. **검색** — 벡터+키워드폴백 → **진짜 하이브리드(벡터∪전체BM25 RRF) + dedup/최신우선**
3. **프레임워크** — 무거운 CrewAI 단일 래퍼 → **경량 PydanticAI**

### 11-2. 프레임워크 비교 (왜 교체가 합리적인가)
| | CrewAI(기존) | PydanticAI(재구축) |
|---|---|---|
| 에이전트 정의 | role/goal/backstory 롤플레이 | model+instructions+output_type 타입선언 |
| 생성 시점 | **매 호출** Agent+Task+Crew 재생성 | **모듈 레벨 1회**(싱글톤 재사용) |
| 구조화 출력 | output_pydantic + 수동 추출 | output_type **네이티브 검증+자동 재시도** |
| LLM 레이어 | litellm(o4-mini 파라미터 수동 제거) | provider 네이티브 |
| 멀티에이전트 협업 | 안 씀(단일 래퍼로 전락) | 동일 목적, 더 경량 |

→ 기존은 "구조화 출력 한 번 뽑으려 무거운 팀협업 프레임워크를 단일에이전트로 쓴 것". 교체 이득은
**기능이 아니라 무게·관용구·유지보수성**.

### 11-3. 정량 비교 (실측)
"경량"이 얼마나 가벼워졌는지 코드 기준 실측:

| 지표 | 기존 CrewAI (crew.py) | 재구축 PydanticAI (agents.py) | 차이 |
|---|---|---|---|
| 에이전트 정의 코드량 | **448줄** | **144줄** | **약 1/3 (−68%)** |
| 호출(턴)당 생성 객체 | Agent+Task+Crew **3개 재생성** | **0개**(모듈 싱글톤 재사용) | 매 호출 객체 생성 제거 |
| 에이전트 1회 호출 코드 | 정의+kickoff+추출 **≈30줄** | `(await agent.run(prompt)).output` **1줄** | 호출부 대폭 축소 |
| 구조화 출력 | `output_pydantic`+수동 `_as_pydantic` | `output_type` 네이티브 검증+**자동 재시도** | 추출 제거 + 재시도 무료 |
| LLM 레이어 | litellm 경유(파라미터 수동 제거) | provider 네이티브 | 중간 레이어 제거 |
| 의존성 무게 | crewai(litellm 등 무거움) | pydantic-ai-slim(경량) | 설치·기동 가벼움 |

→ **핵심**: 같은 일(LLM→검증된 Pydantic 객체)을 **코드 1/3, 호출당 객체 0**으로. 6개 함수가 각각 Agent+Task+Crew를 **매 호출 재생성**하던 안티패턴이 **모듈 1회 정의·재사용**으로 바뀐 게 정량 차이의 핵심. (지연·비용은 LLM 호출이 좌우 → 프레임워크 교체로 직접 안 줆. 줄어드는 건 **코드·객체·의존성**)

**리소스 측면(직관)** — 단순히 "코드가 줄었다"를 넘어:

| 측면 | 기존 CrewAI | 재구축 PydanticAI | 직관적으로 |
|---|---|---|---|
| **호출당 객체 생성**(메모리·GC) | 함수마다 Agent+Task+Crew **3개 생성→폐기**. 한 턴이면 **~9개** 만들고 버림 | 모듈 싱글톤 **재사용 → 호출당 0개** | "매 질문마다 객체 ~9개 만들고 버리기" vs "0개" → 메모리·GC 부담↓ |
| **프레임워크 코어** | crewai 풀 프레임워크(도구·메모리·litellm 번들) | pydantic-ai 코어 **≈36KB**(슬림)+필요 provider만 | 얇은 코어 |
| **LLM 호출 경로** | 앱 → **litellm** → provider(한 겹 더) | 앱 → provider(네이티브) | 중간 레이어 한 겹 덜 |
| **import·기동** | 무거운 deps → 느림 | 가벼움(agents import **≈0.68s**) | 첫 응답까지 빠름 |

> **정직하게**: 정밀 CPU/RAM 벤치마크는 안 함(실행 자원의 대부분은 **LLM 호출=네트워크**라 프레임워크 영향이 작음). 프레임워크가 줄이는 건 **①객체 churn ②설치·코어 무게 ③호출 경로 ④cold start** — "정밀 수치"보다 **구조적 가벼움**으로 이해.

### 11-3b. 정직한 인정
재구축하며 "고친" 것 중 일부는 **기존에도 있었고** 다시 만든 것이다: retrieve-then-read,
인용 정본화(provenance, 기존 `_reconcile`), 임계값 verdict(기존 `_verdict_from_score`), 재무·거시 결합,
날짜필터. **사전요약 트랙은 기존에도 있었고, 재구축에서 (기본 단계로) 다시 구현**(§8). → 재구축의 진짜 가치는
"없던 걸 만든 것"이 아니라 **인제스트·검색 품질 + 프레임워크 현대화**다.

---

## 12. 검증 — 3계층 eval

| 계층 | 무엇 | 비용 | 결과 |
|---|---|---|---|
| **① 검색** (`eval_retrieval.py`) | 정답 청크 회수율 hit@k·MRR — 표파싱·하이브리드·Contextual 직접 측정 | **무료·결정적**(LLM 없음) | must **11/11 hit@5(100%)**, MRR **0.923** |
| **② 행동** (`eval_chat.py`) | 멀티턴·거시결합·표질의·되묻기·스코프비교·숫자신선도 | LLM | **6/6 must + 2 watch** |
| **③ 회귀** (`run_golden_inproc.py`) | 기존 14케이스 회귀 스모크(인텐트·정확수치·스코프) | LLM | **12/12 must + 2 watch** |

- **검색 평가**가 핵심: LLM 없이 임베딩+BM25만 돌려 **공짜·결정적**으로 검색 품질을 격리 측정 →
  재구축의 진짜 개선을 숫자로 증명. CI에서 매번 돌릴 수 있다.
- **행동 평가가 실제 버그를 잡음**: "삼성전자**랑** SK하이닉스 중 누가 더 높아?"가 out_of_scope로
  안 걸리던 걸 발견 → 라우터에 **비교 질문** 규칙 추가해 수정(기존 골든은 순수 타사 질문이라 못 잡던 케이스).
- **숫자 신선도**: 하드코딩 대신 `has_number`+`verdict`로 검증 → 새 보고서 나와도 안 썩음.

### 12-1. 어떤 기준으로 케이스를 구성하나
각 케이스 = **질문(또는 검색쿼리) + 기대(expect) + 중요도(severity)**. JSON 한 줄로 관리.
- **중요도** — `must`=하드 통과 기준(하나라도 실패면 FAIL), `watch`=알려진 약점(미통과 허용·추적용). 합격률은 must로만 집계.
- **선정** — ①핵심 동작(요약·정확수치·스코프) ②어려운 케이스(멀티턴·거시·표질의·되묻기·비교) ③약점 추적(watch). 삼성·현대 둘 다.

**기대(expect) — assertion 종류**

| assertion | 뜻 |
|---|---|
| `intent` | 라우터 분류가 기대와 같은지 |
| `contains_any` | 답·근거에 이 문자열 중 하나 포함(키워드/수치) |
| `has_number` | 콤마 숫자 토큰 포함(값 미고정 → 신선도) |
| `verdict_not` | 이 verdict면 실패(예: `fail` 금지) |
| `out_of_scope`/`macro_used`/`needs_clarification`/`no_citations` | 스코프가드/거시결합/되묻기/근거없음(스몰토크) 확인 |
| `expect_any`(검색) | top-k 결과 섹션·인용에 이 문구 있으면 hit (hit@k·MRR) |

**실제 케이스 예시**
```jsonc
// 행동 평가 — 멀티턴 (history로 생략된 주어 해석)
{ "id":"multiturn-anaphora", "company":{"corpCode":"00126380","corpName":"삼성전자"},
  "history":[{"role":"user","content":"삼성전자 영업이익 알려줘"},
             {"role":"assistant","content":"…영업이익은 제57기 43,601,051,000,000원입니다."}],
  "question":"그럼 매출액은?",
  "expect":{"intent":"qa","has_number":true,"verdict_not":"fail"}, "severity":"must" }

// 검색 평가 — 표-인식이 살린 부문 표
{ "id":"ss-ret-segment", "corp":"00126380", "query":"사업부문별 매출 DX DS 반도체",
  "expect_any":["DX 부문","DS 부문","부문별"], "severity":"must" }
```

### 12-2. 어떻게 실행·확인하나
- **인프로세스(서버 불필요)** — `handle_chat()`/`store.search()` 직접 호출.
- **검색 평가는 무료·결정적** — LLM 없이 임베딩+BM25 → CI 매번 가능. 행동·회귀는 LLM(턴당 비용).
- **통과 기준** — must 전부 통과면 종료코드 0(CI), watch는 분리 집계. 케이스별 PASS/FAIL/WATCH 출력.
```bash
PYTHONPATH=. .venv/bin/python -m eval.eval_retrieval     # 검색(무료·결정적)
PYTHONPATH=. .venv/bin/python -m eval.eval_chat          # 행동
PYTHONPATH=. .venv/bin/python -m eval.run_golden_inproc  # 회귀
```

**예시로 보기 — ① 골든 파일 → ② 검증 코드 → ③ 실제 출력**
```jsonc
// ① eval/chat_golden_set.json (발췌)
{ "_meta": { "purpose": "회귀 방지·동작 검증", "endpoint": "POST /api/v1/chat" },
  "cases": [
    { "id": "ss-num-opincome",
      "company": { "corpCode": "00126380", "corpName": "삼성전자" },
      "question": "삼성전자 영업이익 알려줘",
      "expect": { "intent": "qa", "contains_any": ["43,601,051","32,725,961"] },
      "severity": "must" } ] }
```
```python
# ② eval/run_golden_inproc.py — 검증 로직(발췌)
def evaluate(case, resp):
    exp  = case["expect"]
    text = resp.answer + " " + " ".join(c.quote for c in resp.citations)   # 답 + 근거 인용
    if "intent" in exp and resp.intent.value != exp["intent"]:        ...  # intent 불일치 → 실패
    if "contains_any" in exp and not any(s in text for s in exp["contains_any"]): ... # 문구 없음 → 실패
    if "verdict_not" in exp and resp.verification.verdict.value == exp["verdict_not"]: ... # 금지 verdict
    return (실패사유_없음, 실패사유목록)
# 각 케이스를 handle_chat()에 넣고 evaluate → PASS/FAIL/WATCH 집계 (서버 불필요)
```
```text
# ③ 실제 실행 출력(발췌)
=== 챗 골든셋 14케이스 (인프로세스) ===
  [PASS ] ss-num-opincome        | 숫자 트랙 - 영업이익(RAG exact-match)
  [PASS ] ss-scope-other-company | 스코프 가드 - 다른 회사 질문
  ...
--- 결과 ---   must : 12/12 통과   watch : 2/2 통과
✅ must 전부 통과
```
→ 파일에 케이스 한 줄 추가하면 바로 검증 대상. 미통과 시 사유(`intent=summary (기대 qa)` 등)가 함께 찍혀 디버깅 쉬움.

### 12-3. 결과 (현재)
| 계층 | 케이스 | 결과 |
|---|---|---|
| ① 검색 | 13 (must 11 / watch 2) | **must 11/11 hit@5(100%) · MRR 0.923** |
| ② 행동 | 8 (must 6 / watch 2) | **must 6/6 · watch 2/2** |
| ③ 회귀(골든) | 14 (must 12 / watch 2) | **must 12/12 · watch 2/2** |

사전요약 트랙 도입 후에도 회귀 없음(요약 케이스 전부 통과). 상세는 `eval/EVAL_README.md`.

**측정 방법 (코드 기준)**: `intent`=정확 일치 · `contains_any`=answer+모든 citation.quote 텍스트에 부분문자열 포함 · `has_number`=정규식 `\d{1,3}(,\d{3})+` · `verdict_not`=verdict(=grounded_score 임계값 0.7/0.4로 도출)가 금지값이면 실패 · `out_of_scope`/`macro_used`/`needs_clarification`=불리언 플래그 · `no_citations`=citations 길이 0 · 검색 `expect_any`=top-k의 (section_title+quote)에 첫 등장 순위 → `1/순위`로 MRR. **집계**: must 전부 통과 시 종료코드 0(CI), watch는 분리.

### 12-4. 전체 케이스 목록 (무엇을 검사했나)
실제 검사한 35개 케이스 전부. ✅=must 통과, 🔶=watch(약점·추적용).

**① 회귀 골든 — 14건 · must 12/12**

| 케이스 | 질문 | 검사 포인트 |
|---|---|---|
| ✅ ss-summary-overview | 삼성 회사 개요 요약 | intent=summary·verdict≠fail |
| ✅ ss-summary-business | 삼성 사업 내용 요약 | 반도체·메모리·DX·DS·하만 중 포함 |
| ✅ ss-num-revenue | 삼성 연간 매출액 | 300,870,903 / 333,605,938 |
| ✅ ss-num-opincome | 삼성 영업이익 | 43,601,051 / 32,725,961 |
| ✅ ss-num-assets | 삼성 자산총계 | 566,942,110 / 514,531,948 |
| 🔶 ss-route-business-plain | 삼성 무슨 사업 해? | '요약' 없는 서술 → summary |
| ✅ ss-scope-other-company | SK하이닉스 영업이익 | out_of_scope=true |
| ✅ hd-summary-overview | 현대 회사 개요 요약 | intent=summary·verdict≠fail |
| ✅ hd-summary-business | 현대 사업 내용 요약 | 자동차·전기차·제네시스 등 포함 |
| ✅ hd-num-revenue | 현대 연간 매출액 | 175,231,153 |
| ✅ hd-num-opincome | 현대 영업이익 | 숫자 포함·verdict≠fail |
| ✅ hd-num-liabilities | 현대 부채총계 | 숫자 포함·verdict≠fail |
| 🔶 hd-route-business-plain | 현대 무슨 사업 해? | summary 라우팅 |
| ✅ hd-scope-other-company | 기아 매출 | out_of_scope=true |

**② 행동 — 8건 · must 6/6**

| 케이스 | 질문 | 검사 포인트 |
|---|---|---|
| ✅ multiturn-anaphora | (이전:영업이익) "그럼 매출액은?" | 멀티턴—history로 주어 해석, 숫자 답 |
| ✅ macro-combine | 요즘 환율·금리 상황 | macro_used=true |
| ✅ table-segment | 삼성 사업부문 어떻게 나뉘어? | DX·DS·부문 포함(표-인식) |
| ✅ num-freshness-revenue | 현대 매출액 | 숫자 포함(값 미고정) |
| ✅ smalltalk-thanks | 오 고마워 | intent=smalltalk·근거없음 |
| ✅ scope-compare | 삼성 vs SK하이닉스 비교 | out_of_scope=true |
| 🔶 clarify-ambiguous | 삼성 이익 얼마야? | '이익' 모호 → 되묻기(변동 허용) |
| 🔶 unanswerable-future | 현대 내년 전망치 | 미래 전망 환각 대신 한계 |

**③ 검색 — 13건 · must 11/11 hit@5(100%)**

| 케이스 | 검색쿼리 | 정답 회수 기대 |
|---|---|---|
| 🔶 ss-ret-income-revenue | 연결 손익계산서 매출액 | 300,870,903 / 손익계산서 |
| ✅ ss-ret-segment | 사업부문별 매출 DX DS | DX 부문 / DS 부문 / 부문별 |
| ✅ ss-ret-business | 주요 사업 메모리 반도체 | DRAM / NAND / 메모리 |
| ✅ ss-ret-harman | 하만 전장 디지털 콕핏 | Harman / 하만 / 콕핏 / 전장 |
| ✅ ss-ret-dividend | 배당 정책 결산배당 | 배당에 관한 사항 / 배당 |
| ✅ ss-ret-treasury | 자기주식 취득 처분 | 자기주식 |
| ✅ ss-ret-largest | 최대주주 지분 현황 | 최대주주 |
| ✅ ss-ret-rnd | 연구개발 실적 비용 | 연구개발 |
| ✅ ss-ret-risk | 사업위험 재무위험관리 | 위험관리 / 재무위험 / 파생 |
| 🔶 ss-ret-region | 지역별 매출 미주 유럽 | 지역 / 미주 / 유럽 (terse 약점) |
| ✅ hd-ret-business | 주요 사업 자동차 제조 | 자동차 / 차량 / 사업의 내용 |
| ✅ hd-ret-dividend | 배당 정책 결산배당 | 배당 |
| ✅ hd-ret-rnd | 연구개발 친환경 전동화 | 연구개발 / 친환경 / 전동 |

### 12-5. 개발 일지 — 잡은 버그와 교훈
코드가 지금 모양인 **이유**는 대개 이 버그들에서 왔다. 증상 → 원인 → 수정.

| 증상 | 원인 | 수정 / 교훈 |
|---|---|---|
| 청크 폭증(삼성 1건 11.7M자, 임베딩 한계 초과) | 일부 표의 "헤더"가 1.8만자 거대 셀인데 매 조각에 반복 | 헤더가 비정상이면 반복 끄고 `_hard_wrap` 강제 분할. **표 분할에 안전장치 필수** |
| 요약이 일반지식 환각, 출처가 답 문장과 동일 | summary가 근거 대신 **자기 문장을 citations로 생성**(순환참조) | provenance를 **코드의 실제 근거**(`citations[:5]`)로 고정. **출처를 에이전트에 맡기지 말 것** |
| "현대 매출" 정확수치 빠짐(회귀) | 재무 citation을 corpus 뒤에 붙여 `citations[:5]`에서 잘림 | 재무 정형수치 **앞에 배치**. **1급 근거는 순서가 중요** |
| "지역별 매출"이 엉뚱한 주주현황을 잡음 | RRF 가중 0.6/0.4라 벡터 5개가 BM25 1위보다 높아 **top-5가 순수 벡터** | 동등 가중(0.5)로 1:1 교차. **융합 가중이 한쪽을 묻으면 하이브리드가 아님** |
| "삼성**랑** SK 비교"가 out_of_scope 안 걸림 | 방 회사가 같이 언급돼 in-scope 오판. 기존 골든은 순수 타사라 못 잡음 | 라우터에 **비교 질문** 규칙. **행동 평가(eval)가 이 버그를 잡음** |
| 답마다 말투·도입부 제각각, 기수 오기 | 답 주체 4개가 페르소나 미공유 + 재무 근거에 기수 명칭 없어 추측 | 공통 `_PERSONA` + 재무 quote에 실제 기수(`thstrm_nm`). **일관성=공유 규칙+근거 명시** |
| verifier verdict가 런마다 pass↔fail 변동 | 모델이 verdict 라벨을 직접 매겨 비결정적 | `grounded_score`만 받고 **verdict는 코드가 임계값(0.7/0.4)으로 확정** |

**교훈 요약** — ①에이전트엔 "작성"만, 출처·판정은 코드가 고정 ②융합·분할엔 안전장치 ③일관성은 공유 페르소나+근거 명시 ④**좋은 eval이 진짜 버그를 잡는다.**

---

## 13. API 절약 / 비용 로직

| 기법 | 내용 |
|---|---|
| **모델 티어링** | 쉬운 일(분류·요약)=gpt-4o-mini, 답=gpt-5.1, 검증=o4-mini. 비용 대부분은 writer에만. |
| **retrieve-then-read** | 검색은 코드가 결정적으로 — LLM에 검색 툴 안 줌(왕복·토큰 절약, 환각↓). |
| **정확수치 = 정형 API** | 매출·영업이익은 RAG가 아니라 DART `fnlttSinglAcnt`로 결정적 획득(LLM 추론 불필요·정확). |
| **결정적 Contextual** | 문맥줄을 메타로 템플릿 생성 → 인제스트 LLM 비용 0. |
| **BM25 인덱스 캐시** | 컬렉션별 1회 구축 후 재사용(질의당 재계산 안 함). |
| **거시 날짜 캐시** | 과거 거시값은 불변 → 날짜당 1회 ECOS 호출 후 SQLite 캐시. |
| **verifier 샘플링(옵션)** | `verify_sample_rate`로 검증 빈도 조절 가능(비용↔정확도% 표시 트레이드오프). |

> **비용 구조**: 큰 돈은 **인제스트(빌드 1회)** 에, 런타임(질문당)은 푼돈. 질문 1건 ≈ ~$0.02–0.05.

---

## 14. 시연 강조 포인트

발표·시연 시 강조할 만한 차별 포인트:
1. **표파싱 before/after** — "지역별/부문별 매출" 질문에서 표가 plaintext로 뭉개지지 않고 행·열 보존됨을 대비.
2. **요약 트랙** — "사업 내용 요약" → 본문 청크 기반 서술 요약(키워드: 반도체·메모리·DX·DS·하만).
3. **정확수치 = 재무결합** — "영업이익 얼마?" → DART 정형 API로 **43,601,051,000,000원** 정확 제시(+출처 접수번호·DART 링크).
4. **거시결합** — "요즘 환율·금리 상황에서 실적 어때?" → `macroSnapshot`(환율·기준금리·국고채·KOSPI) 결합.
5. **정확도(groundedScore)·provenance** — 모든 답에 근거 충실도 % + 출처 카드(접수번호·섹션·인용) + DART 원문 링크.
6. **평가 수치** — 검색 must 11/11 hit@5(100%)·MRR 0.923, 회귀 골든 14/14.
7. **API 절약 로직** — 모델 티어링·retrieve-then-read·정형API·캐시(§13)로 "왜 싸고 정확한지" 설명.
8. **X-Trace-Id 추적 + Logfire 콘솔** — 한 요청의 내부 추론(router→검색→writer→verifier) 타임라인을 trace로 시연.
9. **스코프 가드** — 방 회사가 아닌/비교 질문을 차단(out_of_scope) → 객관성·범위 통제.

---

## 15. 추후 개선점

| 개선 | 내용 | 가치 |
|---|---|---|
| **사전요약 고급화**(기본 구현 완료) | 현재=섹션+가중+takeaway. 다음: **변화탐지**(직전 보고서 대비 새 위험·가이던스 변경)+**이벤트 트리거**(M&A·소송·가이던스)+**토픽 태깅**(택소노미/BERTopic) | "이번 공시의 진짜 새 소식"을 takeaway로 |
| **에이전트 쿼리 분해** | 복합/비교 질문을 여러 검색으로 분해(시나리오 D) | terse·복합질의 약점 해소 |
| **cross-encoder 리랭커** | 휴리스틱(중복제거·최신) → 전용 모델 재정렬 | 상위 정확도↑ |
| **LLM Contextual(선택)** | 결정적 문맥 + 청크별 1문장 상황설명(gpt-4o-mini) | 검색 정밀도 추가↑(비용 변수) |
| **XBRL 정형화 확대** | 재무 결합을 더 많은 계정·재무제표로 | 정형 데이터 커버리지 |
| **정형재무 캐시** | 라이브 조회에 rcept_no/짧은 TTL 캐시 추가(거시와 일관) | 중복 호출·레이트리밋 대비 |
| **멀티모달** | 차트·이미지 비전 파싱 | 시각 자료 대응 |
| **운영 품질** | pytest(결정적 단위), Dockerfile, Logfire 클라우드 | production 하이진 |
| **커버리지 확장** | 회사·공시유형(주요사항·발행 등) 추가 | 범위 확대 |

### 15-1. 확장(스케일) 시 주의 — 정형재무 "라이브 조회"
정형재무(매출·영업이익 등)는 **런타임에 DART API로 그때그때 조회**한다(캐시 없음). 이는 **정확성·신선도**가
핵심인 데이터라 의도된 선택이며, 현재 규모(2개사·무료 API·데모)에선 최적이다. 단 **규모가 커지면** 다음을 주의:
- **중복 호출**: 같은 질문이 반복되면 동일 DART 호출이 매번 나간다. (거시는 날짜별 캐시하지만 정형재무는 미캐시 — 비대칭)
- **레이트 리밋**: OpenDART 일 1만건 한도 — 질의량↑ 시 소진 가능.
- **런타임 의존성**: DART 장애 시 재무 답 저하(현재는 graceful 부분실패로 완화).
- → **개선책**: 거시(macro)와 동일하게 **접수번호(rcept_no) 기준 또는 짧은 TTL 캐시**를 붙이면 "신선도 유지 +
  중복 제거"를 동시에 얻는다. 특정 보고서의 확정 수치는 불변이라 캐시가 안전하고, '최신 연도' 판정만 TTL로 갱신하면 된다.

---

## 16. 부록 — 구조·스키마·config·치트시트

### 16-1. 디렉토리 구조 (역할)
```
app/
  main.py            FastAPI 진입점(lifespan: DB init·관찰성)
  config.py          Settings/get_settings (모델·파라미터·경로)
  observability.py   Logfire 콘솔 관찰성 + request_span(X-Trace-Id 바인딩)
  ingest/
    dart.py          OpenDART(목록·원문XML·정형재무)
    parser.py        표-인식 파서(Block)
    chunker.py       청킹(window·표 헤더반복)
    contextual.py    Contextual 문맥줄
    pipeline.py      회사별 적재 오케스트레이션
  rag/
    embedder.py      OpenAI 임베딩(batch)
    vectorstore.py   Chroma + 전체BM25 RRF 하이브리드
    rerank.py        중복제거 + 최신우선
  agents/
    agents.py        4 에이전트 + _PERSONA + format_citations
    deps.py          Deps(주입)
  services/
    chat.py          런타임 오케스트레이터(handle_chat)
    financials.py    재무 결합(DART 정형)
    macro.py         거시 결합(ECOS)
    contract.py      v2.0 계약 어댑터
  data/ecos.py       한국은행 ECOS 클라이언트
  api/routes.py      /api/v1/chat · /api/analyses
  storage/db.py      SQLite(analyses·macro_cache)
  schemas/           ingest·disclosure·external(v2.0)
eval/                eval_retrieval·eval_chat·run_golden_inproc + *.json + EVAL_README
scripts/             ingest_corpus·smoke_retrieval·validate_sample
docs/                설계·아키텍처·기술설명·본 종합설명
```

### 16-2. 스키마 레퍼런스 (요지)
- `ChunkMeta`: corp_code·corp_name·rcept_no·report_nm·rcept_dt·pblntf_ty·section_title·kind·order
- `Citation`: chunk_id·section_title·quote·score·kind·rcept_no·report_nm·rcept_dt
- `RouterResult`: intent·needs_evidence·financial_relevant·macro_relevant·out_of_scope·detected_company·reply·search_query·date_from·date_to·prefer_recent
- `ChatV2Request`: roomId·userSeq·companyContext{corpCode,corpName}·messages[{role,content}]
- `ChatV2Response`: roomId·intent·answerText·sourceContent·macroSnapshot·sources[]·outOfScope·detectedCompany·needsClarification·verification{verdict,groundedScore}·error

### 16-3. 핵심 config 기본값 (`app/config.py`)
```
router/summary/contextual/macro = gpt-4o-mini · qa = gpt-5.1 · verifier = o4-mini
embedding = text-embedding-3-small
chunk_size 800 · overlap 120 · table_max_chars 2400
top_k 5 · candidate_k 20 · bm25_weight 0.5 (RRF, _RRF_K=60)
verify_pass_min 0.7 · verify_partial_min 0.4 · verify_sample_rate 1.0
summary_top_k 8 · chroma_dir ./data/chroma · sqlite_path ./data/app.db
```

### 16-4. 주요 파일별 상세 설명

**프롬프트(지시문)는 어디에?** (기존 CrewAI의 role/goal/backstory 대응) — 기존 CrewAI는 함수마다 `Agent(role/goal/backstory)`+`Task(description)`로 프롬프트가 흩어져 있었다. 재구축에선 **에이전트 지시문이 전부 `agents.py`의 `instructions=` + 공통 `_PERSONA`**에 모였고, **근거 조립은 `chat.py`·`agents.py::format_citations`**에 있다. → "말투·역할·규칙을 바꾸려면 `agents.py`만 보면 된다."

| 파일 | 역할 · 핵심 함수/클래스 |
|---|---|
| `config.py` | 설정(모델·파라미터·경로). `Settings`/`get_settings()` — 모든 튜닝 손잡이. |
| `ingest/dart.py` | OpenDART. `fetch_document_xml`(태그보존 raw XML)·`fetch_financials`(정형재무)·`list_disclosures`. |
| `ingest/parser.py` | ★표-인식 파싱. `parse_document`→`Block`. 표→Markdown·섹션경로·자간정규화(`_despace`). |
| `ingest/chunker.py` | 청킹. `chunk_blocks`. 윈도우(`_window`)·표 헤더반복 분할(`_split_table`). |
| `ingest/contextual.py` | Contextual 문맥줄. `build_context_line`(결정적)·`apply_context`. |
| `ingest/pipeline.py` | 적재 오케스트레이션. `ingest_company`·`list_periodic`. |
| `rag/embedder.py` | OpenAI 임베딩(배치 256). `embed_documents`·`embed_query`. |
| `rag/vectorstore.py` | ★Chroma+BM25 하이브리드. `search`(RRF)·`index_chunks`·`search_summaries`·`has_disclosure`. |
| `rag/rerank.py` | 후처리. `rerank`(중복제거 `dedup`+최신우선). |
| **`agents/agents.py`** | ★**4 에이전트+`_PERSONA`+`section_summary_agent`. 모든 에이전트 지시문(=프롬프트)이 여기.** `format_citations`. |
| `agents/deps.py` | 의존성 주입. `Deps`. |
| **`services/chat.py`** | ★런타임 오케스트레이터. `handle_chat`(라우팅→병렬→작성→검증→폴백)·`_retrieve`·`_verdict_of`. |
| `services/financials.py` | 재무 결합(DART 정형). `fetch_financial_citations`. |
| `services/macro.py` | 거시 결합(ECOS). `get_macro`(날짜캐시)·`format_macro`. |
| `services/contract.py` | v2.0 계약 어댑터. `to_internal`·`to_v2`. |
| `services/summarize.py` | ★사전요약 빌더. `build_summary_chunks`(`_bundles`·`_weight`). `section_summary_agent` 사용. |
| `data/ecos.py` | 한국은행 ECOS. `macro_snapshot`. |
| `api/routes.py` | HTTP. `/api/v1/chat`(X-Trace-Id·보관)·`/api/analyses`. |
| `storage/db.py` | SQLite. `save_chat`·`list_analyses`·거시 캐시. |
| `observability.py` | Logfire 콘솔. `setup_observability`·`request_span`. |
| `schemas/` | `ingest`(Block·Chunk·ChunkMeta)·`disclosure`(Router/QA/Citation…)·`external`(v2.0). |

### 16-5. 실행 치트시트
```bash
# 적재
PYTHONPATH=. .venv/bin/python scripts/ingest_corpus.py --corp 삼성전자
# 서버(+관찰성)
OBSERVABILITY=console PYTHONPATH=. .venv/bin/uvicorn app.main:app --port 8000 --reload
# 평가
PYTHONPATH=. .venv/bin/python -m eval.eval_retrieval     # 검색(무료)
PYTHONPATH=. .venv/bin/python -m eval.eval_chat          # 행동
PYTHONPATH=. .venv/bin/python -m eval.run_golden_inproc  # 회귀
```
