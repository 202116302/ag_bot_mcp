"""Synthetic direct-decision experiment. Labels never enter model context."""
import argparse
import asyncio
import csv
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from agri_dss.irrigation_assistant import run_irrigation_assistant
from agri_dss.irrigation_cases import CASES_PATH


def assess(case, run):
    answer = run.get('structured_answer', {})
    completed = run['status'] == 'completed' and run.get('explanation_check', {}).get('passed') is True
    return {'case_id': case['case_id'], 'category': case['category'], 'status': run['status'],
            'error_code': run.get('error_code'), 'run_id': run.get('run_id'),
            'decision': answer.get('decision'), 'decision_code': answer.get('decision_code'),
            'expected_decision': case['expected_decision'], 'expected_code': case['expected_code'],
            'completed': completed, 'decision_correct': bool(completed and answer.get('decision') == case['expected_decision']),
            'contract_correct': bool(completed and answer.get('decision') == case['expected_decision'] and
                                     answer.get('decision_code') == case['expected_code'])}


def analyze(output):
    protocol = json.loads((output / 'protocol.json').read_text(encoding='utf-8'))
    rows, pairs = [], []
    for trial in range(1, protocol['repeats'] + 1):
        for case in protocol['cases']:
            runs, assessed = {}, {}
            for path in ('mcp', 'rag'):
                name = f"{trial:02d}_{case['case_id']}_{path}.json"
                try:
                    run = json.loads((output / name).read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    run = {'status': 'log_error', 'error_code': 'LOG_MISSING_OR_INVALID', 'manifest': {}}
                runs[path] = run
                row = assess(case, run)
                row.update(trial=trial, path=path, file=name,
                           model_calls=run['manifest'].get('model_calls'), tool_calls=run['manifest'].get('tool_calls'),
                           elapsed_seconds=run['manifest'].get('elapsed_seconds'))
                assessed[path] = row
                rows.append(row)
            fields = ('snapshot_sha256', 'rule_sha256', 'source_sha256', 'question_sha256',
                      'requested_model', 'provider', 'config', 'files_sha256', 'answer_schema_sha256')
            mismatches = [key for key in fields if key not in runs['mcp']['manifest'] or
                          key not in runs['rag']['manifest'] or
                          runs['mcp']['manifest'][key] != runs['rag']['manifest'][key]]
            for path, run in runs.items():
                files = run['manifest'].get('files_sha256', {})
                if files.get('configs/scenarios/irrigation_decisions.json') != protocol['scenario_sha256']:
                    mismatches.append(path + '_scenario_changed')
            valid = not mismatches and all(row['completed'] for row in assessed.values())
            pairs.append({'trial': trial, 'case_id': case['case_id'], 'comparable': not mismatches,
                          'errors': mismatches, 'both_completed': valid,
                          'decisions_equal': assessed['mcp']['decision'] == assessed['rag']['decision'] if valid else None})
    statistics = {}
    for path in ('mcp', 'rag'):
        subset = [row for row in rows if row['path'] == path]
        statistics[path] = {'attempted': len(subset), 'completed': sum(row['completed'] for row in subset),
                            'failed': sum(not row['completed'] for row in subset),
                            'decision_correct': sum(row['decision_correct'] for row in subset),
                            'contract_correct': sum(row['contract_correct'] for row in subset),
                            'decision_accuracy_synthetic': sum(row['decision_correct'] for row in subset) / len(subset)}
        statistics[path]['repeat_consistency'] = {}
        for case in protocol['cases']:
            trials = [row for row in subset if row['case_id'] == case['case_id']]
            counts = Counter(row['decision'] for row in trials if row['completed'])
            statistics[path]['repeat_consistency'][case['case_id']] = {
                'attempted': len(trials), 'completed': sum(counts.values()),
                'majority_fraction_with_failures': max(counts.values(), default=0) / len(trials) if len(trials) > 1 else None}
    summary = {'interpretation': 'synthetic_software_test_not_agricultural_accuracy',
               'provider': protocol['provider'], 'repeats': protocol['repeats'],
               'statistics': statistics, 'pairs': pairs,
               'all_passed': all(row['contract_correct'] for row in rows) and all(pair['comparable'] for pair in pairs)}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    with (output / 'results.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = ['# 합성 관수 직접 판정 비교', '', '농업 처방·정확도 평가가 아닌 소프트웨어 시험 결과다.',
             'RAG 실모델에는 기준 원문과 입력만 제공하며 Python 판정·기대 라벨을 전달하지 않는다.',
             'MCP는 Python 규칙을 실행하고 모델이 그 판정을 보존하는지 검사한다.',
             'Mock RAG는 엔진 기반 시험 대역이므로 독립 추론의 검증이 아니다.', '',
             f"- 공급자: {protocol['provider']}, 사례: {len(protocol['cases'])}, 반복: {protocol['repeats']}", '',
             '| 경로 | 시도 | 완료 | 실패 | 기대 판정 일치 | 판정·사유 일치 |',
             '|---|---|---|---|---|---|']
    for path, stats in statistics.items():
        lines.append(f"| {path} | {stats['attempted']} | {stats['completed']} | {stats['failed']} | "
                     f"{stats['decision_correct']} | {stats['contract_correct']} |")
    lines.extend(['', '실패도 정확도 분모에 포함한다. 경로 간 판정 일치는 양쪽 완료·동일 조건인 쌍에서만 기록한다.',
                  '원본 JSON과 protocol.json으로 --analyze 재집계가 가능하다. 누락·손상 로그는 실패로 집계한다.',
                  '표본이 적은 실제 GPT 점검이나 결정적 Mock의 반복을 일반적인 모델 성능으로 해석하지 않는다.'])
    (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return summary


async def run_suite(output, provider='mock', repeats=1, case_ids=None):
    raw = CASES_PATH.read_bytes()
    cases = json.loads(raw)['cases']
    if case_ids:
        if len(set(case_ids)) != len(case_ids) or not set(case_ids) <= {case['case_id'] for case in cases}:
            raise ValueError('INVALID_CASE_SELECTION')
        cases = [case for case in cases if case['case_id'] in case_ids]
    output.mkdir(parents=True, exist_ok=True)
    protocol = {'version': '1.0-demo', 'provider': provider, 'repeats': repeats, 'cases': cases,
                'scenario_sha256': hashlib.sha256(raw).hexdigest(),
                'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'started_at': datetime.now(timezone.utc).isoformat()}
    (output / 'protocol.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for trial in range(1, repeats + 1):
        for case in cases:
            for path in (('mcp', 'rag') if trial % 2 else ('rag', 'mcp')):
                # Only the case ID enters runtime. Expected labels belong to the assessor.
                run = await run_irrigation_assistant(provider, path, case['case_id'])
                filename = f"{trial:02d}_{case['case_id']}_{path}.json"
                (output / filename).write_text(json.dumps(run, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                print(f"{trial}/{repeats} {case['case_id']} {path}: {run['status']}", flush=True)
    return analyze(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['mock', 'openai'], default='mock')
    parser.add_argument('--repeats', type=int, choices=range(1, 11), default=1)
    parser.add_argument('--case', action='append', dest='case_ids')
    parser.add_argument('--analyze', type=Path, help='Recalculate stored results without API calls')
    args = parser.parse_args()
    if args.analyze:
        output = args.analyze
        summary = analyze(output)
    else:
        output = ROOT / 'outputs/irrigation_comparison' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        summary = asyncio.run(run_suite(output, args.provider, args.repeats, args.case_ids))
    print('Report:', output / 'report.md')
    return 0 if summary['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
