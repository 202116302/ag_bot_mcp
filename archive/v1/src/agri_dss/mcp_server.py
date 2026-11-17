"""Local MCP tools over server-owned demo inputs and saved API responses."""
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4
from mcp.server.fastmcp import FastMCP
from .rules import evaluate_irrigation as evaluate_rule
from .schemas import IrrigationRule, Snapshot
from .fertilizer import load_selected_prescription

ROOT = Path(__file__).resolve().parents[2]
mcp = FastMCP('agri-dss')
logger = logging.getLogger('agri_dss.tools')


def load_snapshot(snapshot_id: str) -> Snapshot:
    # IDs are mapped explicitly; callers cannot supply filesystem paths.
    if snapshot_id != 'SYNTHETIC-001':
        from .irrigation_cases import load_irrigation_case
        return load_irrigation_case(snapshot_id)
    return Snapshot.model_validate_json((ROOT / 'data/snapshots/demo_irrigation.json').read_text(encoding='utf-8'))


def trace(tool: str, snapshot_id: str, result: dict) -> dict:
    canonical = json.dumps(result, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    logger.info(json.dumps({'request_id': str(uuid4()), 'tool': tool,
                            'snapshot_id': snapshot_id, 'rule_version': result.get('rule_version'),
                            'result_sha256': hashlib.sha256(canonical.encode()).hexdigest()}))
    return result


@mcp.tool(structured_output=True)
def get_soil_data(snapshot_id: str) -> dict[str, Any]:
    """Read soil values and provenance from a fixed snapshot."""
    snapshot = load_snapshot(snapshot_id)
    return trace('get_soil_data', snapshot_id, {
        'snapshot_id': snapshot.snapshot_id, 'snapshot_version': snapshot.version,
        'soil_moisture_value': snapshot.soil_moisture_value,
        'soil_moisture_unit': snapshot.soil_moisture_unit,
        'source_ids': snapshot.source_ids,
    })


@mcp.tool(structured_output=True)
def get_environment_context(snapshot_id: str, topics: list[str], tomato_type: Literal['unspecified', 'general', 'cherry']) -> dict[str, Any]:
    """Read historical environment summary and reviewed tomato PDF excerpts.

    Compute min/max from saved raw values, retrieve topic/type-specific literature,
    and preserve unknown units/applicability. This never makes a control decision.
    """
    from .environment_context import build_environment_context
    return trace('get_environment_context', snapshot_id, build_environment_context(snapshot_id, topics, tomato_type))


@mcp.tool(structured_output=True)
def get_environment_data(snapshot_id: str) -> dict[str, Any]:
    """Read a registered historical Data Mart snapshot, not current sensor data.

    Units, timezone, aggregation method and cultivar/stage are unconfirmed.
    It is not linked to the fertilizer parcel. No control recommendation is made.
    """
    from .smartfarm import load_environment_snapshot
    return trace('get_environment_data', snapshot_id, load_environment_snapshot(snapshot_id))


@mcp.tool(structured_output=True)
def get_fertilizer_prescription(pnu_code: str, crop_code: str = '04017') -> dict[str, Any]:
    """Read a saved provider prescription with units and provenance.

    This is a provider-calculated prescription, not a soil moisture measurement
    or a locally evaluated fertilizer rule. Actual crop and applicability are unreviewed.
    """
    prescription = load_selected_prescription(pnu_code, crop_code)
    return trace('get_fertilizer_prescription', pnu_code, prescription.model_dump(mode='json'))


@mcp.tool(structured_output=True)
def evaluate_irrigation(snapshot_id: str, rule_id: str = 'irrigation_synthetic_001', mode: Literal['demo', 'research'] = 'demo') -> dict[str, Any]:
    """Apply a server-owned rule; demo rules cannot run in research mode."""
    snapshot = load_snapshot(snapshot_id)
    if rule_id != 'irrigation_synthetic_001':
        raise ValueError('RULE_NOT_FOUND')
    rule = IrrigationRule.model_validate_json((ROOT / 'configs/rules/demo/irrigation.json').read_text(encoding='utf-8'))
    result = evaluate_rule(snapshot, rule, mode)
    return trace('evaluate_irrigation', snapshot_id, result.model_dump(mode='json'))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport='stdio')
