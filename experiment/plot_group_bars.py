"""포스터 결과 그래프: 시나리오 유형별·영역별 판정 정확도 (RAG vs MCP, seaborn).
python experiment/plot_group_bars.py [outputs/v3/v3.3_combined]
→ figures/results_by_type.png·svg, figures/results_by_domain.png·svg
더 높은 값의 라벨을 빨간색으로 표시한다 (plot_overall_bars.py와 같은 스타일).
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
COLORS = {"RAG": "#F2A65A", "MCP": "#4FB38E"}
HIGHLIGHT, TEXT = "#D62828", "#3A4250"
GROUPS = {
    "type": ("results_by_type", [("simple", "단순 판정"), ("boundary", "기준값 경계"), ("complex", "복합 조건"),
                                 ("calculation", "수치 계산"), ("missing", "정보 누락")]),
    "domain": ("results_by_domain", [("climate", "환경제어"), ("nutrient", "양액관리"), ("fertilizer", "시비"),
                                     ("weather", "기상대응"), ("task", "작업관리")]),
}


def draw(summary: dict, group: str):
    name, items = GROUPS[group]
    df = pd.DataFrame([{"항목": label, "조건": c.upper(), "값": float(summary[(c, group, key)]["accuracy"]) * 100}
                       for key, label in items for c in ("rag", "mcp")])
    sns.set_theme(style="whitegrid", font="Malgun Gothic", rc={"axes.unicode_minus": False})
    fig, ax = plt.subplots(figsize=(10, 6))
    sns.barplot(data=df, x="항목", y="값", hue="조건", hue_order=["RAG", "MCP"], palette=COLORS, width=0.68, gap=0.06,
                edgecolor="white", linewidth=1.5, ax=ax)
    containers = dict(zip(["RAG", "MCP"], ax.containers))
    for i in range(len(items)):
        bars = {c: containers[c][i] for c in ("RAG", "MCP")}
        hi = max(bars, key=lambda c: bars[c].get_height())
        for c, bar in bars.items():
            v = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, v + 1.5, f"{v:.0f}%", ha="center", va="bottom", fontsize=13,
                    fontweight="bold" if c == hi else "normal", color=HIGHLIGHT if c == hi else TEXT)
    ax.set_ylim(0, 112)
    ax.set_yticks(range(0, 101, 20))
    ax.set_yticklabels([f"{t}%" for t in range(0, 101, 20)], fontsize=12)
    ax.set_xlabel("")
    ax.set_ylabel("판정 정확도 (%)", fontsize=13)
    ax.tick_params(axis="x", labelsize=13.5)
    ax.grid(axis="x", visible=False)
    sns.despine(left=True)
    ax.legend(title="", fontsize=13, frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
    for ext in ("png", "svg"):
        fig.savefig(ROOT / "figures" / f"{name}.{ext}", dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(ROOT / "figures" / f"{name}.png")


def main(folder: str):
    summary = {(r["condition"], r["group"], r["value"]): r
               for r in csv.DictReader((Path(folder) / "summary.csv").open(encoding="utf-8-sig"))}
    for group in GROUPS:
        draw(summary, group)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "outputs" / "v3" / "v3.3_combined"))
