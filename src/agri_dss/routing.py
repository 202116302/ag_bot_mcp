"""Conservative local capability routing, not an LLM intent classifier."""
import re
from .schemas import Contract

BASE_NOTICES = ['provider_calculated', 'actual_crop_unknown', 'soil_test_date_unknown',
                'not_irrigation_data', 'applicability_not_reviewed']
LIMITS = {
    'irrigation': ('not_irrigation_data', '관수: 실제 필지의 수분값·생육단계·재배방식 및 검토된 규칙이 없어 판단을 보류합니다.'),
    'weather': ('weather_unavailable', '기상: 기상 도구와 필지 위치 매핑이 연결되지 않아 강수량·예보 답변을 보류합니다.'),
    'growth': ('growth_unavailable', '생육: 해당 필지의 생육 관측자료가 없어 생육단계 판단을 보류합니다.'),
    'climate_control': ('climate_control_unavailable', '환경제어: 온실 센서 자료와 제어 기준이 없어 환기·난방 판단을 보류합니다.'),
    'soil_chemistry': ('soil_chemistry_unavailable', '토양검정: 원시 토양 화학성 자료가 없어 pH·유기물 등의 수치를 제시할 수 없습니다.'),
}
PATTERNS = {
    'irrigation': r'관수|관개|물을|물주|물\s*줘|수분|함수율|수분장력|irrigat|moisture',
    'weather': r'기상|날씨|강수|비가|예보|weather|rain|forecast',
    'growth': r'생육|생장|성장|착과|수확기|growth',
    'climate_control': r'환기|환경제어|난방|냉방|온실|이산화탄소|ventilat|climate',
    'soil_chemistry': r'토양검정|토양분석|토양\s*ph|\bph\b|유기물|산도|치환성|soil\s*(test|chem)',
}


class QuestionRoute(Contract):
    policy_version: str = 'capability-keywords-v1'
    method: str = 'local_rule_based_not_llm_classification'
    domains: list[str]
    blocked_domains: list[str]
    can_query_fertilizer: bool
    disposition: str
    notices: list[str]
    messages: list[str]
    requested_pnus: list[str]


def route_question(question: str, selected_pnu: str, selected_crop: str) -> QuestionRoute:
    requested = list(dict.fromkeys(re.findall(r'(?<![0-9])[0-9]{19}(?![0-9])', question)))
    explicit_crops = re.findall(r'(?:crop[_ ]?code|작물\s*코드)\s*[:=]?\s*([0-9]{5})(?![0-9])', question, re.I)
    domains = [domain for domain, pattern in PATTERNS.items() if re.search(pattern, question, re.I)]
    explicit_fertilizer = bool(re.search(r'비료|시비|밑거름|웃거름|퇴비|fertiliz', question, re.I))
    nutrients = bool(re.search(r'질소|인산|칼리|npk', question, re.I))
    fertilizer = explicit_fertilizer or (nutrients and 'soil_chemistry' not in domains)
    if fertilizer:
        domains.insert(0, 'fertilizer')
    # An explicit unsupported parcel/crop overrides every selected-parcel default.
    if any(pnu != selected_pnu for pnu in requested):
        return QuestionRoute(domains=domains, blocked_domains=domains or ['unknown'],
                             can_query_fertilizer=False, disposition='deferred', notices=[],
                             messages=['요청한 PNU의 자료가 등록되어 있지 않습니다. 기본 필지로 대체하지 않고 조회를 보류합니다.'],
                             requested_pnus=requested)
    other_crop = re.search(r'벼|딸기|고추|오이|상추|배추|rice|strawberry', question, re.I)
    if any(crop != selected_crop for crop in explicit_crops) or (fertilizer and other_crop):
        return QuestionRoute(domains=domains, blocked_domains=domains, can_query_fertilizer=False,
                             disposition='deferred', notices=[], requested_pnus=requested,
                             messages=['요청한 작물의 처방 자료가 등록되어 있지 않습니다. 시설 토마토 처방으로 대체하지 않습니다.'])
    blocked = [domain for domain in domains if domain != 'fertilizer']
    notices = list(dict.fromkeys(BASE_NOTICES + [LIMITS[domain][0] for domain in blocked])) if fertilizer else []
    messages = [LIMITS[domain][1] for domain in blocked]
    if not domains:
        messages = ['질문의 분야가 불명확하거나 현재 지원 범위 밖입니다. 필지와 필요한 자료를 구체적으로 지정해 주세요.']
    return QuestionRoute(domains=domains, blocked_domains=blocked, can_query_fertilizer=fertilizer,
                         disposition=('partial' if blocked else 'completed') if fertilizer else 'deferred',
                         notices=notices, messages=messages, requested_pnus=requested)
