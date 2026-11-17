"""CLI
  python -m agbot ask "질문" [--scenario DEMO|<id>] [--condition mcp|rag] [--mock] [--json]
  python -m agbot scenarios          # 시나리오 목록
  python -m agbot live               # 실시간 API 조회 값 확인
"""
import argparse
import json
import sys

from .chat import ask
from .data import get_scenario, load_scenarios


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="agbot", description="토마토 재배 의사결정지원 (RAG vs MCP)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ask", help="질문하기")
    p.add_argument("question", nargs="?", help="생략하면 시나리오의 질문을 사용")
    p.add_argument("--scenario", default="DEMO", help="시나리오 id (DEMO: 저장된 실제 자료, LIVE: 실시간 API 조회)")
    p.add_argument("--condition", choices=["mcp", "rag"], default="mcp")
    p.add_argument("--mock", action="store_true", help="API 없이 Mock 모델·키워드 검색 사용")
    p.add_argument("--json", action="store_true", help="전체 결과를 JSON으로 출력")
    sub.add_parser("scenarios", help="시나리오 목록")
    sub.add_parser("live", help="외부 API(기상·스마트팜·흙토람)를 실시간 조회해 MCP 조회 도구가 받을 값을 보여줌")
    args = parser.parse_args()

    if args.command == "live":
        print(json.dumps(get_scenario("LIVE")["system_values"], ensure_ascii=False, indent=2))
        return 0

    if args.command == "scenarios":
        for s in load_scenarios():
            print(f"{s['scenario_id']:12} {s['domain']:10} {s['type']:12} {s['question']}")
        return 0

    question = args.question or get_scenario(args.scenario)["question"]
    if not question:
        parser.error("질문을 입력하세요 (DEMO·LIVE 시나리오에는 기본 질문이 없습니다)")
    result = ask(question, scenario_id=args.scenario, condition=args.condition, mock=args.mock)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["error"]:
        print(f"[오류] {result['error']}")
    else:
        print(f"Q. {question}\n")
        print(result["answer"])
        print(f"\n▶ 판정: {result['decision']}")
        for v in result["key_values"]:
            print(f"  - {v['name']}: {v['value']} {v['unit']}")
        print(f"▶ 근거: {result['basis']}")
        for s in result["sources"]:
            print(f"  [{s['doc_id']}] {s['clause']}")
        used = [c["name"] for c in result["tool_calls"]] or [r["chunk_id"] for r in result["retrieved"]]
        print(f"\n[{args.condition.upper()} / {result['model']} / {args.scenario} / {', '.join(used)} / {result['seconds']}초]")
    return 1 if result["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
