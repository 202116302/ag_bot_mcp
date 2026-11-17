import pytest

from agbot.data import get_scenario, load_scenarios
from agbot.rules import DECISION_TOOLS

SCENARIOS = load_scenarios()


def test_scenario_set_shape():
    assert len(SCENARIOS) == 25
    ids = [s["scenario_id"] for s in SCENARIOS]
    assert len(set(ids)) == len(ids)
    for domain in ["climate", "nutrient", "fertilizer", "weather", "task"]:
        types = {s["type"] for s in SCENARIOS if s["domain"] == domain}
        assert types == {"simple", "boundary", "complex", "calculation", "missing"}, domain


@pytest.mark.parametrize("s", SCENARIOS, ids=lambda s: s["scenario_id"])
def test_expected_answer_matches_rule_engine(s):
    """시나리오 정답이 규칙 엔진의 판정과 일치하는지 (정답 작성 오류 점검)."""
    call = s["reference_call"]
    out = DECISION_TOOLS[call["tool"]](**call["args"])
    assert out["status"] == s.get("reference_status", "decided"), out
    key = s["expected"]["decision_key"]
    if key:
        assert key in out["result"]["decision"], (out["result"]["decision"], key)
    if out["status"] != "insufficient_data":
        assert set(s["rule_ids"]) <= set(out["rule_ids"]) | {"ENV-07"}, out["rule_ids"]


def test_demo_scenario_uses_real_data():
    demo = get_scenario("DEMO")["system_values"]
    assert demo["fertilizer_prescription"]["basal_n"] == 14.4
    assert demo["weather"]["outdoor_temp"] == 15.6
    assert demo["greenhouse_env"]["temp"] > 0
