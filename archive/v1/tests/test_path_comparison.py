import asyncio
from copy import deepcopy
import json

import pytest

from agri_dss.assistant import run_fertilizer_assistant
from scripts.compare_fertilizer_paths import assess_pair, run_comparison


@pytest.fixture
def runs():
    # One model supplies both paths to isolate assessor behavior from MCP transport.
    rag = asyncio.run(run_fertilizer_assistant(path='rag'))
    return {'mcp': deepcopy(rag), 'rag': rag}


def test_comparison_ignores_claim_order_and_decimal_format(runs):
    answer = runs['rag']['structured_answer']
    answer['amounts'].reverse()
    answer['notices'].reverse()
    next(claim for claim in answer['amounts'] if claim['field'] == 'basal_n')['value'] = '14.40'
    assert assess_pair(runs)['passed']


@pytest.mark.parametrize('field,value', [('source_sha256', 'different'),
                                         ('normalized_evidence_sha256', 'different'),
                                         ('requested_model', 'different'),
                                         ('config', {}), ('question_sha256', 'different')])
def test_different_inputs_or_settings_block_comparison(runs, field, value):
    runs['rag']['manifest'][field] = value
    row = assess_pair(runs)
    assert not row['passed']
    assert field in row['errors']
    assert row['structured_answers_equal'] is None


def test_failure_is_retained_and_never_counted_as_match(runs):
    runs['rag'].update(status='model_error', error_code='OPENAI_HTTP_429')
    row = assess_pair(runs)
    assert not row['passed']
    assert 'rag_run_failed' in row['errors']


def test_local_deferral_is_not_a_model_answer_match(runs):
    for run in runs.values():
        run.update(status='deferred')
        run.pop('structured_answer')
    row = assess_pair(runs)
    assert row['passed']
    assert row['both_answered'] is False
    assert row['structured_answers_equal'] is None


def test_comparison_persists_both_real_paths_and_summary(tmp_path):
    pytest.importorskip('mcp')
    summary = asyncio.run(run_comparison(tmp_path))
    assert summary['passed'] == 1
    assert json.loads((tmp_path / 'summary.json').read_text(encoding='utf-8')) == summary
    mcp = json.loads((tmp_path / '01_mcp.json').read_text(encoding='utf-8'))
    rag = json.loads((tmp_path / '01_rag.json').read_text(encoding='utf-8'))
    assert mcp['manifest']['tool_calls'] == 1
    assert rag['manifest']['tool_calls'] == 0
    assert rag['manifest']['model_calls'] == 1
    assert mcp['manifest']['normalized_evidence_sha256'] == rag['manifest']['normalized_evidence_sha256']
