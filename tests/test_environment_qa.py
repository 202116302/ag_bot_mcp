import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from agri_dss.cli import main
from agri_dss.fertilizer import ROOT as ROOT_PATH
from agri_dss.environment_assistant import (EnvironmentMockModel, answer_from_context,
    mcp_environment, run_environment_assistant, select_question)
from agri_dss.environment_context import (CATALOG_PATH, build_environment_context, load_catalog)
from agri_dss.llm import ModelError, ModelReply, load_llm_config
from agri_dss.smartfarm import SNAPSHOT_ID
from scripts.check_environment_qa import assess, run_suite

SELECTION = {'snapshot_id': SNAPSHOT_ID, 'topics': ['humidity'], 'tomato_type': 'unspecified'}


class ScriptedModel(EnvironmentMockModel):
    def __init__(self, replies=None, error=None):
        self.replies, self.error, self.calls = iter(replies or []), error, []

    async def complete(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if self.error:
            raise ModelError(self.error)
        return ModelReply(deepcopy(next(self.replies)))


def final_reply(context, change=None):
    answer = answer_from_context(context).model_dump(mode='json')
    if change:
        change(answer)
    return {'status': 'completed', 'output': [{'type': 'message', 'content': [
        {'type': 'output_text', 'text': json.dumps(answer)}]}]}


def tool_reply(**overrides):
    call = {'type': 'function_call', 'name': 'get_environment_context', 'call_id': 'test-1',
            'arguments': json.dumps(SELECTION)}
    call.update(overrides)
    return {'status': 'completed', 'output': [call]}


class Session:
    def __init__(self):
        self.calls = []
        self.context = build_environment_context(**SELECTION)
        self.fail = False

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name='get_environment_context', description='Read context',
                 inputSchema={'type': 'object', 'properties': {'snapshot_id': {'type': 'string'},
                     'tomato_type': {'type': 'string'}, 'topics': {'type': 'array', 'items': {'type': 'string'}}}})])

    async def call_tool(self, name, args):
        self.calls.append(args)
        return SimpleNamespace(isError=self.fail, structuredContent=self.context)


def call_mcp(model, session=None, config=None):
    session = session or Session()
    result = {'manifest': {}, 'responses': [], 'tool_trace': [], 'answer': None}
    asyncio.run(mcp_environment(session, model, config or load_llm_config(), SELECTION,
                build_environment_context(**SELECTION), '과거 습도 자료', result))
    return result, session


def test_reviewed_excerpts_and_tomato_type_retrieval():
    for type_name, present, absent in (
        ('general', 'tomato-general-temperature-management', 'tomato-cherry-temperature-management'),
        ('cherry', 'tomato-cherry-temperature-management', 'tomato-general-temperature-management')):
        context = build_environment_context(SNAPSHOT_ID, ['temperature'], type_name)
        ids = {chunk['chunk_id'] for chunk in context['literature']}
        assert present in ids and absent not in ids
        assert 'tomato-temperature-adaptation' in ids
        assert context['fields'][0]['minimum'] == '24.67'
        assert 'humidity_semantics_unconfirmed' not in context['limitations']


def test_humidity_missing_and_source_review_are_preserved():
    context = build_environment_context(SNAPSHOT_ID, ['humidity', 'co2'])
    field = next(field for field in context['fields'] if field['code'] == 'HI02')
    assert field['record_count'] == 0 and field['minimum'] is None and field['maximum'] is None
    assert 'co2_source_review_required' in context['limitations']
    assert 'humidity_semantics_unconfirmed' in context['limitations']


def test_changed_excerpt_is_rejected(monkeypatch, tmp_path):
    catalog = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    catalog['chunks'][0]['text'] = 'fabricated text'
    file = tmp_path / 'catalog.json'
    file.write_text(json.dumps(catalog), encoding='utf-8')
    monkeypatch.setattr('agri_dss.environment_context.CATALOG_PATH', file)
    with pytest.raises(ValueError, match='CHUNK_CHANGED'):
        load_catalog()


def test_rag_receives_raw_records_without_python_min_max(monkeypatch):
    context = build_environment_context(**SELECTION)
    model = ScriptedModel([final_reply(context)])
    monkeypatch.setitem(__import__('sys').modules, 'mcp', None)
    result = asyncio.run(run_environment_assistant(path='rag', question='과거 습도 자료', model=model))
    assert result['status'] == 'partial'
    assert result['explanation_check']['passed']
    call = model.calls[0]
    assert call['tools'] == []
    user = json.loads(call['input'][0]['content'])
    assert set(user['raw_environment']['fields']) == {'HI', 'HI02'}
    assert user['output_contract'] == {'field_codes': ['HI', 'HI02'], 'citation_ids': ['tomato-air-humidity']}
    assert 'observations' in user['raw_environment']['fields']['HI']
    assert 'minimum' not in call['input'][0]['content']
    assert 'maximum' not in call['input'][0]['content']
    assert '65∼80%' in result['answer']
    assert '환기·난방' in result['answer']


@pytest.mark.parametrize('change,error', [
    (lambda answer: answer['fields'][0].update(minimum='0'), 'ENVIRONMENT_ANSWER_CONFLICT'),
    (lambda answer: answer['fields'][1].update(minimum='0'), 'ENVIRONMENT_ANSWER_CONFLICT'),
    (lambda answer: answer['fields'][0].update(unit='%'), 'INVALID_ENVIRONMENT_ANSWER'),
    (lambda answer: answer.update(assessment='suitable'), 'INVALID_ENVIRONMENT_ANSWER'),
    (lambda answer: answer['citations'].append('wrong-page'), 'ENVIRONMENT_ANSWER_CONFLICT'),
    (lambda answer: answer['limitations'].pop(), 'ENVIRONMENT_ANSWER_CONFLICT'),
    (lambda answer: answer.update(observation_date='2026-11-16'), 'ENVIRONMENT_ANSWER_CONFLICT'),
    (lambda answer: answer['fields'].append(answer['fields'][0]), 'ENVIRONMENT_ANSWER_CONFLICT'),
    (lambda answer: answer['fields'][0].update(maximum='NaN'), 'ENVIRONMENT_ANSWER_CONFLICT')])
def test_false_values_units_citations_assessments_never_render(change, error):
    context = build_environment_context(**SELECTION)
    result = asyncio.run(run_environment_assistant(path='rag', question='과거 습도 자료',
                         model=ScriptedModel([final_reply(context, change)])))
    assert result['error_code'] == error
    assert result['answer'] is None


@pytest.mark.parametrize('question', ['오늘 온실 환기창을 열어줘', '토마토 관수해줘', '딸기 온도 문헌',
    'PNU 5271033027105280033의 온도', '2025-07-25 온도 자료', 'PFS_0000002_01의 온도', '안녕'])
def test_scope_guards_stop_before_model_or_tools(question):
    result = asyncio.run(run_environment_assistant(provider='openai', path='rag', question=question))
    assert result['status'] == 'deferred'
    assert result['manifest']['model_calls'] == result['manifest']['tool_calls'] == 0
    assert not result['retrieval_trace']


@pytest.mark.parametrize('override,error', [
    ({'name': 'read_file'}, 'INVALID_TOOL_CALL'), ({'arguments': '{}'}, 'INVALID_TOOL_ARGUMENTS'),
    ({'arguments': json.dumps(dict(SELECTION, snapshot_id='../API_key.txt'))}, 'UNSELECTED_ENVIRONMENT_CONTEXT'),
    ({'arguments': json.dumps(dict(SELECTION, topics=['temperature']))}, 'UNSELECTED_ENVIRONMENT_CONTEXT')])
def test_tool_calls_checked_before_execution(override, error):
    result, session = call_mcp(ScriptedModel([tool_reply(**override)]))
    assert result['error_code'] == error
    assert not session.calls


def test_mcp_requires_tool_and_preserves_call_limits_and_evidence():
    context = build_environment_context(**SELECTION)
    result, _ = call_mcp(ScriptedModel([final_reply(context)]))
    assert result['error_code'] == 'ANSWER_WITHOUT_EVIDENCE'
    result, session = call_mcp(ScriptedModel([tool_reply(), tool_reply()]))
    assert result['error_code'] == 'INVALID_TOOL_CALL'
    assert len(session.calls) == 1
    session = Session()
    session.context['fields'][0]['minimum'] = '999'
    result, _ = call_mcp(ScriptedModel([tool_reply()]), session)
    assert result['error_code'] == 'ENVIRONMENT_EVIDENCE_MISMATCH'
    session = Session()
    session.fail = True
    result, _ = call_mcp(ScriptedModel([tool_reply()]), session)
    assert result['error_code'] == 'MCP_TOOL_FAILED'


def test_mcp_tool_schema_pins_selection_without_numeric_answers():
    context = build_environment_context(**SELECTION)
    model = ScriptedModel([tool_reply(), final_reply(context)])
    result, _ = call_mcp(model)
    assert result['status'] == 'partial'
    properties = model.calls[0]['tools'][0]['parameters']['properties']
    assert properties['snapshot_id']['enum'] == [SNAPSHOT_ID]
    assert properties['tomato_type']['enum'] == ['unspecified']
    assert properties['topics']['items']['enum'] == ['humidity']
    assert 'minimum' not in json.dumps(properties)


@pytest.mark.parametrize('raw,error', [
    ({'status': 'incomplete', 'output': []}, 'MODEL_RESPONSE_INCOMPLETE'),
    ({'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal'}]}]}, 'MODEL_REFUSAL'),
    ({'status': 'completed', 'output': [{'type': 'function_call'}]}, 'RAG_TOOL_CALL_FORBIDDEN'),
    ({'status': 'completed', 'output': []}, 'INVALID_ENVIRONMENT_ANSWER')])
def test_rag_response_failures_retained(raw, error):
    result = asyncio.run(run_environment_assistant(path='rag', question='과거 습도 자료', model=ScriptedModel([raw])))
    assert result['error_code'] == error
    assert result['responses'] == [raw]
    assert result['answer'] is None


def test_network_error_retained_without_success():
    result = asyncio.run(run_environment_assistant(path='rag', model=ScriptedModel(error='OPENAI_NETWORK_ERROR')))
    assert result['status'] == 'model_error'
    assert result['error_code'] == 'OPENAI_NETWORK_ERROR'
    assert result['answer'] is None


def test_cli_saves_full_record_and_renders_reference(monkeypatch, tmp_path, capsys):
    path = tmp_path / 'answer.json'
    monkeypatch.setattr('sys.argv', ['agri-dss', 'environment-ask', '--path', 'rag', '--question',
                                  '일반토마토 온도 문헌과 과거 자료', '--output', str(path)])
    assert main() == 0
    run = json.loads(path.read_text(encoding='utf-8'))
    assert run['status'] == 'partial'
    text = capsys.readouterr().out
    assert 'PDF 77쪽' in text and 'PDF 91쪽' not in text
    assert '2023-07-25' in text


def test_real_mcp_roundtrip():
    pytest.importorskip('mcp')
    run = asyncio.run(run_environment_assistant(question='방울토마토 온도 문헌과 과거 자료'))
    assert run['status'] == 'partial'
    assert run['manifest']['model_calls'] == 2
    assert run['manifest']['tool_calls'] == 1
    assert 'PDF 91쪽' in run['answer']


def test_fixed_scenario_assessor_counts_raw_error_even_if_runtime_passed():
    study = json.loads((ROOT_PATH / 'configs/scenarios/environment_qa.json').read_text(encoding='utf-8'))
    case = next(case for case in study['cases'] if case['case_id'] == 'humidity')
    run = asyncio.run(run_environment_assistant(path='rag', question=case['question']))
    answer = json.loads(run['responses'][0]['output'][0]['content'][0]['text'])
    answer['fields'][0]['maximum'] = '999'
    run['responses'][0]['output'][0]['content'][0]['text'] = json.dumps(answer)
    assert not assess(case, study['expected_fields'], run, 'rag')['passed']


