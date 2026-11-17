"""3개 분야 자료 로더. 모두 같은 형태의 dict를 돌려준다.

{"domain", "source", "values": [{"name", "value", "unit"}], ...분야별 추가 정보}
"""
import json
from statistics import mean

import requests

from .config import DATA, WEATHER_REGION, WEATHER_URL


def _load(path: str) -> dict:
    return json.loads((DATA / path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 비료
FERTILIZER_NAMES = {
    "basal_n": "밑거름 질소(N)",
    "basal_p": "밑거름 인산(P2O5)",
    "basal_k": "밑거름 칼리(K2O)",
    "topdressing_n": "웃거름 질소(N)",
    "topdressing_p": "웃거름 인산(P2O5)",
    "topdressing_k": "웃거름 칼리(K2O)",
    "compost_cattle": "우분퇴비",
    "compost_pig": "돈분퇴비",
    "compost_chicken": "계분퇴비",
    "compost_mix": "혼합퇴비",
}


def get_fertilizer() -> dict:
    snap = _load("snapshots/wanju_fertilizer.json")
    values = [
        {"name": FERTILIZER_NAMES.get(key, key), "value": float(item["value"]), "unit": item["unit"]}
        for key, item in snap["amounts"].items()
        if item["value"] is not None
    ]
    return {
        "domain": "fertilizer",
        "source": "농촌진흥청 흙토람 비료사용처방 API",
        "address": snap["address"],
        "pnu_code": snap["pnu_code"],
        "crop": snap["crop_name"],
        "values": values,
        "note": "공급자 API가 계산한 처방값이다. 실제 재배 작물·토양검정일은 확인되지 않았다.",
    }


# ---------------------------------------------------------------- 시설 환경
ENV_ITEMS = {
    # 코드: (항목명, 주제, 추정 단위)  ※ API가 단위를 명시하지 않아 일반적인 단위를 표기
    "TI": ("내부온도", "temperature", "℃"),
    "HI": ("내부습도", "humidity", "%"),
    "CI": ("내부 CO2", "co2", "ppm"),
}


def get_environment(item: str = "all") -> dict:
    """item: all | temperature | humidity | co2"""
    snap = _load("snapshots/smartfarm_environment_20230725.json")
    literature = _load("references/tomato_environment.json")

    values, hourly = [], {}
    for code, (name, topic, unit) in ENV_ITEMS.items():
        if item not in ("all", topic):
            continue
        obs = snap["fields"][code]["observations"]
        nums = [float(o["value"]) for o in obs if o["value"] is not None]
        if not nums:
            continue
        values += [
            {"name": f"{name} 최저", "value": min(nums), "unit": unit},
            {"name": f"{name} 최고", "value": max(nums), "unit": unit},
            {"name": f"{name} 평균", "value": round(mean(nums), 2), "unit": unit},
        ]
        hourly[name] = {o["measured_at"][11:16]: float(o["value"]) for o in obs}

    refs = [
        {"page": c["pdf_page"], "tomato_type": c["tomato_type"], "summary": c["reference_summary"]}
        for c in literature["chunks"]
        if item == "all" or c["topic"] == item
    ]
    return {
        "domain": "environment",
        "source": "스마트팜 데이터마트 (시설 PFS_0000001_01, 토마토)",
        "date": snap["date"],
        "values": values,
        "hourly": hourly,
        "literature": {"title": f"{literature['title']} ({literature['publication_date']})", "references": refs},
        "note": "API가 단위를 명시하지 않아 일반적인 단위를 표기했다. 2023-07-25 하루치 과거 자료다.",
    }


# ---------------------------------------------------------------- 기상
def get_weather(live: bool = False) -> dict:
    """기본은 저장된 스냅샷. live=True면 기상 API를 직접 조회한다."""
    snap = _load("snapshots/weather_jeonju.json")
    if live:
        snap = _fetch_weather_live(snap)
    current = snap["current"]
    values = [
        {"name": v["name"], "value": v["value"], "unit": v["unit"]}
        for v in current["values"].values()
    ]
    values += [
        {"name": f"{f['name']} {f['fcst_date']} {f['fcst_time']}", "value": f["value"], "unit": f["unit"]}
        for f in snap["forecast"]
    ]
    return {
        "domain": "weather",
        "source": "기상청 초단기실황·단기예보 (weather-rda.digitalag.kr)",
        "region": snap["region_name"],
        "observed_at": f"{current['base_date']} {current['base_time']}",
        "values": values,
        "note": "PTY(강수형태) 코드: 0 없음, 1 비, 2 비/눈, 3 눈, 5 빗방울, 6 빗방울눈날림, 7 눈날림.",
    }


def _fetch_weather_live(fallback: dict) -> dict:
    url = f"{WEATHER_URL}/api/kma/realtime/latest/pivot"
    rows = requests.get(url, params={"region_name": WEATHER_REGION, "limit": 1}, timeout=15).json()
    if not rows:
        return fallback
    obs = rows[0]
    snap = json.loads(json.dumps(fallback))
    snap["current"]["base_date"], snap["current"]["base_time"] = obs["base_date"], obs["base_time"]
    for code, item in snap["current"]["values"].items():
        item["value"] = obs.get(code)
    fc_url = f"{WEATHER_URL}/api/kma/forecast/short/latest"
    fc = requests.get(fc_url, params={"region_name": WEATHER_REGION, "category": "POP", "limit": 6}, timeout=15).json()
    snap["forecast"] = [
        {"fcst_date": r["fcst_date"], "fcst_time": r["fcst_time"], "category": "POP",
         "name": "강수확률", "value": float(r["fcst_value"]), "unit": "%"}
        for r in fc
    ]
    return snap


LOADERS = {"fertilizer": get_fertilizer, "environment": get_environment, "weather": get_weather}


# ---------------------------------------------------------------- 다른 농가 참고 (스마트팜 데이터마트)
DAY_HOURS, NIGHT_HOURS = range(10, 17), (20, 21, 22, 23, 0, 1, 2, 3, 4)


def get_farm_reference(month: int, time_of_day: str = "day") -> dict:
    """같은 시기(±1개월, 농가가 3곳 미만이면 ±2개월) 다른 시설 토마토 농가의 하우스 온도·습도 기록.
    판정 기준이 아니라 참고용 비교 자료다."""
    snap = _load("snapshots/smartfarm_reference.json")
    hours = set(DAY_HOURS if time_of_day == "day" else NIGHT_HOURS)
    month_gap = lambda m: min(abs(m - month), 12 - abs(m - month))
    for window in (1, 2):
        farms = [f for f in snap["farms"] if month_gap(f["month"]) <= window]
        if len(farms) >= 3:
            break

    def summarize(key: str) -> dict | None:
        per_farm = []
        for f in farms:
            vals = [v for h, v in f[key].items() if int(h) in hours]
            if vals:
                per_farm.append({"facility": f["facility"], "date": f["date"], "mean": round(sum(vals) / len(vals), 1),
                                 "min": min(vals), "max": max(vals)})
        if not per_farm:
            return None
        means = sorted(p["mean"] for p in per_farm)
        mid = len(means) // 2
        median = means[mid] if len(means) % 2 else round((means[mid - 1] + means[mid]) / 2, 1)
        return {"farms": len(per_farm), "farm_mean_median": median, "farm_mean_range": [means[0], means[-1]],
                "highest_record": max(p["max"] for p in per_farm), "lowest_record": min(p["min"] for p in per_farm),
                "per_farm": per_farm}

    return {
        "query": {"month": month, "time_of_day": time_of_day, "months_window": f"±{window}개월"},
        "temp_c": summarize("temp"), "rh_pct": summarize("rh"),
        "source": "스마트팜 빅데이터 데이터마트, 다른 시설 토마토 농가의 실제 기록 (과거 작기, 농가당 하루)",
        "note": "단위가 API에 표기되지 않아 ℃·%로 가정. 판정 기준이 아닌 참고용 비교 자료.",
    }


# ---------------------------------------------------------------- 시나리오 (v3)
SCENARIO_DIR = DATA.parent / "scenarios"


def load_scenarios() -> list[dict]:
    out = []
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        out += json.loads(path.read_text(encoding="utf-8"))
    return out


def live_section(name: str) -> dict | None:
    """LIVE 시나리오: 조회 도구가 불릴 때 외부 API를 실시간 호출한다."""
    from datetime import date

    from . import sources
    from .config import LIVE_FARM as f

    try:
        if name == "weather":
            return sources.fetch_weather()
        if name == "greenhouse_env":
            return sources.fetch_greenhouse_env(f["smartfarm_facility"], f["smartfarm_date"], f["smartfarm_hour"])
        if name == "fertilizer_prescription":
            return sources.fetch_fertilizer(f["pnu"], f["fertilizer_cultivation"])
    except sources.SourceError as exc:
        return {"available": False, "error": str(exc)}
    if name == "crop":
        return {"today": str(date.today()), "note": "작형·정식일·화방 수 등은 질문에서 알려 주세요."}
    return None


def live_scenario() -> dict:
    sections = ["weather", "greenhouse_env", "fertilizer_prescription", "crop"]
    return {"scenario_id": "LIVE", "cultivation": "mixed", "domain": "live", "type": "live", "question": None,
            "system_values": {s: live_section(s) for s in sections}, "expected": None}


def get_scenario(scenario_id: str) -> dict:
    if scenario_id == "DEMO":
        return demo_scenario()
    if scenario_id == "LIVE":
        return live_scenario()
    for s in load_scenarios():
        if s["scenario_id"] == scenario_id:
            return s
    raise KeyError(f"시나리오 없음: {scenario_id}")


def demo_scenario() -> dict:
    """실제 수집 자료로 만든 시연용 상황. 정답(expected)은 없다."""
    w = get_weather()
    wv = {v["name"]: v["value"] for v in w["values"]}
    env = _load("snapshots/smartfarm_environment_20230725.json")["fields"]
    at = lambda code: next(float(o["value"]) for o in env[code]["observations"] if o["measured_at"].endswith("14:00:00"))
    rx = _load("snapshots/wanju_fertilizer.json")["amounts"]
    return {
        "scenario_id": "DEMO", "cultivation": "mixed", "domain": "demo", "type": "demo", "question": None,
        "system_values": {
            "weather": {"station": w["region"], "observed_at": w["observed_at"], "outdoor_temp": wv["기온"],
                        "rain_1h_mm": wv["1시간 강수량"], "outdoor_rh": wv["습도"]},
            "greenhouse_env": {"temp": at("TI"), "rh": at("HI"), "time_of_day": "day",
                               "source": "스마트팜 데이터마트 PFS_0000001_01 2023-07-25 14:00"},
            "fertilizer_prescription": {"unit": "kg/10a", **{k: float(v["value"]) for k, v in rx.items() if not k.startswith("compost")},
                                        "source": "흙토람 완주군 이서면 용서리 528-33 (시설 토마토)"},
            "crop": {"cultivation": "greenhouse_hydroponic", "cropping_type": "반촉성", "hydroponic": True},
        },
        "expected": None,
    }
