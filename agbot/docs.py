"""RAG 문서 검색 (두 조건 공통). knowledge/chunks.jsonl → Chroma 벡터DB.

- 기본: Chroma + OpenAI 임베딩 (scripts/build_index.py로 인덱스 생성)
- Mock 모드(AGBOT_SEARCH=keyword): API 없이 글자 bigram 겹침으로 검색 — 흐름 점검용
"""
import json
import os
import re
from collections import Counter
from functools import lru_cache

import requests

from . import config

CHUNKS_FILE = config.ROOT / "knowledge" / "chunks.jsonl"
COLLECTION = "guidelines"


@lru_cache
def load_chunks() -> list[dict]:
    return [json.loads(line) for line in CHUNKS_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


def embed(texts: list[str]) -> list[list[float]]:
    key = config.get_key("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY가 없어 임베딩을 만들 수 없습니다.")
    resp = requests.post("https://api.openai.com/v1/embeddings", headers={"Authorization": f"Bearer {key}"},
                         json={"model": config.EMBED_MODEL, "input": texts}, timeout=(10, 60))
    resp.raise_for_status()
    return [d["embedding"] for d in sorted(resp.json()["data"], key=lambda d: d["index"])]


def _bigrams(text: str) -> Counter:
    t = re.sub(r"\s+", "", text)
    return Counter(t[i:i + 2] for i in range(len(t) - 1))


def _keyword_search(query: str, n: int) -> list[tuple[dict, float]]:
    q = _bigrams(query)
    scored = [(c, sum(min(cnt, _bigrams(c["text"])[g]) for g, cnt in q.items()) / (sum(q.values()) or 1))
              for c in load_chunks()]
    return sorted(scored, key=lambda x: -x[1])[:n]


@lru_cache
def _collection():
    import chromadb

    return chromadb.PersistentClient(path=str(config.CHROMA_DIR)).get_collection(COLLECTION)


def _vector_search(query: str, n: int) -> list[tuple[dict, float]]:
    by_id = {c["chunk_id"]: c for c in load_chunks()}
    res = _collection().query(query_embeddings=embed([query]), n_results=n)
    return [(by_id[i], round(1 - d, 4)) for i, d in zip(res["ids"][0], res["distances"][0])]


def search_guideline(query: str, k: int = config.SEARCH_K, cultivation: str | None = None) -> list[dict]:
    """질문과 관련된 재배 기준 문단 상위 k개. cultivation: greenhouse_hydroponic | open_field (선택)"""
    backend = _keyword_search if os.environ.get("AGBOT_SEARCH") == "keyword" else _vector_search
    hits = backend(query, k * 3 if cultivation else k)
    if cultivation:
        hits = [h for h in hits if cultivation in h[0]["cultivation"] or "common" in h[0]["cultivation"]] or hits
    return [{"doc_id": c["doc_id"], "chunk_id": c["chunk_id"], "page": c["page"], "source_title": c["source_title"],
             "text": c["text"], "score": round(s, 4)} for c, s in hits[:k]]
