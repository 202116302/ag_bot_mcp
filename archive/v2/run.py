"""MCP vs RAG 반복 비교 실험.

python experiment/run.py --mock --repeats 1       # API 없이 흐름 점검
python experiment/run.py --repeats 10             # 실제 GPT, 질문 × 10회 × 2방식

결과: outputs/v2/<시각>/raw.jsonl(응답 원문), results.csv(채점), summary.csv(요약)
채점: 정답 수치가 모두 응답 values에 있으면(±0.01) 정답. 오류·연결 실패도 오답으로 남기고 재시도하지 않는다.
"""
import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agbot import config  # noqa: E402
from agbot.chat import ask  # noqa: E402

TOL = 0.01


def score(expected: list[float], result: dict) -> dict:
    got = [v["value"] for v in result.get("values", [])] if not result["error"] else []
    found = [any(abs(e - g) <= TOL for g in got) for e in expected]
    return {
        "correct": int(all(found)),
        "found": sum(found),
        "n_expected": len(expected),
        "n_values": len(got),
        "answer_key": json.dumps(sorted(round(g, 2) for g in got)),  # 일관성 비교용
        "traceable": int(bool(result.get("sources")) and (result["mode"] == "rag" or bool(result["tool_calls"]))),
    }


def summarize(rows: list[dict]) -> list[dict]:
    out = []
    groups = sorted({(r["mode"], r["id"]) for r in rows})
    for mode, qid in groups + sorted({(r["mode"], "ALL") for r in rows}):
        sub = [r for r in rows if r["mode"] == mode and (qid == "ALL" or r["id"] == qid)]
        n = len(sub)
        if qid == "ALL":  # 전체 일관성 = 질문별 일관성의 평균
            per_q = [s for s in out if s["mode"] == mode]
            consistency = sum(s["consistency"] for s in per_q) / len(per_q)
        else:
            consistency = Counter(r["answer_key"] for r in sub).most_common(1)[0][1] / n
        out.append({
            "mode": mode, "id": qid, "runs": n,
            "accuracy": round(sum(r["correct"] for r in sub) / n, 3),
            "consistency": round(consistency, 3),
            "traceability": round(sum(r["traceable"] for r in sub) / n, 3),
            "errors": sum(1 for r in sub if r["error"]),
            "avg_seconds": round(sum(r["seconds"] for r in sub) / n, 2),
        })
    return out


def write_csv(path: Path, rows: list[dict]):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--mock", action="store_true")
    p.add_argument("--repeats", type=int, default=10)
    p.add_argument("--modes", nargs="+", default=["mcp", "rag"])
    p.add_argument("--only", nargs="+", help="실행할 질문 id (예: F1 E2)")
    args = p.parse_args()

    questions = json.loads((Path(__file__).parent / "questions.json").read_text(encoding="utf-8"))
    if args.only:
        questions = [q for q in questions if q["id"] in args.only]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = config.OUTPUTS / "v2" / f"{stamp}{'_mock' if args.mock else ''}"
    out_dir.mkdir(parents=True)
    (out_dir / "settings.json").write_text(json.dumps({
        "model": "mock" if args.mock else config.MODEL, "reasoning_effort": config.REASONING_EFFORT,
        "repeats": args.repeats, "modes": args.modes, "questions": questions, "tolerance": TOL,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = []
    total = len(questions) * len(args.modes) * args.repeats
    with (out_dir / "raw.jsonl").open("w", encoding="utf-8") as raw:
        for q in questions:
            for mode in args.modes:
                for rep in range(1, args.repeats + 1):
                    result = ask(q["question"], mode=mode, mock=args.mock)
                    result.update(id=q["id"], repeat=rep)
                    raw.write(json.dumps(result, ensure_ascii=False) + "\n")
                    raw.flush()
                    row = {"id": q["id"], "domain": q["domain"], "type": q["type"], "mode": mode, "repeat": rep,
                           **score(q["expected"], result),
                           "tools": "|".join(c["name"] for c in result["tool_calls"]),
                           "error": result["error"] or "", "seconds": result["seconds"]}
                    rows.append(row)
                    mark = "O" if row["correct"] else "X"
                    print(f"[{len(rows)}/{total}] {q['id']} {mode} #{rep} {mark} {row['error'][:60]}")

    summary = summarize(rows)
    write_csv(out_dir / "results.csv", rows)
    write_csv(out_dir / "summary.csv", summary)
    print(f"\n결과 폴더: {out_dir}")
    for s in summary:
        if s["id"] == "ALL":
            print(f"  {s['mode'].upper()}: 정확도 {s['accuracy']:.1%}, 일관성 {s['consistency']:.1%}, "
                  f"근거추적 {s['traceability']:.1%}, 오류 {s['errors']}건, 평균 {s['avg_seconds']}초")


if __name__ == "__main__":
    main()
