"""결과 그래프.  python experiment/plot.py outputs/v3/<폴더>

summary.csv → overall.png(조건별 4개 지표), by_type.png(시나리오 유형별 정확도), by_domain.png(영역별 정확도)
"""
import csv
import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
plt.rcParams["font.family"] = ["Malgun Gothic", "AppleGothic", "NanumGothic", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
COLORS = {"rag": "#dd8452", "mcp": "#2b6cb0"}
TYPE_KO = {"simple": "단순", "boundary": "경계", "complex": "복합", "calculation": "계산", "missing": "누락"}
DOMAIN_KO = {"climate": "환경제어", "nutrient": "양액", "fertilizer": "시비", "weather": "기상대응", "task": "작업관리"}


def bars(ax, labels, series: dict, title, ylabel="%", annotate=True):
    conds = list(series)
    width = 0.8 / len(conds)
    for i, c in enumerate(conds):
        xs = [j + i * width for j in range(len(labels))]
        b = ax.bar(xs, series[c], width, label=c.upper(), color=COLORS.get(c))
        if annotate:
            ax.bar_label(b, fmt="%.0f", fontsize=8)
    ax.set_xticks([j + width * (len(conds) - 1) / 2 for j in range(len(labels))], labels)
    ax.set_ylim(0, 110)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend()


def main(folder: str):
    folder = Path(folder)
    with (folder / "summary.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    conds = [c for c in ["rag", "mcp"] if any(r["condition"] == c for r in rows)]
    get = lambda c, g, v, m: float(next(r[m] for r in rows if r["condition"] == c and r["group"] == g and r["value"] == v)) * 100

    metrics = [("accuracy", "판정 정확도"), ("consistency", "판정 일치율"), ("missing_rate", "필수 항목 누락률"), ("evidence_rate", "근거 제시율")]
    fig, ax = plt.subplots(figsize=(7, 4))
    bars(ax, [m[1] for m in metrics], {c: [get(c, "all", "all", m) for m, _ in metrics] for c in conds}, "RAG vs MCP 전체 비교")
    fig.tight_layout()
    fig.savefig(folder / "overall.png", dpi=200)

    for group, names, fname, title in [("type", TYPE_KO, "by_type.png", "시나리오 유형별 판정 정확도"),
                                       ("domain", DOMAIN_KO, "by_domain.png", "영역별 판정 정확도")]:
        keys = [k for k in names if any(r["group"] == group and r["value"] == k for r in rows)]
        fig, ax = plt.subplots(figsize=(7, 4))
        bars(ax, [names[k] for k in keys], {c: [get(c, group, k, "accuracy") for k in keys] for c in conds}, title, "정확도 (%)")
        fig.tight_layout()
        fig.savefig(folder / fname, dpi=200)
    print(f"저장: {folder}/overall.png, by_type.png, by_domain.png")


if __name__ == "__main__":
    main(sys.argv[1])
