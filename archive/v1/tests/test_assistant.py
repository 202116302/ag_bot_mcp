import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from agri_dss.assistant import conversation, run_fertilizer_assistant
from agri_dss.explanation import (FertilizerExplanation, check_explanation,
                                 explanation_from_prescription, render_explanation, strict_schema)
from agri_dss.fertilizer import load_selected_prescription
from agri_dss.llm import (MockModel, ModelError, ModelReply, OpenAIModel,
                         load_llm_config, read_openai_key)


@pytest.fixture
def evidence():
    return load_selected_prescription()


@pytest.mark.parametrize('field,value,error', [
    ('basal_n', '99', 'basal_n_value_mismatch'),
    ('topdressing_k', None, 'topdressing_k_value_mismatch'),
    ('basal_n', 'NaN', 'basal_n_value_mismatch'),
])
def test_claim_conflicts_block_rendering(evidence, field, value, error):
    answer = explanation_from_prescription(evidence)
    next(claim for claim in answer.amounts if claim.field == field).value = value
    assert error in check_explanation(answer, evidence)
    with pytest.raises(ValueError, match='EXPLANATION_CONFLICT'):
        render_explanation(answer, evidence)


@pytest.mark.parametrize('change,error', [('unit', 'basal_n_unit_mismatch'),
                                        ('duplicate', 'amount_fields_mismatch'),
                                        ('source', 'source_sha256_mismatch'),
                                        ('notices', 'notices_mismatch')])
def test_other_claim_conflicts(evidence, change, error):
    answer = explanation_from_prescription(evidence)
    if change == 'unit':
        answer.amounts[0].unit = 'kg/ha'
    elif change == 'duplicate':
        answer.amounts.append(answer.amounts[0])
    elif change == 'source':
        answer.source_sha256 = 'wrong-source'
    else:
        answer.notices.pop()
    assert error in check_explanation(answer, evidence)


class FakeSession:
    def __init__(self, evidence, fail=False):
        self.evidence = evidence
        self.calls = []
        self.fail = fail

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name='get_fertilizer_prescription',
                 description='Read saved prescription', inputSchema={'type': 'object', 'properties': {
                     'pnu_code': {'type': 'string'}, 'crop_code': {'type': 'string'}}})])

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return SimpleNamespace(isError=self.fail, structuredContent=self.evidence.model_dump(mode='json'))


def run_conversation(evidence, model, config=None, fail=False):
    session = FakeSession(evidence, fail)
    result = {'manifest': {}, 'responses': [], 'tool_trace': [], 'answer': None}
    asyncio.run(conversation(session, model, config or load_llm_config(), evidence, '비료 처방을 알려줘', result))
    return result, session


class ScriptedModel(MockModel):
    def __init__(self, replies):
        self.replies = iter(replies)

    async def complete(self, **kwargs):
        return ModelReply(deepcopy(next(self.replies)))


def tool_reply(evidence, **overrides):
    call = {'type': 'function_call', 'call_id': 'test-1', 'name': 'get_fertilizer_prescription',
            'arguments': json.dumps({'pnu_code': evidence.pnu_code,
                                     'crop_code': evidence.requested_crop_code})}
    call.update(overrides)
    return {'status': 'completed', 'output': [call]}


def test_tool_selection_then_evidence_then_answer(evidence):
    result, session = run_conversation(evidence, MockModel())
    assert result['status'] == 'completed'
    assert len(session.calls) == 1
    assert len(result['responses']) == 2
    assert result['explanation_check']['passed']
    assert '14.4 / 3.0 / 3.0 kg/10a' in result['answer']


def test_answer_without_tool_is_blocked(evidence):
    result, session = run_conversation(evidence, ScriptedModel([{'status': 'completed', 'output': []}]))
    assert result['status'] == 'no_tool_used'
    assert result['answer'] is None
    assert not session.calls


@pytest.mark.parametrize('call_override,error', [
    ({'name': 'read_file'}, 'INVALID_TOOL_CALL'),
    ({'arguments': '{invalid'}, 'INVALID_TOOL_ARGUMENTS'),
    ({'arguments': '{"pnu_code":"../API_key.txt","crop_code":"04017"}'}, 'INVALID_TOOL_ARGUMENTS'),
    ({'arguments': '{"pnu_code":"5211110100100120003","crop_code":"04017"}'}, 'UNSELECTED_PRESCRIPTION'),
    ({'call_id': ''}, 'INVALID_TOOL_CALL'),
])
def test_unapproved_tools_or_arguments_never_execute(evidence, call_override, error):
    result, session = run_conversation(evidence, ScriptedModel([tool_reply(evidence, **call_override)]))
    assert result['error_code'] == error
    assert not session.calls


def test_tool_failure_is_not_success(evidence):
    result, _ = run_conversation(evidence, MockModel(), fail=True)
    assert result['error_code'] == 'MCP_TOOL_FAILED'
    assert result['answer'] is None


def test_model_call_limit(evidence):
    config = load_llm_config().model_copy(update={'max_model_calls': 1})
    result, session = run_conversation(evidence, MockModel(), config)
    assert result['error_code'] == 'MODEL_CALL_LIMIT'
    assert len(session.calls) == 1


def test_duplicate_call_ids_are_rejected(evidence):
    reply = tool_reply(evidence)
    result, session = run_conversation(evidence, ScriptedModel([reply, reply]))
    assert result['error_code'] == 'INVALID_TOOL_CALL'
    assert len(session.calls) == 1


def test_model_conflict_never_shown_as_answer(evidence):
    answer = explanation_from_prescription(evidence)
    answer.amounts[0].value = '999'
    final = {'status': 'completed', 'output': [{'type': 'message', 'content': [
        {'type': 'output_text', 'text': answer.model_dump_json()}]}]}
    result, _ = run_conversation(evidence, ScriptedModel([tool_reply(evidence), final]))
    assert result['status'] == 'conflict'
    assert result['answer'] is None
    assert not result['explanation_check']['passed']


@pytest.mark.parametrize('reply,error', [
    ({'status': 'incomplete', 'output': []}, 'MODEL_RESPONSE_INCOMPLETE'),
    ({'status': 'completed', 'output': [{'type': 'message', 'content': [
        {'type': 'refusal', 'refusal': 'No'}]}]}, 'MODEL_REFUSAL'),
])
def test_incomplete_and_refusal(evidence, reply, error):
    result, _ = run_conversation(evidence, ScriptedModel([reply]))
    assert result['error_code'] == error


def test_keys_env_then_local_dotenv_without_exposing_values(monkeypatch, tmp_path):
    monkeypatch.setattr('agri_dss.llm.ROOT', tmp_path)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    with pytest.raises(ModelError, match='OPENAI_API_KEY_MISSING'):
        read_openai_key()
    (tmp_path / '.env').write_text('OPENAI_API_KEY="test-only-local"\n', encoding='utf-8')
    assert read_openai_key() == 'test-only-local'
    monkeypatch.setenv('OPENAI_API_KEY', 'test-only-env')
    assert read_openai_key() == 'test-only-env'


def test_responses_request_and_reasoning_items_preserved(monkeypatch):
    captured = {}
    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return SimpleNamespace(status_code=200, text=json.dumps({
            'status': 'completed', 'model': 'gpt-5.4-mini-2026-03-17',
            'output': [], 'usage': {'input_tokens': 10, 'output_tokens': 2}}))
    monkeypatch.setattr('agri_dss.llm.requests.post', post)
    model = OpenAIModel(load_llm_config(), api_key='test-only')
    inputs = [{'type': 'reasoning', 'id': 'rs_1', 'summary': []}]
    reply = asyncio.run(model.complete(instructions='test', input=inputs, tools=[], schema={}))
    assert captured['url'] == 'https://api.openai.com/v1/responses'
    payload = captured['json']
    assert payload['input'] == inputs
    assert payload['reasoning'] == {'effort': 'none'}
    assert payload['store'] is False
    assert payload['parallel_tool_calls'] is False
    assert payload['text']['format']['strict'] is True
    assert reply.raw['usage']['input_tokens'] == 10


@pytest.mark.parametrize('http_status', [401, 429, 500])
def test_api_errors_do_not_expose_response_body(monkeypatch, http_status):
    monkeypatch.setattr('agri_dss.llm.requests.post', lambda *a, **kw:
                        SimpleNamespace(status_code=http_status, text='test-secret-must-not-appear'))
    model = OpenAIModel(load_llm_config(), api_key='test-secret')
    with pytest.raises(ModelError, match='^OPENAI_HTTP_' + str(http_status) + '$'):
        asyncio.run(model.complete(instructions='', input=[], tools=[], schema={}))


def test_model_response_echoed_key_is_redacted(monkeypatch):
    monkeypatch.setattr('agri_dss.llm.requests.post', lambda *a, **kw:
        SimpleNamespace(status_code=200, text='{"output":[],"echo":"test-secret"}'))
    reply = asyncio.run(OpenAIModel(load_llm_config(), api_key='test-secret').complete(
        instructions='', input=[], tools=[], schema={}))
    assert 'test-secret' not in json.dumps(reply.raw)


def test_structured_schema_requires_every_field():
    schema = strict_schema(FertilizerExplanation.model_json_schema())
    assert schema['additionalProperties'] is False
    assert set(schema['required']) == set(schema['properties'])
    assert schema['$defs']['AmountClaim']['additionalProperties'] is False


def test_real_mcp_mock_assistant_roundtrip():
    pytest.importorskip('mcp')
    result = asyncio.run(run_fertilizer_assistant())
    assert result['status'] == 'completed'
    assert result['manifest']['synthetic_model'] is True
    assert result['manifest']['model_calls'] == 2
    assert result['manifest']['tool_calls'] == 1
    assert result['tool_trace'][0]['result']['amounts']['basal_n']['value'] == '14.4'
