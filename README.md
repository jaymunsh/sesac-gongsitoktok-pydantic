# gongsitoktok-pydantic

**PydanticAI 기반 한국 공시(DART) 분석 RAG 챗봇 — AI 서버(FastAPI).**

특정 기업 "방"에 들어가 그 회사의 정기보고서(사업보고서·분기/반기보고서)를 근거로
**요약·근거 기반 QA·재무 수치**를 답한다. 모든 답은 검색한 실제 근거 안에서만 작성되며
(retrieve-then-read), 근거 충실도를 별도 검증자가 채점한다.

> 3-레포 구성 중 **AI 추론 서버**다. 데이터 흐름: **React → Spring(백엔드) → 이 서버(AI)**.
> 이 서버는 stateless 추론만 담당하고, 대화 보관/조회는 백엔드(Spring)가 맡는다.

---

## 핵심 특징

- **PydanticAI** — 각 에이전트가 `output_type=<Pydantic 모델>`로 구조화 출력을 강제하고,
  스키마 위반 시 자동 재시도. router·writer·summary·verifier를 타입세이프하게 오케스트레이션.
- **하이브리드 검색** — 벡터(코사인) ∪ BM25 키워드를 RRF로 융합(`bm25_weight=0.5`). 본문 RAG와
  사전요약 트랙 모두 하이브리드.
- **사업연도(bsns_year) 필터** — "2024년 사업보고서" 같은 기간 질의를 접수일이 아닌 **사업연도**로
  필터링. "제N기"는 DART 정형재무에서 기준점을 얻어 **코드가 결정적으로** 사업연도로 환산
  (LLM 산수 불신).
- **모델 티어링** — 쉬운 일(분류·요약·문맥생성)=`gpt-4o-mini`, 답 작성=`gpt-5.1`,
  검증=추론형 `o4-mini`. `.env`로 조정.
- **근거 검증** — verifier가 답의 각 주장이 근거 안에서 뒷받침되는지 `grounded_score`(0~1)로
  채점하고, 문서화된 임계값(0.7/0.4)으로 `pass/partial/fail` 판정.
- **스코프 가드** — 방 회사가 아닌 다른 회사/도메인 밖 질문(맛집·날씨 등)은 out_of_scope로 안내.

---

## 아키텍처

```
React(gongsitoktok/)  →  Spring(finance_v2/)  →  FastAPI AI(이 레포, :8000)
   채팅 UI                보관/조회·세션관리         stateless 추론
```

**런타임 한 턴** (`app/services/chat.py`):

```
질문 → router(의도분류·검색쿼리·기간·플래그)
     → 검색(corpus RAG + 재무결합 + 거시지표를 asyncio 병렬, 부분실패 graceful)
     → writer(요약 또는 QA, 근거 안에서만 작성)
     → verifier(샘플링/조건부 채점)
     → 응답(answer + citations + verification)
```

**인제스트(빌드 타임, 이미 완료)**:

```
DART 정기보고서 → 표-인식 파싱 → Contextual 문맥 주입 → 청킹 → 임베딩
              → Chroma(벡터) + BM25 인덱스 / 섹션별 사전요약 생성
```

---

## 기술 스택

| 영역 | 사용 |
|---|---|
| 에이전트 | PydanticAI 1.x (구조화 출력 + 자동 재시도) |
| LLM / 임베딩 | OpenAI (`gpt-5.1`·`gpt-4o-mini`·`o4-mini`, `text-embedding-3-small`) |
| 검색 | Chroma 0.5 (벡터) + rank-bm25 (RRF 하이브리드) |
| API | FastAPI + uvicorn |
| 데이터 | OpenDART(공시)·ECOS(거시) REST, BeautifulSoup/lxml 파싱 |
| 관찰성 | logfire (OBSERVABILITY=console 시 콘솔 trace) |

---

## 디렉토리 구조

```
app/
├── main.py              # FastAPI 진입점
├── config.py            # 설정(.env 로드, 모델 티어·검색 파라미터)
├── api/routes.py        # HTTP — 챗 + 보관/조회
├── agents/agents.py     # PydanticAI 에이전트(router·qa·summary·verifier)
├── services/
│   ├── chat.py          # 오케스트레이션(router→검색→writer→verifier)
│   ├── financials.py    # DART 정형재무(fiscal_anchor·재무인용)
│   ├── macro.py         # ECOS 거시지표 결합
│   └── contract.py      # 백엔드 연동 계약 v2.0 번역
├── rag/vectorstore.py   # Chroma + BM25 하이브리드 검색
├── ingest/              # 표-인식 파싱·Contextual·청킹·파이프라인
├── schemas/             # Pydantic 모델(에이전트 output_type)
└── storage/db.py        # SQLite 보관(분석 목록/상세)

eval/                    # 3계층 평가(검색·행동·골든)
scripts/                 # 인제스트·사전요약 빌드·마이그레이션(일회성)
docs/                    # 종합 설명서(MD/HTML)·트러블슈팅·다이어그램
data/                    # chroma/ · app.db · corpcode.json (이미 구축됨)
```

---

## 실행

```bash
# 1) 가상환경 + 의존성
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2) .env 설정 (OPENAI_API_KEY, DART_API_KEY 등)

# 3) 서버 기동 (실서버 포트 8000)
uvicorn app.main:app --reload --port 8000
```

> **데이터(Chroma 코퍼스 약 6.8만 청크·사전요약 약 1.2천)는 이미 적재되어 있다 — 재적재 금지.**
> 인제스트 스크립트(`scripts/ingest_corpus.py`·`build_summaries.py`)는 일회성 빌드용이다.
> 적재 회사: 삼성전자(`00126380`)·현대자동차(`00164742`) 정기보고서.

---

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/v1/chat` | 챗 한 턴(요약/근거 QA) — 백엔드 계약 v2.0, 근거 있는 답은 자동 보관 |
| GET | `/api/analyses` | 보관된 분석 목록(마이페이지) |
| GET | `/api/analyses/{id}` | 분석 상세(근거·검증 포함) |
| GET | `/health` | 헬스체크 |

---

## 평가 (eval)

3계층으로 회귀를 막는다 — 검색은 LLM 없이 무료·결정적, 위로 갈수록 동작에 가깝다.

```bash
# 검색(무료·결정적) — hit@k / MRR
PYTHONPATH=. .venv/bin/python -m eval.eval_retrieval

# 행동(스코프·라우팅 등)
PYTHONPATH=. .venv/bin/python -m eval.eval_chat

# 골든셋(인프로세스 회귀)
PYTHONPATH=. .venv/bin/python -m eval.run_golden_inproc
```

현재 기준선: **검색 13/13 (MRR 0.933) · 행동 7/7 · 골든 17/17(must).**

---

## 문서

- **`docs/AI_프로젝트_종합설명.md`** / **`docs/agent_mvp2.0.html`** — 설계·파이프라인·트러블슈팅의
  source of truth. HTML §17에 트러블슈팅 14건(증상/원인/해결·시각 배지)이 정리돼 있다.
- `docs/데모_정량수치_PPT용.md` — 정량 성능(hit@k·MRR·groundedScore) 요약.
- `docs/mermaid/` — 파이프라인 다이어그램 PNG.
