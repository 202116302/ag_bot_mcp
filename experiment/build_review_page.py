"""검수 페이지 생성: python experiment/build_review_page.py outputs/v3/<폴더>

results.csv의 review_sample=1 표본과 raw.jsonl 응답 원문, 시나리오 정답을 묶어
<폴더>/review_page.html 로 저장한다. 연구자의 O/X 판정은 페이지의 db(reviews/sNN)에 저장된다.
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agbot.chat import situation_text  # noqa: E402
from agbot.data import get_scenario  # noqa: E402

TEMPLATE = Path(__file__).parent / "review_page_template.html"


def main(folder: str):
    folder = Path(folder)
    rows = [r for r in csv.DictReader((folder / "results.csv").open(encoding="utf-8-sig")) if r["review_sample"] == "1"]
    raw = {(r["scenario_id"], r["condition"], r["repeat"]): r
           for r in map(json.loads, (folder / "raw.jsonl").open(encoding="utf-8"))}
    second = {}
    review_csv = folder / "review_sample.csv"
    if review_csv.exists():
        for r in csv.DictReader(review_csv.open(encoding="utf-8-sig")):
            second[int(r["no"])] = {"verdict": r["claude_review"], "note": r["note"]}

    items = []
    for i, r in enumerate(rows, 1):
        s = get_scenario(r["scenario_id"])
        rr = raw[(r["scenario_id"], r["condition"], int(r["repeat"]))]
        decision_calls = [c for c in rr["tool_calls"] if c["name"].endswith(("_decision", "_schedule"))]
        dc = decision_calls[-1] if decision_calls else None
        items.append({
            "no": i, "key": f"s{i:02d}", "sid": r["scenario_id"], "cond": r["condition"], "rep": int(r["repeat"]),
            "domain": s["domain"], "type": s["type"], "question": s["question"],
            "situation": situation_text(s["system_values"]),
            "expected": s["expected"]["decision"], "required": s["expected"]["required_items"],
            "answer": rr.get("answer", ""), "decision": rr.get("decision", ""), "basis": rr.get("basis", ""),
            "key_values": rr.get("key_values", []), "sources": [x.get("doc_id", "") for x in rr.get("sources", [])],
            "tools": [c["name"] for c in rr["tool_calls"]],
            "tool_decision": None if not dc else {
                "name": dc["name"],
                "args": {k: v for k, v in dc["arguments"].items() if v not in (None, False, "")},
                "result": (dc["output"] or {}).get("result", {}).get("decision") if isinstance(dc["output"], dict) else None,
                "status": (dc["output"] or {}).get("status") if isinstance(dc["output"], dict) else None,
            },
            "retrieved": [x["chunk_id"] for x in rr.get("retrieved", [])],
            "judge": {"verdict": "O" if r["decision_correct"] == "1" else "X",
                      "items": f"{r['n_present']}/{r['n_items']}", "error": r["error_type"], "comment": r["judge_comment"]},
            "second": second.get(i),
        })
    data = json.dumps({"run": folder.name, "items": items}, ensure_ascii=False).replace("</", "<\\/")
    out = folder / "review_page.html"
    out.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", data), encoding="utf-8")
    print(f"{out} ({len(items)}건)")


if __name__ == "__main__":
    main(sys.argv[1])
