"""애플리케이션 설정. .env 에서 로드한다.

모델 티어링(보고서 §4-2-1b): 쉬운 일(분류·요약·문맥생성)=싼 모델(gpt-4o-mini),
답 작성(writer)=상위(gpt-5.1), 검증=추론형(o4-mini). 모델명은 .env로 조정.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- LLM (OpenAI) ---
    openai_api_key: str = ""
    router_model: str = "gpt-4o-mini"        # 라우터(의도 분류) — 쉬운 작업
    summary_model: str = "gpt-4o-mini"       # 사전요약 생성(빌드 타임)
    contextual_model: str = "gpt-4o-mini"    # Contextual 문맥 한 줄 생성(인제스트)
    qa_model: str = "gpt-5.1"                # writer(답 작성) — 품질이 핵심
    macro_model: str = "gpt-4o-mini"         # ECOS 거시 결합
    verification_model: str = "o4-mini"      # 검증(근거 채점) — 추론형, 샘플링

    # --- 데이터 소스 ---
    dart_api_key: str = ""
    ecos_api_key: str = "sample"

    # --- 임베딩 (OpenAI) ---
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"

    # --- 저장 ---
    chroma_dir: str = "./data/chroma"
    sqlite_path: str = "./data/app.db"

    # --- 검증 임계값 (grounded_score → verdict) ---
    verify_pass_min: float = 0.7      # 이상이면 pass
    verify_partial_min: float = 0.4   # 이상이면 partial, 미만이면 fail(→ CRAG 재검색)
    # verifier 실행 비율. 1.0=매 턴(프론트 '정확도 %'가 항상 뜨도록 — 기존 동작과 일치).
    # 비용 절감이 필요하면 0.2 등으로 낮춰 샘플링(보고서 §4-2-1b), 단 그만큼 groundedScore가 빔.
    verify_sample_rate: float = 1.0

    # --- 청킹 파라미터 (표-인식) ---
    chunk_size: int = 800             # 텍스트 청크당 대략 글자 수
    chunk_overlap: int = 120          # 텍스트 청크 간 겹침
    table_max_chars: int = 2400       # 표 1개가 이보다 크면 행 단위로 분할

    # --- 검색 (하이브리드) ---
    top_k: int = 5                    # 최종 근거 문단 수
    candidate_k: int = 20             # 리랭킹 전 후보 수
    bm25_weight: float = 0.5          # RRF 융합 가중(0.5=표준 동등, 벡터/BM25 1:1 교차)

    # --- 사전요약 ---
    small_disclosure_chars: int = 12000   # 이하면 '작은 공시' → 원문 통째 요약
    summary_top_k: int = 8
    summary_section_target_chars: int = 6000   # 사전요약 1묶음 목표 길이
    summary_max_sections: int = 40             # 공시 1건당 요약(=LLM 호출) 상한
    min_section_chars: int = 200               # 이보다 짧은 섹션은 요약 스킵


@lru_cache
def get_settings() -> Settings:
    return Settings()
