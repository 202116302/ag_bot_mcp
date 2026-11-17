import asyncio
import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agbot import config, data
from agbot.chat import ask, situation_text
from agbot.docs import search_guideline


def value_of(payload, name):
    return next(v["value"] for v in payload["values"] if v["name"] == name)


def test_snapshot_loaders():
    assert value_of(data.get_fertilizer(), "밑거름 질소(N)") == 14.4
    assert value_of(data.get_environment(), "내부온도 최고") == 32.33
    assert value_of(data.get_weather(), "기온") == 15.6


def test_keyword_search(monkeypatch):
    monkeypatch.setenv("AGBOT_SEARCH", "keyword")
    hits = search_guideline("침수 피해율", k=3)
    assert hits[0]["doc_id"] == "RDA-WEATHER-2025"
    assert {"doc_id", "chunk_id", "page", "text", "score"} <= set(hits[0])


def test_farm_reference():
    r = data.get_farm_reference(7, "day")
    assert r["temp_c"]["farms"] >= 1 and r["temp_c"]["farm_mean_range"][0] <= r["temp_c"]["farm_mean_median"]
    assert "참고" in r["note"]


def test_questions_carry_values():
    """값 포함 질문: 시스템은 흙토람 처방·재배 정보만 주고, 하우스·양액·기상 값은 주지 않는다."""
    for s in data.load_scenarios():
        assert set(s["system_values"]) <= {"crop", "fertilizer_prescription"}, s["scenario_id"]
    assert "33℃" in data.get_scenario("ENV-GH-001")["question"]


def test_situation_text_marks_missing():
    text = situation_text({"greenhouse_env": {"temp": 26.0, "rh": None}})
    assert "하우스 내 기온(℃) 26.0" in text and "상대습도(%) 자료 없음" in text


def test_mcp_server_tools_and_scenario_values():
    async def run():
        env = {**os.environ, "AGBOT_SCENARIO": "NUT-GH-004", "AGBOT_SEARCH": "keyword"}
        params = StdioServerParameters(command=sys.executable, args=["-m", "agbot.mcp_server"], cwd=str(config.ROOT), env=env)
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            status = json.loads((await s.call_tool("get_nutrient_status", {})).content[0].text)
            decision = json.loads((await s.call_tool("nutrient_decision", {"supply_volume": 2400, "drain_volume": 840})).content[0].text)
            return names, status, decision

    names, status, decision = asyncio.run(run())
    assert len(names) == 13
    assert {"get_weather", "search_guideline", "get_farm_reference", "task_decision", "fertilizer_schedule"} <= names
    assert status["available"] is False  # 값은 이제 질문 안에 있고, 시스템은 양액 값을 주지 않는다
    assert decision["result"]["drain_rate_pct"] == 35.0 and decision["rule_ids"] == ["NUT-02"]


@pytest.mark.parametrize("scenario_id, tool", [("TSK-OF-003", "task_decision"), ("NUT-GH-004", "nutrient_decision"),
                                                ("ENV-GH-003", "climate_control_decision"), ("WTH-OF-003", "weather_risk_decision")])
def test_ask_mcp_mock_pipeline(scenario_id, tool):
    """Mock은 질문 속 값을 추출하지 않으므로 판정 내용이 아니라 MCP 왕복 흐름만 확인한다."""
    s = data.get_scenario(scenario_id)
    result = ask(s["question"], scenario_id, "mcp", mock=True)
    assert result["error"] is None
    assert result["tool_calls"][-1]["name"] == tool


def test_ask_rag_mock():
    result = ask(data.get_scenario("WTH-OF-004")["question"], "WTH-OF-004", "rag", mock=True)
    assert result["error"] is None and result["tool_calls"] == []
    assert result["retrieved"]


def test_key_file_parsing(tmp_path, monkeypatch):
    """API_key.txt: 제목줄 아래 '인증키' 줄을 서비스별 키로, 'NAME=값' 줄은 그대로 읽는다."""
    key_file = tmp_path / "API_key.txt"
    key_file.write_text("농촌진흥청 비료사용처방 정보\n인증키: AAA\n스마트팜 빅데이터 정보\n인증키: BBB\nOPENAI_API_KEY=CCC\n", encoding="utf-8")
    monkeypatch.setattr(config, "KEY_FILE", key_file)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    for name in ["FERTILIZER_API_KEY", "SMARTFARM_API_KEY", "OPENAI_API_KEY"]:
        monkeypatch.delenv(name, raising=False)
    assert config.get_key("FERTILIZER_API_KEY") == "AAA"
    assert config.get_key("SMARTFARM_API_KEY") == "BBB"
    assert config.get_key("OPENAI_API_KEY") == "CCC"
