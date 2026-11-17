import argparse
import asyncio
import json
from pathlib import Path
import sys
from .rules import evaluate_irrigation
from .schemas import IrrigationRule, Snapshot


def main():
    parser = argparse.ArgumentParser(description='Traceable irrigation prototype (demo data is synthetic)')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('mcp-demo', help='Run stdio MCP checks with synthetic irrigation and a saved fertilizer response')
    environment = commands.add_parser('environment', help='Read the saved historical Smartfarm Data Mart environment snapshot')
    environment.add_argument('--json', action='store_true')
    environment_ask = commands.add_parser('environment-ask', help='Ask about historical environment data with reviewed tomato literature')
    environment_ask.add_argument('--provider', choices=['mock', 'openai'], default='mock')
    environment_ask.add_argument('--path', choices=['mcp', 'rag'], default='mcp')
    environment_ask.add_argument('--question')
    environment_ask.add_argument('--output', type=Path)
    environment_ask.add_argument('--json', action='store_true')
    fertilizer = commands.add_parser('fertilizer', help='Read the selected saved API prescription (no network)')
    fertilizer.add_argument('--output', type=Path, help='Also save normalized JSON to this path')
    ask = commands.add_parser('ask', help='Ask a Mock or GPT-5.4-mini model to retrieve the selected MCP prescription')
    ask.add_argument('--provider', choices=['mock', 'openai'], default='mock')
    ask.add_argument('--path', choices=['mcp', 'rag'], default='mcp', help='Evidence delivery path')
    ask.add_argument('--question', help='Question about the selected fertilizer prescription')
    ask.add_argument('--output', type=Path, help='Run log path (default: outputs/llm/<run-id>.json)')
    ask.add_argument('--json', action='store_true', help='Print the full run record instead of Korean text')
    irrigation = commands.add_parser('irrigation-ask', help='Synthetic direct-decision test; not a real parcel prescription')
    irrigation.add_argument('--provider', choices=['mock', 'openai'], default='mock')
    irrigation.add_argument('--path', choices=['mcp', 'rag'], default='mcp')
    irrigation.add_argument('--case', default='SYNTHETIC-BELOW')
    irrigation.add_argument('--output', type=Path)
    for name in ('demo', 'evaluate'):
        sub = commands.add_parser(name)
        sub.add_argument('--snapshot', type=Path, default=Path('data/snapshots/demo_irrigation.json') if name == 'demo' else None, required=name == 'evaluate')
        sub.add_argument('--rule', type=Path, default=Path('configs/rules/demo/irrigation.json') if name == 'demo' else None, required=name == 'evaluate')
        sub.add_argument('--mode', choices=['demo', 'research'], default='demo')
    args = parser.parse_args()
    if args.command == 'environment-ask':
        from .environment_assistant import DEFAULT_QUESTION, run_environment_assistant
        from .fertilizer import ROOT
        try:
            result = asyncio.run(run_environment_assistant(args.provider, args.path, args.question or DEFAULT_QUESTION))
            output = args.output or ROOT / 'outputs/environment_qa' / (result['run_id'] + '.json')
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        except (OSError, ValueError, KeyError):
            print('Environment assistant input/configuration/output error.', file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else
              result['answer'] or f"{result['status']}: {result.get('error_code', 'UNKNOWN_ERROR')}")
        print('Run log:', output, file=sys.stderr)
        return 0 if result['status'] in ('partial', 'deferred') else 2
    if args.command == 'environment':
        from .smartfarm import describe_environment, load_environment_snapshot
        try:
            snapshot = load_environment_snapshot()
        except (OSError, ValueError, KeyError):
            print('Environment snapshot/source error.', file=sys.stderr)
            return 2
        print(json.dumps(snapshot, ensure_ascii=False, indent=2) if args.json else describe_environment(snapshot))
        return 0
    if args.command == 'irrigation-ask':
        from .irrigation_assistant import run_irrigation_assistant
        from .fertilizer import ROOT
        try:
            result = asyncio.run(run_irrigation_assistant(args.provider, args.path, args.case))
            output = args.output or ROOT / 'outputs/irrigation' / (result['run_id'] + '.json')
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        except (OSError, ValueError, KeyError):
            print('Synthetic irrigation input/configuration/output error.', file=sys.stderr)
            return 2
        print(result['answer'] or f"{result['status']}: {result.get('error_code', 'UNKNOWN_ERROR')}")
        print('Run log:', output, file=sys.stderr)
        return 0 if result['status'] == 'completed' else 2
    if args.command == 'ask':
        from .assistant import DEFAULT_QUESTION, run_fertilizer_assistant
        from .fertilizer import ROOT
        try:
            result = asyncio.run(run_fertilizer_assistant(args.provider, args.question or DEFAULT_QUESTION,
                                                        path=args.path))
            output = args.output or ROOT / 'outputs/llm' / (result['run_id'] + '.json')
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        except (OSError, ValueError, KeyError):
            print('Assistant input/configuration/output error.', file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(result, ensure_ascii=True, indent=2))
        else:
            print(result['answer'] or f"{result['status']}: {result.get('error_code', 'UNKNOWN_ERROR')}")
        print('Run log:', output, file=sys.stderr)
        return 0 if result['status'] in ('completed', 'partial', 'deferred') else 2
    if args.command == 'fertilizer':
        from .fertilizer import load_selected_prescription
        try:
            result = load_selected_prescription()
            payload = result.model_dump_json(indent=2)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(payload + '\n', encoding='utf-8')
        except (OSError, ValueError, KeyError):
            print('Prescription input/configuration error.', file=sys.stderr)
            return 2
        print(payload)
        return 0
    if args.command == 'mcp-demo':
        from .mcp_client import run_demo
        print(json.dumps(asyncio.run(run_demo()), indent=2))
        return 0
    try:
        snapshot = Snapshot.model_validate_json(args.snapshot.read_text(encoding='utf-8'))
        rule = IrrigationRule.model_validate_json(args.rule.read_text(encoding='utf-8'))
        result = evaluate_irrigation(snapshot, rule, args.mode)
    except (OSError, ValueError):
        print('Input/configuration error; check files, schemas and research eligibility.', file=sys.stderr)
        return 2
    print(result.model_dump_json(indent=2))
    return 0
