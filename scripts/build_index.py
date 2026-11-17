"""knowledge/chunks.jsonl → Chroma 벡터DB (knowledge/chroma). OpenAI 임베딩 사용.

python scripts/build_index.py
"""
import sys
from pathlib import Path

import chromadb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agbot import config  # noqa: E402
from agbot.docs import COLLECTION, embed, load_chunks  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    chunks = load_chunks()
    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    if COLLECTION in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION)
    col = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine", "embed_model": config.EMBED_MODEL})
    for i in range(0, len(chunks), 64):
        batch = chunks[i:i + 64]
        col.add(
            ids=[c["chunk_id"] for c in batch],
            embeddings=embed([c["text"] for c in batch]),
            documents=[c["text"] for c in batch],
            metadatas=[{"doc_id": c["doc_id"], "page": c["page"], "cultivation": ",".join(c["cultivation"]),
                        "domain": ",".join(c["domain"])} for c in batch],
        )
        print(f"{min(i + 64, len(chunks))}/{len(chunks)}")
    print(f"→ {config.CHROMA_DIR} ({col.count()} chunks, {config.EMBED_MODEL})")


if __name__ == "__main__":
    main()
