from copy import deepcopy
from pathlib import Path
import json
import math
import pytest
from pydantic import ValidationError
from agri_dss.rules import evaluate_irrigation
from agri_dss.schemas import Decision, Snapshot

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs():
    return (
        json.loads((ROOT / 'data/snapshots/demo_irrigation.json').read_text(encoding='utf-8')),
        json.loads((ROOT / 'configs/rules/demo/irrigation.json').read_text(encoding='utf-8')),
    )


@pytest.mark.parametrize('op,value,required', [
    ('<', 19.0, True), ('<', 20.0, False), ('<', 21.0, False),
    ('<=', 19.0, True), ('<=', 20.0, True), ('<=', 21.0, False),
    ('>', 19.0, False), ('>', 20.0, False), ('>', 21.0, True),
    ('>=', 19.0, False), ('>=', 20.0, True), ('>=', 21.0, True),
])
def test_boundary(inputs, op, value, required):
    snapshot, rule = inputs
    snapshot['soil_moisture_value'] = value
    rule['operator'] = op
    result = evaluate_irrigation(snapshot, rule)
    assert result.decision == (Decision.REQUIRED if required else Decision.NOT_REQUIRED)
    assert result.calculation_steps[0]['matched'] is required


@pytest.mark.parametrize('field', ['crop', 'growth_stage', 'cultivation_system', 'soil_moisture_value', 'soil_moisture_unit'])
def test_missing_is_abstention(inputs, field):
    snapshot, rule = inputs
    snapshot.pop(field)
    result = evaluate_irrigation(snapshot, rule)
    assert result.decision == Decision.INSUFFICIENT
    assert field in result.missing_fields


@pytest.mark.parametrize('field,value,code', [
    ('crop', 'other', 'CROP_MISMATCH'),
    ('growth_stage', 'other', 'STAGE_MISMATCH'),
    ('cultivation_system', 'hydroponic', 'CULTIVATION_MISMATCH'),
    ('soil_moisture_unit', 'kpa_tension', 'UNIT_MISMATCH'),
    ('soil_moisture_value', 101.0, 'VALUE_OUT_OF_RANGE'),
])
def test_invalid_applicability(inputs, field, value, code):
    snapshot, rule = inputs
    snapshot[field] = value
    result = evaluate_irrigation(snapshot, rule)
    assert result.decision == Decision.INSUFFICIENT
    assert result.decision_code == code


@pytest.mark.parametrize('value', [-1.0, math.nan, math.inf, True, '18'])
def test_malformed_numbers_rejected(inputs, value):
    snapshot, _ = inputs
    snapshot['soil_moisture_value'] = value
    with pytest.raises(ValidationError):
        Snapshot.model_validate(snapshot)


def test_zero_is_valid(inputs):
    snapshot, rule = inputs
    snapshot['soil_moisture_value'] = 0.0
    assert evaluate_irrigation(snapshot, rule).decision == Decision.REQUIRED


def test_determinism_provenance_and_no_mutation(inputs):
    snapshot, rule = inputs
    before = deepcopy(inputs)
    results = [evaluate_irrigation(snapshot, rule).model_dump_json() for _ in range(100)]
    assert len(set(results)) == 1
    assert inputs == before
    data = json.loads(results[0])
    assert data['rule_status'] == 'demo_only'
    assert data['source_refs'][0]['location'] == 'data/references/demo/irrigation.md'
    assert data['input_source_ids'] == ['synthetic_fixture']
    assert data['calculation_steps'][0]['value'] == 18.0


def test_demo_blocked_in_research(inputs):
    with pytest.raises(ValueError, match='verified'):
        evaluate_irrigation(*inputs, mode='research')


@pytest.mark.parametrize('sources,code', [([], 'MISSING_SOURCE')])
def test_missing_source(inputs, sources, code):
    snapshot, rule = inputs
    rule['sources'] = sources
    assert evaluate_irrigation(snapshot, rule).decision_code == code


def test_missing_threshold(inputs):
    snapshot, rule = inputs
    rule['threshold'] = None
    assert evaluate_irrigation(snapshot, rule).decision_code == 'MISSING_THRESHOLD'


def test_unverified_source_cannot_be_promoted(inputs):
    snapshot, rule = inputs
    rule['status'] = 'verified'
    assert evaluate_irrigation(snapshot, rule).decision_code == 'UNVERIFIED_SOURCE'
    with pytest.raises(ValueError):
        evaluate_irrigation(snapshot, rule, mode='research')


def test_tension_dryness_uses_explicit_greater_operator(inputs):
    snapshot, rule = inputs
    snapshot['soil_moisture_unit'] = rule['input_unit'] = 'kpa_tension'
    snapshot['soil_moisture_value'] = 21.0
    rule['operator'] = '>'
    assert evaluate_irrigation(snapshot, rule).decision == Decision.REQUIRED


def test_unknown_unit_is_contract_error(inputs):
    snapshot, rule = inputs
    snapshot['soil_moisture_unit'] = 'ADC'
    with pytest.raises(ValidationError):
        evaluate_irrigation(snapshot, rule)
