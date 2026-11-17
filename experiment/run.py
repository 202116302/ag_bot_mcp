"""시나리오 × 조건(RAG/MCP) × 반복 실행 → 응답 원문 저장 (명세 7.4).

python experiment/run.py --mock --repeats 1          # API 없이 파이프라인 점검
python experiment/run.py --repeats 10                # 실제 GPT (시나리오 25 × 2 × 10 = 500회)
python experiment/run.py --only TSK-OF-003 --repeats 2

결과: outputs/v3/<시각>/settings.json, raw.jsonl (응답·도구 호출 인자/반환값·검색 결과)
채점은 experiment/judge.py로 따로 한다. 실패도 그대로 기록하고 재시도하지 않는다.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agbot import config  # noqa: E402
from agbot.chat import ask  # noqa: E402
from agbot.data import load_scenarios  # noqa: E402


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--mock", action="store_true")
    p.add_argument("--repeats", type=int, default=10)
    p.add_argument("--conditions", nargs="+", default=["rag", "mcp"])
    p.add_argument("--only", nargs="+", help="시나리오 id")
    args = p.parse_args()

    scenarios = [s for s in load_scenarios() if not args.only or s["scenario_id"] in args.only]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = config.OUTPUTS / "v3" / f"{stamp}{'_mock' if args.mock else ''}"
    out_dir.mkdir(parents=True)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=config.ROOT).stdout.strip()
    (out_dir / "settings.json").write_text(json.dumps({
        "model": "mock" if args.mock else config.MODEL, "reasoning_effort": config.REASONING_EFFORT,
        "max_output_tokens": config.MAX_OUTPUT_TOKENS, "embed_model": "keyword" if args.mock else config.EMBED_MODEL,
        "search_k": config.SEARCH_K, "repeats": args.repeats, "conditions": args.conditions,
        "scenarios": [s["scenario_id"] for s in scenarios], "git_commit": commit,
        "hashes": {name: file_hash(config.ROOT / name) for name in
                   ["knowledge/rules.yaml", "knowledge/chunks.jsonl", "agbot/chat.py", "agbot/rules.py"]},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    total, n, errors = len(scenarios) * len(args.conditions) * args.repeats, 0, 0
    with (out_dir / "raw.jsonl").open("w", encoding="utf-8") as raw:
        for s in scenarios:
            for cond in args.conditions:
                for rep in range(1, args.repeats + 1):
                    result = ask(s["question"], s["scenario_id"], cond, mock=args.mock)
                    result["repeat"] = rep
                    raw.write(json.dumps(result, ensure_ascii=False) + "\n")
                    raw.flush()
                    n += 1
                    errors += bool(result["error"])
                    print(f"[{n}/{total}] {s['scenario_id']} {cond} #{rep} "
                          f"{(result['error'] or result.get('decision', ''))[:70]}")
    print(f"\n완료: {out_dir}  (오류 {errors}건)\n다음: python experiment/judge.py {out_dir}{' --mock' if args.mock else ''}")


if __name__ == "__main__":
    main()
