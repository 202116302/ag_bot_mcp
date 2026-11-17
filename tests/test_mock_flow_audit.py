import json

from scripts.check_mock_flows import ROOT, assess


def cases():
    return {case['case_id']: case for case in json.loads(
        (ROOT / 'configs/scenarios/mock_domain_flows.json').read_text(encoding='utf-8'))['cases']}


def prescription_result():
    return {'status': 'completed', 'tool_trace': [{'name': 'get_fertilizer_prescription'}],
            'structured_answer': {'notices': ['provider_calculated', 'not_irrigation_data']},
            'explanation_check': {'passed': True},
            'manifest': {'model_calls': 2, 'tool_calls': 1}}


def test_accurate_fertilizer_values_do_not_make_weather_route_correct():
    row = assess(cases()['weather_forecast'], prescription_result())
    assert not row['flow_passed']
    assert 'tool_sequence_mismatch' in row['errors']
    assert 'outcome_mismatch' in row['errors']
    assert row['structured_claims_passed'] is True


def test_supported_request_requires_validated_explanation():
    result = prescription_result()
    assert assess(cases()['fertilizer_prescription'], result)['flow_passed']
    result['explanation_check']['passed'] = False
    assert not assess(cases()['fertilizer_prescription'], result)['flow_passed']


def test_partial_answer_requires_notice_for_requested_domain():
    result = prescription_result()
    assert assess(cases()['fertilizer_and_irrigation'], result)['flow_passed']
    weather = assess(cases()['fertilizer_and_weather'], result)
    assert not weather['flow_passed']
    assert weather['errors'] == ['missing_domain_limit_notice']


def test_unregistered_parcel_must_not_receive_default_prescription():
    assert not assess(cases()['unregistered_parcel'], prescription_result())['flow_passed']
    deferred = {'status': 'deferred', 'tool_trace': [],
                'manifest': {'model_calls': 0, 'tool_calls': 0}}
    assert assess(cases()['unregistered_parcel'], deferred)['flow_passed']
