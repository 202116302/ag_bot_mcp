"""응답 채점·집계 (명세 8절).  python experiment/judge.py outputs/v3/<폴더> [--mock]

1) 각 응답을 LLM 채점기로 구조화 추출: 판정 정답 여부, 필수 항목 포함 여부, 근거 제시 여부, 행동 목록, 오류 유형
2) MCP 조건은 판정 도구 인자를 시나리오 reference_call과 코드로 비교해 입력값 전달 오류를 표시
3) results.csv(응답별), summary.csv(조건×전체/영역/유형), errors.csv(오류 유형) 저장
   review_sample=1 표시된 약 10%는 사람이 검수한다.
"""
import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agbot import config  # noqa: E402
from agbot.data import get_scenario  # noqa: E402
from agbot.llm import ModelError, call_openai, output_text  # noqa: E402

# 판정 일치율 계산용 공통 행동 어휘 (자유 문장 대신 이 목록으로 정규화)
ACTIONS = ["환기", "차광", "난방", "송풍", "조치 불필요", "급액 실시", "급액 대기", "급액량 증가", "급액량 감소", "급액량 유지",
           "급액 EC 조정", "근권 EC 조정", "pH 조정", "제품량 환산", "1차 웃거름", "2차 웃거름", "3차 웃거름", "웃거름 시기 아님",
           "보온 피복", "고온 대응", "배수로 확보", "피해율 제시", "착과제 처리 가능", "착과제 처리 보류", "50배액", "100배액",
           "고온 시간대 회피", "적심 시기 제시", "적심 단수 제시", "수확 가능", "수확 대기", "판단 보류", "지원 범위 밖", "기타"]
ERRORS = ["none", "retrieval_failure", "interpretation_error", "calculation_error", "range_answer", "evasion",
          "input_transfer_error", "explanation_error", "missing_info_ignored", "other"]
TOL = 0.01  # 수치 상대 허용오차 ±1% (사전 고정)

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision_correct": {"type": "boolean"},
        "required_items": {"type": "array", "items": {"type": "object", "properties": {
            "item": {"type": "string"}, "present": {"type": "boolean"}}, "required": ["item", "present"], "additionalProperties": False}},
        "evidence_presented": {"type": "boolean", "description": "판단 기준값과 출처 문서를 함께 제시했는가"},
        "actions": {"type": "array", "items": {"type": "string", "enum": ACTIONS}},
        "error_type": {"type": "string", "enum": ERRORS},
        "comment": {"type": "string"},
    },
    "required": ["decision_correct", "required_items", "evidence_presented", "actions", "error_type", "comment"],
    "additionalProperties": False,
}

JUDGE_INSTRUCTIONS = f"""당신은 농업 의사결정지원 응답의 채점자다. 표현이 달라도 추천 결과가 같으면 일치로 본다.
- decision_correct: 응답의 판정이 정답 판정과 실질적으로 같은가. 정답이 '판단 보류'인데 값을 추측해 판정했으면 false.
- required_items: 각 필수 항목이 응답(answer·decision·basis·key_values)에 들어 있는가. 수치는 상대오차 ±1% 이내면 포함.
- evidence_presented: 판단 기준값(예: 30℃ 이상)과 출처 문서를 함께 제시했는가.
- actions: 응답이 권고한 행동을 목록 어휘로만 정규화.
- error_type: 판정이 틀렸거나 필수 항목이 빠졌을 때의 주된 원인. 정답이고 누락이 없으면 none.
  RAG: retrieval_failure(필요 기준을 못 찾음), interpretation_error(기준 해석 오류), calculation_error(계산 오류),
  range_answer(구체 판정 없이 범위만), evasion("지켜보라" 식 판정 회피).
  MCP: input_transfer_error(질문/조회 값을 판정 도구에 잘못 전달), explanation_error(도구 결과를 설명하며 틀림).
  공통: missing_info_ignored(누락된 값을 추측해 판정), other."""


def judge_prompt(s: dict, r: dict, input_mismatch: list) -> str:
    response = {k: r.get(k) for k in ["answer", "decision", "key_values", "basis", "sources"]}
    extra = ""
    if r["condition"] == "mcp":
        calls = [{"name": c["name"], "arguments": c["arguments"],
                  **({"result": c["output"].get("result"), "status": c["output"].get("status")} if isinstance(c["output"], dict) and "status" in c["output"] else {})}
                 for c in r["tool_calls"] if c["name"] != "search_guideline"]
        extra = f"\n[MCP 도구 호출]\n{json.dumps(calls, ensure_ascii=False)}\n[판정 도구 인자 불일치(코드 비교)] {input_mismatch or '없음'}"
    return (f"[시나리오]\n질문: {s['question']}\n현재 상황: {json.dumps(s['system_values'], ensure_ascii=False)}\n"
            f"[정답]\n판정: {s['expected']['decision']}\n필수 항목: {json.dumps(s['expected']['required_items'], ensure_ascii=False)}\n"
            f"[응답 ({r['condition'].upper()})]\n{json.dumps(response, ensure_ascii=False)}{extra}")


def input_mismatch(s: dict, r: dict) -> list:
    """MCP: 판정 도구 인자를 reference_call과 비교 (코드). 값이 다르거나 빠진 인자 목록."""
    ref = s["reference_call"]
    calls = [c for c in r["tool_calls"] if c["name"] == ref["tool"]]
    if not calls:
        return [f"{ref['tool']} 미호출"]
    got = calls[-1]["arguments"]
    out = []
    for k, v in ref["args"].items():
        g = got.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and isinstance(g, (int, float)):
            if abs(g - v) > TOL * max(abs(v), 1e-9):
                out.append(f"{k}: {g} ≠ {v}")
        elif g != v and not (isinstance(v, str) and isinstance(g, str) and v in g):
            out.append(f"{k}: {g!r} ≠ {v!r}")
    return out


def mock_judge(s: dict, r: dict) -> dict:
    """API 없이 채점 파이프라인 점검: 정답 키워드 포함 여부만 본다."""
    text = " ".join(str(r.get(k, "")) for k in ["answer", "decision", "basis"])
    key = s["expected"]["decision_key"]
    correct = (key in text) if key else ("보류" in r.get("decision", ""))
    return {"decision_correct": correct,
            "required_items": [{"item": i, "present": correct} for i in s["expected"]["required_items"]],
            "evidence_presented": bool(r.get("sources")) and any(ch.isdigit() for ch in r.get("basis", "")),
            "actions": ["판단 보류"] if "보류" in r.get("decision", "") else ["기타"],
            "error_type": "none" if correct else "other", "comment": "mock"}


def llm_judge(prompt: str) -> dict:
    reply = call_openai({
        "model": config.MODEL, "instructions": JUDGE_INSTRUCTIONS, "input": [{"role": "user", "content": prompt}],
        "reasoning": {"effort": config.REASONING_EFFORT}, "max_output_tokens": 1200, "store": False,
        "text": {"format": {"type": "json_schema", "name": "judge", "strict": True, "schema": JUDGE_SCHEMA}}})
    return json.loads(output_text(reply))


def write_csv(path: Path, rows: list[dict]):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def summarize(rows: list[dict]) -> list[dict]:
    out = []
    for cond in sorted({r["condition"] for r in rows}):
        sub_all = [r for r in rows if r["condition"] == cond]
        groups = [("all", "all")] + [("domain", d) for d in sorted({r["domain"] for r in rows})] + \
                 [("type", t) for t in sorted({r["type"] for r in rows})]
        for gk, gv in groups:
            sub = [r for r in sub_all if gk == "all" or r[gk] == gv]
            by_s = defaultdict(list)
            for r in sub:
                by_s[r["scenario_id"]].append(r["actions"])
            consistency = sum(Counter(v).most_common(1)[0][1] / len(v) for v in by_s.values()) / len(by_s)
            n_items = sum(r["n_items"] for r in sub)
            out.append({
                "condition": cond, "group": gk, "value": gv, "responses": len(sub),
                "accuracy": round(sum(r["decision_correct"] for r in sub) / len(sub), 3),
                "consistency": round(consistency, 3),
                "missing_rate": round(1 - sum(r["n_present"] for r in sub) / n_items, 3) if n_items else 0,
                "evidence_rate": round(sum(r["evidence_presented"] for r in sub) / len(sub), 3),
                "errors": sum(1 for r in sub if r["system_error"]),
            })
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("folder")
    p.add_argument("--mock", action="store_true")
    args = p.parse_args()
    folder = Path(args.folder)
    records = [json.loads(line) for line in (folder / "raw.jsonl").read_text(encoding="utf-8").splitlines()]
    rng = random.Random(42)

    rows, judged = [], []
    for i, r in enumerate(records, 1):
        s = get_scenario(r["scenario_id"])
        mismatch = input_mismatch(s, r) if r["condition"] == "mcp" and not r["error"] else []
        if r["error"]:
            j = {"decision_correct": False, "required_items": [{"item": x, "present": False} for x in s["expected"]["required_items"]],
                 "evidence_presented": False, "actions": ["기타"], "error_type": "other", "comment": r["error"]}
        else:
            try:
                j = mock_judge(s, r) if args.mock else llm_judge(judge_prompt(s, r, mismatch))
            except (ModelError, json.JSONDecodeError) as exc:
                j = {"decision_correct": False, "required_items": [], "evidence_presented": False, "actions": ["기타"],
                     "error_type": "other", "comment": f"채점 실패: {exc}"}
        judged.append({"scenario_id": r["scenario_id"], "condition": r["condition"], "repeat": r["repeat"], **j,
                       "input_mismatch": mismatch})
        rows.append({
            "scenario_id": r["scenario_id"], "domain": s["domain"], "type": s["type"], "condition": r["condition"],
            "repeat": r["repeat"], "decision_correct": int(j["decision_correct"]),
            "n_items": len(s["expected"]["required_items"]), "n_present": sum(x["present"] for x in j["required_items"]),
            "evidence_presented": int(j["evidence_presented"]), "actions": "|".join(sorted(set(j["actions"]))),
            "error_type": j["error_type"], "input_mismatch": "; ".join(mismatch), "system_error": r["error"] or "",
            "decision": r.get("decision", ""), "tools": "|".join(c["name"] for c in r["tool_calls"]),
            "reference_called": int(any(c["name"] == "get_farm_reference" for c in r["tool_calls"])),
            "seconds": r["seconds"], "review_sample": int(rng.random() < 0.1), "judge_comment": j["comment"],
        })
        print(f"[{i}/{len(records)}] {r['scenario_id']} {r['condition']} #{r['repeat']} "
              f"{'O' if j['decision_correct'] else 'X'} {j['error_type']}")

    (folder / "judged.jsonl").write_text("\n".join(json.dumps(j, ensure_ascii=False) for j in judged), encoding="utf-8")
    write_csv(folder / "results.csv", rows)
    summary = summarize(rows)
    write_csv(folder / "summary.csv", summary)
    errs = Counter((r["condition"], r["error_type"]) for r in rows)
    write_csv(folder / "errors.csv", [{"condition": c, "error_type": e, "count": n} for (c, e), n in sorted(errs.items())])
    print(f"\n저장: {folder}/results.csv, summary.csv, errors.csv")
    climate_mcp = [r for r in rows if r["condition"] == "mcp" and r["domain"] == "climate"]
    if climate_mcp:
        n = sum(r["reference_called"] for r in climate_mcp)
        print(f"  MCP 환경제어 응답 중 다른 농가 참고(get_farm_reference) 사용: {n}/{len(climate_mcp)}")
    for s in summary:
        if s["group"] == "all":
            print(f"  {s['condition'].upper()}: 정확도 {s['accuracy']:.1%}, 일치율 {s['consistency']:.1%}, "
                  f"필수항목 누락률 {s['missing_rate']:.1%}, 근거 제시 {s['evidence_rate']:.1%}, 시스템 오류 {s['errors']}")


if __name__ == "__main__":
    main()
