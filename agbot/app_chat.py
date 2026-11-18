"""웹 챗봇용 대화 처리 (MCP 방식, 실시간 API = LIVE 시나리오).

실험 코드(chat.ask)와 같은 MCP 서버·판정 규칙을 쓰고, 다음만 다르다.
- 대화 이력을 이어서 보낸다 (최근 6턴).
- 응답에 그래프(chart) 필드가 있다. 사용자가 그래프를 요청하면 도구로 받은 실제 수치로 채운다.
- ToBRFV(토마토갈색과일주름바이러스) 질문은 문서 검색으로 답한다.
"""
import asyncio
import copy
import json
import time

from . import config
from .chat import _ask_mcp, _UsageTracker
from .llm import ANSWER_SCHEMA, ModelError, make_model, output_text

MAX_TURNS = 6

APP_SCHEMA = copy.deepcopy(ANSWER_SCHEMA)
APP_SCHEMA["properties"]["chart"] = {
    "type": "object",
    "description": "사용자가 그래프·차트를 요청했을 때만 show=true. 수치는 도구 결과의 실제 값만 사용",
    "properties": {
        "show": {"type": "boolean"},
        "type": {"type": "string", "enum": ["bar", "line"]},
        "title": {"type": "string"},
        "x_label": {"type": "string"},
        "y_label": {"type": "string"},
        "labels": {"type": "array", "items": {"type": "string"}},
        "datasets": {"type": "array", "items": {
            "type": "object",
            "properties": {"label": {"type": "string"}, "data": {"type": "array", "items": {"type": "number"}}},
            "required": ["label", "data"], "additionalProperties": False}},
    },
    "required": ["show", "type", "title", "x_label", "y_label", "labels", "datasets"],
    "additionalProperties": False,
}
APP_SCHEMA["required"] = APP_SCHEMA["required"] + ["chart"]

APP_INSTRUCTIONS = """당신은 토마토 재배 농가를 돕는 AI 상담 챗봇이다. 한국어로 짧고 친절하게, 바로 행동할 수 있게 답한다.
- 지원 범위: 시설(양액재배) 환경제어·양액관리, 노지 시비·기상대응, 작업관리(적심·착과제·수확),
  병해충 중 ToBRFV(토마토갈색과일주름바이러스). 그 밖의 병해충·품종·판매 질문은 decision을 "지원 범위 밖"으로 답한다.
- 판정이 필요한 질문은 질문 속 값과 조회 도구 값을 판정 도구(*_decision, fertilizer_schedule)에 넘기고,
  판정 도구 결과를 바꾸지 않고 설명한다. 필요한 값이 없으면 추측하지 말고 무엇이 필요한지 묻는다.
  판정 도구에는 질문이나 조회 도구에 실제로 있는 값만 넣는다. 사용자가 말하지 않은 값(예: 침수 형태·일수, 개화 수)은 넣지 않는다.
- decision은 사람이 읽는 짧은 결론으로 쓴다(예: "보온 피복 필요", "그래프 제공"). 필드 이름이나 코드 값은 쓰지 않는다.
- ToBRFV 질문은 먼저 get_tobrfv_status를 호출해 국내 현황(3절)을 기준으로 답한다. 재배 지침 질문은 search_guideline으로
  문서를 찾아 답한다. sources에 doc_id(ToBRFV는 "TOBRFV-2026")와 문구·출처를 넣는다.
  문서에 없는 내용은 지어내지 말고 관계 기관(농촌진흥청·농림축산검역본부) 확인을 권한다.
  ToBRFV 답변의 방제 조치·날짜·농가 수·소독제는 검색된 문서 문구에 있는 것만 쓰고, 기준 날짜를 함께 밝힌다
  (예: "11월 13일 기준 117농가, 언론 보도"). 의심 증상은 시·군 농업기술센터나 도 농업기술원에 신고하도록 안내한다.
- 데이터 출처를 밝힌다: get_weather = 기상청 실시간 예보·실황(전주시완산구),
  get_fertilizer_prescription = 흙토람 비료처방(완주군 이서면 용서리 528-33, 노지 토마토),
  get_greenhouse_env = 스마트팜 데이터마트의 과거 기록(2023-07-25, 시설 1곳), get_farm_reference = 다른 농가 기록.
- 사용자가 그래프·차트·추이를 요청하면 필요한 도구를 호출해 받은 실제 수치로 chart를 채우고 show=true로 한다.
  예: 내일 시간별 기온 → get_weather의 hourly_temp_forecast, 하우스 시간별 온도·습도 → get_greenhouse_env의 hourly_temp·hourly_rh,
  실험 결과 → get_experiment_summary. 수치를 만들어 내지 않는다. 그래프 요청이 아니면 show=false, 나머지는 빈 값.
- 이전 대화 내용을 이어서 이해한다."""


def ask_app(messages: list[dict], mock: bool = False) -> dict:
    """messages: [{"role": "user"|"assistant", "content": str}, ...] 마지막은 user."""
    turns = [m for m in messages if m.get("role") in ("user", "assistant") and str(m.get("content", "")).strip()]
    turns = turns[-(MAX_TURNS * 2 - 1):]
    if not turns or turns[-1]["role"] != "user":
        raise ValueError("마지막 메시지는 사용자 질문이어야 합니다.")
    inputs = [{"role": m["role"], "content": str(m["content"])[:2000]} for m in turns]
    model = make_model(mock)
    start = time.perf_counter()
    result = {"model": model.name, "tool_calls": [], "error": None,
              "usage": {"model_calls": 0, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0}}
    tracked = _UsageTracker(model, result["usage"])
    try:
        reply = asyncio.run(_ask_mcp(tracked, inputs[-1]["content"], "LIVE", result, mock,
                                     instructions=APP_INSTRUCTIONS, inputs=inputs, schema=APP_SCHEMA,
                                     extra_env={"AGBOT_APP": "1"}))
        result.update(json.loads(output_text(reply)))
    except (ModelError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["seconds"] = round(time.perf_counter() - start, 2)
    for c in result["tool_calls"]:  # 화면에는 도구 이름과 인자만 보낸다
        c.pop("output", None)
    return result


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(ask_app([{"role": "user", "content": " ".join(sys.argv[1:]) or "내일 기온 그래프 그려줘"}]),
                     ensure_ascii=False, indent=1)[:3000])
    _ = config
