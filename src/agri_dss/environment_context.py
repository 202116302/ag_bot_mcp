"""Reviewed tomato excerpts and historical environment lookup, without control rules."""
from decimal import Decimal
import hashlib
import json

from .fertilizer import ROOT
from .smartfarm import load_environment_snapshot

CATALOG_PATH = ROOT / 'data/references/tomato_environment.json'
TOPICS = ('temperature', 'humidity', 'co2')
TOPIC_CODES = {'temperature': ('TI',), 'humidity': ('HI', 'HI02'), 'co2': ('CI',)}
LIMITATIONS = ['historical_only', 'units_unconfirmed', 'timezone_unconfirmed',
               'aggregation_unknown', 'cultivar_stage_unknown',
               'not_linked_to_fertilizer_parcel', 'no_control_decision']
LIMIT_TEXT = {
    'historical_only': '이 자료는 과거 기록이며 현재 온실 상태가 아닙니다.',
    'units_unconfirmed': 'API 측정값의 단위가 미확인이라 문헌 단위와 직접 비교하지 않습니다.',
    'timezone_unconfirmed': '시각의 시간대가 미확인이라 오전·오후·야간 문헌 기준에 자동 대응시키지 않습니다.',
    'aggregation_unknown': '원시 측정값의 집계 방식은 미확인입니다.',
    'cultivar_stage_unknown': '품종·생육단계가 미확인이라 문헌의 적용 조건을 확정하지 않았습니다.',
    'humidity_semantics_unconfirmed': 'HI를 상대습도로 단정하지 않으며 HI02 자료 없음은 별도로 보존합니다.',
    'not_linked_to_fertilizer_parcel': '이 환경시설과 기존 비료 필지의 연결은 확인하지 않았습니다.',
    'no_control_decision': '환기·난방 등 설비 제어와 환경 적합성 판단은 보류합니다.',
    'co2_source_review_required': 'CO₂ 문단의 단위 병기·상한 설명은 추가 검토가 필요해 자동 수치 기준으로 사용하지 않습니다.'}


def context_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_catalog():
    catalog = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    source = (ROOT / catalog['source_document']).resolve()
    if source != (ROOT / 'data/29 토마토_저화질_단면.pdf').resolve():
        raise ValueError('UNREGISTERED_LITERATURE_DOCUMENT')
    if hashlib.sha256(source.read_bytes()).hexdigest() != catalog['source_sha256']:
        raise ValueError('LITERATURE_DOCUMENT_CHANGED')
    ids = set()
    for chunk in catalog['chunks']:
        if chunk['chunk_id'] in ids or hashlib.sha256(chunk['text'].encode()).hexdigest() != chunk['text_sha256']:
            raise ValueError('LITERATURE_CHUNK_CHANGED_OR_DUPLICATED')
        ids.add(chunk['chunk_id'])
    return catalog


def retrieve_chunks(catalog, topics, tomato_type):
    return [dict(chunk, source_document=catalog['source_document'], source_sha256=catalog['source_sha256'])
            for chunk in catalog['chunks'] if chunk['topic'] in topics and
            (tomato_type == 'unspecified' or chunk['tomato_type'] in ('unspecified', tomato_type))]


def build_environment_context(snapshot_id, topics, tomato_type='unspecified'):
    if (not topics or len(set(topics)) != len(topics) or not set(topics) <= set(TOPICS) or
            tomato_type not in ('unspecified', 'general', 'cherry')):
        raise ValueError('UNSUPPORTED_ENVIRONMENT_SELECTION')
    snapshot, catalog = load_environment_snapshot(snapshot_id), load_catalog()
    topics = [topic for topic in TOPICS if topic in topics]
    fields = []
    for topic in topics:
        for code in TOPIC_CODES[topic]:
            field = snapshot['fields'][code]
            values = [Decimal(row['value']) for row in field['observations'] if row['value'] is not None]
            fields.append({'code': code, 'status': field['status'], 'record_count': len(field['observations']),
                           'minimum': str(min(values)) if values else None,
                           'maximum': str(max(values)) if values else None, 'unit': None,
                           'source_sha256': field['source_sha256']})
    chunks = retrieve_chunks(catalog, topics, tomato_type)
    if any(not any(chunk['topic'] == topic for chunk in chunks) for topic in topics):
        raise ValueError('LITERATURE_TOPIC_NOT_FOUND')
    limitations = (LIMITATIONS + (['humidity_semantics_unconfirmed'] if 'humidity' in topics else []) +
                   (['co2_source_review_required'] if 'co2' in topics else []))
    context = {'snapshot_id': snapshot['snapshot_id'], 'facility_id': snapshot['facility_id'],
               'observation_date': snapshot['date'], 'snapshot_sha256': context_digest(snapshot),
               'document_sha256': catalog['source_sha256'], 'topics': topics, 'tomato_type': tomato_type,
               'fields': fields, 'literature': chunks, 'limitations': limitations,
               'assessment': 'deferred_units_and_applicability'}
    context['evidence_sha256'] = context_digest(context)
    return context
