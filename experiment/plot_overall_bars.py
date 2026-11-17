"""포스터 결과 그래프: 지표별 RAG vs MCP 막대 (seaborn).
python experiment/plot_overall_bars.py [outputs/v3/v3.3_combined]
→ figures/results_overall.png (300dpi), figures/results_overall.svg
두 조건 중 더 높은 값의 라벨을 빨간색으로 표시한다.
"""
import csv
import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
ROOT = Path(__file__).resolve().parent.parent
METRICS = [("accuracy", "판정 정확도"), ("consistency", "판정 일치율"),
           ("missing_rate", "필수 항목 누락률"), ("evidence_rate", "근거 제시율")]
COLORS = {"RAG": "#F2A65A", "MCP": "#4FB38E"}   # 흐름도와 같은 계열의 부드러운 주황·초록
HIGHLIGHT, TEXT = "#D62828", "#3A4250"


def main(folder: str):
    rows = {r["condition"]: r for r in csv.DictReader((Path(folder) / "summary.csv").open(encoding="utf-8-sig"))
            if r["group"] == "all"}
    df = pd.DataFrame([{"지표": label, "조건": cond.upper(), "값": float(rows[cond][key]) * 100}
                       for key, label in METRICS for cond in ("rag", "mcp")])

    sns.set_theme(style="whitegrid", font="Malgun Gothic", rc={"axes.unicode_minus": False})
    fig, ax = plt.subplots(figsize=(10, 6))
    sns.barplot(data=df, x="지표", y="값", hue="조건", hue_order=["RAG", "MCP"], palette=COLORS, width=0.68, gap=0.06,
                edgecolor="white", linewidth=1.5, ax=ax)

    # 막대 위 수치: 지표마다 더 높은 쪽을 빨간색 굵게
    containers = dict(zip(["RAG", "MCP"], ax.containers))  # hue_order 순서
    for i, (_, label) in enumerate(METRICS):
        bars = {cond: containers[cond][i] for cond in ("RAG", "MCP")}
        hi = max(bars, key=lambda c: bars[c].get_height())
        for cond, bar in bars.items():
            v = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, v + 1.5, f"{v:.1f}%", ha="center", va="bottom",
                    fontsize=13, fontweight="bold" if cond == hi else "normal",
                    color=HIGHLIGHT if cond == hi else TEXT)

    ax.set_ylim(0, 112)
    ax.set_yticks(range(0, 101, 20))
    ax.set_yticklabels([f"{t}%" for t in range(0, 101, 20)], fontsize=12)
    ax.set_xlabel("")
    ax.set_ylabel("비율 (%)", fontsize=13)
    ax.tick_params(axis="x", labelsize=13.5)
    ax.grid(axis="x", visible=False)
    sns.despine(left=True)
    ax.legend(title="", fontsize=13, frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)

    out = ROOT / "figures"
    for ext in ("png", "svg"):
        fig.savefig(out / f"results_overall.{ext}", dpi=300, bbox_inches="tight", facecolor="white")
    print(out / "results_overall.png")
    print(df.pivot(index="지표", columns="조건", values="값").round(1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "outputs" / "v3" / "v3.3_combined"))
