"""Normalize a saved provider prescription without inventing soil observations."""
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Literal
import xml.etree.ElementTree as ET

from pydantic import AwareDatetime, Field
from .schemas import Contract

ROOT = Path(__file__).resolve().parents[2]
ENDPOINT = 'https://apis.data.go.kr/1390802/SoilEnviron/FrtlzrUse/getSoilFrtlzrExamInfo'
FIELDS = {
    'basal_n': 'pre_Fert_N', 'basal_p': 'pre_Fert_P', 'basal_k': 'pre_Fert_K',
    'topdressing_n': 'post_Fert_N', 'topdressing_p': 'post_Fert_P',
    'topdressing_k': 'post_Fert_K', 'compost_cattle': 'pre_Compost_Cattl',
    'compost_pig': 'pre_Compost_Pig', 'compost_chicken': 'pre_Compost_Chick',
    'compost_mix': 'pre_Compost_Mix',
}


class FertilizerAmount(Contract):
    value: Decimal | None = Field(default=None, ge=0)
    unit: Literal['kg/10a'] = 'kg/10a'
    provider_field: str


class FertilizerPrescription(Contract):
    schema_version: Literal['1.0'] = '1.0'
    pnu_code: str = Field(pattern=r'^[0-9]{19}$')
    requested_crop_code: str = Field(pattern=r'^[0-9]{5}$')
    address: str | None = None
    crop_name: str | None = None
    status: Literal['available', 'incomplete', 'no_data', 'provider_error']
    http_status: int | None = None
    service_code: str | None = None
    service_message: str | None = None
    amounts: dict[str, FertilizerAmount] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    retrieved_at: AwareDatetime
    source_record: str
    source_sha256: str
    provider_endpoint: Literal[ENDPOINT] = ENDPOINT
    unit_reference: str = 'data/OPEN API기술명세서_비료사용처방 정보.pdf'
    result_origin: Literal['provider_prescription'] = 'provider_prescription'
    soil_tested_at: None = None
    actual_crop_confirmed: Literal[False] = False
    applicability_status: Literal['not_reviewed'] = 'not_reviewed'


def normalize_fertilizer(raw: bytes, source_record: str, *,
                         expected_pnu: str, expected_crop: str) -> FertilizerPrescription:
    """Validate request/response identity, preserve missing values and provider failures.

    Retrieval time is not the unknown soil examination time. Provider calculations
    are not independent ground truth or locally evaluated fertilizer rules.
    """
    record = json.loads(raw.decode('utf-8-sig'))
    params = record['parameters']
    if params.get('PNU_Code') != expected_pnu or params.get('crop_Code') != expected_crop:
        raise ValueError('REQUEST_IDENTITY_MISMATCH')
    if record.get('endpoint') != ENDPOINT:
        raise ValueError('UNSUPPORTED_PROVIDER_ENDPOINT')
    result = dict(pnu_code=expected_pnu, requested_crop_code=expected_crop,
                  http_status=record.get('http_status'), retrieved_at=record['retrieved_at'],
                  source_record=source_record, source_sha256=hashlib.sha256(raw).hexdigest())
    if record.get('http_status') != 200:
        return FertilizerPrescription(status='provider_error', **result)
    try:
        tree = ET.fromstring(record['body'])
    except (KeyError, TypeError, ET.ParseError) as exc:
        raise ValueError('INVALID_PROVIDER_XML') from exc
    code = tree.findtext('./header/result_Code')
    result.update(service_code=code, service_message=tree.findtext('./header/result_Msg'))
    if code != '200':
        return FertilizerPrescription(status='no_data' if code == '301' else 'provider_error', **result)
    items = tree.findall('./body/items/item')
    if len(items) != 1:
        raise ValueError('EXPECTED_ONE_PRESCRIPTION')
    item = items[0]
    if item.findtext('pnu_Code') != expected_pnu or item.findtext('crop_Code') != expected_crop:
        raise ValueError('RESPONSE_IDENTITY_MISMATCH')
    amounts, missing = {}, []
    for name, provider_field in FIELDS.items():
        text = item.findtext(provider_field)
        value = None
        if text is None or not text.strip():
            missing.append(provider_field)
        else:
            try:
                value = Decimal(text.strip())
            except InvalidOperation as exc:
                raise ValueError('INVALID_PROVIDER_AMOUNT') from exc
            if not value.is_finite() or value < 0:
                raise ValueError('INVALID_PROVIDER_AMOUNT')
        amounts[name] = FertilizerAmount(value=value, provider_field=provider_field)
    return FertilizerPrescription(status='incomplete' if missing else 'available',
                                 address=item.findtext('addr'), crop_name=item.findtext('crop_Nm'),
                                 amounts=amounts, missing_fields=missing, **result)


def load_selected_prescription(pnu_code: str | None = None,
                               crop_code: str | None = None) -> FertilizerPrescription:
    config = json.loads((ROOT / 'configs/data_sources.json').read_text(encoding='utf-8'))['fertilizer']
    if pnu_code is not None and pnu_code != config['default_pnu_code']:
        raise ValueError('PRESCRIPTION_NOT_FOUND')
    if crop_code is not None and crop_code != config['crop_code']:
        raise ValueError('PRESCRIPTION_NOT_FOUND')
    path = (ROOT / config['record_path']).resolve()
    if not path.is_relative_to(ROOT / 'data/references/fertilizer'):
        raise ValueError('INVALID_RECORD_PATH')
    return normalize_fertilizer(path.read_bytes(), config['record_path'],
                                expected_pnu=config['default_pnu_code'], expected_crop=config['crop_code'])
