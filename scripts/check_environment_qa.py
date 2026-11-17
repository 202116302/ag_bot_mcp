"""Check both historical environment QA paths against fixed lookup contracts."""
import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from agri_dss.environment_assistant import run_environment_assistant
from agri_dss.fertilizer_evaluation import raw_answer


def assess(case, expected_fields, run, path):
    errors = []
    if run['status'] != case['status']:
        errors.append('status_mismatch')
    answer = raw_answer(run)
    if case['status'] == 'deferred':
        if run['responses'] or run['tool_trace'] or run['retrieval_trace']:
            errors.append('deferred_case_called_model_or_evidence')
    else:
        if not run.get('explanation_check', {}).get('passed'):
            errors.append('runtime_check_failed')
        if not answer:
            errors.append('raw_answer_missing')
        else:
            citations = answer.get('citations')
            if (not isinstance(citations, list) or any(not isinstance(value, str) for value in citations) or
                    sorted(citations) != sorted(case['citations'])):
                errors.append('citations_mismatch')
            fields = answer.get('fields', [])
            valid_fields = isinstance(fields, list) and all(isinstance(field, dict) and
                           isinstance(field.get('code'), str) for field in fields)
            indexed = {field['code']: field for field in fields} if valid_fields else {}
            if not valid_fields or len(indexed) != len(fields) or set(indexed) != set(case['codes']):
                errors.append('field_set_mismatch')
            for code in case['codes']:
                field = indexed.get(code, {})
                for key, expected in expected_fields[code].items():
                    actual = field.get(key)
                    try:
                        equal = (isinstance(actual, str) and Decimal(actual).is_finite() and Decimal(actual) == Decimal(expected)) if key in ('minimum', 'maximum') and expected is not None else actual == expected
                    except (TypeError, InvalidOperation):
                        equal = False
                    if not equal:
                        errors.append(code + '_' + key + '_mismatch')
                if 'unit' not in field or field['unit'] is not None:
                    errors.append(code + '_unit_invented')
            if answer.get('assessment') != 'deferred_units_and_applicability':
                errors.append('unsupported_assessment')
        if path == 'mcp' and not run['tool_trace']:
            errors.append('mcp_tool_missing')
        if path == 'rag' and (run['tool_trace'] or not run['retrieval_trace']):
            errors.append('rag_evidence_path_mismatch')
    return {'case_id': case['case_id'], 'path': path, 'status': run['status'],
            'error_code': run.get('error_code'), 'passed': not errors, 'errors': errors,
            'model_calls': run['manifest'].get('model_calls'), 'tool_calls': run['manifest'].get('tool_calls')}


async def run_suite(output, provider='mock'):
    source = ROOT / 'configs/scenarios/environment_qa.json'
    raw = source.read_bytes()
    study = json.loads(raw)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'protocol.json').write_text(json.dumps(study, ensure_ascii=False, indent=2), encoding='utf-8')
    rows, pairs = [], []
    for case in study['cases']:
        runs = {}
        for path in ('mcp', 'rag'):
            run = await run_environment_assistant(provider, path, case['question'])
            runs[path] = run
            (output / (case['case_id'] + '_' + path + '.json')).write_text(
                json.dumps(run, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            row = assess(case, study['expected_fields'], run, path)
            rows.append(row)
            print(f"{case['case_id']} {path}: {'PASS' if row['passed'] else 'FAIL'} status={run['status']}", flush=True)
        keys = ('requested_model', 'provider', 'config', 'code_sha256', 'question_sha256',
                'snapshot_sha256', 'document_sha256', 'evidence_sha256', 'catalog_sha256', 'answer_schema_sha256')
        mismatches = [key for key in keys if runs['mcp']['manifest'].get(key) != runs['rag']['manifest'].get(key)]
        pairs.append({'case_id': case['case_id'], 'same_conditions': not mismatches, 'errors': mismatches})
    summary = {'provider': provider, 'scenario_sha256': hashlib.sha256(raw).hexdigest(),
               'interpretation': 'lookup_and_citation_contract_check_not_control_accuracy',
               'total': len(rows), 'passed': sum(row['passed'] for row in rows),
               'all_passed': all(row['passed'] for row in rows) and all(pair['same_conditions'] for pair in pairs),
               'cases': rows, 'pairs': pairs}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# 환경자료·재배문서 질의응답 점검', '',
             f"- 공급자: {provider}, 경로별 사례 합계: {len(rows)}, 계약 일치: {summary['passed']}",
             '과거 환경자료의 수치·문헌 인용·판단 보류 계약을 확인했다. 환경 적정성이나 제어 정확도 평가는 아니다.',
             '5개 자료/문헌 질문과 4개 로컬 보류 질문을 경로별로 실행했다. 로컬 보류는 모델 평가가 아니다.',
             'RAG 실모델은 원시 환경값에서 건수·최솟값·최댓값을 읽고, MCP는 Python 요약 도구를 호출한다.',
             '문헌 인용은 검토된 5개 문단의 topic/type 필터다. 자유서술 의미나 일반 검색 품질을 검증하지 않는다.', '',
             '| 사례 | 경로 | 상태 | 계약 일치 | 오류 |', '|---|---|---|---|---|']
    for row in rows:
        lines.append(f"| {row['case_id']} | {row['path']} | {row['status']} | {row['passed']} | {row['error_code'] or ','.join(row['errors'])} |")
    (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['mock', 'openai'], default='mock')
    args = parser.parse_args()
    output = ROOT / 'outputs/environment_qa_checks' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    result = asyncio.run(run_suite(output, args.provider))
    print('Report:', output / 'report.md')
    return 0 if result['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
