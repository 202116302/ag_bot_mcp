import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

from agri_dss.environment_assistant import run_environment_assistant
from agri_dss.environment_audit import audit_environment
from agri_dss.fertilizer import ROOT
from agri_dss.smartfarm import SNAPSHOT_PATH
from scripts.run_environment_experiment import (SCENARIOS, aggregate, analyze, canonical_answer,
                                                run_study, score)

STUDY = json.loads(SCENARIOS.read_text(encoding='utf-8'))


def test_independent_raw_audit_confirms_references_but_not_units():
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding='utf-8'))
    audit = audit_environment(snapshot, STUDY['expected_fields'])
    assert audit['passed']
    for code in ('TI','HI','CI'):
        field = audit['fields'][code]
        assert field['record_count'] == 24
        assert field['observed_wall_clock_intervals_seconds'] == [3600]
        assert field['first_timestamp'] == '2023-07-25 00:00:00'
        assert field['last_timestamp'] == '2023-07-25 23:00:00'
        assert field['unit_confirmed'] is False
        assert field['timezone_confirmed'] is False
        assert field['aggregation_confirmed'] is False
    assert audit['fields']['HI02']['record_count'] == 0


def test_bad_reference_and_changed_normalized_value_are_detected():
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding='utf-8'))
    fields = deepcopy(STUDY['expected_fields'])
    fields['TI']['minimum'] = '999'
    result = audit_environment(snapshot, fields)
    assert not result['passed']
    assert 'reference_minimum_mismatch' in result['fields']['TI']['errors']
    snapshot['fields']['TI']['observations'][0]['value'] = None
    result = audit_environment(snapshot, STUDY['expected_fields'])
    assert 'raw_normalized_record_mismatch' in result['fields']['TI']['errors']


def test_audit_catches_source_change_and_wrong_request(tmp_path):
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding='utf-8'))
    for code, field in snapshot['fields'].items():
        source = tmp_path / field['source_record']
        source.parent.mkdir(parents=True, exist_ok=True)
        raw = json.loads((ROOT / field['source_record']).read_text(encoding='utf-8'))
        if code == 'TI':
            raw['arguments'][0] = 'OTHER_FARM'
        source.write_text(json.dumps(raw), encoding='utf-8')
    result = audit_environment(snapshot, STUDY['expected_fields'], root=tmp_path)
    assert not result['passed']
    assert 'source_hash_mismatch' in result['fields']['TI']['errors']
    assert 'request_identity_mismatch' in result['fields']['TI']['errors']


def test_canonical_consistency_keeps_errors_but_ignores_order_and_decimal_format():
    answer = {'fields':[{'code':'TI','minimum':'24.670','maximum':'32.33'}],
              'citations':['b','a'], 'limitations':['y','x']}
    same = deepcopy(answer)
    same['fields'][0]['minimum']='24.67'
    same['citations'].reverse()
    assert canonical_answer(answer)==canonical_answer(same)
    same['fields'][0]['maximum']='999'
    assert canonical_answer(answer)!=canonical_answer(same)
    same['fields'][0]['maximum']='NaN'
    assert canonical_answer(same) is None


def test_study_offline_reanalysis_missing_logs_and_artifact_changes(tmp_path):
    pytest.importorskip('mcp')
    result = asyncio.run(run_study(tmp_path, repeats=1, case_ids=['humidity','different_facility']))
    assert result['all_passed']
    assert analyze(tmp_path)==result
    assert (tmp_path/'results.csv').is_file()
    assert result['statistics']['rag']['model_attempted']==1
    assert result['statistics']['rag']['guard_attempted']==1
    (tmp_path/'01_humidity_rag.json').unlink()
    result=analyze(tmp_path)
    assert not result['all_passed']
    assert result['statistics']['rag']['delivered_valid']['fraction']==0
    assert result['statistics']['rag']['failures_by_code']['LOG_MISSING_OR_INVALID']==1
    (tmp_path/'snapshot.json').write_text('{}',encoding='utf-8')
    assert analyze(tmp_path)['conditions_failed']==4


def test_raw_citation_error_is_measured_even_when_runtime_answer_is_clean(tmp_path):
    pytest.importorskip('mcp')
    asyncio.run(run_study(tmp_path, repeats=1, case_ids=['humidity']))
    protocol=json.loads((tmp_path/'protocol.json').read_text(encoding='utf-8'))
    run=json.loads((tmp_path/'01_humidity_rag.json').read_text(encoding='utf-8'))
    answer=json.loads(run['responses'][0]['output'][0]['content'][0]['text'])
    answer['citations']=[]
    run['responses'][0]['output'][0]['content'][0]['text']=json.dumps(answer)
    case=protocol['study']['cases'][0]
    row=score(case,protocol['study'],run,'rag',protocol['pinned'])
    assert row['raw_numeric_pass']
    assert not row['raw_citation_pass']
    assert not row['delivered_valid']
    stats=aggregate([row,deepcopy(row)])['rag']
    assert stats['repeat_consistency']['humidity']['majority_fraction_with_failures']==1
    assert stats['delivered_valid']['fraction']==0
