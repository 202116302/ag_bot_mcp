"""Check structured LLM claims against tool evidence before rendering Korean text."""
from decimal import Decimal, InvalidOperation
from typing import Literal
from .schemas import Contract
from .fertilizer import FertilizerPrescription

AmountName = Literal['basal_n', 'basal_p', 'basal_k', 'topdressing_n',
                     'topdressing_p', 'topdressing_k', 'compost_cattle',
                     'compost_pig', 'compost_chicken', 'compost_mix']
Notice = Literal['provider_calculated', 'actual_crop_unknown', 'soil_test_date_unknown',
                 'not_irrigation_data', 'applicability_not_reviewed', 'weather_unavailable',
                 'growth_unavailable', 'climate_control_unavailable', 'soil_chemistry_unavailable']
NOTICES = ['provider_calculated', 'actual_crop_unknown', 'soil_test_date_unknown',
           'not_irrigation_data', 'applicability_not_reviewed']


class AmountClaim(Contract):
    field: AmountName
    value: str | None
    unit: str


class FertilizerExplanation(Contract):
    pnu_code: str
    crop_code: str
    source_sha256: str
    status: Literal['available', 'incomplete', 'no_data', 'provider_error']
    amounts: list[AmountClaim]
    notices: list[Notice]


def explanation_from_prescription(data: FertilizerPrescription) -> FertilizerExplanation:
    """Deterministic Mock response and checker expectation; not an LLM evaluator."""
    return FertilizerExplanation(pnu_code=data.pnu_code, crop_code=data.requested_crop_code,
                                source_sha256=data.source_sha256, status=data.status,
                                amounts=[AmountClaim(field=name,
                                         value=str(amount.value) if amount.value is not None else None,
                                         unit=amount.unit) for name, amount in data.amounts.items()],
                                notices=NOTICES)


def check_explanation(answer: FertilizerExplanation, evidence: FertilizerPrescription,
                      required_notices: list[str] | None = None) -> list[str]:
    errors = []
    expected = explanation_from_prescription(evidence)
    for field in ('pnu_code', 'crop_code', 'source_sha256', 'status'):
        if getattr(answer, field) != getattr(expected, field):
            errors.append(field + '_mismatch')
    claims = {claim.field: claim for claim in answer.amounts}
    if len(claims) != len(answer.amounts) or set(claims) != set(evidence.amounts):
        errors.append('amount_fields_mismatch')
    for name, amount in evidence.amounts.items():
        if name not in claims:
            continue
        claim = claims[name]
        if claim.unit != amount.unit:
            errors.append(name + '_unit_mismatch')
        try:
            if claim.value is None or amount.value is None:
                equal = claim.value is None and amount.value is None
            else:
                value = Decimal(claim.value)
                equal = value.is_finite() and value == amount.value
        except InvalidOperation:
            equal = False
        if not equal:
            errors.append(name + '_value_mismatch')
    notices = NOTICES if required_notices is None else required_notices
    if len(answer.notices) != len(notices) or set(answer.notices) != set(notices):
        errors.append('notices_mismatch')
    return errors


def strict_schema(schema: dict) -> dict:
    """Responses strict schemas require all properties and no additional properties."""
    if isinstance(schema, list):
        return [strict_schema(value) for value in schema]
    if not isinstance(schema, dict):
        return schema
    result = {key: strict_schema(value) for key, value in schema.items() if key not in ('default', 'title')}
    if 'const' in result:
        result['enum'] = [result.pop('const')]
    if result.get('type') == 'object':
        result['required'] = list(result.get('properties', {}))
        result['additionalProperties'] = False
    return result


def render_explanation(answer: FertilizerExplanation, evidence: FertilizerPrescription,
                       required_notices: list[str] | None = None) -> str:
    if check_explanation(answer, evidence, required_notices):
        raise ValueError('EXPLANATION_CONFLICT')
    lines = [f'{evidence.address} / {evidence.crop_name}',
             f'PNU: {answer.pnu_code}, 조회 상태: {answer.status}']
    # Render canonical tool values after validation, not alternate model spellings.
    values = {name: str(amount.value) if amount.value is not None else None
              for name, amount in evidence.amounts.items()}
    for label, prefix in [('밑거름', 'basal'), ('웃거름', 'topdressing')]:
        if all(prefix + '_' + nutrient in values for nutrient in ('n', 'p', 'k')):
            amounts = [values[prefix + '_' + nutrient] for nutrient in ('n', 'p', 'k')]
            lines.append(label + ' 질소/인산/칼리: ' + ' / '.join(
                value if value is not None else '자료 없음' for value in amounts) + ' kg/10a')
    compost_labels = [('compost_cattle', '우분'), ('compost_pig', '돈분'),
                      ('compost_chicken', '계분'), ('compost_mix', '혼합')]
    for field, label in compost_labels:
        if field in values:
            lines.append(f'{label} 퇴비: {values[field] if values[field] is not None else "자료 없음"} kg/10a')
    lines.extend(['농촌진흥청 API가 반환한 처방이며 적용 적합성은 아직 검토하지 않았습니다.',
                  '실제 재배 작물과 토양검정 일자는 미확인입니다. 조회 시각은 검정 일자가 아닙니다.',
                  '관수 판단에 필요한 수분 데이터는 포함되어 있지 않습니다.',
                  f'출처: {evidence.source_record} (SHA-256: {answer.source_sha256})',
                  f'자료 조회 시각: {evidence.retrieved_at.isoformat()}'])
    return '\n'.join(lines)
