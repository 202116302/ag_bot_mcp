"""Fixed MCP transport smoke check. LLM-driven calls live in assistant.py."""
import asyncio
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run_demo() -> dict:
    root = Path(__file__).resolve().parents[2]
    params = StdioServerParameters(
        command=sys.executable, args=['-m', 'agri_dss.mcp_server'], cwd=str(root),
        env={'PYTHONPATH': str(root / 'src'), 'PYTHONIOENCODING': 'utf-8'},
    )
    async with asyncio.timeout(30):
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                listing = await session.list_tools()
                soil = await session.call_tool('get_soil_data', {'snapshot_id': 'SYNTHETIC-001'})
                decision = await session.call_tool('evaluate_irrigation', {'snapshot_id': 'SYNTHETIC-001'})
                blocked = await session.call_tool('evaluate_irrigation', {'snapshot_id': 'SYNTHETIC-001', 'mode': 'research'})
                unknown = await session.call_tool('get_soil_data', {'snapshot_id': '../API_key.txt'})
                from .fertilizer import load_selected_prescription
                selected = load_selected_prescription()
                fertilizer = await session.call_tool('get_fertilizer_prescription',
                                                     {'pnu_code': selected.pnu_code,
                                                      'crop_code': selected.requested_crop_code})
                unknown_fertilizer = await session.call_tool('get_fertilizer_prescription',
                                                             {'pnu_code': '../API_key.txt'})
                return {'tools': [t.name for t in listing.tools],
                        'soil': soil.model_dump(mode='json'),
                        'decision': decision.model_dump(mode='json'),
                        'research_blocked': blocked.isError,
                        'unknown_snapshot_blocked': unknown.isError,
                        'fertilizer': fertilizer.model_dump(mode='json'),
                        'unknown_fertilizer_blocked': unknown_fertilizer.isError}
