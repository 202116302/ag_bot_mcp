"""외부 농업 API 실시간 조회. 키는 config.get_key (환경변수 → .env → API_key.txt)로 읽는다.

- 흙토람 비료사용처방 (공공데이터포털)      FERTILIZER_API_KEY
- 스마트팜 빅데이터 데이터마트 (PROVIDE)    SMARTFARM_API_KEY
- 기상 (weather-rda.digitalag.kr, 기상청 중계) 키 불필요, 주소만

반환값은 MCP 조회 도구가 그대로 돌려주는 형태(dict). 키는 결과·오류 메시지에 남기지 않는다.
"""
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from urllib.parse import quote, unquote

import requests

from . import config

FERTILIZER_URL = "https://apis.data.go.kr/1390802/SoilEnviron/FrtlzrUse/getSoilFrtlzrExamInfo"
SMARTFARM_URL = "https://www.smartfarmkorea.net/Agree_WS/webservices/ProvideRestService"
CROP_CODES = {"open_field": "04016", "greenhouse": "04017"}  # 토마토(노지) / 토마토(시설), 비료 API 명세서
FERT_FIELDS = {"basal_n": "pre_Fert_N", "basal_p": "pre_Fert_P", "basal_k": "pre_Fert_K",
               "topdressing_n": "post_Fert_N", "topdressing_p": "post_Fert_P", "topdressing_k": "post_Fert_K"}
SMARTFARM_CODES = {"TI": "temp", "HI": "rh"}  # 내부온도, 내부습도 (단위는 API 미표기: ℃·%로 가정)


KST = timezone(timedelta(hours=9))


def today_kst() -> date:
    """서버(컨테이너)가 UTC여도 한국 날짜 기준으로 '오늘·내일'을 계산한다."""
    return datetime.now(KST).date()


class SourceError(Exception):
    pass


def _key(name: str) -> str:
    key = config.get_key(name)
    if not key:
        raise SourceError(f"{name}가 없습니다 (API_key.txt 또는 .env 확인)")
    return key


def _get(url: str, secret: str = "", **kwargs) -> requests.Response:
    try:
        resp = requests.get(url, timeout=(8, 25), allow_redirects=False, **kwargs)
    except requests.RequestException as exc:
        raise SourceError(f"네트워크 오류: {type(exc).__name__}") from None
    resp.encoding = "utf-8"
    if resp.status_code != 200:
        text = resp.text[:200].replace(secret, "[KEY]") if secret else resp.text[:200]
        raise SourceError(f"HTTP {resp.status_code}: {text}")
    return resp


# ------------------------------------------------------------------ 흙토람 비료사용처방
def fetch_fertilizer(pnu: str, cultivation: str = "open_field") -> dict:
    """필지(PNU 19자리)의 토마토 비료 처방 성분량(kg/10a)."""
    key = unquote(_key("FERTILIZER_API_KEY"))
    crop = CROP_CODES[cultivation]
    resp = _get(FERTILIZER_URL, key, params={"serviceKey": key, "PNU_Code": pnu, "crop_Code": crop})
    try:
        tree = ET.fromstring(resp.text)
    except ET.ParseError:
        raise SourceError("비료 API 응답이 XML이 아닙니다 (키·트래픽 확인)") from None
    code = tree.findtext("./header/result_Code")
    if code != "200":
        msg = tree.findtext("./header/result_Msg")
        raise SourceError(f"비료 API 결과코드 {code} {msg}" + (" (해당 필지·작물 검정자료 없음)" if code == "301" else ""))
    item = tree.find("./body/items/item")
    values = {k: (float(item.findtext(f)) if (item.findtext(f) or "").strip() else None) for k, f in FERT_FIELDS.items()}
    return {"unit": "kg/10a", **values, "pnu": pnu, "address": item.findtext("addr"), "crop": item.findtext("crop_Nm"),
            "crop_code": crop, "source": "흙토람 비료사용처방 API", "retrieved_at": datetime.now().isoformat(timespec="seconds")}


# ------------------------------------------------------------------ 스마트팜 데이터마트
def _smartfarm(operation: str, *args) -> list[dict]:
    key = _key("SMARTFARM_API_KEY")
    enc = quote(unquote(key), safe="")
    url = f"{SMARTFARM_URL}/{operation}/{enc}" + "".join("/" + quote(str(a), safe="") for a in args)
    resp = _get(url, enc)
    try:
        rows = resp.json()
    except ValueError:
        raise SourceError("스마트팜 응답이 JSON이 아닙니다") from None
    codes = {str(r["statusCode"]) for r in rows if isinstance(r, dict) and r.get("statusCode") is not None}
    if codes == {"03"}:
        raise SourceError("스마트팜 자료 없음(03)")
    if codes != {"00"}:
        raise SourceError(f"스마트팜 서비스 오류 {codes}")
    return rows


def fetch_greenhouse_env(facility_id: str, day: str, hour: int | None = None) -> dict:
    """데이터마트 시설의 특정 날짜 내부 온도·습도. hour를 주면 그 시각 값, 없으면 그날 마지막 기록."""
    out, hourly = {}, {}
    for code, name in SMARTFARM_CODES.items():
        rows = _smartfarm("getEnvDataList", facility_id, day, "FG", "EI", code, "080300")
        series = sorted((r["measDate"], float(r["senVal"])) for r in rows if str(r.get("senVal") or "").strip())
        pick = [v for t, v in series if hour is not None and int(t[11:13]) == hour] or [series[-1][1]]
        out[name] = pick[0]
        hourly[name] = {t[11:16]: v for t, v in series}
    h = hour if hour is not None else 12
    return {"temp": out["temp"], "rh": out["rh"], "time_of_day": "day" if 6 <= h < 19 else "night",
            "facility_id": facility_id, "measured_at": f"{day} {h:02d}:00" if hour is not None else day,
            "temp_range": [min(hourly["temp"].values()), max(hourly["temp"].values())],
            "hourly_temp": hourly["temp"], "hourly_rh": hourly["rh"],
            "source": "스마트팜 빅데이터 데이터마트 (단위 미표기: ℃, %로 가정)"}


# ------------------------------------------------------------------ 기상
def fetch_weather(region: str = config.WEATHER_REGION) -> dict:
    """기상청 초단기실황 + 단기예보(내일 최저·최고기온, 평균기온, 강수확률·강수량)."""
    base = config.WEATHER_URL
    now = _get(f"{base}/api/kma/realtime/latest/pivot", params={"region_name": region, "limit": 1}).json()
    if not now:
        raise SourceError(f"기상 실황 없음: {region}")
    now = now[0]

    def forecast(category: str, limit: int) -> list[dict]:
        return _get(f"{base}/api/kma/forecast/short/latest",
                    params={"region_name": region, "category": category, "limit": limit}).json()

    tomorrow = str(today_kst() + timedelta(days=1))
    pick = lambda rows: next((float(r["fcst_value"]) for r in rows if r["fcst_date"] == tomorrow), None)
    tmp_rows = sorted((r["fcst_time"], float(r["fcst_value"])) for r in forecast("TMP", 80) if r["fcst_date"] == tomorrow)
    tmp = [v for _, v in tmp_rows]
    pop = [float(r["fcst_value"]) for r in forecast("POP", 80) if r["fcst_date"] == tomorrow]
    pcp = sorted({r["fcst_value"] for r in forecast("PCP", 80) if r["fcst_date"] == tomorrow and r["fcst_value"] != "강수없음"})
    return {
        "station": region, "observed_at": f"{now['base_date']} {now['base_time']}",
        "outdoor_temp": now.get("T1H"), "outdoor_rh": now.get("REH"), "rain_1h_mm": now.get("RN1"),
        "forecast_date": tomorrow, "tmin_forecast": pick(forecast("TMN", 10)), "tmax_forecast": pick(forecast("TMX", 10)),
        "temp_mean": round(mean(tmp), 1) if tmp else None, "temp_max": max(tmp) if tmp else None,
        "pop_max": max(pop) if pop else None, "rain_forecast": pcp or ["강수없음"],
        "hourly_temp_forecast": {f"{t[:2]}:{t[2:]}": v for t, v in tmp_rows},
        "heavy_rain_warning": None,
        "note": "호우 특보는 이 API에서 제공하지 않음(None). 평균기온·최고기온은 내일 시간별 기온(TMP) 기준.",
        "source": "기상청 단기예보·초단기실황 (weather-rda.digitalag.kr)",
    }
