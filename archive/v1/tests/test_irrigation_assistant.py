import asyncio
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from agri_dss.irrigation_assistant import (IrrigationMockModel, QUESTION, run_irrigation_assistant,
                                          tool_conversation)
from agri_dss.irrigation_cases import (CASES_PATH, REFERENCE_PATH, load_demo_rule,
                                      load_irrigation_case)
from agri_dss.llm import ModelReply, load_llm_config
from agri_dss.rules import evaluate_irrigation
from scripts.compare_irrigation_paths import analyze, assess, run_suite


CASES = json.loads(CASES_PATH.read_text(encoding='utf-8'))['cases']


class ScriptedModel(IrrigationMockModel):
    def __init__(self, replies):
        self.replies, self.calls = iter(replies), []

    async def complete(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        return ModelReply(deepcopy(next(self.replies)))


def metadata():
    return {'rule_id': 'irrigation_synthetic_001', 'rule_version': '0.1.0-demo',
            'source_ids': ['synthetic_rule_reference'],
            'source_sha256': hashlib.sha256(REFERENCE_PATH.read_bytes()).hexdigest()}


def final_reply(case_id, decision='IRRIGATION_NOT_REQUIRED', code='RULE_NOT_MATCH', **overrides):
    answer = dict(metadata(), snapshot_id=case_id, decision=decision, decision_code=code, demo_only=True)
    answer.update(overrides)
    return {'status': 'completed', 'output': [{'type': 'message', 'content': [
        {'type': 'output_text', 'text': json.dumps(answer)}]}]}


def call_reply(case_id='SYNTHETIC-EQUAL', **overrides):
    call = {'type': 'function_call', 'call_id': 'test-1', 'name': 'evaluate_irrigation',
            'arguments': json.dumps({'snapshot_id': case_id, 'rule_id': 'irrigation_synthetic_001', 'mode': 'demo'})}
    call.update(overrides)
    return {'status': 'completed', 'output': [call]}


class Session:
    def __init__(self, case_id='SYNTHETIC-EQUAL', fail=False):
        self.calls, self.fail = [], fail
        self.result = evaluate_irrigation(load_irrigation_case(case_id), load_demo_rule()).model_dump(mode='json')

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name='evaluate_irrigation', description='Synthetic rule',
                                                     inputSchema={'type': 'object', 'properties': {}})])

    async def call_tool(self, name, arguments):
        self.calls.append(arguments)
        return SimpleNamespace(isError=self.fail, structuredContent=self.result)


def run_tool(model, session=None, config=None):
    session = session or Session()
    result = {'manifest': {}, 'responses': [], 'tool_trace': [], 'answer': None}
    asyncio.run(tool_conversation(session, model, config or load_llm_config(), load_irrigation_case('SYNTHETIC-EQUAL'),
                                 load_demo_rule(), metadata(), result))
    return result, session


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['case_id'])
def test_fixed_labels_match_engine_and_rag_mock(case):
    result = asyncio.run(run_irrigation_assistant(path='rag', case_id=case['case_id']))
    assert assess(case, result)['contract_correct']
    assert result['manifest']['tool_calls'] == 0
    assert result['manifest']['synthetic_model']


def test_real_rag_path_does_not_execute_python_rule_or_receive_labels(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('RAG must not call the Python oracle')
    monkeypatch.setattr('agri_dss.rules.evaluate_irrigation', forbidden)
    model = ScriptedModel([final_reply('SYNTHETIC-EQUAL')])
    result = asyncio.run(run_irrigation_assistant(path='rag', case_id='SYNTHETIC-EQUAL', model=model))
    assert result['status'] == 'completed'
    call = model.calls[0]
    assert call['tools'] == []
    context = json.loads(call['input'][0]['content'])
    assert set(context) == {'question', 'snapshot', 'source_metadata', 'retrieved_documents'}
    assert 'expected_decision' not in json.dumps(call)
    assert 'expected_code' not in json.dumps(call)
    assert 'calculation_steps' not in json.dumps(call)
    assert context['retrieved_documents'][0]['content'] == REFERENCE_PATH.read_text(encoding='utf-8')
    assert result['explanation_check']['scope'] == 'metadata_only'


def test_wrong_rag_decision_is_preserved_for_evaluation():
    model = ScriptedModel([final_reply('SYNTHETIC-EQUAL', 'IRRIGATION_REQUIRED', 'RULE_MATCH')])
    result = asyncio.run(run_irrigation_assistant(path='rag', case_id='SYNTHETIC-EQUAL', model=model))
    assert result['status'] == 'completed'
    assert result['structured_answer']['decision'] == 'IRRIGATION_REQUIRED'
    assert not assess(next(case for case in CASES if case['case_id'] == 'SYNTHETIC-EQUAL'), result)['decision_correct']


def test_mcp_cannot_change_python_decision():
    model = ScriptedModel([call_reply(), final_reply('SYNTHETIC-EQUAL', 'IRRIGATION_REQUIRED', 'RULE_MATCH')])
    result, session = run_tool(model)
    assert result['status'] == 'conflict'
    assert result['answer'] is None
    assert 'tool_decision_changed' in result['explanation_check']['errors']
    assert len(session.calls) == 1


@pytest.mark.parametrize('override,error', [
    ({'name': 'read_file'}, 'INVALID_TOOL_CALL'),
    ({'arguments': '{}'}, 'INVALID_TOOL_ARGUMENTS'),
    ({'arguments': json.dumps({'snapshot_id': '../API_key.txt', 'rule_id': 'irrigation_synthetic_001', 'mode': 'demo'})}, 'UNSELECTED_IRRIGATION_CASE'),
    ({'arguments': json.dumps({'snapshot_id': 'SYNTHETIC-EQUAL', 'rule_id': 'irrigation_synthetic_001', 'mode': 'research'})}, 'INVALID_TOOL_ARGUMENTS')])
def test_tool_calls_checked_before_execution(override, error):
    result, session = run_tool(ScriptedModel([call_reply(**override)]))
    assert result['error_code'] == error
    assert not session.calls


def test_answer_without_mcp_and_duplicate_calls_are_blocked():
    result, _ = run_tool(ScriptedModel([final_reply('SYNTHETIC-EQUAL')]))
    assert result['error_code'] == 'ANSWER_WITHOUT_EVIDENCE'
    result, session = run_tool(ScriptedModel([call_reply(), call_reply()]))
    assert result['error_code'] == 'INVALID_TOOL_CALL'
    assert len(session.calls) == 1


@pytest.mark.parametrize('kind,error', [('failure', 'MCP_TOOL_FAILED'),
                                      ('identity', 'IRRIGATION_EVIDENCE_MISMATCH')])
def test_tool_failure_or_changed_inputs_never_become_answers(kind, error):
    session = Session(fail=kind == 'failure')
    if kind == 'identity':
        session.result['inputs_used']['soil_moisture_value'] = 0.0
    result, _ = run_tool(ScriptedModel([call_reply()]), session)
    assert result['error_code'] == error
    assert result['answer'] is None


@pytest.mark.parametrize('raw,error', [
    ({'status': 'incomplete', 'output': []}, 'MODEL_RESPONSE_INCOMPLETE'),
    ({'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal'}]}]}, 'MODEL_REFUSAL'),
    ({'status': 'completed', 'output': [{'type': 'function_call'}]}, 'RAG_TOOL_CALL_FORBIDDEN'),
    ({'status': 'completed', 'output': []}, 'INVALID_IRRIGATION_ANSWER')])
def test_rag_failures_remain_in_record(raw, error):
    result = asyncio.run(run_irrigation_assistant(path='rag', model=ScriptedModel([raw])))
    assert result['error_code'] == error
    assert result['answer'] is None
    assert result['responses'] == [raw]


def test_source_tampering_blocks_rag_output():
    model = ScriptedModel([final_reply('SYNTHETIC-EQUAL', source_sha256='fake')])
    result = asyncio.run(run_irrigation_assistant(path='rag', case_id='SYNTHETIC-EQUAL', model=model))
    assert result['status'] == 'conflict'
    assert result['answer'] is None


def test_real_mcp_registered_case_roundtrip():
    pytest.importorskip('mcp')
    result = asyncio.run(run_irrigation_assistant(case_id='SYNTHETIC-MISSING'))
    assert result['status'] == 'completed'
    assert result['structured_answer']['decision_code'] == 'MISSING_INPUT'
    assert result['manifest']['tool_calls'] == 1


def test_unknown_case_and_real_parcel_are_rejected():
    for case_id in ('../API_key.txt', '5271033027105280033'):
        with pytest.raises(ValueError, match='NOT_FOUND'):
            load_irrigation_case(case_id)


def test_suite_reanalysis_includes_missing_logs_in_denominator(tmp_path):
    pytest.importorskip('mcp')
    summary = asyncio.run(run_suite(tmp_path, case_ids=['SYNTHETIC-EQUAL']))
    assert summary['all_passed']
    assert analyze(tmp_path) == summary
    (tmp_path / '01_SYNTHETIC-EQUAL_rag.json').unlink()
    again = analyze(tmp_path)
    assert not again['all_passed']
    assert again['statistics']['rag']['attempted'] == 1
    assert again['statistics']['rag']['failed'] == 1
    assert again['statistics']['rag']['decision_accuracy_synthetic'] == 0
    assert again['pairs'][0]['decisions_equal'] is None
    assert (tmp_path / 'results.csv').is_file()
