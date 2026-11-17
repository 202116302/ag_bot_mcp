"""Frozen repeated environment/literature lookup study, with offline reanalysis."""
import argparse
import asyncio
from collections import Counter
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from agri_dss.environment_assistant import (EnvironmentAnswer, MCP_INSTRUCTIONS, RAG_INSTRUCTIONS,
                                           run_environment_assistant)
from agri_dss.environment_audit import audit_environment
from agri_dss.environment_context import CATALOG_PATH, build_environment_context, context_digest
from agri_dss.explanation import strict_schema
from agri_dss.fertilizer_evaluation import raw_answer
from agri_dss.llm import load_llm_config
from agri_dss.smartfarm import SNAPSHOT_PATH
from scripts.check_environment_qa import assess

SCENARIOS = ROOT / 'configs/scenarios/environment_qa.json'
BASE_NOTICES = ['historical_only', 'units_unconfirmed', 'timezone_unconfirmed', 'aggregation_unknown',
                'cultivar_stage_unknown', 'not_linked_to_fertilizer_parcel', 'no_control_decision']
CODE_FILES = ('environment_assistant.py', 'environment_context.py', 'smartfarm.py', 'mcp_server.py',
              'llm.py', 'assistant.py', 'explanation.py', 'schemas.py')


def canonical_answer(answer):
    try:
        normalized = dict(answer)
        fields = []
        for field in answer['fields']:
            field = dict(field)
            for key in ('minimum', 'maximum'):
                if field[key] is not None:
                    if not isinstance(field[key], str) or not Decimal(field[key]).is_finite():
                        return None
                    field[key] = str(Decimal(field[key]).normalize())
            fields.append(field)
        normalized['fields'] = sorted(fields, key=lambda field: field['code'])
        for key in ('citations', 'limitations'):
            normalized[key] = sorted(answer[key])
        return json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    except (ValueError, TypeError, KeyError, InvalidOperation):
        return None


def score(case, study, run, path, pinned):
    row = assess(case, study['expected_fields'], run, path)
    answer = raw_answer(run)
    is_model = case['status'] == 'partial'
    row.update(is_model_case=is_model, raw_numeric_pass=False, raw_citation_pass=False,
               raw_scope_pass=False, raw_identity_pass=False, delivered_valid=False,
               consistency_key=canonical_answer(answer) if answer else None,
               elapsed_seconds=run['manifest'].get('elapsed_seconds'))
    if not is_model:
        row['guard_pass'] = row['passed']
        return row
    row['guard_pass'] = None
    if not answer:
        return row
    row['raw_numeric_pass'] = not any(
        error == 'field_set_mismatch' or any(error.startswith(code + '_') for code in case['codes'])
        for error in row['errors'])
    row['raw_citation_pass'] = 'citations_mismatch' not in row['errors']
    notices = BASE_NOTICES + (['humidity_semantics_unconfirmed'] if 'HI' in case['codes'] else []) + (
        ['co2_source_review_required'] if 'CI' in case['codes'] else [])
    row['raw_scope_pass'] = (isinstance(answer.get('limitations'), list) and
        all(isinstance(value, str) for value in answer['limitations']) and
        sorted(answer['limitations']) == sorted(notices) and
        answer.get('assessment') == 'deferred_units_and_applicability')
    expected_identity = dict(pinned['identity'], snapshot_sha256=pinned['snapshot_sha256'],
                             document_sha256=pinned['document_sha256'],
                             evidence_sha256=pinned['contexts'][case['case_id']])
    row['raw_identity_pass'] = all(answer.get(key) == value for key, value in expected_identity.items())
    row['delivered_valid'] = bool(row['passed'] and row['raw_scope_pass'] and row['raw_identity_pass'] and run.get('answer'))
    row['passed'] = row['delivered_valid']
    return row


def aggregate(rows):
    stats = {}
    for path in ('mcp', 'rag'):
        model = [row for row in rows if row['path'] == path and row['is_model_case']]
        guards = [row for row in rows if row['path'] == path and not row['is_model_case']]
        stat = {'model_attempted': len(model), 'guard_attempted': len(guards),
                'guard_passed': sum(row['guard_pass'] for row in guards),
                'failures_by_code': dict(Counter(row['error_code'] or row['status']
                                                 for row in model if not row['delivered_valid'])),
                'repeat_consistency': {}}
        for metric in ('raw_numeric_pass', 'raw_citation_pass', 'raw_scope_pass', 'raw_identity_pass', 'delivered_valid'):
            count = sum(row[metric] for row in model)
            stat[metric] = {'passed': count, 'attempted': len(model), 'fraction': count/len(model) if model else None}
        for case_id in sorted({row['case_id'] for row in model}):
            group = [row for row in model if row['case_id'] == case_id]
            counts = Counter(row['consistency_key'] for row in group if row['consistency_key'] is not None)
            stat['repeat_consistency'][case_id] = {'attempted': len(group), 'parseable': sum(counts.values()),
                'majority_fraction_with_failures': max(counts.values(), default=0)/len(group) if len(group)>1 else None}
        stats[path] = stat
    return stats


def analyze(output):
    protocol = json.loads((output / 'protocol.json').read_text(encoding='utf-8'))
    study, pinned = protocol['study'], protocol['pinned']
    artifact_errors = []
    if context_digest(study) != protocol['study_sha256']:
        artifact_errors.append('study_changed')
    for name, expected_hash in protocol['artifacts'].items():
        file = output / name
        if not file.exists() or hashlib.sha256(file.read_bytes()).hexdigest() != expected_hash:
            artifact_errors.append(name + '_missing_or_changed')
    rows, pairs = [], []
    for trial in range(1, protocol['repeats']+1):
        for case in study['cases']:
            runs, scored = {}, {}
            for path in ('mcp', 'rag'):
                filename = '{:02d}_{}_{}.json'.format(trial, case['case_id'], path)
                try:
                    run = json.loads((output / filename).read_text(encoding='utf-8'))
                    row = score(case, study, run, path, pinned)
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    run = {'status': 'log_error', 'error_code': 'LOG_MISSING_OR_INVALID', 'manifest': {},
                           'responses': [], 'tool_trace': [], 'retrieval_trace': []}
                    row = score(case, study, run, path, pinned)
                manifest = run['manifest']
                errors = list(artifact_errors)
                for key in ('provider', 'requested_model', 'config', 'code_sha256'):
                    if manifest.get(key) != pinned[key]:
                        errors.append(key)
                if manifest.get('evidence_path') != path or manifest.get('question_sha256') != context_digest(case['question']):
                    errors.append('path_or_question')
                if manifest.get('prompt_sha256') != pinned['prompts'][path]:
                    errors.append('prompt')
                if row['is_model_case']:
                    for key in ('snapshot_sha256', 'document_sha256', 'catalog_sha256', 'answer_schema_sha256'):
                        if manifest.get(key) != pinned[key]:
                            errors.append(key)
                    if manifest.get('evidence_sha256') != pinned['contexts'][case['case_id']]:
                        errors.append('evidence_sha256')
                row.update(trial=trial, file=filename, conditions_match=not errors,
                           condition_errors=','.join(errors))
                if errors:
                    row['passed'] = False
                rows.append(row)
                runs[path], scored[path] = run, row
            left, right = scored['mcp'], scored['rag']
            same = left['conditions_match'] and right['conditions_match'] and runs['mcp'].get('routing') == runs['rag'].get('routing')
            keys = left['consistency_key'] is not None and right['consistency_key'] is not None
            pairs.append({'trial': trial, 'case_id': case['case_id'], 'same_conditions': same,
                          'raw_answers_equal': left['consistency_key'] == right['consistency_key'] if same and keys else None,
                          'both_passed': bool(same and left['passed'] and right['passed'])})
    summary = {'provider': protocol['provider'], 'repeats': protocol['repeats'],
               'interpretation': 'historical_lookup_citation_fidelity_not_agricultural_or_control_accuracy',
               'statistics': aggregate(rows), 'pairs': pairs,
               'conditions_failed': sum(not row['conditions_match'] for row in rows),
               'all_passed': all(pair['both_passed'] for pair in pairs),
               'analysis_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    public = [{key: (','.join(value) if key=='errors' else value) for key, value in row.items()
               if key!='consistency_key'} for row in rows]
    with (output / 'results.csv').open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(public[0]))
        writer.writeheader()
        writer.writerows(public)
    lines = ['# 과거 환경자료·문헌 질의응답 반복 평가', '',
             f"- 공급자: {protocol['provider']}, 질문별 반복: {protocol['repeats']}, 사례: {len(study['cases'])}",
             '단위·시간대·집계 의미는 미확인 상태를 유지했다. 원본 값·인용·보류 계약을 평가하며 제어 정확도를 뜻하지 않는다.',
             '고정 참조 수치는 앱 정규화기와 별도로 원본 JSON에서 계산·대조한 감사 결과를 선행 확인했다.',
             f"- 실행 조건 불일치: {summary['conditions_failed']}", '',
             '| 경로 | 모델 시도 | 원시 수치 일치 | 원시 인용 일치 | 원시 한계 고지 일치 | 원시 식별·해시 일치 | 전달 검증 통과 | 로컬 보류 통과 |',
             '|---|---|---|---|---|---|---|---|']
    for path, stat in summary['statistics'].items():
        count = stat['model_attempted']
        values = [str(stat[key]['passed'])+'/'+str(count) for key in (
            'raw_numeric_pass', 'raw_citation_pass', 'raw_scope_pass', 'raw_identity_pass', 'delivered_valid')]
        lines.append('| '+path+' | '+str(count)+' | '+' | '.join(values)+' | '+str(stat['guard_passed'])+'/'+str(stat['guard_attempted'])+' |')
    lines.extend(['', '실패를 제외하지 않으며 로컬 보류는 모델 평가와 분리한다.',
                  '반복 일관성은 원시 구조화 응답의 최빈 값 횟수/전체 시도이며 실패를 분모에 포함한다.',
                  '일관되게 틀린 값도 일관적일 수 있다. 단일 시설·하루·고정5문단의 결과를 일반 성능으로 확대하지 않는다.',
                  'audit.json·snapshot.json·catalog.json·metadata_review.json과 원시 실행 JSON을 보존한다.',
                  'protocol.json과 저장 파일만으로 --analyze 재집계할 수 있다. 누락·손상 실행도 실패로 집계한다.'])
    (output / 'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return summary


async def run_study(output, provider='mock', repeats=10, case_ids=None):
    if not 1 <= repeats <= 10:
        raise ValueError('REPEAT_LIMIT')
    study = json.loads(SCENARIOS.read_text(encoding='utf-8'))
    if case_ids:
        if len(set(case_ids)) != len(case_ids) or not set(case_ids) <= {case['case_id'] for case in study['cases']}:
            raise ValueError('INVALID_CASE_SELECTION')
        study['cases'] = [case for case in study['cases'] if case['case_id'] in case_ids]
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding='utf-8'))
    audit = audit_environment(snapshot, study['expected_fields'])
    if not audit['passed']:
        raise ValueError('RAW_SOURCE_AUDIT_FAILED')
    catalog = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    contexts = {}
    from agri_dss.environment_assistant import select_question
    for case in study['cases']:
        if case['status'] == 'partial':
            selection, _ = select_question(case['question'])
            contexts[case['case_id']] = build_environment_context(**selection)['evidence_sha256']
    config = load_llm_config()
    pinned = {'provider': provider, 'requested_model': config.model if provider=='openai' else 'mock-environment-v1',
              'config': config.model_dump(), 'snapshot_sha256': context_digest(snapshot),
              'document_sha256': catalog['source_sha256'], 'catalog_sha256': hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest(),
              'answer_schema_sha256': context_digest(strict_schema(EnvironmentAnswer.model_json_schema())),
              'contexts': contexts, 'identity': {'snapshot_id': snapshot['snapshot_id'], 'facility_id': snapshot['facility_id'],
                                                'observation_date': snapshot['date']},
              'prompts': {'mcp': context_digest(MCP_INSTRUCTIONS), 'rag': context_digest(RAG_INSTRUCTIONS)},
              'code_sha256': {name: hashlib.sha256((ROOT / 'src/agri_dss' / name).read_bytes()).hexdigest() for name in CODE_FILES}}
    output.mkdir(parents=True, exist_ok=True)
    (output / 'snapshot.json').write_bytes(SNAPSHOT_PATH.read_bytes())
    (output / 'catalog.json').write_bytes(CATALOG_PATH.read_bytes())
    (output / 'metadata_review.json').write_bytes((ROOT / 'data/references/environment_metadata_review.json').read_bytes())
    (output / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    artifacts = {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in (
                 'snapshot.json', 'catalog.json', 'metadata_review.json', 'audit.json')}
    protocol = {'version': '1.0', 'study': study, 'provider': provider, 'repeats': repeats,
                'started_at': datetime.now(timezone.utc).isoformat(), 'pinned': pinned, 'artifacts': artifacts,
                'study_sha256': context_digest(study), 'analysis_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (output / 'protocol.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    for trial in range(1, repeats+1):
        for case in study['cases']:
            for path in (('mcp','rag') if trial%2 else ('rag','mcp')):
                run = await run_environment_assistant(provider, path, case['question'])
                filename = '{:02d}_{}_{}.json'.format(trial, case['case_id'], path)
                (output / filename).write_text(json.dumps(run, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
                print('{}/{} {} {}: {}'.format(trial,repeats,case['case_id'],path,run['status']), flush=True)
    return analyze(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['mock','openai'], default='mock')
    parser.add_argument('--repeats', type=int, choices=range(1,11), default=10)
    parser.add_argument('--case', action='append', dest='case_ids')
    parser.add_argument('--analyze', type=Path)
    args = parser.parse_args()
    output = args.analyze or ROOT / 'outputs/environment_experiment' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    result = analyze(output) if args.analyze else asyncio.run(run_study(output,args.provider,args.repeats,args.case_ids))
    print('Report:', output / 'report.md')
    return 0 if result['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
