"""Audit Mock or GPT against independent domain-flow expectations.

Expected labels are used only by the assessor, never sent to the router/model.
Supported cases use a real stdio MCP session; unsupported cases stop locally.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from agri_dss.assistant import run_fertilizer_assistant


def assess(case, result):
    actual_tools = [entry['name'] for entry in result['tool_trace']]
    notices = result.get('structured_answer', {}).get('notices', [])
    errors = []
    if actual_tools != case['expected_tools']:
        errors.append('tool_sequence_mismatch')
    if result['status'] not in case['expected_statuses']:
        errors.append('outcome_mismatch')
    if any(notice not in notices for notice in case['required_notices']):
        errors.append('missing_domain_limit_notice')
    if actual_tools and not result.get('explanation_check', {}).get('passed'):
        errors.append('explanation_check_failed')
    return {'case_id': case['case_id'], 'domain': case['domain'],
            'question': case['question'], 'expected_behavior': case['expected_behavior'],
            'expected_tools': case['expected_tools'], 'expected_statuses': case['expected_statuses'],
            'actual_tools': actual_tools, 'actual_status': result['status'],
            'structured_claims_passed': result.get('explanation_check', {}).get('passed'),
            'flow_passed': not errors, 'errors': errors,
            'model_calls': result['manifest']['model_calls'],
            'tool_calls': result['manifest']['tool_calls']}


def markdown_report(summary):
    lines = [f"# {summary['provider']} 분야별 호출 흐름 점검", '',
             '분야별 지원 범위 사전 검사와 모델/MCP 호출 기록을 기대 조건과 비교했다.',
             '예상 경로는 사람이 작성한 테스트 조건이며 LLM 질문 이해 성능이나 농업 정확도의 정답이 아니다.', '',
             f"- 점검 시각: {summary['started_at']}",
             f"- 사례: {summary['total']}개, 예상 흐름 일치 {summary['passed']}개, 불일치 {summary['failed']}개",
             ('- Mock은 외부 API 호출 없음.' if summary['provider'] == 'mock' else '- 지원 질문은 OpenAI API를 호출했다. 미지원 질문은 로컬에서 보류한다.'),
             '- MCP 도구는 저장된 실제 비료 응답을 읽는다.', '',
             '| 분야 | 질문 | 기대 흐름 | 실제 호출 | 흐름 일치 |',
             '|---|---|---|---|---|']
    for row in summary['cases']:
        actual = ' → '.join(row['actual_tools']) or '없음'
        lines.append(f"| {row['domain']} | {row['question']} | {row['expected_behavior']} | {actual} | {'통과' if row['flow_passed'] else '불일치'} |")
    lines.extend(['', '## 해석', '',
                  '지원 범위 분기는 로컬 키워드 규칙이며 GPT의 분야 분류 능력을 측정한 것이 아니다.',
                  '기대 경로 라벨은 평가기에만 전달하며 모델이나 분기 규칙에 입력하지 않는다.',
                  '구조화 수치·단위·출처 검증이 통과하더라도 질문 분야에 맞는 호출이라는 의미는 아니다.',
                  '시비+관수 사례의 통과는 비료 조회와 관수 자료 부재 고지만 확인하며 관수 판단 성공이 아니다.',
                  '시비+기상은 기상 미지원 고지가 없으면 실패로 처리한다.',
                  '미등록 필지 질문에 기본 필지 자료를 반환하면 수치가 정확해도 흐름 불일치다.', '',
                  '## 다음 수정 후보', '',
                  '분야별 지원 범위와 보류/부분응답 계약을 먼저 정의하고, Mock 시나리오 및 실제 모델 경로에 적용한다.',
                  '합성 관수 예제를 실제 필지 질문에 연결하지 않는다. GPT 연결 후 같은 사례를 별도로 평가한다.', '',
                  '개별 원본 실행 기록은 `runs/<case_id>.json`, 기계 판독 요약은 `summary.json`에 있다.'])
    return '\n'.join(lines) + '\n'


async def run_suite(output, provider='mock'):
    source = ROOT / 'configs/scenarios/mock_domain_flows.json'
    raw = source.read_bytes()
    cases = json.loads(raw)['cases']
    (output / 'runs').mkdir(parents=True, exist_ok=True)
    rows = []
    started = datetime.now(timezone.utc).isoformat()
    for case in cases:
        result = await run_fertilizer_assistant(provider, case['question'])
        (output / 'runs' / (case['case_id'] + '.json')).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        row = assess(case, result)
        rows.append(row)
        print(f"{case['case_id']}: {'PASS' if row['flow_passed'] else 'MISMATCH'} "
              f"tools={','.join(row['actual_tools'])} status={row['actual_status']}", flush=True)
    summary = {'started_at': started, 'provider': provider,
               'model': result['manifest']['requested_model'],
               'scenario_sha256': hashlib.sha256(raw).hexdigest(),
               'interpretation': 'flow_contract_check_not_model_accuracy',
               'total': len(rows), 'passed': sum(row['flow_passed'] for row in rows),
               'failed': sum(not row['flow_passed'] for row in rows), 'cases': rows}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (output / 'report.md').write_text(markdown_report(summary), encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--provider', choices=['mock', 'openai'], default='mock')
    args = parser.parse_args()
    output = args.output or ROOT / 'outputs' / ('mock_flow' if args.provider == 'mock' else 'gpt_flow') / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    summary = asyncio.run(run_suite(output, args.provider))
    print(f"Expected flow matches: {summary['passed']}/{summary['total']}")
    print('Report:', output / 'report.md')
    return 0 if not summary['failed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
