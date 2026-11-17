"""질문 하나를 RAG 조건 또는 MCP 조건으로 처리한다 (mcp_agri_dss_spec.md 1.2절).

- RAG: [현재 상황](시나리오 system_values) + 검색 문단을 프롬프트에 넣고 LLM이 직접 판정한다. 도구 없음.
- MCP: LLM이 조회 도구로 값을 받고, 판정 도구(Python 규칙)의 결과를 설명한다. search_guideline도 쓸 수 있다.
두 조건은 같은 시나리오 값, 같은 문서(벡터DB), 같은 모델·설정, 같은 응답 형식을 쓴다.
"""
import asyncio
import json
import os
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from . import config, data, docs
from .llm import ModelError, function_calls, make_model, output_text

COMMON = """당신은 토마토 재배 농가를 돕는 농업 의사결정지원 도우미다.
- 지원 범위: 시설(양액재배) 환경제어·양액관리, 노지 시비·기상대응, 작업관리(적심·착과제·수확).
  병해충 진단·방제, 품종 선택, 출하·판매 등 범위 밖 질문에는 decision을 "지원 범위 밖"으로 답한다.
- 필요한 값이 없으면 추측하지 말고 decision을 "판단 보류: <없는 값>"으로 답한다.
- key_values에는 판단에 쓴 입력값·기준값·계산값을, sources에는 근거 문서의 doc_id와 해당 문구를 넣는다.
- 답변은 농민이 바로 행동할 수 있게 짧고 구체적으로 쓴다."""

RAG_INSTRUCTIONS = COMMON + """
- [현재 상황]의 값과 [참고 문서]의 기준을 비교해 직접 판단하고 필요한 계산을 한다."""

MCP_INSTRUCTIONS = COMMON + """
- 조회 도구(get_*)로 현재 농장 값을 확인하고, 질문에 들어 있는 값(화방 수, 개화 수, 날짜 등)은 직접 추출해
  해당 판정 도구(*_decision, fertilizer_schedule)에 인자로 넘긴다.
- 판정은 판정 도구의 결과(result, status)를 그대로 따르고 바꾸지 않는다. 당신은 결과를 설명한다.
- 도구 결과의 rule_ids·sources를 근거로 제시한다. 설명에 문서가 더 필요하면 search_guideline을 쓴다.
- 하우스 온도·습도에 관한 질문이면 get_farm_reference(월, 시간대)로 비슷한 시기 다른 시설 토마토 농가의 실제 기록을
  확인하고, answer 끝에 한두 문장으로 비교해 덧붙인다(예: "같은 시기 다른 농가 n곳의 낮 평균은 ○~○℃").
  이 참고 자료로 판정을 바꾸지 않으며, sources에는 doc_id "SMARTFARM-DATAMART"로 표기한다."""

LABELS = {
    "temp": "하우스 내 기온(℃)", "rh": "하우스 내 상대습도(%)", "time_of_day": "시간대(day=주간, night=야간)",
    "outdoor_temp": "외기온(℃)", "tmin_forecast": "최저기온 예보(℃)", "tmax_forecast": "최고기온 예보(℃)",
    "temp_mean": "평균기온(℃)", "temp_max": "최고기온(℃)", "rain_forecast_mm": "강수 예보(mm)",
    "heavy_rain_warning": "호우 특보", "solar_accum": "적산일사량(J/㎠)", "supply_volume": "급액량(mL)",
    "drain_volume": "배액량(mL)", "supply_ec": "급액 EC(dS/m)", "drain_ec": "배액(근권) EC(mS/cm)",
    "supply_ph": "급액 pH", "basal_n": "밑거름 질소(kg/10a)", "basal_p": "밑거름 인산(kg/10a)",
    "basal_k": "밑거름 칼리(kg/10a)", "topdressing_n": "웃거름 질소(kg/10a)", "topdressing_p": "웃거름 인산(kg/10a)",
    "topdressing_k": "웃거름 칼리(kg/10a)", "cultivation": "재배형태", "cropping_type": "작형",
    "hydroponic": "양액재배", "planting_date": "정식일", "today": "오늘", "season": "시기(hot=혹서기, cold=저온기)",
}
SECTION_NAMES = {"weather": "기상", "greenhouse_env": "하우스 환경", "nutrient": "양액", "soil": "토양",
                 "fertilizer_prescription": "흙토람 처방", "crop": "작물"}


def situation_text(system_values: dict) -> str:
    """시나리오 값 → [현재 상황] 텍스트 (RAG 조건). 값이 없으면 '자료 없음'."""
    lines = []
    for section, values in system_values.items():
        items = [f"{LABELS.get(k, k)} {'자료 없음' if v is None else v}" for k, v in values.items()]
        lines.append(f"- {SECTION_NAMES.get(section, section)}: " + ", ".join(items))
    return "\n".join(lines)


def ask(question: str, scenario_id: str = "DEMO", condition: str = "mcp", mock: bool = False) -> dict:
    model = make_model(mock)
    if mock:
        os.environ["AGBOT_SEARCH"] = "keyword"
    start = time.perf_counter()
    result = {"scenario_id": scenario_id, "condition": condition, "model": model.name, "question": question,
              "tool_calls": [], "retrieved": [], "error": None,
              "usage": {"model_calls": 0, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0}}
    model = _UsageTracker(model, result["usage"])
    try:
        if condition == "rag":
            reply = _ask_rag(model, question, scenario_id, result)
        elif condition == "mcp":
            reply = asyncio.run(_ask_mcp(model, question, scenario_id, result, mock))
        else:
            raise ValueError(f"알 수 없는 condition: {condition}")
        result.update(json.loads(output_text(reply)))
    except (ModelError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["seconds"] = round(time.perf_counter() - start, 2)
    return result


class _UsageTracker:
    """모델 호출마다 OpenAI가 돌려준 토큰 사용량을 결과에 누적한다 (비용·지연 비교용)."""

    def __init__(self, model, usage: dict):
        self.model, self.usage, self.name = model, usage, model.name

    def complete(self, *args, **kwargs) -> dict:
        reply = self.model.complete(*args, **kwargs)
        u = reply.get("usage") or {}
        self.usage["model_calls"] += 1
        self.usage["input_tokens"] += u.get("input_tokens", 0)
        self.usage["cached_tokens"] += (u.get("input_tokens_details") or {}).get("cached_tokens", 0)
        self.usage["output_tokens"] += u.get("output_tokens", 0)
        return reply


def _ask_rag(model, question: str, scenario_id: str, result: dict) -> dict:
    scenario = data.get_scenario(scenario_id)
    hits = docs.search_guideline(question)
    result["retrieved"] = [{"chunk_id": h["chunk_id"], "score": h["score"]} for h in hits]
    doc_text = "\n\n".join(f"[doc_id: {h['doc_id']} | {h['source_title']}, p.{h['page']}]\n{h['text']}" for h in hits)
    inputs = [
        {"role": "developer", "content": f"[현재 상황]\n{situation_text(scenario['system_values'])}\n\n[참고 문서]\n{doc_text}"},
        {"role": "user", "content": question},
    ]
    return model.complete(RAG_INSTRUCTIONS, inputs, tools=[])


async def _ask_mcp(model, question: str, scenario_id: str, result: dict, mock: bool) -> dict:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "AGBOT_SCENARIO": scenario_id,
           "AGBOT_SEARCH": "keyword" if mock else os.environ.get("AGBOT_SEARCH", "")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "agbot.mcp_server"], cwd=str(config.ROOT), env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = [{"type": "function", "name": t.name, "description": t.description or "", "parameters": t.inputSchema}
                 for t in (await session.list_tools()).tools]
        inputs = [{"role": "user", "content": question}]
        for _ in range(config.MAX_MODEL_CALLS):
            reply = model.complete(MCP_INSTRUCTIONS, inputs, tools)
            calls = function_calls(reply)
            if not calls:
                return reply
            inputs += reply["output"]
            for call in calls:
                args = json.loads(call.get("arguments") or "{}")
                res = await session.call_tool(call["name"], args)
                text = "".join(c.text for c in res.content if hasattr(c, "text"))
                if len(res.content) > 1:  # list 반환(search_guideline)은 항목별 content로 온다
                    text = "[" + ",".join(c.text for c in res.content if hasattr(c, "text")) + "]"
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = text
                result["tool_calls"].append({"name": call["name"], "arguments": args, "output": parsed, "is_error": res.isError})
                inputs.append({"type": "function_call_output", "call_id": call["call_id"], "output": text})
        raise ModelError("모델 호출 횟수 초과")
