"""OpenAI 임베딩 (text-embedding-3-small).

문서/쿼리를 벡터로 변환. 배치로 호출해 비용·지연을 줄인다.
"""
from __future__ import annotations

from functools import lru_cache

from openai import OpenAI

from app.config import get_settings

_MAX_BATCH = 256


class Embedder:
    def __init__(self) -> None:
        s = get_settings()
        self.model = s.embedding_model
        self.client = OpenAI(api_key=s.openai_api_key)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), _MAX_BATCH):
            batch = [t.replace("\n", " ") if t else " " for t in texts[i : i + _MAX_BATCH]]
            resp = self.client.embeddings.create(model=self.model, input=batch)
            out.extend(d.embedding for d in resp.data)
        return out

    def embed_query(self, text: str) -> list[float]:
        resp = self.client.embeddings.create(model=self.model, input=[text.replace("\n", " ")])
        return resp.data[0].embedding


@lru_cache
def get_embedder() -> Embedder:
    return Embedder()
