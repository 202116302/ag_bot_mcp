"""Compare evidence delivery for one question; not agricultural accuracy."""
import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from agri_dss.assistant import DEFAULT_QUESTION, run_fertilizer_assistant


def canonical_claims(answer):
    """Compare checked numerical claims without list-order or decimal-format noise."""
    result = dict(answer)
    result['notices'] = sorted(answer['notices'])
    result['amounts'] = sorted([
        dict(claim, value=str(Decimal(claim['value']).normalize()) if claim['value'] is not None else None)
        for claim in answer['amounts']], key=lambda claim: claim['field'])
    return result


def assess_pair(runs):
    left, right = runs['mcp'], runs['rag']
    fields = ('provider', 'requested_model', 'synthetic_model', 'config', 'source_sha256',
              'source_record', 'normalized_evidence_sha256', 'code_sha256', 'question_sha256')
    mismatches = [field for field in fields if field not in left['manifest'] or
                  field not in right['manifest'] or left['manifest'][field] != right['manifest'][field]]
    # Deferred questions have no answer schema or model response, on either path.
    if left['manifest'].get('answer_schema_sha256') != right['manifest'].get('answer_schema_sha256'):
        mismatches.append('answer_schema_sha256')
    if left.get('routing') != right.get('routing'):
        mismatches.append('routing')
    for path, run in runs.items():
        if run['status'] not in ('completed', 'partial', 'deferred'):
            mismatches.append(path + '_run_failed')
        elif run['status'] != 'deferred' and not run.get('explanation_check', {}).get('passed'):
            mismatches.append(path + '_claims_unchecked')
    answered = all(run['status'] in ('completed', 'partial') for run in runs.values())
    checked = answered and not mismatches
    claims_equal = (canonical_claims(left['structured_answer']) == canonical_claims(right['structured_answer'])) if checked else None
    return {'comparable': not mismatches, 'errors': mismatches,
            'both_answered': answered, 'structured_answers_equal': claims_equal,
            'statuses_equal': left['status'] == right['status'],
            'passed': not mismatches and left['status'] == right['status'] and
                      (claims_equal if answered else left['status'] == right['status'] == 'deferred')}


async def run_comparison(output, provider='mock', question=DEFAULT_QUESTION, repeats=1):
    output.mkdir(parents=True, exist_ok=True)
    pairs = []
    for index in range(repeats):
        runs = {}
        order = ('mcp', 'rag') if index % 2 == 0 else ('rag', 'mcp')
        for path in order:
            run = await run_fertilizer_assistant(provider, question, path=path)
            runs[path] = run
            filename = f'{index + 1:02d}_{path}.json'
            (output / filename).write_text(json.dumps(run, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(f"{index + 1}/{repeats} {path}: {run['status']}", flush=True)
        row = assess_pair(runs)
        row.update(trial=index + 1, order=list(order),
                   runs={path: {'run_id': run['run_id'], 'status': run['status'],
                                'error_code': run.get('error_code'),
                                'elapsed_seconds': run['manifest']['elapsed_seconds'],
                                'model_calls': run['manifest']['model_calls'],
                                'tool_calls': run['manifest']['tool_calls']}
                         for path, run in runs.items()})
        pairs.append(row)
    summary = {'question': question, 'provider': provider, 'repeats': repeats,
               'interpretation': 'saved_prescription_delivery_check_not_agricultural_accuracy',
               'passed': sum(row['passed'] for row in pairs), 'pairs': pairs}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# 비료 자료 MCP/RAG 전달 비교', '', f'- 공급자: {provider}',
             f'- 질문: {question}', f"- 시행: {repeats}, 계약 일치: {summary['passed']}", '',
             '동일한 정규화 자료를 MCP 도구 또는 PNU·작물 메타데이터 검색으로 전달했다.',
             'RAG 검색 대상은 선택 필지의 처방 문서 1개다. 벡터 검색과 문헌 기준 해석은 아직 포함하지 않는다.',
             '수치·단위·출처·누락·한계 고지는 같은 검사기로 검증했다. 독립 농업 정답 평가는 아니다.',
             '로컬 보류는 모델 응답 일치율에 포함하지 않는다. 실패한 시행도 JSON에 보존한다.', '',
             '| 시행 | MCP 상태 | RAG 상태 | 비교 조건 일치 | 구조화 응답 일치 |',
             '|---|---|---|---|---|']
    for row in pairs:
        lines.append(f"| {row['trial']} | {row['runs']['mcp']['status']} | {row['runs']['rag']['status']} | "
                     f"{row['comparable']} | {row['structured_answers_equal']} |")
    (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['mock', 'openai'], default='mock')
    parser.add_argument('--question', default=DEFAULT_QUESTION)
    parser.add_argument('--repeats', type=int, choices=range(1, 11), default=1)
    parser.add_argument('--suite', action='store_true', help='Run frozen fertilizer delivery questions and offline scoring')
    parser.add_argument('--case', action='append', dest='case_ids', help='Case ID from fertilizer_delivery.json (suite only)')
    parser.add_argument('--analyze', type=Path, help='Re-score a saved delivery suite without model/API calls')
    args = parser.parse_args()
    if args.suite or args.analyze:
        from scripts.fertilizer_delivery_suite import analyze_delivery, run_delivery_suite
        output = args.analyze or ROOT / 'outputs/fertilizer_delivery' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        summary = (analyze_delivery(output) if args.analyze else
                   asyncio.run(run_delivery_suite(output, args.provider, args.repeats, args.case_ids)))
        print('Report:', output / 'report.md')
        return 0 if summary['all_passed'] else 1
    if args.case_ids:
        parser.error('--case requires --suite')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = ROOT / 'outputs/path_comparison' / stamp
    summary = asyncio.run(run_comparison(output, args.provider, args.question, args.repeats))
    print('Report:', output / 'report.md')
    return 0 if summary['passed'] == summary['repeats'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
