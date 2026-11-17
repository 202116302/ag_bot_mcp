"""Frozen multi-question delivery study with offline, raw-response scoring."""
import asyncio
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from agri_dss.assistant import digest, run_fertilizer_assistant
from agri_dss.fertilizer import ROOT, load_selected_prescription
from agri_dss.fertilizer_evaluation import score_run, same_value, summarize
from agri_dss.llm import load_llm_config

SCENARIOS = ROOT / 'configs/scenarios/fertilizer_delivery.json'


def verify_reference(reference):
    """Check fixed transcriptions against raw provider XML, not app-generated answers."""
    path = (ROOT / reference['source_record']).resolve()
    if not path.is_relative_to(ROOT / 'data/references/fertilizer'):
        raise ValueError('INVALID_REFERENCE_PATH')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference['source_sha256']:
        raise ValueError('REFERENCE_SOURCE_CHANGED')
    record = json.loads(raw)
    tree = ET.fromstring(record['body'])
    items = tree.findall('./body/items/item')
    if record['http_status'] != 200 or tree.findtext('./header/result_Code') != '200' or len(items) != 1:
        raise ValueError('REFERENCE_NOT_AVAILABLE')
    if (items[0].findtext('pnu_Code') != reference['pnu_code'] or
            items[0].findtext('crop_Code') != reference['crop_code']):
        raise ValueError('REFERENCE_IDENTITY_CHANGED')
    for name, value in reference['amounts'].items():
        raw_value = items[0].findtext(reference['provider_fields'][name])
        raw_value = raw_value.strip() if raw_value and raw_value.strip() else None
        if not same_value(raw_value, value):
            raise ValueError('REFERENCE_TRANSCRIPTION_MISMATCH')


def failed_log():
    return {'status': 'log_error', 'error_code': 'LOG_MISSING_OR_INVALID', 'manifest': {}, 'responses': []}


def analyze_delivery(output):
    protocol = json.loads((output / 'protocol.json').read_text(encoding='utf-8'))
    reference, cases = protocol['study']['reference'], protocol['study']['cases']
    rows, pairs = [], []
    artifact_errors = []
    if digest(protocol['study']) != protocol['study_snapshot_sha256']:
        artifact_errors.append('study_snapshot_changed')
    try:
        evidence_hash = digest(json.loads((output / 'evidence.json').read_text(encoding='utf-8')))
        if evidence_hash != protocol['pinned']['normalized_evidence_sha256']:
            artifact_errors.append('frozen_evidence_changed')
    except (OSError, ValueError):
        artifact_errors.append('frozen_evidence_missing_or_invalid')
    pin_fields = ('source_sha256', 'source_record', 'normalized_evidence_sha256', 'config',
                  'requested_model', 'provider', 'code_sha256')
    for trial in range(1, protocol['repeats'] + 1):
        for case in cases:
            runs, assessed = {}, {}
            for path in ('mcp', 'rag'):
                filename = f"{trial:02d}_{case['case_id']}_{path}.json"
                try:
                    run = json.loads((output / filename).read_text(encoding='utf-8'))
                    if not isinstance(run, dict) or not isinstance(run.get('manifest'), dict):
                        run = failed_log()
                    row = score_run(case, run, reference, path)
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    run = failed_log()
                    row = score_run(case, run, reference, path)
                manifest = run['manifest']
                condition_errors = [key for key in pin_fields if manifest.get(key) != protocol['pinned'][key]]
                condition_errors.extend(artifact_errors)
                if manifest.get('question_sha256') != digest(case['question']):
                    condition_errors.append('question_sha256')
                if manifest.get('evidence_path') != path:
                    condition_errors.append('evidence_path')
                row.update(trial=trial, file=filename, conditions_match=not condition_errors,
                           condition_errors=','.join(condition_errors))
                if condition_errors:
                    row['passed'] = False
                runs[path], assessed[path] = run, row
                rows.append(row)
            left, right = assessed['mcp'], assessed['rag']
            comparable = left['conditions_match'] and right['conditions_match']
            for key in ('answer_schema_sha256', 'routing'):
                a = runs['mcp']['manifest'].get(key) if key.endswith('sha256') else runs['mcp'].get(key)
                b = runs['rag']['manifest'].get(key) if key.endswith('sha256') else runs['rag'].get(key)
                comparable = comparable and a == b
            keys_exist = left['consistency_key'] is not None and right['consistency_key'] is not None
            pairs.append({'trial': trial, 'case_id': case['case_id'], 'kind': case['kind'],
                          'comparable': bool(comparable),
                          'raw_answers_equal': left['consistency_key'] == right['consistency_key']
                                               if comparable and keys_exist else None,
                          'both_passed': bool(comparable and left['passed'] and right['passed'])})
    summary = {'interpretation': 'provider_transcription_fidelity_not_agricultural_accuracy',
               'provider': protocol['provider'], 'repeats': protocol['repeats'],
               'case_count': len(cases), 'statistics': summarize(rows),
               'conditions_failed': sum(not row['conditions_match'] for row in rows),
               'all_passed': all(pair['both_passed'] for pair in pairs), 'pairs': pairs,
               'analysis_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'scorer_sha256': hashlib.sha256((ROOT / 'src/agri_dss/fertilizer_evaluation.py').read_bytes()).hexdigest()}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    public_rows = [{key: value for key, value in row.items() if key != 'consistency_key'} for row in rows]
    with (output / 'results.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(public_rows[0]))
        writer.writeheader()
        writer.writerows(public_rows)
    lines = ['# 비료 처방 전달·근거 추적 반복 평가', '',
             '관수는 이번 실험 범위에서 제외했다. 단일 필지·작물의 저장된 공급자 처방을 사용한다.',
             '평가 기준은 원본 XML과 대조한 고정 전사값이며 농업적 시비 정답이 아니다.',
             'RAG 검색은 문서 1개에 대한 정확한 PNU·작물 필터이며 일반 문헌 검색 성능을 평가하지 않는다.', '',
             f"- 공급자: {protocol['provider']}, 질문: {len(cases)}, 질문별 반복: {protocol['repeats']}",
             f"- 비교 조건 불일치 실행: {summary['conditions_failed']}", '',
             '| 경로 | 모델 시도 | 원시 수치 일치 | 원시 단위 일치 | 원시 식별·출처 일치 | 원시 한계 고지 일치 | 전달 검증 통과 | 로컬 보류 통과 |',
             '|---|---|---|---|---|---|---|---|']
    for path, stats in summary['statistics'].items():
        count = stats['model_attempted']
        values = [f"{stats[key]['passed']}/{count}" for key in (
            'raw_numeric_pass', 'raw_unit_pass', 'raw_identity_pass', 'raw_notices_pass', 'delivered_valid')]
        lines.append(f"| {path} | {count} | " + ' | '.join(values) +
                     f" | {stats['guard_passed']}/{stats['guard_attempted']} |")
    lines.extend(['', '원시 응답을 별도 검사하므로 런타임에서 차단된 오류도 측정한다. 실패·누락 로그는 분모에 남긴다.',
                  '원시 수치 일치는 10개 성분 전체의 정확한 Decimal 비교이며 0과 null을 구분한다.',
                  '원시 식별·출처 일치는 PNU·작물·상태·원본 해시를 검사한다. 도구/검색 기록의 출처 추적도 별도로 집계한다.',
                  '일관성은 원시 구조화 응답의 최빈 값 횟수 / 전체 시도이며, 일관되게 틀린 답변도 일관적일 수 있다.',
                  '로컬 보류는 모델 성능 분모에 포함하지 않는다. 기본 필지 치환 방지를 위한 별도 기능 검사다.',
                  '이 자료에는 비료량 결측이 없다. 실제 결측 비료량의 모델 처리 성능을 측정했다고 주장하지 않는다.',
                  '한계 고지는 구조화된 notice 항목의 보존이며 자유서술 전체의 사실성을 평가하지 않는다.',
                  '실행 조건이 바뀌면 all_passed=false다. 개별 원시 지표를 비교 가능한 연구 성능으로 해석하지 않는다.',
                  'Mock의 응답은 결정적 대역이다. 같은 자료에서의 소량 GPT 실행으로 일반적인 우열을 주장하지 않는다.', '',
                  'protocol.json·evidence.json·개별 원본 JSON을 보관한다. results.csv·summary.json은 --analyze로 재생성할 수 있다.'])
    (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return summary


async def run_delivery_suite(output, provider='mock', repeats=10, case_ids=None):
    if not 1 <= repeats <= 10:
        raise ValueError('REPEAT_LIMIT')
    study = json.loads(SCENARIOS.read_text(encoding='utf-8'))
    verify_reference(study['reference'])
    if case_ids:
        if len(set(case_ids)) != len(case_ids) or not set(case_ids) <= {case['case_id'] for case in study['cases']}:
            raise ValueError('INVALID_CASE_SELECTION')
        study['cases'] = [case for case in study['cases'] if case['case_id'] in case_ids]
    evidence, config = load_selected_prescription(), load_llm_config()
    if evidence.source_sha256 != study['reference']['source_sha256']:
        raise ValueError('SELECTED_EVIDENCE_CHANGED')
    output.mkdir(parents=True, exist_ok=True)
    protocol = {'version': '1.0', 'study': study, 'provider': provider, 'repeats': repeats,
                'study_snapshot_sha256': digest(study),
                'started_at': datetime.now(timezone.utc).isoformat(),
                'study_sha256': hashlib.sha256(SCENARIOS.read_bytes()).hexdigest(),
                'suite_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'scorer_sha256': hashlib.sha256((ROOT / 'src/agri_dss/fertilizer_evaluation.py').read_bytes()).hexdigest(),
                'pinned': {'source_sha256': evidence.source_sha256, 'source_record': evidence.source_record,
                           'normalized_evidence_sha256': digest(evidence.model_dump(mode='json')),
                           'config': config.model_dump(), 'provider': provider,
                           'requested_model': config.model if provider == 'openai' else 'mock-fertilizer-v1',
                           'code_sha256': {name: hashlib.sha256((ROOT / 'src/agri_dss' / name).read_bytes()).hexdigest()
                                           for name in ('assistant.py', 'rag.py', 'llm.py', 'explanation.py',
                                                        'fertilizer.py', 'mcp_server.py', 'routing.py')}}}
    (output / 'protocol.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (output / 'evidence.json').write_text(evidence.model_dump_json(indent=2) + '\n', encoding='utf-8')
    for trial in range(1, repeats + 1):
        for case in study['cases']:
            for path in (('mcp', 'rag') if trial % 2 else ('rag', 'mcp')):
                run = await run_fertilizer_assistant(provider, case['question'], path=path)
                filename = f"{trial:02d}_{case['case_id']}_{path}.json"
                (output / filename).write_text(json.dumps(run, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                print(f"{trial}/{repeats} {case['case_id']} {path}: {run['status']}", flush=True)
    return analyze_delivery(output)
