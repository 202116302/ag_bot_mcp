import asyncio

import pytest

from agri_dss.assistant import run_fertilizer_assistant
from agri_dss.routing import route_question

PNU = '5271033027105280033'


@pytest.mark.parametrize('question,domain', [
    ('この圃場の灌水を判断して', None),  # Unrecognized language is conservatively deferred.
    ('밭에 물 줘야 하나?', 'irrigation'),
    ('모레 강수량 예측해줘', 'weather'),
    ('착과 단계인지 확인해줘', 'growth'),
    ('하우스 환기할까?', 'climate_control'),
    ('토양 pH와 유기물을 보여줘', 'soil_chemistry'),
])
def test_unsupported_domains_do_not_call_fertilizer(question, domain):
    route = route_question(question, PNU, '04017')
    assert route.disposition == 'deferred'
    assert not route.can_query_fertilizer
    if domain:
        assert domain in route.blocked_domains


@pytest.mark.parametrize('question', [
    'PNU 5211110100100120003 비료를 알려줘',
    '이 필지 벼 비료 처방을 알려줘',
    '토마토 말고 딸기 시비량을 알려줘',
    '작물코드=00001 비료 처방을 알려줘',
])
def test_explicit_unsupported_identity_overrides_default(question):
    route = route_question(question, PNU, '04017')
    assert route.disposition == 'deferred'
    assert not route.can_query_fertilizer


def test_compound_supported_and_unsupported_parts_are_preserved():
    route = route_question('비료 처방과 내일 날씨, 관수 여부를 알려줘', PNU, '04017')
    assert route.can_query_fertilizer
    assert route.disposition == 'partial'
    assert set(route.blocked_domains) == {'weather', 'irrigation'}
    assert 'weather_unavailable' in route.notices
    assert 'not_irrigation_data' in route.notices


def test_soil_nitrogen_is_not_fertilizer_recommendation():
    route = route_question('토양검정 질소 함량은?', PNU, '04017')
    assert not route.can_query_fertilizer


def test_ambiguous_prescription_does_not_default_to_fertilizer():
    assert not route_question('처방을 알려줘', PNU, '04017').can_query_fertilizer


def test_preflight_defers_without_openai_key_or_mcp(monkeypatch):
    def must_not_initialize(*args, **kwargs):
        raise AssertionError('OpenAI must not be initialized for unsupported requests')
    monkeypatch.setattr('agri_dss.assistant.OpenAIModel', must_not_initialize)
    result = asyncio.run(run_fertilizer_assistant('openai', '이 농장 환기를 해도 될까?'))
    assert result['status'] == 'deferred'
    assert result['manifest']['model_calls'] == 0
    assert result['manifest']['tool_calls'] == 0
    assert '환경제어' in result['answer']


def test_compound_question_real_mcp_roundtrip():
    pytest.importorskip('mcp')
    result = asyncio.run(run_fertilizer_assistant('mock', '비료 처방과 내일 강수량을 함께 알려줘'))
    assert result['status'] == 'partial'
    assert result['explanation_check']['passed']
    assert 'weather_unavailable' in result['structured_answer']['notices']
    assert '기상:' in result['answer']
    assert len(result['tool_trace']) == 1
