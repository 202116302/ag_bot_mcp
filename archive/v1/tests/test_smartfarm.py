import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
import requests

from agri_dss.cli import main
from agri_dss.smartfarm import (SNAPSHOT_ID, SmartfarmClient, business_rows,
                                load_environment_snapshot, normalize_environment, read_smartfarm_key)


def record(value='0'):
    return {'http_status': 200, 'retrieved_at': '2026-11-16T00:00:00+00:00', 'body': json.dumps([
        {'statusCode': '00', 'facilityId': 'TEST_01', 'itemCode': '080300', 'fldCode': 'FG',
         'sectCode': 'EI', 'fatrCode': 'TI', 'measDate': '2023-07-25 00:00:00', 'senVal': value}])}


def normalize(raw):
    return normalize_environment(raw, facility_id='TEST_01', day='2023-07-25', code='TI', source_record='test.json')


def test_key_alias_from_dotenv_and_environment_priority(monkeypatch, tmp_path):
    monkeypatch.setattr('agri_dss.smartfarm.ROOT', tmp_path)
    for name in ('SMARTFARM_API_KEY', 'smartfarm_data'):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match='MISSING'):
        read_smartfarm_key()
    (tmp_path / '.env').write_text('smartfarm_data="test-local-only"\n', encoding='utf-8')
    assert read_smartfarm_key() == ('test-local-only', '.env:smartfarm_data')
    monkeypatch.setenv('SMARTFARM_API_KEY', 'test-env-only')
    assert read_smartfarm_key() == ('test-env-only', 'environment:SMARTFARM_API_KEY')


def test_client_redacts_encoded_and_decoded_key_and_does_not_follow_redirects(monkeypatch):
    captured = {}
    def get(url, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status_code=200, text='echo secret%2Fonly and secret/only')
    monkeypatch.setattr('agri_dss.smartfarm.requests.get', get)
    raw = SmartfarmClient('secret%2Fonly').fetch('getIdentityDataList')
    saved = json.dumps(raw)
    assert 'secret' not in saved
    assert '[REDACTED]' in saved
    assert '{serviceKey}' in raw['endpoint_template']
    assert captured['allow_redirects'] is False


def test_network_exception_details_are_not_saved(monkeypatch):
    def get(*args, **kwargs):
        raise requests.ConnectionError('credential-bearing-secret-url')
    monkeypatch.setattr('agri_dss.smartfarm.requests.get', get)
    raw = SmartfarmClient('test-only').fetch('getIdentityDataList')
    assert raw['error_code'] == 'SMARTFARM_NETWORK_ERROR'
    assert 'credential-bearing' not in json.dumps(raw)


@pytest.mark.parametrize('value,expected', [('0', '0'), (None, None), ('', None), ('-3.5', '-3.5')])
def test_numbers_preserve_zero_missing_and_negative_temperature(value, expected):
    result = normalize(record(value))
    assert result['observations'][0]['value'] == expected
    assert result['unit'] is None
    assert result['observations'][0]['timezone'] is None
    assert result['status'] == ('incomplete' if expected is None else 'available')


@pytest.mark.parametrize('value', ['NaN', 'Infinity', 'invalid', True])
def test_invalid_numbers_are_not_measurements(value):
    with pytest.raises(ValueError, match='INVALID_NUMBER'):
        normalize(record(value))


@pytest.mark.parametrize('field,value', [('facilityId', 'OTHER'), ('itemCode', '080600'),
                                        ('fldCode', 'OTHER'), ('sectCode', 'EO'), ('fatrCode', 'HI')])
def test_mixed_identity_or_environment_category_rejected(field, value):
    raw = record()
    rows = json.loads(raw['body'])
    rows[0][field] = value
    raw['body'] = json.dumps(rows)
    with pytest.raises(ValueError, match='IDENTITY_MISMATCH'):
        normalize(raw)


@pytest.mark.parametrize('kind', ['wrong_day', 'duplicate'])
def test_wrong_day_and_duplicate_times_rejected(kind):
    raw = record()
    rows = json.loads(raw['body'])
    if kind == 'wrong_day':
        rows[0]['measDate'] = '2023-07-26 00:00:00'
    else:
        rows.append(deepcopy(rows[0]))
    raw['body'] = json.dumps(rows)
    with pytest.raises(ValueError, match='WRONG_DAY_OR_DUPLICATE'):
        normalize(raw)


def test_business_no_data_and_http_failures_do_not_become_zero_values():
    raw = record()
    raw['body'] = '[{"statusCode":"03"}]'
    result = normalize(raw)
    assert result['status'] == 'no_data'
    assert result['observations'] == []
    raw['http_status'] = 403
    assert normalize(raw)['status'] == 'provider_error'
    raw = record()
    rows = json.loads(raw['body'])
    rows.append({'statusCode': '30'})
    raw['body'] = json.dumps(rows)
    with pytest.raises(ValueError, match='SERVICE_ERROR'):
        business_rows(raw)


def test_saved_real_snapshot_sources_and_cli(monkeypatch, capsys):
    snapshot = load_environment_snapshot()
    assert snapshot['date'] == '2023-07-25'
    assert snapshot['fertilizer_parcel_link'] == 'not_established'
    for code in ('TI', 'HI', 'CI'):
        assert snapshot['fields'][code]['record_count'] == 24
        assert snapshot['fields'][code]['unit'] is None
    assert snapshot['fields']['HI02']['status'] == 'no_data'
    monkeypatch.setattr('sys.argv', ['agri-dss', 'environment'])
    assert main() == 0
    text = capsys.readouterr().out
    assert '2023-07-25' in text
    assert '32.33' in text
    assert '단위 미확인' in text
    with pytest.raises(ValueError, match='NOT_FOUND'):
        load_environment_snapshot('../API_key.txt')


def test_modified_saved_values_are_detected(monkeypatch, tmp_path):
    snapshot = load_environment_snapshot()
    snapshot['fields']['TI']['observations'][0]['value'] = '999'
    path = tmp_path / 'snapshot.json'
    path.write_text(json.dumps(snapshot), encoding='utf-8')
    monkeypatch.setattr('agri_dss.smartfarm.SNAPSHOT_PATH', path)
    with pytest.raises(ValueError, match='SOURCE_MISMATCH'):
        load_environment_snapshot()


def test_real_mcp_can_read_only_registered_environment_snapshot():
    pytest.importorskip('mcp')
    import sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from agri_dss.smartfarm import ROOT

    async def call():
        params = StdioServerParameters(command=sys.executable, args=['-m', 'agri_dss.mcp_server'], cwd=str(ROOT),
                                      env={'PYTHONPATH': str(ROOT / 'src'), 'PYTHONIOENCODING': 'utf-8'})
        async with asyncio.timeout(30):
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    result = await session.call_tool('get_environment_data', {'snapshot_id': SNAPSHOT_ID})
                    blocked = await session.call_tool('get_environment_data', {'snapshot_id': '../API_key.txt'})
                    return result, blocked

    result, blocked = asyncio.run(call())
    assert not result.isError
    assert result.structuredContent['fields']['TI']['record_count'] == 24
    assert blocked.isError
