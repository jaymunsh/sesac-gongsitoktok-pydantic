# gongsitoktok-pydantic

기존 `gongsi-agent`(FastAPI 공시분석, CrewAI)를 **PydanticAI 기반 + production 파이프라인**(표-인식 파싱·Contextual·하이브리드 검색)으로 **처음부터 클린 재구축**하는 프로젝트.
→ 코드는 새로 작성한다. 이 폴더엔 **핸드오프 문서 + 재사용 데이터자산**만 둔다.

## 먼저 읽기 (핸드오프)
- **`docs/PydanticAI_재구축_종합보고서.md`** — 결정사항·파이프라인·로드맵. 특히 **§9 다음 세션 착수 가이드**, §4 파이프라인, §6-1 착수 순서.
- 보조: `docs/공시분석_production_아키텍처.md`, `docs/현업대비_개선전략.md`, `docs/에이전트_프레임워크_입문.html`, `docs/RFP-금융-공시분석.md`

## 핵심 결정 (요약)
- 프레임워크 **PydanticAI** (기존 Pydantic 스키마를 `output_type`으로 재사용+관용구화)
- 인제스트 **표-인식 파싱 + Contextual 문맥 주입 + 메타 태깅** (정기보고서 우선)
- 모델: router/요약=gpt-4o-mini, writer=gpt-5.1, verifier=o4-mini(샘플링)
- 챗봇 유지하되 RFP 과제형(요약·근거·보관·조회) 1급
- 데이터: 삼성(00126380)·현대(00164742) 정기보고서 33건

## 이 폴더에 있는 것 (재사용 자산)
- `docs/` — 재구축 컨텍스트 문서 + RFP
- `eval/` — 골든셋(`chat_golden_set.json` 14케이스·`run_chat_golden.py`·README) = 회귀 검증 목표 스펙
- `.env` — API 키 / `data/corpcode.json` — DART corp_code 캐시(무료, 재다운로드 회피)

## 여기 없는 것 = 새로 작성
- 앱 코드(ingest·rag·agents·services·api·schemas), requirements, 인제스트 스크립트 → **이번에 재설계해 새로 작성**.
- 기존 코드 참고가 필요하면: **`../gongsitoktok-fastapi/gongsi-agent`** (사이드 참조용, 복사 금지)

## 착수 순서 (보고서 §6-1)
1. 스캐폴딩 + venv/requirements(PydanticAI 등)
2. 청크/Contextual 설계 + 표-인식 파싱을 **삼성 사업보고서 1건(20250311001085) 샘플로 검증**(저비용) → 스키마 확정
3. (확인 후) 백그라운드 풀 재적재 → 병렬로 PydanticAI 에이전트·오케스트레이션
4. 골든셋(`eval/`) 통합 검증
