"""LLM 호출: OpenAI Responses API와 API 없이 흐름만 점검하는 Mock 모델."""
import json

import requests

from . import config

# 두 조건(MCP·RAG) 공통 응답 형식 (명세 8.1: 표현과 추천 결과 분리)
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "농민에게 보여줄 한국어 답변"},
        "decision": {"type": "string", "description": "추천 결과 한 줄 요약. 판단할 수 없으면 '판단 보류: 이유'"},
        "key_values": {
            "type": "array",
            "description": "판단에 쓴 수치(입력값·기준값·계산값)",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "value": {"type": "number"}, "unit": {"type": "string"}},
                "required": ["name", "value", "unit"],
                "additionalProperties": False,
            },
        },
        "basis": {"type": "string", "description": "판단 근거(기준값과 비교 내용)"},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"doc_id": {"type": "string"}, "clause": {"type": "string"}},
                "required": ["doc_id", "clause"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer", "decision", "key_values", "basis", "sources"],
    "additionalProperties": False,
}


class ModelError(Exception):
    pass


def output_text(reply: dict) -> str:
    return "".join(
        part.get("text", "")
        for item in reply.get("output", [])
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )


def function_calls(reply: dict) -> list[dict]:
    return [item for item in reply.get("output", []) if item.get("type") == "function_call"]


def call_openai(payload: dict) -> dict:
    key = config.get_key("OPENAI_API_KEY")
    if not key:
        raise ModelError("OPENAI_API_KEY가 환경 변수나 .env에 없습니다.")
    try:
        resp = requests.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {key}"},
                             json=payload, timeout=(10, 90))
    except requests.RequestException as exc:
        raise ModelError(f"네트워크 오류: {type(exc).__name__}") from None
    if resp.status_code != 200:
        raise ModelError(f"OpenAI HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


class OpenAIModel:
    name = config.MODEL

    def complete(self, instructions: str, input: list[dict], tools: list[dict], schema: dict = ANSWER_SCHEMA) -> dict:
        payload = {
            "model": config.MODEL,
            "instructions": instructions,
            "input": input,
            "tools": tools,
            "reasoning": {"effort": config.REASONING_EFFORT},
            "max_output_tokens": config.MAX_OUTPUT_TOKENS,
            "store": False,
            "text": {"format": {"type": "json_schema", "name": "answer", "strict": True, "schema": schema}},
        }
        if tools:
            payload["parallel_tool_calls"] = False
        return call_openai(payload)


# ------------------------------------------------------------------ Mock
TASK_WORDS = {"fruit_set": ["착과제", "토마토톤"], "topping": ["적심", "순지르기"], "harvest": ["수확", "따도", "착색"]}
DOMAIN_WORDS = {
    "task": sum(TASK_WORDS.values(), []),
    "nutrient": ["급액", "배액", "양액", "EC", "pH", "일사"],
    "fertilizer": ["비료", "거름", "요소", "용성인비", "염화가리", "시비"],
    "weather": ["예보", "날씨", "비 ", "비가", "호우", "침수", "보온 덮"],
    "climate": ["하우스", "환기", "송풍", "차광", "습도", "온도"],
}


def guess_domain(question: str) -> str:
    return next((d for d, words in DOMAIN_WORDS.items() if any(w in question for w in words)), "climate")


def _mock_decision_call(question: str, looked: dict) -> tuple[str, dict]:
    """Mock 전용: 조회 결과를 판정 도구 인자로 옮긴다 (질문 속 사용자 값은 해석하지 않음)."""
    env, w, n = looked.get("get_greenhouse_env", {}), looked.get("get_weather", {}), looked.get("get_nutrient_status", {})
    rx, crop = looked.get("get_fertilizer_prescription", {}), looked.get("get_crop_status", {})
    domain = guess_domain(question)
    if domain == "climate":
        return "climate_control_decision", {"greenhouse_temp": env.get("temp"), "greenhouse_rh": env.get("rh"),
                                            "outdoor_temp": w.get("outdoor_temp"), "time_of_day": env.get("time_of_day", "day")}
    if domain == "nutrient":
        return "nutrient_decision", {k: n.get(k) for k in ["solar_accum", "supply_volume", "drain_volume",
                                                           "supply_ec", "drain_ec", "supply_ph"]}
    if domain == "fertilizer":
        args = {k: v for k, v in rx.items() if k.startswith(("basal", "topdressing"))}
        return "fertilizer_schedule", {**args, "planting_date": crop.get("planting_date"), "today": crop.get("today")}
    if domain == "weather":
        return "weather_risk_decision", {k: w.get(k) for k in ["tmin_forecast", "tmax_forecast", "heavy_rain_warning"]}
    task = next(t for t, words in TASK_WORDS.items() if any(x in question for x in words))
    return "task_decision", {"task": task, "cropping_type": crop.get("cropping_type"), "today": crop.get("today"),
                             "temp_mean": w.get("temp_mean"), "temp_max": w.get("temp_max"), "season": crop.get("season")}


LOOKUPS = {"climate": ["get_greenhouse_env", "get_weather"], "nutrient": ["get_nutrient_status"],
           "fertilizer": ["get_fertilizer_prescription", "get_crop_status"], "weather": ["get_weather"],
           "task": ["get_crop_status", "get_weather"]}


class MockModel:
    """API 없이 파이프라인을 점검하는 결정적 대역. 실제 모델 성능과 무관하다.
    MCP: 조회 도구 → 판정 도구 → 판정 결과를 그대로 답변.  RAG: 검색 문단의 출처만 담아 '판단 보류'."""

    name = "mock"

    def complete(self, instructions: str, input: list[dict], tools: list[dict], schema: dict = ANSWER_SCHEMA) -> dict:
        question = next(i["content"] for i in input if i.get("role") == "user")
        calls = {i["call_id"]: i["name"] for i in input if i.get("type") == "function_call"}
        results = {calls[i["call_id"]]: json.loads(i["output"]) for i in input if i.get("type") == "function_call_output"}
        if tools:
            for name in LOOKUPS[guess_domain(question)]:
                if name not in results:
                    return _call(name, {})
            decision_tool = next((n for n in results if n.endswith(("_decision", "_schedule"))), None)
            if decision_tool is None:
                name, args = _mock_decision_call(question, results)
                return _call(name, {k: v for k, v in args.items() if v is not None})
            out = results[decision_tool]
            answer = {"answer": " / ".join(out["basis"]) or out["result"]["decision"],
                      "decision": out["result"]["decision"], "key_values": [],
                      "basis": "; ".join(out["basis"]), "sources": out["sources"]}
        else:
            docs = [c for m in input if m.get("role") == "developer" for c in _doc_ids(m["content"])]
            answer = {"answer": "Mock: 문서만으로는 판정하지 않음", "decision": "판단 보류: Mock 모델",
                      "key_values": [], "basis": "", "sources": [{"doc_id": d, "clause": ""} for d in docs[:3]]}
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer, ensure_ascii=False)}]}]}


def _call(name: str, args: dict) -> dict:
    return {"output": [{"type": "function_call", "call_id": f"mock-{name}", "name": name,
                        "arguments": json.dumps(args, ensure_ascii=False)}]}


def _doc_ids(text: str) -> list[str]:
    import re

    return list(dict.fromkeys(re.findall(r"doc_id: ([A-Z0-9-]+)", text)))


def make_model(mock: bool):
    return MockModel() if mock else OpenAIModel()
