"""MCP 서버: 조회 도구 7개 + 판정 도구 5개 (mcp_agri_dss_spec.md 5절). stdio로 실행된다.

조회 도구는 활성 시나리오(환경변수 AGBOT_SCENARIO, 기본 DEMO)의 system_values를 돌려준다.
"""
import os

from mcp.server.fastmcp import FastMCP

from . import data, docs, rules

mcp = FastMCP("agbot", log_level="WARNING")


def _section(name: str) -> dict:
    scenario = os.environ.get("AGBOT_SCENARIO", "DEMO")
    if scenario == "LIVE":  # 이 도구가 불릴 때 해당 API만 실시간 호출
        values = data.live_section(name)
    else:
        values = data.get_scenario(scenario)["system_values"].get(name)
    return values if values is not None else {"available": False, "note": "이 농장에는 해당 자료가 없습니다."}


# ------------------------------------------------------------------ 조회 도구
@mcp.tool()
def get_weather() -> dict:
    """기상 정보: 외기온, 최고·최저기온 예보, 평균기온, 강수 예보, 호우 특보 여부."""
    return _section("weather")


@mcp.tool()
def get_greenhouse_env() -> dict:
    """하우스(시설) 내부 온도(℃)·상대습도(%)와 현재 시간대(day/night)."""
    return _section("greenhouse_env")


@mcp.tool()
def get_nutrient_status() -> dict:
    """양액 상태: 적산일사량(J/㎠), 급액량·배액량(mL), 급액 EC(dS/m), 배액(근권) EC(mS/cm), 급액 pH."""
    return _section("nutrient")


@mcp.tool()
def get_soil_status() -> dict:
    """토양 상태: 토양수분, 토양검정값(pH, 유기물, 유효인산, 교환성 K 등)."""
    return _section("soil")


@mcp.tool()
def get_fertilizer_prescription() -> dict:
    """흙토람 비료사용처방: 밑거름·웃거름 성분량(N, P₂O₅, K₂O, kg/10a)."""
    return _section("fertilizer_prescription")


@mcp.tool()
def get_crop_status() -> dict:
    """작물 상태: 재배형태, 작형(촉성/반촉성/억제/노지), 양액재배 여부, 정식일, 오늘 날짜, 생육단계 등."""
    return _section("crop")


@mcp.tool()
def search_guideline(query: str, k: int = 5) -> list[dict]:
    """토마토 재배 기준 문서(제주농기원 토마토, 농진청 기상재해 가이드북, 양액 논문)에서 관련 문단을 검색한다."""
    return docs.search_guideline(query, k)


# ------------------------------------------------------------------ 판정 도구
DESCRIPTIONS = {
    "climate_control_decision": "시설 환경제어 판정: 하우스 온도·습도·외기온·시간대(day/night)로 환기·차광·난방·송풍 필요 여부. "
                                "값 출처: greenhouse_temp·greenhouse_rh·time_of_day는 get_greenhouse_env, outdoor_temp는 get_weather.",
    "nutrient_decision": "양액 관리 판정: 적산일사량으로 급액 시점, 급액량·배액량으로 배액률 계산과 급액량 증감, 급액·배액 EC와 pH 조정. "
                         "값 출처: get_nutrient_status. 질문과 관련된 항목의 값만 넣는다.",
    "fertilizer_schedule": "시비 판정: 흙토람 성분량(kg/10a) → 요소·용성인비·염화가리 제품량 환산(area_m2 넣으면 면적 환산), 정식일·오늘 날짜로 웃거름 시기. "
                           "값 출처: 성분량은 get_fertilizer_prescription, planting_date·today는 get_crop_status, 면적은 질문.",
    "weather_risk_decision": "기상 대응 판정: 최저·최고기온 예보, 호우 특보, 침수 형태(ridge=이랑 위 10cm, furrow=고랑)와 침수 일수로 대응과 피해율. "
                             "값 출처: 기온 예보·호우 특보는 get_weather, 침수 형태·일수는 질문.",
    "task_decision": "작업관리 판정. task=topping(적심 시기·단수: harvest_end_date, today, cropping_type, current_truss), "
                     "fruit_set(착과제 농도·처리 가능 여부: temp_mean, temp_max, open_flowers, already_treated), "
                     "harvest(수확 여부: coloring_pct, cropping_type, season=hot|cold). cropping_type: 촉성|반촉성|억제|노지. "
                     "값 출처: temp_mean·temp_max는 get_weather, cropping_type·today·season은 get_crop_status, 화방·개화·착색은 질문.",
}
for name, fn in rules.DECISION_TOOLS.items():
    mcp.add_tool(fn, name=name, description=DESCRIPTIONS[name])


if __name__ == "__main__":
    mcp.run(transport="stdio")
