import operator
from typing import Literal
from ..schemas import Decision, DecisionResult, IrrigationRule, Snapshot


def evaluate_irrigation(
    snapshot: Snapshot | dict,
    rule: IrrigationRule | dict,
    mode: Literal['demo', 'research'] = 'demo',
) -> DecisionResult:
    """Pure evaluation. Invalid contracts raise; missing facts abstain."""
    if mode not in ('demo', 'research'):
        raise ValueError('Unsupported execution mode')
    snapshot = Snapshot.model_validate(snapshot)
    rule = IrrigationRule.model_validate(rule)
    if mode == 'research' and (rule.status != 'verified' or not rule.sources or any(not s.verified for s in rule.sources)):
        raise ValueError('Research requires a verified rule and verified source references')
    result = DecisionResult(
        snapshot_id=snapshot.snapshot_id, snapshot_version=snapshot.version,
        mode=mode, decision=Decision.INSUFFICIENT, decision_code='PENDING',
        rule_id=rule.rule_id, rule_version=rule.version, rule_status=rule.status,
        source_refs=rule.sources, input_source_ids=snapshot.source_ids,
        inputs_used=snapshot.model_dump(include={'crop', 'growth_stage', 'cultivation_system', 'soil_moisture_value', 'soil_moisture_unit'}),
    )
    missing = [k for k in ('crop', 'growth_stage', 'cultivation_system', 'soil_moisture_value', 'soil_moisture_unit') if getattr(snapshot, k) is None]
    if missing:
        return result.model_copy(update={'decision_code': 'MISSING_INPUT', 'missing_fields': missing})
    if not rule.sources:
        return result.model_copy(update={'decision_code': 'MISSING_SOURCE'})
    if rule.threshold is None:
        return result.model_copy(update={'decision_code': 'MISSING_THRESHOLD', 'missing_fields': ['rule.threshold']})
    if rule.status == 'verified' and any(not s.verified for s in rule.sources):
        return result.model_copy(update={'decision_code': 'UNVERIFIED_SOURCE'})
    for field, expected, reason in (
        ('crop', rule.applicable_crop, 'CROP_MISMATCH'),
        ('growth_stage', rule.growth_stage, 'STAGE_MISMATCH'),
        ('cultivation_system', rule.cultivation_system, 'CULTIVATION_MISMATCH'),
        ('soil_moisture_unit', rule.input_unit, 'UNIT_MISMATCH'),
    ):
        if getattr(snapshot, field) != expected:
            return result.model_copy(update={'decision_code': reason})
    if rule.input_unit == 'percent_vwc' and (snapshot.soil_moisture_value > 100 or rule.threshold > 100):
        return result.model_copy(update={'decision_code': 'VALUE_OUT_OF_RANGE'})
    matched = {'<': operator.lt, '<=': operator.le, '>': operator.gt, '>=': operator.ge}[rule.operator](snapshot.soil_moisture_value, rule.threshold)
    return result.model_copy(update={
        'decision': Decision.REQUIRED if matched else Decision.NOT_REQUIRED,
        'decision_code': 'RULE_MATCH' if matched else 'RULE_NOT_MATCH',
        'calculation_steps': [{'input': 'soil_moisture_value', 'value': snapshot.soil_moisture_value,
                               'operator': rule.operator, 'threshold': rule.threshold,
                               'unit': rule.input_unit, 'matched': matched}],
    })
