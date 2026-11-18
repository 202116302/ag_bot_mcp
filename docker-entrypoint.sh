#!/bin/sh
# 벡터 DB가 없으면(첫 실행) OpenAI 임베딩으로 만든 뒤 웹 서버를 시작한다.
set -e
if [ ! -f knowledge/chroma/chroma.sqlite3 ]; then
  echo "[agbot] building vector DB (knowledge/chroma)..."
  python scripts/build_index.py
fi
exec uvicorn agbot.web:app --host 0.0.0.0 --port 8110 --proxy-headers --forwarded-allow-ips="*"
