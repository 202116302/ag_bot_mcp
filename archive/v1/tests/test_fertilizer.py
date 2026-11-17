from decimal import Decimal
import hashlib
import json

import pytest

from agri_dss.fertilizer import ROOT, load_selected_prescription, normalize_fertilizer

PNU = '5271033027105280033'
SOURCE = ROOT / 'data/references/fertilizer/wanju_tomato_20261115.json'


def normalize(record):
    return normalize_fertilizer(json.dumps(record).encode(), 'test-record.json',
                                expected_pnu=PNU, expected_crop='04017')


@pytest.fixture
def record():
    return json.loads(SOURCE.read_text(encoding='utf-8'))


def test_real_saved_prescription_values_and_provenance():
    result = load_selected_prescription()
    assert result.pnu_code == PNU
    assert result.requested_crop_code == '04017'
    assert result.status == 'available'
    assert result.amounts['basal_n'].value == Decimal('14.4')
    assert result.amounts['topdressing_n'].value == Decimal('10.9')
    assert result.amounts['topdressing_k'].value == 0
    assert result.amounts['compost_mix'].value == 0
    assert all(amount.unit == 'kg/10a' for amount in result.amounts.values())
    assert result.source_sha256 == hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    assert result.retrieved_at.utcoffset().total_seconds() == 0
    assert result.soil_tested_at is None
    assert not result.actual_crop_confirmed
    assert result.result_origin == 'provider_prescription'


def test_missing_amount_is_not_zero(record):
    record['body'] = record['body'].replace('<post_Fert_K>0.0</post_Fert_K>', '')
    result = normalize(record)
    assert result.status == 'incomplete'
    assert result.amounts['topdressing_k'].value is None
    assert result.amounts['topdressing_p'].value == 0
    assert result.missing_fields == ['post_Fert_K']


@pytest.mark.parametrize('code,status', [('301', 'no_data'), ('201', 'provider_error'),
                                          ('401', 'provider_error')])
def test_provider_failure_never_yields_prescription(record, code, status):
    record['body'] = record['body'].replace('<result_Code>200', '<result_Code>' + code)
    result = normalize(record)
    assert result.status == status
    assert not result.amounts


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-1', 'invalid'])
def test_invalid_provider_amounts_rejected(record, value):
    record['body'] = record['body'].replace('<pre_Fert_N>14.4', '<pre_Fert_N>' + value)
    with pytest.raises(ValueError, match='INVALID_PROVIDER_AMOUNT'):
        normalize(record)


@pytest.mark.parametrize('target', ['parameters', 'body'])
def test_mismatched_parcel_rejected(record, target):
    if target == 'parameters':
        record['parameters']['PNU_Code'] = '5211110100100120003'
    else:
        record['body'] = record['body'].replace(PNU, '5211110100100120003')
    with pytest.raises(ValueError, match='IDENTITY_MISMATCH'):
        normalize(record)


def test_mismatched_crop_rejected(record):
    record['body'] = record['body'].replace('<crop_Code>04017', '<crop_Code>00001')
    with pytest.raises(ValueError, match='RESPONSE_IDENTITY_MISMATCH'):
        normalize(record)


def test_http_failure_does_not_parse_success_body(record):
    record['http_status'] = 503
    result = normalize(record)
    assert result.status == 'provider_error'
    assert not result.amounts


def test_malformed_xml_rejected(record):
    record['body'] = '<broken'
    with pytest.raises(ValueError, match='INVALID_PROVIDER_XML'):
        normalize(record)


@pytest.mark.parametrize('pnu,crop', [('../API_key.txt', '04017'), (PNU, '00001')])
def test_unregistered_inputs_rejected(pnu, crop):
    with pytest.raises(ValueError, match='PRESCRIPTION_NOT_FOUND'):
        load_selected_prescription(pnu, crop)
