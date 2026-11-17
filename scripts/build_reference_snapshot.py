"""데이터마트 참고 조회 결과(raw.jsonl) → data/snapshots/smartfarm_reference.json

python scripts/build_reference_snapshot.py [outputs/smartfarm_reference/<폴더> ...]
폴더를 여러 개 주면 합친다(같은 농가·날짜는 한 번만). 생략하면 모든 조회 폴더를 합친다.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODES = {"TI": "temp", "HI": "rh"}


def main(folders):
    folders = [Path(f).resolve() for f in folders] or sorted((ROOT / "outputs" / "smartfarm_reference").glob("*Z"))
    farms = {}
    for folder in folders:
        for line in (folder / "raw.jsonl").open(encoding="utf-8"):
            r = json.loads(line)
            if r["op"] != "getEnvDataList" or not r.get("rows"):
                continue
            fid, day, _, sect, code, _ = r["args"]
            if sect != "EI" or code not in CODES:
                continue
            f = farms.setdefault((fid, day), {"facility": fid, "date": day, "month": int(day[5:7]), "temp": {}, "rh": {}})
            for x in r["rows"]:
                v = str(x.get("senVal") or "").strip()
                if v:
                    f[CODES[code]][str(int(x["measDate"][11:13]))] = float(v)
    rows = [f for f in farms.values() if f["temp"]]
    out = ROOT / "data" / "snapshots" / "smartfarm_reference.json"
    out.write_text(json.dumps({"source": "스마트팜 빅데이터 데이터마트 getEnvDataList (FG/EI/TI·HI, 토마토 080300)",
                               "probe_folders": [str(f.relative_to(ROOT)).replace("\\", "/") for f in folders],
                               "farms": sorted(rows, key=lambda f: (f["month"], f["facility"]))},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    months = {}
    for f in rows:
        months[f["month"]] = months.get(f["month"], 0) + 1
    print(f"{out}: 농가 {len(rows)}곳, 월별 {dict(sorted(months.items()))}")


if __name__ == "__main__":
    main(sys.argv[1:])
