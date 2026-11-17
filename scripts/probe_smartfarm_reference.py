"""스마트팜 데이터마트에서 '다른 시설 토마토 농가' 참고 자료를 모은다 (조회 횟수 제한).

python scripts/probe_smartfarm_reference.py [--farms 20]

1) 저장된 농가 목록(identity)에서 토마토 시설을 고르게 N곳 고른다.
2) 농가마다 작기 목록 1회 → 끝난 작기의 정식 후 60일째(작기 중간) 하루를 고른다.
3) 그날 내부온도(TI)를 조회하고, 자료가 있는 농가만 내부습도(HI)와
   양액 항목(공급EC·배액EC·공급량·배액량·공급pH)을 조회한다.
결과(키 없음): outputs/smartfarm_reference/<시각>/raw.jsonl, summary.json
"""
import argparse
import glob
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agbot import config  # noqa: E402
from agbot.sources import SourceError, _smartfarm  # noqa: E402

ITEMS = [("EI", "HI", "내부습도"), ("NT", "EI", "공급EC"), ("NT", "EO", "배액EC"),
         ("NT", "NI", "공급량"), ("NT", "NO", "배액량"), ("NT", "PI", "공급pH")]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--farms", type=int, default=20)
    p.add_argument("--months", type=int, nargs="*", default=[],
                   help="이 달(예: 7 11)이 들어 있는 작기를 골라 그 달 15일을 조회. 생략하면 정식 후 60일째")
    p.add_argument("--max-calls", type=int, default=300)
    p.add_argument("--env-only", action="store_true", help="양액 항목은 조회하지 않음")
    args = p.parse_args()
    seen = set()
    for f in (config.OUTPUTS / "smartfarm_reference").glob("*Z/raw.jsonl"):
        for line in f.open(encoding="utf-8"):
            r = json.loads(line)
            if r["op"] == "getEnvDataList":
                seen.add(r["args"][0])

    ident = sorted(glob.glob(str(config.OUTPUTS / "smartfarm_environment" / "*" / "identity.json")))[-1]
    rows = [r for r in json.loads(json.load(open(ident, encoding="utf-8"))["body"]) if r.get("itemCode") == "080300"]
    step = max(1, len(rows) // args.farms)
    picks = [r for r in rows[::step] if r["facilityId"] not in seen][: args.farms]
    if args.months:  # 고르게 뽑은 뒤 남은 농가로 채움
        picks += [r for r in rows if r["facilityId"] not in seen and r not in picks][: max(0, args.farms - len(picks))]

    out = config.OUTPUTS / "smartfarm_reference" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True)
    raw = (out / "raw.jsonl").open("w", encoding="utf-8")
    calls, summary = 0, []

    def fetch(op, *a):
        nonlocal calls
        calls += 1
        try:
            data = _smartfarm(op, *a)
            raw.write(json.dumps({"op": op, "args": list(a), "rows": data}, ensure_ascii=False) + "\n")
            return data
        except SourceError as e:
            raw.write(json.dumps({"op": op, "args": list(a), "error": str(e)}, ensure_ascii=False) + "\n")
            return None

    def parse(d):
        try:
            return date.fromisoformat(str(d)[:10])
        except ValueError:
            return None

    got = {m: 0 for m in args.months}
    for f in picks:
        if calls >= args.max_calls:
            break
        fid, uid = f["facilityId"], f["userId"]
        seasons = fetch("getCroppingSeasonDataList", uid) or []
        done = []
        for s in seasons:
            a, b = parse(s.get("croppingDate")), parse(s.get("croppingEndDate"))
            if s.get("itemCode") in ("080300", "80300") and a and b and a.year > 2000 and a <= b < date.today():
                done.append((s, a, b))
        if not done:
            summary.append({"facility": fid, "status": "no_completed_season"})
            continue
        day = None
        for m in sorted(args.months, key=lambda m: got[m]):  # 아직 적게 모인 달부터
            for s, a, b in sorted(done, key=lambda x: x[2], reverse=True):
                for y in range(b.year, a.year - 1, -1):
                    d = date(y, m, 15)
                    if a <= d <= b:
                        day, got[m] = str(d), got[m] + 1
                        break
                if day:
                    break
            if day:
                break
        if args.months and not day:
            summary.append({"facility": fid, "status": "no_season_in_target_months"})
            continue
        if not day:
            s, a, b = max(done, key=lambda x: x[2])
            day = str(min(a + timedelta(days=60), b))
        rec = {"facility": fid, "date": day, "items": {}}
        ti = fetch("getEnvDataList", fid, day, "FG", "EI", "TI", "080300")
        rec["items"]["내부온도"] = len(ti or [])
        if ti:
            for sect, code, name in (ITEMS[:1] if args.env_only else ITEMS):
                d = fetch("getEnvDataList", fid, day, "FG", sect, code, "080300")
                rec["items"][name] = len(d or [])
        summary.append(rec)
        print(fid, day, rec["items"])
    raw.close()
    (out / "summary.json").write_text(json.dumps({"calls": calls, "farms": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n호출 {calls}회 → {out}")


if __name__ == "__main__":
    main()
