import asyncio
from copy import deepcopy
import json
import sys

import pytest

from agri_dss.assistant import digest, run_fertilizer_assistant
from agri_dss.cli import main
from agri_dss.explanation import explanation_from_prescription
from agri_dss.fertilizer import load_selected_prescription
from agri_dss.llm import MockModel, ModelError, ModelReply
from agri_dss.rag import build_corpus, rag_conversation, retrieve_prescription
from agri_dss.routing import route_question


class CapturingModel(MockModel):
    def __init__(self, raw=None, error=None):
        self.raw, self.error, self.calls = raw, error, []

    async def complete(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if self.error:
            raise ModelError(self.error)
        return ModelReply(self.raw) if self.raw is not None else await super().complete(**kwargs)


def run_rag(model, corpus=None):
    selected = load_selected_prescription()
    result = {'manifest': {}, 'responses': [], 'tool_trace': [], 'answer': None}
    route = route_question('비료 처방', selected.pnu_code, selected.requested_crop_code)
    asyncio.run(rag_conversation(model, selected, '비료 처방', route, result, corpus=corpus))
    return result


def test_rag_uses_same_evidence_without_tools_or_mcp(monkeypatch):
    monkeypatch.setitem(sys.modules, 'mcp', None)
    model = CapturingModel()
    result = asyncio.run(run_fertilizer_assistant(model=model, path='rag'))
    assert result['status'] == 'completed'
    assert result['explanation_check']['passed']
    assert result['manifest']['model_calls'] == 1
    assert result['manifest']['tool_calls'] == 0
    call = model.calls[0]
    assert call['tools'] == []
    document = json.loads(call['input'][0]['content'])['retrieved_documents'][0]
    assert digest(document['content']) == result['manifest']['normalized_evidence_sha256']
    assert document['source_sha256'] == result['manifest']['source_sha256']
    assert '14.4 / 3.0 / 3.0 kg/10a' in result['answer']


@pytest.mark.parametrize('pnu,crop', [('5211110100100120003', '04017'),
                                     ('5271033027105280033', '00001')])
def test_metadata_retrieval_never_falls_back(pnu, crop):
    assert retrieve_prescription(build_corpus(load_selected_prescription()), pnu, crop) == []


@pytest.mark.parametrize('kind', ['empty', 'duplicate', 'tampered', 'different_content'])
def test_retrieval_failure_stops_before_model(kind):
    corpus = build_corpus(load_selected_prescription())
    if kind == 'empty':
        corpus = []
    elif kind == 'duplicate':
        corpus += deepcopy(corpus)
    else:
        corpus[0]['content']['amounts']['basal_n']['value'] = '999'
        if kind == 'different_content':
            corpus[0]['content_sha256'] = digest(corpus[0]['content'])
    model = CapturingModel()
    result = run_rag(model, corpus)
    assert result['status'] == 'retrieval_error'
    assert result['answer'] is None
    assert not model.calls


@pytest.mark.parametrize('kind,error', [
    ('conflict', 'EXPLANATION_CONFLICT'), ('invalid', 'INVALID_ANSWER_SCHEMA'),
    ('incomplete', 'MODEL_RESPONSE_INCOMPLETE'), ('refusal', 'MODEL_REFUSAL'),
    ('tool', 'RAG_TOOL_CALL_FORBIDDEN'), ('network', 'OPENAI_NETWORK_ERROR')])
def test_rag_failures_are_recorded_without_rendering(kind, error):
    answer = explanation_from_prescription(load_selected_prescription())
    answer.amounts[0].value = '999'
    raw = {'status': 'completed', 'output': [{'type': 'message', 'content': [
        {'type': 'output_text', 'text': answer.model_dump_json() if kind == 'conflict' else '{}'}]}]}
    if kind == 'incomplete':
        raw['status'] = 'incomplete'
    if kind == 'refusal':
        raw['output'][0]['content'] = [{'type': 'refusal', 'refusal': 'test'}]
    if kind == 'tool':
        raw['output'] = [{'type': 'function_call', 'name': 'read_file'}]
    result = run_rag(CapturingModel(raw, error if kind == 'network' else None))
    assert result['error_code'] == error
    assert result['answer'] is None
    assert len(result['responses']) == (0 if kind == 'network' else 1)


@pytest.mark.parametrize('question,status,calls', [
    ('비료 처방과 내일 강수량', 'partial', 1),
    ('오늘 관수가 필요한가?', 'deferred', 0),
    ('PNU 5211110100100120003의 비료 처방', 'deferred', 0)])
def test_rag_shares_support_boundaries(question, status, calls):
    result = asyncio.run(run_fertilizer_assistant(question=question, path='rag'))
    assert result['status'] == status
    assert result['manifest']['model_calls'] == calls
    assert result['manifest']['tool_calls'] == 0
    if status == 'partial':
        assert 'weather_unavailable' in result['structured_answer']['notices']


def test_rag_cli_saves_full_record(monkeypatch, capsys, tmp_path):
    output = tmp_path / 'rag.json'
    monkeypatch.setattr('sys.argv', ['agri-dss', 'ask', '--path', 'rag', '--output', str(output)])
    assert main() == 0
    record = json.loads(output.read_text(encoding='utf-8'))
    assert record['manifest']['evidence_path'] == 'rag'
    assert record['retrieval_trace'][0]['document_id'].startswith('fertilizer:')
    assert '14.4' in capsys.readouterr().out
