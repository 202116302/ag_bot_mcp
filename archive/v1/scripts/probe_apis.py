"""Small read-only connectivity probes. Never print credential-bearing URLs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, quote
import json
import re
import argparse
import os
import xml.etree.ElementTree as ET
import requests

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--discover', action='store_true')
    modes.add_argument('--sample', action='store_true')
    modes.add_argument('--sensors', action='store_true')
    modes.add_argument('--fertilizer-example', action='store_true')
    modes.add_argument('--fertilizer-jeonbuk', action='store_true',
                       help='Probe at most six publicly listed Wanju parcels, both code prefixes and two crops')
    modes.add_argument('--fertilizer-code', help='Probe one supplied code verbatim without changing the default PNU')
    args = parser.parse_args()
    keys = [os.getenv('FERTILIZER_API_KEY'), os.getenv('SMARTFARM_API_KEY')]
    if not all(keys):
        content = (ROOT / 'data/API_key.txt').read_text(encoding='utf-8-sig')
        file_keys = re.findall(r'인증키\s*[:：]\s*(\S+)', content)
        keys = [keys[i] or file_keys[i] for i in range(2)] if len(file_keys) == 2 else []
    if len(keys) != 2:
        raise SystemExit('Expected two labeled credentials; no values printed.')
    config = json.loads((ROOT / 'configs/data_sources.json').read_text(encoding='utf-8'))
    pnu = config['fertilizer']['default_pnu_code']
    secrets = {value for key in keys for value in (key, unquote(key), quote(unquote(key), safe=''))}

    def redact(value):
        for secret in sorted(secrets, key=len, reverse=True):
            value = value.replace(secret, '[REDACTED]')
        return value

    def fetch(job):
        name, url, params = job
        record = {'probe': name, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                  'endpoint': redact(url),
                  'parameters': {k:v for k,v in (params or {}).items() if k != 'serviceKey'}}
        try:
            response = requests.get(url, params=params, timeout=(8, 20), allow_redirects=False)
            response.encoding = 'utf-8'
            body = redact(response.text)
            record.update(http_status=response.status_code, content_type=response.headers.get('Content-Type'), body=body)
            try:
                data = response.json()
                # Only metadata is printed. Original body stays in local output.
                record['structure'] = list(data)[:20] if isinstance(data, dict) else {'records': len(data)} if isinstance(data, list) else type(data).__name__
                if isinstance(data, list):
                    record['tomato_records'] = sum(isinstance(x, dict) and str(x.get('itemCode')) in ('080300', '80300') for x in data)
                    if data and isinstance(data[0], dict) and 'statusCode' in data[0]:
                        record['service_status'] = {k:data[0].get(k) for k in ('statusCode', 'statusMessage')}
            except (ValueError, TypeError):
                try:
                    tree = ET.fromstring(body)
                    record['service_status'] = {x.tag.split('}')[-1]: x.text for x in tree.iter() if x.tag.split('}')[-1] in ('result_Code','result_Msg','returnReasonCode','returnAuthMsg','errMsg','resultCode','resultMsg')}
                except ET.ParseError:
                    record['parse_status'] = 'not_json_or_xml'
        except requests.RequestException as exc:
            record['error_type'] = type(exc).__name__
        return record

    jobs = [
        ('fertilizer_facility_tomato', 'https://apis.data.go.kr/1390802/SoilEnviron/FrtlzrUse/getSoilFrtlzrExamInfo', {'serviceKey': unquote(keys[0]), 'PNU_Code': pnu, 'crop_Code': config['fertilizer']['crop_code']}),
        ('smartfarm_identity', 'https://www.smartfarmkorea.net/Agree_WS/webservices/ProvideRestService/getIdentityDataList/' + quote(unquote(keys[1]), safe=''), None),
        ('weather_realtime', 'http://weather-rda.digitalag.kr:8001/api/kma/realtime/latest/pivot', {'region_name': '전주시', 'limit': 1}),
        ('weather_forecast', 'http://weather-rda.digitalag.kr:8001/api/kma/forecast/short/latest', {'region_name': '전주시', 'limit': 3}),
    ]
    if args.discover:
        base = 'https://www.smartfarmkorea.net/Agree_WS/webservices/ProvideRestService'
        prior = sorted((ROOT / 'outputs/api_probe').glob('*/smartfarm_identity.json'))
        identities = json.loads(json.loads(prior[-1].read_text(encoding='utf-8'))['body']) if prior else []
        tomatoes = [r for r in identities if r.get('itemCode') == '080300'][:3]
        jobs = [('weather_regions', 'http://weather-rda.digitalag.kr:8001/api/kma/realtime/regions', None),
                ('weather_sample', 'http://weather-rda.digitalag.kr:8001/api/kma/realtime/latest/pivot', {'limit': 1}),
                ('forecast_sample', 'http://weather-rda.digitalag.kr:8001/api/kma/forecast/short/latest', {'limit': 3})]
        for i, row in enumerate(tomatoes, 1):
            jobs.append((f'smartfarm_seasons_{i}', base + '/getCroppingSeasonDataList/' + quote(unquote(keys[1]), safe='') + '/' + quote(row['userId'], safe=''), None))
    if args.sample or args.sensors:
        prior = sorted((ROOT / 'outputs/api_probe').glob('*/smartfarm_seasons_1.json'))
        if not prior:
            raise SystemExit('Run --discover first.')
        seasons = json.loads(json.loads(prior[-1].read_text(encoding='utf-8'))['body'])
        season = max((s for s in seasons if s.get('croppingDate')), key=lambda s: s['croppingDate'])
        region = config['weather']['sample_region_name']
        jobs = [
            ('jeonju_weather', 'http://weather-rda.digitalag.kr:8001/api/kma/realtime/latest/pivot', {'region_name': region, 'limit': 1}),
            ('jeonju_forecast', 'http://weather-rda.digitalag.kr:8001/api/kma/forecast/short/latest', {'region_name': region, 'category': 'POP', 'limit': 3}),
            ('smartfarm_environment_page1', 'https://www.smartfarmkorea.net/Agree_WS/webservices/CropseasonRestService/getCroppingSeasonEnvDataList/' + quote(unquote(keys[1]), safe='') + '/' + str(season['croppingSerlNo']) + '/1', None),
        ]
        if args.sensors:
            ids_file = sorted((ROOT / 'outputs/api_probe').glob('*/smartfarm_identity.json'))[-1]
            identities = json.loads(json.loads(ids_file.read_text(encoding='utf-8'))['body'])
            facility = next(r for r in identities if r.get('itemCode') == '080300')['facilityId']
            date = season.get('croppingEndDate') or season['croppingDate']
            prefix = 'https://www.smartfarmkorea.net/Agree_WS/webservices/ProvideRestService/getEnvDataList/' + quote(unquote(keys[1]), safe='') + '/' + quote(facility, safe='') + '/' + date + '/FG/'
            jobs = [(f'smartfarm_sensor_{code}', prefix + section + '/' + code + '/080300', None)
                    for section, code in [('EI', 'TI'), ('EL', 'MC'), ('EL', 'MT')]]
    if args.fertilizer_example:
        base = 'https://apis.data.go.kr/1390802/SoilEnviron/FrtlzrUse'
        common = {'serviceKey': unquote(keys[0]), 'PNU_Code': '4571033027106720012',
                  'animix_Ratio_Cattl': 28, 'animix_Ratio_Pig': 22, 'animix_Ratio_Chick': 19}
        jobs = [
            ('fertilizer_example_rice', base + '/getSoilFrtlzrExamRiceInfo',
             {**common, 'crop_Code': '00001', 'rice_Qlt_Code': '1'}),
            ('fertilizer_example_facility_tomato', base + '/getSoilFrtlzrExamInfo',
             {**common, 'crop_Code': '04017'}),
        ]
    if args.fertilizer_code:
        if not args.fertilizer_code.isascii() or not args.fertilizer_code.isdigit():
            raise SystemExit('Code must contain ASCII digits only.')
        jobs = [('fertilizer_supplied_code',
                 'https://apis.data.go.kr/1390802/SoilEnviron/FrtlzrUse/getSoilFrtlzrExamInfo',
                 {'serviceKey': unquote(keys[0]), 'PNU_Code': args.fertilizer_code,
                  'crop_Code': config['fertilizer']['crop_code']})]
    discovery = []
    if args.fertilizer_jeonbuk:
        # Read the same public parcel selector used by the official website.
        # No invented parcel numbers: take at most two listed parcels per village.
        jobs = []
        for village in ('33027', '33029', '33031'):
            listing = fetch((f'jeonbuk_parcels_{village}',
                             'https://soil.rda.go.kr/sibi/sibiPrescriptProc.do',
                             {'mode': 'JIBN', 'sgg_cd': '52710', 'umd_cd': village,
                              'exam_type': '',
                              'exam_day_str': f'{datetime.now().year - 5}0101',
                              'exam_day_end': datetime.now().strftime('%Y%m%d')}))
            discovery.append(listing)
            if listing.get('http_status') != 200:
                continue
            options = re.findall(r'<option\s+value="([12]\d{8}),([1-9])"', listing.get('body', ''))
            # Selector returns nine-digit parcel suffixes; prepend the selected
            # five-digit county and five-digit village codes to form the PNU.
            chosen = []
            for land_type in ('3', '1'):
                match = next((suffix for suffix, kind in options
                              if kind == land_type and suffix not in chosen), None)
                if match:
                    chosen.append(match)
            codes = ['52710' + village + suffix for suffix in chosen]
            listing['selected_pnus'] = codes
            for code in codes:
                for prefix in ('52', '45'):
                    candidate = prefix + code[2:]
                    common = {'serviceKey': unquote(keys[0]), 'PNU_Code': candidate,
                              'animix_Ratio_Cattl': 28, 'animix_Ratio_Pig': 22,
                              'animix_Ratio_Chick': 19}
                    for crop, method in (('04017', 'getSoilFrtlzrExamInfo'),
                                         ('00001', 'getSoilFrtlzrExamRiceInfo')):
                        params = {**common, 'crop_Code': crop}
                        if crop == '00001':
                            params['rice_Qlt_Code'] = '1'
                        jobs.append((f'jeonbuk_{candidate}_{crop}',
                                     'https://apis.data.go.kr/1390802/SoilEnviron/FrtlzrUse/' + method,
                                     params))
    out = ROOT / 'outputs/api_probe' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out.mkdir(parents=True)
    with ThreadPoolExecutor(max_workers=2 if args.fertilizer_jeonbuk else 4) as pool:
        records = discovery + list(pool.map(fetch, jobs))
    for record in records:
        (out / (record['probe'] + '.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in record.items() if k not in ('body', 'endpoint', 'parameters')}, ensure_ascii=True))
    print('Saved redacted local results:', out.relative_to(ROOT))


if __name__ == '__main__':
    main()
