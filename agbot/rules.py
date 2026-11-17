"""판정 규칙 엔진 (MCP 조건의 판정 도구). 임계값·출처는 knowledge/rules.yaml에서 읽는다.

모든 함수는 명세 5.3 형식을 반환한다:
{result: {decision, ...}, basis: [...], rule_ids, sources: [{doc_id, clause}], inputs_used, missing_inputs, status}
status: decided | partial(일부 입력 누락) | insufficient_data(판정 불가) | no_rule(문서 기준 없음)
"""
from datetime import date, timedelta
from functools import lru_cache

import yaml

from .config import ROOT

CROPPING = {"촉성": "forcing", "반촉성": "semi_forcing", "억제": "retarding", "노지": "open_field",
            "forcing": "forcing", "semi_forcing": "semi_forcing", "retarding": "retarding", "open_field": "open_field"}
CROPPING_KO = {"forcing": "촉성", "semi_forcing": "반촉성", "retarding": "억제", "open_field": "노지"}


@lru_cache
def RULES() -> dict:
    data = yaml.safe_load((ROOT / "knowledge" / "rules.yaml").read_text(encoding="utf-8"))
    return {rid: r for group in data.values() for rid, r in group.items()}


def rule(rid: str) -> dict:
    return RULES()[rid]


def _output(decision, basis, rule_ids, inputs, required, extra=None, status=None):
    missing = [k for k in required if inputs.get(k) is None]
    if status is None:
        status = "insufficient_data" if not rule_ids else ("partial" if missing else "decided")
    rule_ids = list(dict.fromkeys(rule_ids))
    return {
        "result": {"decision": decision if status != "insufficient_data" else "판단 보류(필수 입력 누락)", **(extra or {})},
        "basis": basis,
        "rule_ids": rule_ids,
        "sources": [dict(t) for t in dict.fromkeys(
            (("doc_id", rule(r)["doc_id"]), ("clause", rule(r)["clause"])) for r in rule_ids)],
        "inputs_used": {k: v for k, v in inputs.items() if v is not None},
        "missing_inputs": missing,
        "status": status,
    }


def _date(value) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) and value else value


# ------------------------------------------------------------------ 환경제어 (시설)
def climate_control_decision(greenhouse_temp: float | None = None, greenhouse_rh: float | None = None,
                             outdoor_temp: float | None = None, time_of_day: str = "day") -> dict:
    inputs = dict(greenhouse_temp=greenhouse_temp, greenhouse_rh=greenhouse_rh,
                  outdoor_temp=outdoor_temp, time_of_day=time_of_day)
    actions = {"환기": False, "차광": False, "난방": False, "송풍": False}
    basis, ids = [], []
    night = time_of_day == "night"
    t = greenhouse_temp
    if t is not None:
        if t <= rule("ENV-05")["growth_stop"]:
            actions["난방"] = True
            ids += ["ENV-05", "ENV-04"]
            basis.append(f"하우스 기온 {t}℃ ≤ 5℃: 생육 정지 위험 → 즉시 난방")
        elif t <= rule("ENV-04")["min_growth"]:
            actions["난방"] = True
            ids.append("ENV-04")
            basis.append(f"하우스 기온 {t}℃ ≤ 10℃: 생육 저하 → 난방·보온")
        elif not night:
            lo, hi = rule("ENV-02")["day_optimal"]
            if t >= rule("ENV-01")["day_max"]:
                actions["환기"] = actions["차광"] = True
                ids.append("ENV-01")
                basis.append(f"주간 기온 {t}℃ ≥ 30℃: 생육 불량·낙화 위험 → 환기·차광")
            elif t > hi:
                actions["환기"] = True
                ids.append("ENV-02")
                basis.append(f"주간 기온 {t}℃ > 적온 상한 {hi}℃ → 환기로 적온({lo}~{hi}℃) 유도")
            else:
                ids.append("ENV-02")
                basis.append(f"주간 기온 {t}℃: 적온({lo}~{hi}℃) 이내" if t >= lo
                             else f"주간 기온 {t}℃ < 적온 하한 {lo}℃ → 환기 최소화·보온")
        else:
            if t >= rule("ENV-03")["night_max"]:
                actions["환기"] = True
                ids.append("ENV-03")
                basis.append(f"야간 기온 {t}℃ ≥ 20℃: 공동과·낙화 위험 → 야간 환기")
            else:
                ids.append("ENV-02")
                basis.append(f"야간 기온 {t}℃: 야간 적온(17℃ 정도) 범위로 관리 가능")
    rh = greenhouse_rh
    if rh is not None:
        r6 = rule("ENV-06")
        if rh >= r6["rh_max"]:
            actions["송풍"] = actions["환기"] = True
            ids.append("ENV-06")
            basis.append(f"상대습도 {rh}% ≥ 70%: 열과 우려 → 송풍·환기 (목표 50% 이하)")
        else:
            ids.append("ENV-06")
            basis.append(f"상대습도 {rh}% < 70%: 열과 우려 기준 미만")
    else:
        ids.append("ENV-06")
        basis.append("상대습도 값 없음 → 열과 우려(송풍) 여부 판단 불가")
    if night and actions["환기"] and outdoor_temp is not None and outdoor_temp <= rule("ENV-08")["outdoor_min_for_night_vent"]:
        actions["환기"] = False
        ids.append("ENV-08")
        basis.append(f"[충돌] 외기온 {outdoor_temp}℃ ≤ 10℃: 야간 환기 중지 → 환기 대신 송풍으로 습도 저하")
        if rh is not None and rh >= rule("ENV-06")["rh_max"]:
            actions["송풍"] = True
    needed = [k for k, v in actions.items() if v]
    decision = (" · ".join(needed) + " 필요") if needed else "기온 기준 조치 불필요"
    if t is None:
        decision += " / 기온 값 없음 → 온도 관련 판단 보류"
    if rh is None:
        decision += " / 습도 값 없음 → 송풍·열과 판단 보류"
    status = "insufficient_data" if t is None and rh is None else None
    return _output(decision, basis, ids, inputs, ["greenhouse_temp", "greenhouse_rh"], {"actions": actions}, status)


# ------------------------------------------------------------------ 양액 관리 (시설)
def nutrient_decision(solar_accum: float | None = None, supply_volume: float | None = None,
                      drain_volume: float | None = None, supply_ec: float | None = None,
                      drain_ec: float | None = None, supply_ph: float | None = None) -> dict:
    inputs = dict(solar_accum=solar_accum, supply_volume=supply_volume, drain_volume=drain_volume,
                  supply_ec=supply_ec, drain_ec=drain_ec, supply_ph=supply_ph)
    items, basis, ids, extra = [], [], [], {}
    if solar_accum is not None:
        trig = rule("NUT-01")["solar_trigger"]
        ids.append("NUT-01")
        if solar_accum >= trig:
            items.append("급액 시점: 급액 실시")
            basis.append(f"적산일사량 {solar_accum} J/㎠ ≥ {trig} J/㎠ → 급액")
        else:
            items.append("급액 시점: 급액 대기")
            basis.append(f"적산일사량 {solar_accum} J/㎠ < {trig} J/㎠ → 아직 급액 시점 아님")
    volume_dir = None
    if supply_volume and drain_volume is not None:
        raw = drain_volume / supply_volume * 100
        rate = round(raw, 1)
        lo, hi = rule("NUT-02")["drain_rate"]
        extra["drain_rate_pct"] = rate
        ids.append("NUT-02")
        if raw < lo:
            volume_dir = "increase"
            items.append(f"배액률 {rate}%: 급액량 증가")
            basis.append(f"배액률 {rate}% (= {drain_volume} ÷ {supply_volume} × 100) < {lo}% → 급액량 증가")
        elif raw > hi:
            volume_dir = "decrease"
            items.append(f"배액률 {rate}%: 급액량 감소")
            basis.append(f"배액률 {rate}% (= {drain_volume} ÷ {supply_volume} × 100) > {hi}% → 급액량 감소")
        else:
            items.append(f"배액률 {rate}%: 급액량 유지")
            basis.append(f"배액률 {rate}% (= {drain_volume} ÷ {supply_volume} × 100): 목표 {lo}~{hi}% 이내")
    if drain_ec is not None:
        lo, hi = rule("NUT-03")["root_ec"]
        ids.append("NUT-03")
        if drain_ec > hi:
            want = "increase"
            ec_item = "근권 EC 높음: 배액률 높여 근권 EC 낮춤"
            basis.append(f"근권(배액) EC {drain_ec} mS/cm > {hi} → 배액률을 높여 근권 EC 낮춤")
        elif drain_ec < lo:
            want = "decrease"
            ec_item = "근권 EC 낮음: 배액률 낮춰 근권 EC 높임"
            basis.append(f"근권(배액) EC {drain_ec} mS/cm < {lo} → 배액률을 낮춰 근권 EC 높임")
        else:
            want = None
            ec_item = "근권 EC 적정"
            basis.append(f"근권(배액) EC {drain_ec} mS/cm: 관리 범위 {lo}~{hi} 이내")
        if want and volume_dir and want != volume_dir:
            ec_item = ("근권 EC 낮음" if want == "decrease" else "근권 EC 높음") +                 ": [충돌] 배액률 기준과 방향이 반대 → 배액률 기준 우선, 근권 EC는 급액 EC로 보정"
            basis.append("[충돌] 배액률 기준과 근권 EC 조절 방향이 반대 → 배액률(20~30%) 범위 유지를 우선하고 급액 EC로 조정")
        items.append(ec_item)
    if supply_ec is not None:
        lo, hi = rule("NUT-04")["supply_ec"]
        ids.append("NUT-04")
        if supply_ec > hi:
            items.append("급액 EC 높음: 급액 EC 낮춤")
            basis.append(f"급액 EC {supply_ec} > {hi} dS/m → 급액 EC 낮춤 (기준 {lo}~{hi})")
        elif supply_ec < lo:
            items.append("급액 EC 낮음: 급액 EC 높임")
            basis.append(f"급액 EC {supply_ec} < {lo} dS/m → 급액 EC 높임 (기준 {lo}~{hi})")
        else:
            items.append("급액 EC 적정")
            basis.append(f"급액 EC {supply_ec} dS/m: 기준 {lo}~{hi} 이내")
    if supply_ph is not None:
        lo, hi = rule("NUT-05")["supply_ph"]
        ids.append("NUT-05")
        if supply_ph > hi:
            items.append("급액 pH 높음: pH 낮춤")
            basis.append(f"급액 pH {supply_ph} > {hi} → pH 낮춤 (기준 {lo}~{hi})")
        elif supply_ph < lo:
            items.append("급액 pH 낮음: pH 높임")
            basis.append(f"급액 pH {supply_ph} < {lo} → pH 높임 (기준 {lo}~{hi})")
        else:
            items.append("급액 pH 적정")
            basis.append(f"급액 pH {supply_ph}: 기준 {lo}~{hi} 이내")
    decision = " / ".join(items) if items else "판단 보류"
    # 모든 입력은 선택. 배액률 계산에 필요한 짝(급액량·배액량) 중 하나만 있으면 누락으로 본다.
    pair_missing = ["drain_volume"] if supply_volume is not None and drain_volume is None else         (["supply_volume"] if drain_volume is not None and supply_volume is None else [])
    return _output(decision, basis, ids, inputs, pair_missing, extra)


# ------------------------------------------------------------------ 시비 (노지)
def fertilizer_schedule(basal_n: float | None = None, basal_p: float | None = None, basal_k: float | None = None,
                        topdressing_n: float | None = None, topdressing_p: float | None = None,
                        topdressing_k: float | None = None, planting_date: str | None = None,
                        today: str | None = None, area_m2: float | None = None) -> dict:
    """성분량(kg/10a, 흙토람 처방) → 제품량(요소·용성인비·염화가리) 환산과 웃거름 시기."""
    inputs = dict(basal_n=basal_n, basal_p=basal_p, basal_k=basal_k, topdressing_n=topdressing_n,
                  topdressing_p=topdressing_p, topdressing_k=topdressing_k,
                  planting_date=planting_date, today=today, area_m2=area_m2)
    basis, ids, extra = [], [], {}
    c = rule("FER-01")["contents"]
    scale = (area_m2 / 1000) if area_m2 else 1
    unit = f"kg/{area_m2:g}㎡" if area_m2 else "kg/10a"

    def products(n, p, k):
        return {"요소": round(n / c["urea_n"] * scale, 1) if n is not None else None,
                "용성인비": round(p / c["fused_p"] * scale, 1) if p is not None else None,
                "염화가리": round(k / c["kcl_k"] * scale, 1) if k is not None else None}

    have_rx = any(v is not None for v in (basal_n, basal_p, basal_k, topdressing_n, topdressing_p, topdressing_k))
    if have_rx:
        ids += ["FER-01", "FER-04"]
        extra["basal_products"] = products(basal_n, basal_p, basal_k)
        extra["topdressing_products"] = products(topdressing_n, topdressing_p, topdressing_k)
        extra["unit"] = unit
        basis.append(f"제품량 = 성분량 ÷ 성분 함량 (요소 N 46%, 용성인비 P₂O₅ 20%, 염화가리 K₂O 60%), 단위 {unit}")
        basis.append(f"밑거름 {extra['basal_products']}, 웃거름 합계 {extra['topdressing_products']}")
    else:
        r2 = rule("FER-02")
        k10a = 1000 / r2["pyeong_300_m2"]
        std = {x: round(v * k10a, 1) for x, v in r2["per_300pyeong"].items()}
        ids += ["FER-02", "FER-01"]
        extra["standard_10a"] = std
        extra["total_products"] = products(std["n"], std["p"], std["k"])
        extra["unit"] = unit
        basis.append(f"흙토람 처방 없음 → 노지 표준시비량(300평당 N 24.0, P 16.4, K 23.8kg)을 10a로 환산: {std}")
        basis.append(f"총 제품량 {extra['total_products']} ({unit}); 밑거름/웃거름 배분 수치는 문서에 없음")

    pd_, td = _date(planting_date), _date(today)
    if pd_:
        r3 = rule("FER-03")
        (f0, f1), (i0, i1) = r3["first"], r3["interval"]
        windows = [(pd_ + timedelta(f0), pd_ + timedelta(f1))]
        for _ in range(r3["rounds"] - 1):
            windows.append((windows[-1][0] + timedelta(i0), windows[-1][1] + timedelta(i1)))
        extra["topdressing_windows"] = [f"{i + 1}차 {a} ~ {b}" for i, (a, b) in enumerate(windows)]
        ids.append("FER-03")
        basis.append("웃거름 시기: 1차 정식 후 25~30일, 2·3차는 앞 웃거름 후 20~25일 → " + "; ".join(extra["topdressing_windows"]))
        if td:
            days = (td - pd_).days
            extra["days_after_planting"] = days
            now = next((i for i, (a, b) in enumerate(windows) if a <= td <= b), None)
            if now is not None:
                extra["topdressing_now"] = f"{now + 1}차 웃거름 적기"
            else:
                nxt = next((i for i, (a, _) in enumerate(windows) if td < a), None)
                extra["topdressing_now"] = f"{nxt + 1}차 웃거름 전 ({windows[nxt][0]}부터)" if nxt is not None else "3차 이후: 생육 상태를 보아 시용"
            basis.append(f"오늘 {td}은 정식 후 {days}일 → {extra['topdressing_now']}")
    asks_schedule = today is not None or planting_date is not None or not have_rx
    if asks_schedule and not pd_:
        ids.append("FER-03")
        basis.append("정식일 정보가 없어 웃거름 날짜 계산 불가 (기준: 1차 정식 후 25~30일, 2·3차는 앞 웃거름 후 20~25일)")
    decision = extra.get("topdressing_now") or ("제품량 환산 완료" + (" (웃거름 날짜는 정식일 필요)" if asks_schedule and not pd_ else ""))
    return _output(decision, basis, ids, inputs, ["planting_date", "today"] if asks_schedule else [], extra)


# ------------------------------------------------------------------ 기상 대응 (노지)
def _flood_rate(table: dict, days: float) -> str:
    keys = sorted(float(k) for k in table)
    tab = {float(k): v for k, v in table.items()}
    if days in tab:
        return f"{tab[days]}%"
    if days < keys[0]:
        return f"{tab[keys[0]]}% 미만"
    if days > keys[-1]:
        return f"{tab[keys[-1]]}% 이상"
    lo = max(k for k in keys if k < days)
    hi = min(k for k in keys if k > days)
    return f"{tab[lo]}~{tab[hi]}%"


def weather_risk_decision(tmin_forecast: float | None = None, tmax_forecast: float | None = None,
                          heavy_rain_warning: bool | None = None, flood_type: str | None = None,
                          flood_days: float | None = None) -> dict:
    """flood_type: "ridge"(이랑 위 10cm 침수) | "furrow"(고랑 침수)"""
    inputs = dict(tmin_forecast=tmin_forecast, tmax_forecast=tmax_forecast, heavy_rain_warning=heavy_rain_warning,
                  flood_type=flood_type, flood_days=flood_days)
    items, basis, ids, extra = [], [], [], {}
    if tmin_forecast is not None:
        ids.append("WTH-01")
        if tmin_forecast <= rule("WTH-01")["tmin"]:
            items.append("보온 피복")
            basis.append(f"최저기온 예보 {tmin_forecast}℃ ≤ 10℃: 생육 저하 위험 → 보온 피복")
        else:
            basis.append(f"최저기온 예보 {tmin_forecast}℃ > 10℃: 저온 위험 없음")
    if tmax_forecast is not None:
        ids.append("WTH-02")
        if tmax_forecast >= rule("WTH-02")["tmax"]:
            items.append("고온 대응")
            basis.append(f"최고기온 예보 {tmax_forecast}℃ ≥ 30℃: 낙화·생육 불량 위험 → 고온 대응")
        else:
            basis.append(f"최고기온 예보 {tmax_forecast}℃ < 30℃: 고온 위험 없음")
    if heavy_rain_warning:
        ids.append("WTH-03")
        items.append("배수로 확보")
        basis.append("호우 예보 → 배수로 확보로 침수 대비")
    elif heavy_rain_warning is False:
        ids.append("WTH-03")
        basis.append("호우 예보 없음")
    if flood_type and flood_days:  # 침수 0일·미입력이면 피해율을 계산하지 않음
        r3 = rule("WTH-03")
        table = r3["ridge_flood"] if flood_type == "ridge" else r3["furrow_flood"]
        rate = _flood_rate(table, float(flood_days))
        extra["flood_damage_rate"] = rate
        ids.append("WTH-03")
        items.append(f"침수 피해율 {rate}")
        kind = "이랑 위 10cm 침수" if flood_type == "ridge" else "고랑 침수"
        basis.append(f"{kind} {flood_days}일 (과비대기) → 피해율 {rate}; 배수로 확보로 신속 배출")
    decision = ", ".join(items) if items else "특별 대응 불필요"
    return _output(decision, basis, ids, inputs, [], extra)


# ------------------------------------------------------------------ 작업관리 (공통)
def task_decision(task: str, cropping_type: str | None = None, hydroponic: bool = False,
                  harvest_end_date: str | None = None, today: str | None = None, current_truss: int | None = None,
                  temp_mean: float | None = None, temp_max: float | None = None, open_flowers: int | None = None,
                  already_treated: bool | None = None, coloring_pct: float | None = None,
                  season: str | None = None) -> dict:
    """task: topping(적심) | fruit_set(착과제) | harvest(수확)
    cropping_type: 촉성 | 반촉성 | 억제 | 노지   season(억제재배 수확): hot(혹서기) | cold(저온기)"""
    ct = CROPPING.get(cropping_type or "")
    inputs = dict(task=task, cropping_type=cropping_type, hydroponic=hydroponic, harvest_end_date=harvest_end_date,
                  today=today, current_truss=current_truss, temp_mean=temp_mean, temp_max=temp_max,
                  open_flowers=open_flowers, already_treated=already_treated, coloring_pct=coloring_pct, season=season)
    if task == "topping":
        return _topping(ct, hydroponic, _date(harvest_end_date), _date(today), current_truss, inputs)
    if task == "fruit_set":
        return _fruit_set(temp_mean, temp_max, open_flowers, already_treated, inputs)
    if task == "harvest":
        return _harvest(ct, coloring_pct, season, inputs)
    return _output("지원하지 않는 작업", [f"task={task}"], [], inputs, ["task"], status="no_rule")


def _topping(ct, hydroponic, end, today, current_truss, inputs):
    basis, ids, extra = [], [], {}
    if end:
        when = end - timedelta(rule("TSK-01")["days_before_end"])
        extra["topping_date"] = str(when)
        ids.append("TSK-01")
        basis.append(f"적심일 = 수확 종료 예정일 {end} − 50일 = {when}, 마지막 수확 화방 위 잎 2매 남김")
        if today:
            d = (when - today).days
            extra["days_until_topping"] = d
            basis.append(f"오늘 {today} 기준 {'D-' + str(d) if d > 0 else ('오늘' if d == 0 else str(-d) + '일 지남')}")
    r2 = rule("TSK-02")
    if ct:
        rng = r2["trusses"].get(ct)
        ids.append("TSK-02")
        if rng:
            extra["target_trusses"] = rng
            basis.append(f"{CROPPING_KO[ct]} 작형 적심 단수 {rng[0]}~{rng[1]}단")
            if current_truss is not None:
                extra["truss_reached"] = current_truss >= rng[0]
                basis.append(f"현재 {current_truss}화방 → " + ("적심 단수 도달" if current_truss >= rng[0] else f"{rng[0]}단까지 {rng[0] - current_truss}화방 남음"))
        else:
            basis.append(f"{CROPPING_KO[ct]} 작형은 적심 단수 수치 기준 없음 (과번무 시 적심)")
        if hydroponic:
            basis.append("양액재배: 세력이 왕성할 때 일찍 적심하면 열과 우려 → 세력을 보아 적심")
    if not end and not (ct and r2["trusses"].get(ct)):
        status = "no_rule" if ct == "forcing" else None
        return _output("판단 보류", basis, ids, inputs, ["harvest_end_date", "cropping_type"], extra, status=status)
    parts = []
    if "topping_date" in extra:
        parts.append(f"적심일 {extra['topping_date']}")
    if extra.get("truss_reached"):
        parts.append("적심 단수 도달")
    elif "target_trusses" in extra:
        parts.append(f"{extra['target_trusses'][0]}~{extra['target_trusses'][1]}단 적심")
    return _output(", ".join(parts), basis, ids, inputs, ["harvest_end_date", "cropping_type"], extra)


def _fruit_set(temp_mean, temp_max, open_flowers, already_treated, inputs):
    basis, ids, extra = [], [], {}
    r3, r4 = rule("TSK-03"), rule("TSK-04")
    if temp_mean is not None:
        conc = r3["low"] if temp_mean <= r3["temp_threshold"] else r3["high"]
        extra["concentration"] = conc
        ids.append("TSK-03")
        basis.append(f"평균기온 {temp_mean}℃ {'≤' if temp_mean <= 20 else '>'} 20℃ → 토마토톤 {conc} (문서상 20℃는 '이하'(50배액)와 '이상'(100배액)에 모두 해당 — 이 시스템은 50배액으로 처리)")
    ok, hold = True, []
    if open_flowers is not None:
        lo, hi = r4["open_flowers"]
        ids.append("TSK-04")
        if open_flowers < lo:
            ok = False
            hold.append(f"개화 수 부족({open_flowers}개 < {lo}개)")
            basis.append(f"화방당 개화 {open_flowers}개 < {lo}개 → 처리 적기 전")
        elif open_flowers > hi:
            basis.append(f"화방당 개화 {open_flowers}개 > {hi}개 → 처리 적기(3~5개) 지남, 늦어지면 착과율 저하")
        else:
            basis.append(f"화방당 개화 {open_flowers}개: 처리 적기(3~5개)")
    if already_treated:
        ok = False
        ids.append("TSK-04")
        hold.append("중복 처리")
        basis.append("이미 처리한 화방 → 중복 처리는 피한다")
    caution = None
    if temp_max is not None:
        ids.append("TSK-04")
        if temp_max >= r4["high_temp"]:
            caution = "고온(30℃ 이상) 시간대 처리 회피"
            basis.append(f"최고기온 {temp_max}℃ ≥ 30℃ → 고온 시간대 처리 피함 (공동과·기형과 증가)")
    if temp_mean is None and open_flowers is None:
        return _output("판단 보류", basis, ids, inputs, ["temp_mean", "open_flowers"], extra)
    if not ok:
        decision = "처리 보류: " + ", ".join(hold)
    else:
        decision = f"처리 가능 ({extra.get('concentration', '농도 판단 불가')})" + (f", {caution}" if caution else "")
    return _output(decision, basis, ids, inputs, ["temp_mean", "open_flowers"], extra)


def _harvest(ct, coloring_pct, season, inputs):
    basis, ids, extra = [], [], {}
    r5 = rule("TSK-05")
    if coloring_pct is None:
        return _output("판단 보류", basis, ids, inputs, ["coloring_pct", "cropping_type"], extra)
    # stage_upper: [상한%, 단계] — 상한 이하이면 그 단계, 90% 이상은 완숙기 (boundary는 rules.yaml 참고)
    if coloring_pct <= 0:
        stage = "녹숙기"
    elif coloring_pct >= 90:
        stage = "완숙기"
    else:
        stage = next(name for upper, name in r5["stage_upper"] if coloring_pct <= upper)
    extra["stage"] = stage
    ids.append("TSK-05")
    basis.append(f"착색 {coloring_pct}% → {stage}")
    hp = r5["harvest_pct"]
    if ct == "retarding":
        if season not in ("hot", "cold"):
            return _output("판단 보류(억제재배는 혹서기/저온기 구분 필요)", basis, ids, inputs,
                           ["coloring_pct", "cropping_type", "season"], extra, status="insufficient_data")
        target = hp["retarding_hot"] if season == "hot" else hp["retarding_cold"]
    elif ct in ("open_field", "semi_forcing"):
        target = hp[ct]
    else:
        target = hp["default"]
    label = "착색초기(변색기 진입)" if target <= 1 else f"{target}% 착색"
    extra["harvest_criterion"] = label
    ready = coloring_pct >= target if target > 1 else coloring_pct > 0
    basis.append(f"{CROPPING_KO.get(ct, '일반')} 기준 수확: {label} → " + ("수확 가능" if ready else "아직 이름"))
    return _output("수확 가능" if ready else "수확 대기", basis, ids, inputs, ["coloring_pct", "cropping_type"], extra)


DECISION_TOOLS = {
    "climate_control_decision": climate_control_decision,
    "nutrient_decision": nutrient_decision,
    "fertilizer_schedule": fertilizer_schedule,
    "weather_risk_decision": weather_risk_decision,
    "task_decision": task_decision,
}
