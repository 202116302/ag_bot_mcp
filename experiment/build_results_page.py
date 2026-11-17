"""결과 비교 페이지: python experiment/build_results_page.py outputs/v3/<폴더> ["제목"]

시나리오 25개 × (RAG, MCP) × 10회 응답과 채점 결과를 묶어 <폴더>/results_page.html 로 저장한다.
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agbot.data import load_scenarios  # noqa: E402

TEMPLATE = Path(__file__).parent / "results_page_template.html"


def main(folder: str, title: str = "RAG vs MCP 응답 비교"):
    folder = Path(folder)
    judged = {(r["scenario_id"], r["condition"], int(r["repeat"])): r
              for r in csv.DictReader((folder / "results.csv").open(encoding="utf-8-sig"))}
    raw = {}
    for r in map(json.loads, (folder / "raw.jsonl").open(encoding="utf-8")):
        raw[(r["scenario_id"], r["condition"], int(r["repeat"]))] = r
    summary = {(r["condition"], r["group"], r["value"]): r
               for r in csv.DictReader((folder / "summary.csv").open(encoding="utf-8-sig"))}

    def run(sid, cond, rep):
        r, j = raw[(sid, cond, rep)], judged[(sid, cond, rep)]
        dc = [c for c in r["tool_calls"] if c["name"].endswith(("_decision", "_schedule"))]
        ref = [c for c in r["tool_calls"] if c["name"] == "get_farm_reference"]
        return {
            "ok": j["decision_correct"] == "1", "items": f"{j['n_present']}/{j['n_items']}", "err": j["error_type"],
            "decision": r.get("decision", ""), "answer": r.get("answer", ""), "basis": r.get("basis", ""),
            "sources": sorted({s.get("doc_id", "") for s in r.get("sources", [])}),
            "tools": [c["name"] for c in r["tool_calls"]],
            "tool": None if not dc else {"name": dc[-1]["name"],
                                         "args": {k: v for k, v in dc[-1]["arguments"].items() if v not in (None, False, "")},
                                         "result": (dc[-1]["output"] or {}).get("result", {}).get("decision") if isinstance(dc[-1]["output"], dict) else None},
            "reference": bool(ref),
            "retrieved": [x["chunk_id"].rsplit("-", 1)[0] for x in r.get("retrieved", [])],
            "seconds": r["seconds"],
        }

    scenarios = []
    for s in load_scenarios():
        sid = s["scenario_id"]
        runs = {c: [run(sid, c, i) for i in range(1, 11)] for c in ("rag", "mcp")}
        scenarios.append({
            "sid": sid, "domain": s["domain"], "type": s["type"], "question": s["question"],
            "score": {c: sum(x["ok"] for x in runs[c]) for c in runs}, "runs": runs,
        })
    overall = {c: {k: summary[(c, "all", "all")][k] for k in ("accuracy", "consistency", "missing_rate", "evidence_rate")}
               for c in ("rag", "mcp")}
    data = json.dumps({"run": folder.name, "overall": overall, "scenarios": scenarios}, ensure_ascii=False).replace("</", "<\\/")
    out = folder / "results_page.html"
    out.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", data).replace("__TITLE__", title), encoding="utf-8")
    print(f"{out} ({len(scenarios)} 시나리오, {out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "RAG vs MCP 응답 비교")
