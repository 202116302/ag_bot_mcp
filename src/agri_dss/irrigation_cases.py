"""Server-owned synthetic inputs; expected labels stay out of runtime context."""
import json

from .fertilizer import ROOT
from .schemas import IrrigationRule, Snapshot

CASES_PATH = ROOT / 'configs/scenarios/irrigation_decisions.json'
RULE_PATH = ROOT / 'configs/rules/demo/irrigation.json'
REFERENCE_PATH = ROOT / 'data/references/demo/irrigation.md'


def load_irrigation_case(case_id: str) -> Snapshot:
    data = json.loads(CASES_PATH.read_text(encoding='utf-8'))
    cases = [case for case in data['cases'] if case['case_id'] == case_id]
    if len(cases) != 1:
        raise ValueError('SYNTHETIC_CASE_NOT_FOUND')
    return Snapshot.model_validate(dict(data['base_snapshot'], **cases[0]['overrides'], snapshot_id=case_id))


def load_demo_rule() -> IrrigationRule:
    return IrrigationRule.model_validate_json(RULE_PATH.read_text(encoding='utf-8'))
