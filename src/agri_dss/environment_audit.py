"""Independent audit of saved provider records; never calls the app normalizer."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json

from .fertilizer import ROOT


def audit_environment(snapshot, expected_fields, *, root=ROOT):
    result = {'snapshot_id': snapshot['snapshot_id'], 'date': snapshot['date'], 'fields': {},
              'interpretation': 'raw_record_integrity_and_reference_audit_not_unit_confirmation'}
    for code, field in snapshot['fields'].items():
        errors, values, timestamps, rows = [], [], [], []
        source = (root / field['source_record']).resolve()
        if not source.is_relative_to(root / 'data/references/smartfarm'):
            raise ValueError('AUDIT_SOURCE_PATH_OUTSIDE_REGISTERED_DIRECTORY')
        raw_bytes = source.read_bytes()
        raw = json.loads(raw_bytes)
        canonical_hash = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if canonical_hash != field['source_sha256']:
            errors.append('source_hash_mismatch')
        expected_args = [snapshot['facility_id'], snapshot['date'], 'FG', 'EI', code, '080300']
        if raw.get('operation') != 'getEnvDataList' or raw.get('arguments') != expected_args:
            errors.append('request_identity_mismatch')
        data = json.loads(raw['body'])
        if (raw.get('http_status') != 200 or not isinstance(data, list) or not data or
                any(not isinstance(row, dict) for row in data)):
            errors.append('http_or_response_shape_error')
        else:
            statuses = {str(row['statusCode']) for row in data if row.get('statusCode') is not None}
            if statuses == {'03'}:
                status = 'no_data'
            elif statuses == {'00'}:
                rows = data
                status = 'available'
            else:
                status = 'provider_error'
                errors.append('business_status_error')
        if errors and not rows:
            status = 'provider_error'
        records = []
        for row in rows:
            if any(str(row.get(key)) != value for key, value in (
                ('facilityId', snapshot['facility_id']), ('itemCode', '080300'),
                ('fldCode', 'FG'), ('sectCode', 'EI'), ('fatrCode', code))):
                errors.append('response_identity_mismatch')
            stamp = row.get('measDate')
            try:
                parsed = datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S')
                timestamps.append(parsed)
                if parsed.date().isoformat() != snapshot['date']:
                    errors.append('wrong_day')
            except (TypeError, ValueError):
                errors.append('invalid_timestamp')
            value = row.get('senVal')
            number = None
            if value is not None and str(value).strip():
                try:
                    number = Decimal(str(value).strip())
                    if not number.is_finite():
                        raise InvalidOperation
                    values.append(number)
                except InvalidOperation:
                    errors.append('invalid_number')
                    number = None
            records.append((stamp, str(number) if number is not None else None))
        if len(set(timestamps)) != len(timestamps):
            errors.append('duplicate_timestamp')
        missing = len(rows) - len(values)
        if rows and missing:
            status = 'incomplete'
        computed = {'status': status, 'record_count': len(rows),
                    'minimum': str(min(values)) if values else None,
                    'maximum': str(max(values)) if values else None}
        reference = expected_fields[code]
        for key, expected in reference.items():
            actual = computed[key]
            equal = actual == expected
            if key in ('minimum', 'maximum') and actual is not None and expected is not None:
                equal = Decimal(actual) == Decimal(expected)
            if not equal:
                errors.append('reference_' + key + '_mismatch')
        normalized = [(row['measured_at'], row['value']) for row in field['observations']]
        if sorted(records, key=lambda row: (str(row[0]), row[1] or '')) != sorted(normalized, key=lambda row: (str(row[0]), row[1] or '')):
            errors.append('raw_normalized_record_mismatch')
        if field.get('unit') is not None:
            errors.append('unconfirmed_unit_was_assigned')
        stamps = sorted(timestamps)
        intervals = sorted({int((b-a).total_seconds()) for a, b in zip(stamps, stamps[1:])})
        result['fields'][code] = dict(computed, passed=not errors, errors=sorted(set(errors)),
            missing_values=missing, duplicate_timestamps=len(stamps)-len(set(stamps)),
            first_timestamp=stamps[0].isoformat(sep=' ') if stamps else None,
            last_timestamp=stamps[-1].isoformat(sep=' ') if stamps else None,
            observed_wall_clock_intervals_seconds=intervals,
            timestamp_interpretation='naive_record_spacing_not_sensor_frequency_or_hourly_average',
            unit_confirmed=False, timezone_confirmed=False, aggregation_confirmed=False,
            source_record=field['source_record'], source_file_sha256=hashlib.sha256(raw_bytes).hexdigest(),
            source_canonical_sha256=canonical_hash)
    result['passed'] = all(field['passed'] for field in result['fields'].values())
    return result
