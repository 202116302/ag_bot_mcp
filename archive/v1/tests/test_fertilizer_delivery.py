import asyncio
from copy import deepcopy
import json

import pytest

from agri_dss.assistant import run_fertilizer_assistant
from agri_dss.fertilizer_evaluation import raw_answer, same_value, score_run, summarize
from scripts.fertilizer_delivery_suite import (SCENARIOS, analyze_delivery, run_delivery_suite,
                                              verify_reference)

STUDY = json.loads(SCENARIOS.read_text(encoding='utf-8'))
REFERENCE = STUDY['reference']
CASE = STUDY['cases'][0]


@pytest.fixture
def run():
    return asyncio.run(run_fertilizer_assistant(path='rag', question=CASE['question']))


def change_raw(run, change):
    answer = raw_answer(run)
    change(answer)
    run['responses'][-1]['output'][0]['content'][0]['text'] = json.dumps(answer)


def test_fixed_reference_matches_provider_xml_and_rejects_changed_label():
    verify_reference(REFERENCE)
    reference = deepcopy(REFERENCE)
    reference['amounts']['basal_n'] = '999'
    with pytest.raises(ValueError, match='TRANSCRIPTION'):
        verify_reference(reference)


def test_raw_scoring_detects_errors_even_if_runtime_claims_success(run):
    change_raw(run, lambda answer: answer['amounts'][0].update(value='999'))
    assert run['explanation_check']['passed']
    assert run['structured_answer']['amounts'][0]['value'] == '14.4'
    row = score_run(CASE, run, REFERENCE, 'rag')
    assert not row['raw_numeric_pass']
    assert not row['delivered_valid']


@pytest.mark.parametrize('value', [None, 'NaN', 'Infinity', 'wrong', 0])
def test_raw_zero_is_not_missing_or_nonfinite_or_json_number(run, value):
    def change(answer):
        next(claim for claim in answer['amounts'] if claim['field'] == 'compost_cattle')['value'] = value
    change_raw(run, change)
    assert not score_run(CASE, run, REFERENCE, 'rag')['raw_numeric_pass']


def test_equivalent_decimal_spelling_and_order_are_preserved(run):
    original = score_run(CASE, run, REFERENCE, 'rag')
    def change(answer):
        answer['amounts'][0]['value'] = '14.40'
        answer['amounts'].reverse()
        answer['notices'].reverse()
    change_raw(run, change)
    row = score_run(CASE, run, REFERENCE, 'rag')
    assert row['passed']
    assert row['consistency_key'] == original['consistency_key']


@pytest.mark.parametrize('kind,metric', [('duplicate', 'raw_numeric_pass'), ('unit', 'raw_unit_pass'),
                                       ('notice', 'raw_notices_pass'), ('source', 'raw_identity_pass')])
def test_separate_fidelity_metrics(run, kind, metric):
    def change(answer):
        if kind == 'duplicate':
            answer['amounts'].append(answer['amounts'][0])
        elif kind == 'unit':
            answer['amounts'][0]['unit'] = 'kg/ha'
        elif kind == 'notice':
            answer['notices'].pop()
        else:
            answer['source_sha256'] = 'other'
    change_raw(run, change)
    row = score_run(CASE, run, REFERENCE, 'rag')
    assert not row[metric]
    assert not row['passed']


def test_conflict_retains_raw_error_and_failure_denominator(run):
    change_raw(run, lambda answer: answer['amounts'][0].update(value='999'))
    run.update(status='conflict', answer=None, error_code='EXPLANATION_CONFLICT')
    row = score_run(CASE, run, REFERENCE, 'rag')
    stats = summarize([row])['rag']
    assert stats['model_attempted'] == 1
    assert stats['delivered_failed'] == 1
    assert stats['raw_numeric_pass']['fraction'] == 0


def test_a_pair_of_wrong_answers_can_be_consistent(run):
    change_raw(run, lambda answer: answer['amounts'][0].update(value='999'))
    row = score_run(CASE, run, REFERENCE, 'rag')
    stats = summarize([row, deepcopy(row)])['rag']
    assert stats['repeat_consistency'][CASE['case_id']]['majority_fraction_with_failures'] == 1
    assert stats['raw_numeric_pass']['fraction'] == 0


def test_missing_trace_blocks_delivery_even_with_matching_model_values(run):
    run['retrieval_trace'] = []
    row = score_run(CASE, run, REFERENCE, 'rag')
    assert row['raw_numeric_pass']
    assert not row['traceable']
    assert not row['delivered_valid']


def test_guard_cases_are_local_and_separate_from_model_denominator():
    case = next(case for case in STUDY['cases'] if case['kind'] == 'local_guard')
    run = asyncio.run(run_fertilizer_assistant(path='rag', question=case['question']))
    row = score_run(case, run, REFERENCE, 'rag')
    stats = summarize([row])['rag']
    assert row['guard_pass']
    assert stats['guard_passed'] == 1
    assert stats['model_attempted'] == 0
    assert stats['raw_numeric_pass']['fraction'] is None
    run['responses'] = [{'status': 'completed', 'output': []}]
    assert not score_run(case, run, REFERENCE, 'rag')['guard_pass']


def test_latest_incomplete_response_does_not_fall_back_to_older_success(run):
    run['responses'].append({'status': 'incomplete', 'output': []})
    assert raw_answer(run) is None


def test_null_only_matches_null():
    assert same_value(None, None)
    assert not same_value('0', None)
    assert not same_value(None, '0')


def test_suite_reanalysis_and_missing_logs(tmp_path):
    pytest.importorskip('mcp')
    summary = asyncio.run(run_delivery_suite(tmp_path, repeats=1,
                         case_ids=['prescription_full', 'unregistered_parcel']))
    assert summary['all_passed']
    assert analyze_delivery(tmp_path) == summary
    assert (tmp_path / 'results.csv').is_file()
    (tmp_path / '01_prescription_full_rag.json').unlink()
    summary = analyze_delivery(tmp_path)
    assert not summary['all_passed']
    assert summary['statistics']['rag']['model_attempted'] == 1
    assert summary['statistics']['rag']['delivered_failed'] == 1
    assert summary['statistics']['rag']['raw_numeric_pass']['fraction'] == 0
    assert summary['conditions_failed'] == 1
    # Source artifacts are pinned, too; a changed saved evidence file blocks all comparisons.
    (tmp_path / 'evidence.json').write_text('{}', encoding='utf-8')
    assert analyze_delivery(tmp_path)['conditions_failed'] == 4
