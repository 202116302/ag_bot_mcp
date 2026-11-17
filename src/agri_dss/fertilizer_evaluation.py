"""Offline scoring independent of the runtime explanation checker.

Expected values are fixed provider transcriptions, not agronomic truth. Inspect
raw final model output so runtime rejection cannot hide a model mistake.
"""
from collections import Counter
from decimal import Decimal, InvalidOperation
import json


def same_value(value, expected):
    if value is None or expected is None:
        return value is None and expected is None
    if not isinstance(value, str):
        return False
    try:
        number, target = Decimal(value), Decimal(expected)
        return number.is_finite() and target.is_finite() and number == target
    except (InvalidOperation, TypeError):
        return False


def raw_answer(run):
    """No fallback to renderer or structured_answer; these may have been filtered."""
    for response in run.get('responses', [])[-1:]:
        output = response.get('output', [])
        if response.get('status') != 'completed' or any(item.get('type') == 'function_call' for item in output):
            return None
        if any(part.get('type') == 'refusal' for item in output
               if item.get('type') == 'message' for part in item.get('content', [])):
            return None
        text = ''.join(part.get('text', '') for item in output if item.get('type') == 'message'
                       for part in item.get('content', []) if part.get('type') == 'output_text')
        try:
            answer = json.loads(text)
            return answer if isinstance(answer, dict) else None
        except (ValueError, TypeError):
            return None
    return None


def normalize_answer(answer):
    """Consistency key includes wrong-but-parseable values; order is irrelevant."""
    try:
        amounts = answer['amounts']
        if not isinstance(amounts, list) or any(not isinstance(claim, dict) for claim in amounts):
            return None
        claims = []
        for claim in amounts:
            value = claim['value']
            if value is not None:
                if not isinstance(value, str) or not Decimal(value).is_finite():
                    return None
                value = str(Decimal(value).normalize())
            claims.append((claim['field'], value, claim['unit']))
        result = dict(answer, amounts=sorted(claims, key=lambda row: row[0]), notices=sorted(answer['notices']))
        return json.dumps(result, sort_keys=True, ensure_ascii=False)
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None


def score_run(case, run, reference, path):
    answer = raw_answer(run)
    manifest = run.get('manifest', {})
    has_model = bool(run.get('responses'))
    row = {'case_id': case['case_id'], 'kind': case['kind'], 'path': path,
           'run_id': run.get('run_id'), 'status': run.get('status', 'missing'),
           'error_code': run.get('error_code'), 'raw_answer_present': answer is not None,
           'model_calls': manifest.get('model_calls', 0), 'tool_calls': manifest.get('tool_calls', 0),
           'elapsed_seconds': manifest.get('elapsed_seconds'),
           'raw_numeric_pass': False, 'raw_unit_pass': False, 'raw_identity_pass': False,
           'raw_notices_pass': False, 'traceable': False, 'delivered_valid': False,
           'guard_pass': None, 'passed': False, 'consistency_key': normalize_answer(answer) if answer else None}
    if case['kind'] == 'local_guard':
        passed = (run.get('status') == case['expected_status'] and not has_model and
                  manifest.get('model_calls') == 0 and manifest.get('tool_calls') == 0 and
                  not run.get('tool_trace') and not run.get('retrieval_trace') and
                  not run.get('structured_answer'))
        row.update(guard_pass=passed, passed=passed)
        return row
    if answer:
        claims = answer.get('amounts', [])
        well_formed = isinstance(claims, list) and all(isinstance(claim, dict) for claim in claims)
        indexed = {claim.get('field'): claim for claim in claims if isinstance(claim.get('field'), str)} if well_formed else {}
        fields_match = (well_formed and len(indexed) == len(claims) and set(indexed) == set(reference['amounts']))
        row['raw_numeric_pass'] = bool(fields_match and all(
            'value' in indexed[name] and same_value(indexed[name]['value'], value)
            for name, value in reference['amounts'].items()))
        row['raw_unit_pass'] = bool(fields_match and all(
            indexed[name].get('unit') == reference['unit'] for name in reference['amounts']))
        row['raw_identity_pass'] = all(answer.get(key) == reference[key]
                                       for key in ('pnu_code', 'crop_code', 'source_sha256', 'status'))
        notices = answer.get('notices')
        row['raw_notices_pass'] = (isinstance(notices, list) and all(isinstance(value, str) for value in notices) and
                                    sorted(notices) == sorted(reference['notices']))
    if path == 'mcp':
        traces = run.get('tool_trace', [])
        row['traceable'] = bool(traces) and all(
            trace.get('name') == 'get_fertilizer_prescription' and not trace.get('is_error') and
            trace.get('arguments') == {'pnu_code': reference['pnu_code'], 'crop_code': reference['crop_code']} and
            isinstance(trace.get('result'), dict) and trace['result'].get('source_sha256') == reference['source_sha256'] and
            trace['result'].get('pnu_code') == reference['pnu_code'] and
            trace['result'].get('requested_crop_code') == reference['crop_code'] and
            trace['result'].get('source_record') == reference['source_record']
            for trace in traces)
    else:
        traces = run.get('retrieval_trace', [])
        row['traceable'] = (len(traces) == 1 and not run.get('tool_trace') and
                            bool(manifest.get('normalized_evidence_sha256')) and
                            traces[0].get('source_sha256') == reference['source_sha256'] and
                            traces[0].get('source_record') == reference['source_record'] and
                            traces[0].get('content_sha256') == manifest.get('normalized_evidence_sha256') and
                            traces[0].get('pnu_code') == reference['pnu_code'] and
                            traces[0].get('crop_code') == reference['crop_code'])
    row['delivered_valid'] = bool(run.get('status') == case['expected_status'] and run.get('answer') and
                                  run.get('explanation_check', {}).get('passed') and
                                  all(row[key] for key in ('raw_numeric_pass', 'raw_unit_pass', 'raw_identity_pass',
                                                          'raw_notices_pass', 'traceable')))
    row['passed'] = row['delivered_valid']
    return row


def summarize(rows):
    result = {}
    for path in ('mcp', 'rag'):
        model_rows = [row for row in rows if row['path'] == path and row['kind'] == 'model_delivery']
        guards = [row for row in rows if row['path'] == path and row['kind'] == 'local_guard']
        stats = {'model_attempted': len(model_rows), 'guard_attempted': len(guards),
                 'guard_passed': sum(row['guard_pass'] for row in guards),
                 'delivered_failed': sum(not row['delivered_valid'] for row in model_rows),
                 'repeat_consistency': {}}
        for metric in ('raw_numeric_pass', 'raw_unit_pass', 'raw_identity_pass', 'raw_notices_pass',
                       'traceable', 'delivered_valid'):
            count = sum(row[metric] for row in model_rows)
            stats[metric] = {'passed': count, 'attempted': len(model_rows),
                             'fraction': count / len(model_rows) if model_rows else None}
        for case_id in sorted({row['case_id'] for row in model_rows}):
            group = [row for row in model_rows if row['case_id'] == case_id]
            counts = Counter(row['consistency_key'] for row in group if row['consistency_key'] is not None)
            stats['repeat_consistency'][case_id] = {
                'attempted': len(group), 'parseable': sum(counts.values()),
                'majority_fraction_with_failures': max(counts.values(), default=0) / len(group) if len(group) > 1 else None}
        result[path] = stats
    return result
