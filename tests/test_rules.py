import json
import re

import pytest

from agbot import rules
from agbot.config import ROOT
from agbot.rules import (climate_control_decision, fertilizer_schedule, nutrient_decision,
                         task_decision, weather_risk_decision)


def norm(s):
    return re.sub(r"\s+", "", s)


def test_every_rule_clause_is_in_rag_documents():
    """원칙 2: MCP 규칙의 근거 문구는 모두 RAG 문서(chunks)에 있어야 한다."""
    chunks = [norm(json.loads(line)["text"]) for line in (ROOT / "knowledge/chunks.jsonl").open(encoding="utf-8")]
    for rid, r in rules.RULES().items():
        for clause in [r["clause"], *(r.get("clauses") or {}).values()]:
            assert any(norm(clause) in c for c in chunks), (rid, clause)


def test_output_format():
    out = climate_control_decision(greenhouse_temp=31, greenhouse_rh=60)
    assert set(out) == {"result", "basis", "rule_ids", "sources", "inputs_used", "missing_inputs", "status"}
    assert out["sources"][0]["doc_id"] == "JEJU-TOMATO"


# ---- 환경제어
@pytest.mark.parametrize("temp, vent, shade", [(30, True, True), (29.9, True, False), (26, False, False)])
def test_climate_day_boundary(temp, vent, shade):
    a = climate_control_decision(greenhouse_temp=temp, greenhouse_rh=60)["result"]["actions"]
    assert (a["환기"], a["차광"]) == (vent, shade)


def test_climate_cold_and_humid():
    out = climate_control_decision(greenhouse_temp=5, greenhouse_rh=70)
    assert out["result"]["actions"]["난방"] and out["result"]["actions"]["송풍"]
    assert {"ENV-05", "ENV-06"} <= set(out["rule_ids"])


def test_climate_conflict_night_humid_cold_outside():
    out = climate_control_decision(greenhouse_temp=15, greenhouse_rh=85, outdoor_temp=8, time_of_day="night")
    a = out["result"]["actions"]
    assert a["송풍"] and not a["환기"]
    assert "ENV-08" in out["rule_ids"]


def test_climate_missing():
    out = climate_control_decision()
    assert out["status"] == "insufficient_data"


# ---- 양액
def test_nutrient_drain_rate_calc():
    out = nutrient_decision(supply_volume=2000, drain_volume=300)
    assert out["result"]["drain_rate_pct"] == 15.0
    assert "급액량 증가" in out["result"]["decision"]
    assert out["status"] == "decided"
    assert nutrient_decision(supply_volume=2000)["status"] == "insufficient_data"


@pytest.mark.parametrize("drain, expect", [(400, "유지"), (600, "유지"), (601, "감소")])
def test_nutrient_drain_boundary(drain, expect):
    assert expect in nutrient_decision(supply_volume=2000, drain_volume=drain)["result"]["decision"]


def test_nutrient_solar_and_ec_ph():
    out = nutrient_decision(solar_accum=180, supply_ec=1.8, supply_ph=6.3, drain_ec=3.4)
    d = out["result"]["decision"]
    assert "급액 실시" in d and "급액 EC 낮춤" in d and "pH 낮춤" in d and "근권 EC 낮춤" in d
    d = nutrient_decision(supply_ec=1.5, drain_ec=3.0)["result"]["decision"]
    assert d == "근권 EC 적정 / 급액 EC 적정"


def test_nutrient_conflict_recorded():
    out = nutrient_decision(supply_volume=1000, drain_volume=100, drain_ec=1.5)
    assert any("[충돌]" in b for b in out["basis"])
    assert "[충돌]" in out["result"]["decision"] and "배액률 기준 우선" in out["result"]["decision"]


def test_climate_missing_humidity_in_decision():
    d = climate_control_decision(greenhouse_temp=26, outdoor_temp=20)["result"]["decision"]
    assert "습도 값 없음" in d and "판단 보류" in d


# ---- 시비
def test_fertilizer_products_from_prescription():
    out = fertilizer_schedule(basal_n=14.4, basal_p=3.0, basal_k=3.0, topdressing_n=10.9)
    assert out["result"]["basal_products"] == {"요소": 31.3, "용성인비": 15.0, "염화가리": 5.0}
    assert out["result"]["topdressing_products"]["요소"] == 23.7


def test_fertilizer_fallback_standard():
    out = fertilizer_schedule(planting_date="2026-07-01", today="2026-07-28")
    assert "FER-02" in out["rule_ids"]
    assert out["result"]["standard_10a"]["n"] == 24.2
    assert out["result"]["topdressing_now"] == "1차 웃거름 적기"


def test_fertilizer_schedule_windows():
    out = fertilizer_schedule(basal_n=10, planting_date="2026-07-01", today="2026-08-18")
    assert out["result"]["topdressing_windows"][1] == "2차 2026-08-15 ~ 2026-08-25"
    assert out["result"]["topdressing_now"] == "2차 웃거름 적기"


# ---- 기상
def test_weather_thresholds():
    d = weather_risk_decision(tmin_forecast=10, tmax_forecast=30)["result"]["decision"]
    assert "보온 피복" in d and "고온 대응" in d
    d = weather_risk_decision(tmin_forecast=10.1, tmax_forecast=29.9)["result"]["decision"]
    assert d == "특별 대응 불필요"


@pytest.mark.parametrize("ftype, days, rate", [("ridge", 1, "5%"), ("ridge", 1.2, "5~20%"), ("furrow", 12, "30% 이상")])
def test_weather_flood_rate(ftype, days, rate):
    assert weather_risk_decision(flood_type=ftype, flood_days=days)["result"]["flood_damage_rate"] == rate


# ---- 작업관리
@pytest.mark.parametrize("temp, conc", [(20, "50배액"), (20.1, "100배액"), (15, "50배액")])
def test_fruit_set_concentration_boundary(temp, conc):
    assert task_decision("fruit_set", temp_mean=temp, open_flowers=3)["result"]["concentration"] == conc


def test_fruit_set_high_temp_and_repeat():
    d = task_decision("fruit_set", temp_mean=22, temp_max=31, open_flowers=3)["result"]["decision"]
    assert d == "처리 가능 (100배액), 고온(30℃ 이상) 시간대 처리 회피"
    d = task_decision("fruit_set", temp_mean=22, open_flowers=4, already_treated=True)["result"]["decision"]
    assert d.startswith("처리 보류")
    d = task_decision("fruit_set", temp_mean=22, open_flowers=2)["result"]["decision"]
    assert "개화 수 부족" in d


def test_topping_by_cropping_type():
    out = task_decision("topping", cropping_type="반촉성", harvest_end_date="2026-07-20", current_truss=6)
    assert out["result"]["topping_date"] == "2026-05-31"
    assert out["result"]["target_trusses"] == [6, 8] and out["result"]["truss_reached"]
    assert task_decision("topping", cropping_type="억제")["result"]["target_trusses"] == [5, 6]
    assert task_decision("topping", cropping_type="촉성")["status"] == "no_rule"


@pytest.mark.parametrize("ct, season, pct, decision", [
    ("노지", None, 5, "수확 가능"), ("노지", None, 0, "수확 대기"),
    ("반촉성", None, 49, "수확 대기"), ("반촉성", None, 50, "수확 가능"),
    ("억제", "hot", 3, "수확 가능"), ("억제", "cold", 30, "수확 대기"),
    ("촉성", None, 90, "수확 가능"),
])
def test_harvest(ct, season, pct, decision):
    assert task_decision("harvest", cropping_type=ct, season=season, coloring_pct=pct)["result"]["decision"] == decision


def test_harvest_retarding_needs_season():
    assert task_decision("harvest", cropping_type="억제", coloring_pct=30)["status"] == "insufficient_data"


@pytest.mark.parametrize("pct, stage", [(10, "변색기"), (10.5, "최색기"), (60, "도색기"), (90, "완숙기")])
def test_coloring_stage(pct, stage):
    assert task_decision("harvest", cropping_type="노지", coloring_pct=pct)["result"]["stage"] == stage


def test_weather_zero_flood_days_no_rate():
    out = weather_risk_decision(tmin_forecast=12, tmax_forecast=30, flood_type="ridge", flood_days=0)
    assert "flood_damage_rate" not in out["result"] and "피해율" not in out["result"]["decision"]
