import asyncio
import pytest

pytest.importorskip('mcp')
from agri_dss.mcp_client import run_demo


def test_real_stdio_roundtrip():
    result = asyncio.run(run_demo())
    assert {'get_soil_data', 'evaluate_irrigation'} <= set(result['tools'])
    assert not result['soil']['isError']
    assert not result['decision']['isError']
    assert result['soil']['structuredContent']['soil_moisture_value'] == 18.0
    decision = result['decision']['structuredContent']
    assert decision['decision'] == 'IRRIGATION_REQUIRED'
    assert decision['rule_status'] == 'demo_only'
    assert decision['source_refs']
    assert result['research_blocked']
    assert result['unknown_snapshot_blocked']
    assert 'get_fertilizer_prescription' in result['tools']
    assert not result['fertilizer']['isError']
    prescription = result['fertilizer']['structuredContent']
    assert prescription['pnu_code'] == '5271033027105280033'
    assert prescription['amounts']['basal_n']['value'] == '14.4'
    assert prescription['result_origin'] == 'provider_prescription'
    assert result['unknown_fertilizer_blocked']
