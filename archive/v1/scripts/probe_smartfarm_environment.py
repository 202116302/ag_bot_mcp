"""Bounded Data Mart probe: one tomato farm, latest completed season, one day.

At most six calls: identity, seasons, and TI/HI/HI02/CI. No retries, no weather,
no irrigation, and no joins with the selected fertilizer parcel.
"""
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from agri_dss.smartfarm import (ENV_CODES, SmartfarmClient, business_rows,
                               normalize_environment, read_smartfarm_key)


def main():
    key, key_source = read_smartfarm_key()
    client = SmartfarmClient(key)
    output = ROOT / 'outputs/smartfarm_environment' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True, exist_ok=True)
    calls = 0

    def fetch(name, operation, *args):
        nonlocal calls
        calls += 1
        record = client.fetch(operation, *args)
        path = output / (name + '.json')
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return record, path.relative_to(ROOT).as_posix()

    summary = {'key_source': key_source, 'call_limit': 6, 'interpretation': 'historical_data_mart_availability_check',
               'fertilizer_parcel_link': 'not_established', 'direct_sensor_connection': False,
               'unit_status': 'unconfirmed', 'fields': {}}
    try:
        identities, identity_path = fetch('identity', 'getIdentityDataList')
        tomatoes = [row for row in business_rows(identities) if row.get('itemCode') == '080300']
        if not tomatoes:
            raise ValueError('NO_TOMATO_FACILITY')
        selected = tomatoes[0]
        seasons, season_path = fetch('seasons', 'getCroppingSeasonDataList', selected['userId'])
        candidates = []
        for row in business_rows(seasons):
            if row.get('itemCode') != '080300' or not row.get('croppingDate') or not row.get('croppingEndDate'):
                continue
            start, end = date.fromisoformat(row['croppingDate']), date.fromisoformat(row['croppingEndDate'])
            if start <= end < date.today():
                candidates.append(row)
        if not candidates:
            raise ValueError('NO_COMPLETED_TOMATO_SEASON')
        season = max(candidates, key=lambda row: row['croppingEndDate'])
        day = season['croppingEndDate']
        summary.update(facility_id=selected['facilityId'], user_id=selected['userId'], date=day,
                       cropping_season_id=season['croppingSerlNo'], cropping_system_raw=season.get('croppingSystem'),
                       season_start=season['croppingDate'], season_end=day,
                       identity_source=identity_path, season_source=season_path,
                       selection_method='first_tomato_identity_latest_completed_season_end_day_not_representative')
        for code in ENV_CODES:
            raw, path = fetch('environment_' + code, 'getEnvDataList', selected['facilityId'], day, 'FG', 'EI', code, '080300')
            try:
                field = normalize_environment(raw, facility_id=selected['facilityId'], day=day, code=code, source_record=path)
            except ValueError as exc:
                field = {'status': 'invalid_data', 'error_code': str(exc), 'source_record': path}
            summary['fields'][code] = field
            print(json.dumps({'field': code, 'status': field['status'], 'records': field.get('record_count', 0)}, ensure_ascii=False), flush=True)
        summary['status'] = 'available' if any(field['status'] in ('available', 'incomplete') for field in summary['fields'].values()) else 'no_environment_data'
    except ValueError as exc:
        summary.update(status='probe_failed', error_code=str(exc))
    finally:
        summary['calls'] = calls
        (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('Report:', output / 'summary.json')
    return 0 if summary['status'] == 'available' else 1


if __name__ == '__main__':
    raise SystemExit(main())
