"""모바일 웹 챗봇 서버 (FastAPI).  uvicorn agbot.web:app --host 0.0.0.0 --port 8110

- GET  /           채팅 화면 (webapp/index.html)
- POST /api/chat   {"messages":[{"role","content"}...], "code": "<접속 코드>"} → 답변·근거·그래프
- GET  /healthz
환경 변수: OPENAI_API_KEY, FERTILIZER_API_KEY, SMARTFARM_API_KEY, APP_PASSCODE(설정 시 접속 코드 필요)
"""
import hmac
import json
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .app_chat import ask_app
from .config import ROOT

app = FastAPI(title="토마토 재배 상담 챗봇", docs_url=None, redoc_url=None)
PAGE = ROOT / "webapp" / "index.html"
RATE_LIMIT, WINDOW = 15, 60.0          # IP당 1분에 15회
_hits: dict[str, deque] = defaultdict(deque)
FEEDBACK_FILE = Path(os.environ.get("FEEDBACK_DIR", str(ROOT / "feedback"))) / "feedback.jsonl"
_fb_lock = threading.Lock()


class Message(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)


class FeedbackRequest(BaseModel):
    question: str = Field(default="", max_length=2000)
    answer: str = Field(default="", max_length=6000)
    decision: str = Field(default="", max_length=300)
    comment: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=24)
    code: str = ""


def _check_code(code: str):
    expected = os.environ.get("APP_PASSCODE", "")
    if expected and not hmac.compare_digest(code.strip(), expected):
        raise HTTPException(status_code=401, detail="접속 코드가 맞지 않습니다.")


def _check_rate(ip: str):
    now, q = time.monotonic(), _hits[ip]
    while q and now - q[0] > WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.")
    q.append(now)


@app.get("/")
def index():
    # 수정한 화면이 바로 반영되도록 캐시하지 않는다
    return FileResponse(PAGE, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store"})


@app.get("/healthz")
def health():
    return {"ok": True}


@app.post("/api/auth")
def auth(req: dict):
    required = bool(os.environ.get("APP_PASSCODE", ""))
    _check_code(str(req.get("code", "")))
    return {"ok": True, "required": required}


@app.post("/api/chat")
def chat(req: ChatRequest, request: Request):
    _check_code(req.code)
    _check_rate(request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0])
    try:
        result = ask_app([m.model_dump() for m in req.messages])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if result.get("error"):
        raise HTTPException(status_code=502, detail="답변을 만드는 중 문제가 생겼습니다. 다시 시도해 주세요.")
    keep = ("answer", "decision", "key_values", "basis", "sources", "chart", "seconds")
    return {**{k: result.get(k) for k in keep}, "tools": [c["name"] for c in result["tool_calls"]]}


@app.post("/api/feedback")
def feedback(req: FeedbackRequest, request: Request):
    """답변에 대한 수정사항·의견 (로그인 없음, 선택 사항). feedback/feedback.jsonl에 한 줄씩 쌓는다."""
    _check_rate(request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0])
    comment = req.comment.strip()
    if not comment:
        raise HTTPException(status_code=400, detail="의견을 입력해 주세요.")
    row = {"at": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
           "question": req.question, "decision": req.decision, "answer": req.answer, "comment": comment}
    with _fb_lock:
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with FEEDBACK_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"ok": True}
