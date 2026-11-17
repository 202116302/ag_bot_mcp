"""Smartfarm Data Mart PROVIDE client; no direct sensor connection."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from urllib.parse import quote, unquote

import requests

from .fertilizer import ROOT

BASE = 'https://www.smartfarmkorea.net/Agree_WS/webservices/ProvideRestService'
KEY_NAMES = ('SMARTFARM_API_KEY', 'smartfarm_data')
ENV_CODES = {'TI': '내부온도', 'HI': '내부습도', 'HI02': '내부 상대습도', 'CI': '내부CO2'}
SNAPSHOT_ID = 'SMARTFARM-PFS_0000001_01-20230725'
SNAPSHOT_PATH = ROOT / 'data/snapshots/smartfarm_environment_20230725.json'


def read_smartfarm_key():
    for name in KEY_NAMES:
        if os.getenv(name, '').strip():
            return os.environ[name].strip(), 'environment:' + name
    path = ROOT / '.env'
    values = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            name, sep, value = line.strip().partition('=')
            if sep and name.strip() in KEY_NAMES:
                values[name.strip()] = value.strip().strip('\"\'')
    for name in KEY_NAMES:
        if values.get(name):
            return values[name], '.env:' + name
    raise ValueError('SMARTFARM_API_KEY_MISSING')


def business_rows(record):
    if record.get('http_status') != 200:
        raise ValueError('SMARTFARM_HTTP_OR_NETWORK_ERROR')
    try:
        rows = json.loads(record['body'])
    except (KeyError, ValueError, TypeError):
        raise ValueError('SMARTFARM_INVALID_JSON') from None
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError('SMARTFARM_EMPTY_OR_INVALID_RESPONSE')
    codes = {str(row['statusCode']) for row in rows if row.get('statusCode') is not None}
    if codes == {'03'}:
        raise ValueError('SMARTFARM_NO_DATA')
    if codes != {'00'}:
        raise ValueError('SMARTFARM_SERVICE_ERROR')
    return rows


class SmartfarmClient:
    def __init__(self, key):
        self.key = key
        self.encoded_key = quote(unquote(key), safe='')
        self.secrets = sorted({key, unquote(key), self.encoded_key}, key=len, reverse=True)

    def redact(self, text):
        for secret in self.secrets:
            if secret:
                text = text.replace(secret, '[REDACTED]')
        return text

    def fetch(self, operation, *arguments):
        if operation not in ('getIdentityDataList', 'getCroppingSeasonDataList', 'getEnvDataList'):
            raise ValueError('UNSUPPORTED_SMARTFARM_OPERATION')
        # Records store a template, never the credential-bearing request URL.
        record = {'operation': operation, 'retrieved_at': datetime.now().astimezone().isoformat(),
                  'endpoint_template': BASE + '/' + operation + '/{serviceKey}',
                  'arguments': list(arguments)}
        url = BASE + '/' + operation + '/' + self.encoded_key
        if arguments:
            url += '/' + '/'.join(quote(str(value), safe='') for value in arguments)
        try:
            response = requests.get(url, timeout=(8, 25), allow_redirects=False)
            response.encoding = 'utf-8'
            record.update(http_status=response.status_code, body=self.redact(response.text))
        except requests.RequestException:
            record.update(error_code='SMARTFARM_NETWORK_ERROR')
        return record


def normalize_environment(record, *, facility_id, day, code, source_record):
    """Preserve raw numbers and unknown units; refuse mixed facility/date/field data."""
    if code not in ENV_CODES:
        raise ValueError('UNSUPPORTED_ENVIRONMENT_CODE')
    result = {'facility_id': facility_id, 'date': day, 'item_code': '080300', 'field_code': 'FG',
              'section_code': 'EI', 'attribute_code': code, 'attribute_name': ENV_CODES[code],
              'unit': None, 'unit_status': 'not_declared_by_api_contract', 'observations': [],
              'source_record': source_record,
              'source_sha256': hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
              'source_hash_scope': 'canonical_saved_record', 'retrieved_at': record['retrieved_at']}
    try:
        rows = business_rows(record)
    except ValueError as exc:
        result.update(status='no_data' if str(exc) == 'SMARTFARM_NO_DATA' else 'provider_error', error_code=str(exc))
        return result
    times = set()
    for row in rows:
        if any(str(row.get(key)) != expected for key, expected in (
                ('facilityId', facility_id), ('itemCode', '080300'), ('fldCode', 'FG'),
                ('sectCode', 'EI'), ('fatrCode', code))):
            raise ValueError('SMARTFARM_ENVIRONMENT_IDENTITY_MISMATCH')
        timestamp = row.get('measDate')
        try:
            parsed = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            raise ValueError('SMARTFARM_INVALID_TIMESTAMP') from None
        if parsed.date().isoformat() != day or timestamp in times:
            raise ValueError('SMARTFARM_WRONG_DAY_OR_DUPLICATE')
        times.add(timestamp)
        raw_value = row.get('senVal')
        value = None
        if raw_value is not None and str(raw_value).strip():
            try:
                numeric = Decimal(str(raw_value).strip())
            except InvalidOperation:
                raise ValueError('SMARTFARM_INVALID_NUMBER') from None
            if not numeric.is_finite():
                raise ValueError('SMARTFARM_INVALID_NUMBER')
            value = str(numeric)
        result['observations'].append({'measured_at': timestamp, 'timezone': None,
                                       'raw_value': raw_value, 'value': value,
                                       'standard_category': row.get('standardCategory'),
                                       'standard_element': row.get('standardElement'),
                                       'standard_type': row.get('standardType')})
    result['observations'].sort(key=lambda row: row['measured_at'])
    result.update(status='incomplete' if any(row['value'] is None for row in result['observations']) else 'available',
                  record_count=len(rows),
                  missing_count=sum(row['value'] is None for row in result['observations']))
    return result


def load_environment_snapshot(snapshot_id=SNAPSHOT_ID):
    """Read only the registered historical snapshot and verify its source records."""
    if snapshot_id != SNAPSHOT_ID:
        raise ValueError('ENVIRONMENT_SNAPSHOT_NOT_FOUND')
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding='utf-8'))
    if snapshot['snapshot_id'] != snapshot_id:
        raise ValueError('ENVIRONMENT_SNAPSHOT_ID_MISMATCH')
    for code, field in snapshot['fields'].items():
        source = (ROOT / field['source_record']).resolve()
        if not source.is_relative_to(ROOT / 'data/references/smartfarm'):
            raise ValueError('INVALID_ENVIRONMENT_SOURCE_PATH')
        raw = json.loads(source.read_text(encoding='utf-8'))
        expected = normalize_environment(raw, facility_id=snapshot['facility_id'], day=snapshot['date'],
                                         code=code, source_record=field['source_record'])
        if expected != field:
            raise ValueError('ENVIRONMENT_SOURCE_MISMATCH')
    return snapshot


def describe_environment(snapshot):
    lines = [f"스마트팜 데이터마트 과거 자료: {snapshot['date']} / {snapshot['facility_id']}",
             '단위·집계 방식·시간대는 미확인입니다. 현재 농장 상태나 제어 지시를 뜻하지 않습니다.']
    for code, field in snapshot['fields'].items():
        values = [Decimal(row['value']) for row in field['observations'] if row['value'] is not None]
        label = ENV_CODES[code]
        if values:
            lines.append(f'{label} ({code}): {len(values)}건, 원시 최솟값 {min(values)}, 최댓값 {max(values)} (단위 미확인)')
        else:
            lines.append(f"{label} ({code}): {field['status']}")
    return '\n'.join(lines)
