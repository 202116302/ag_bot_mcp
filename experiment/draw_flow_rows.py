"""포스터용 그림: RAG(윗줄)와 MCP(아랫줄) 처리 흐름.  python experiment/draw_flow_rows.py
→ figures/rag_mcp_flow.png (300dpi), figures/rag_mcp_flow.svg
"""
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
plt.rcParams["font.family"] = ["Malgun Gothic", "AppleGothic", "NanumGothic", "sans-serif"]
plt.rcParams["svg.fonttype"] = "none"

NAVY, MUTED, LINE = "#2E3A4D", "#5B6573", "#C9D1DC"
RAG, RAG_FILL, RAG_HEAD = "#E07B24", "#FFF5EA", "#FCE3C8"
MCP, MCP_FILL, MCP_HEAD = "#1E9A72", "#EEF9F4", "#CDEEDF"
OUT = Path(__file__).resolve().parent.parent / "figures"

W, H = 3.1, 2.15     # 상자 크기
GAP = 0.75           # 상자 사이 간격
X0 = 1.55            # 첫 상자 왼쪽
ROWS = {"rag": 5.05, "mcp": 1.55}   # 각 줄 상자 아래쪽 y


def box(ax, x, y, title, lines, color, fill, head, strong=False):
    ax.add_patch(FancyBboxPatch((x, y), W, H, boxstyle="round,pad=0,rounding_size=0.14",
                                fc=fill if strong else "white", ec=color if strong else LINE,
                                lw=2.6 if strong else 1.4, zorder=2))
    ax.add_patch(FancyBboxPatch((x + 0.12, y + H - 0.62), W - 0.24, 0.5, boxstyle="round,pad=0,rounding_size=0.08",
                                fc=head, ec="none", zorder=3))
    ax.text(x + W / 2, y + H - 0.37, title, ha="center", va="center", fontsize=13.5, fontweight="bold", color=NAVY, zorder=4)
    for i, line in enumerate(lines):
        ax.text(x + W / 2, y + H - 1.0 - i * 0.36, line, ha="center", va="center", fontsize=11, color=MUTED, zorder=4)


def arrow(ax, x1, y1, x2, y2, color=NAVY, style="-|>", ls="-"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=18, lw=2.2,
                                 color=color, linestyle=ls, zorder=1, shrinkA=0, shrinkB=0))


def row(ax, key, label, color, fill, head, steps, strong_idx):
    y = ROWS[key]
    ax.add_patch(FancyBboxPatch((0.15, y + H / 2 - 0.36), 1.05, 0.72, boxstyle="round,pad=0,rounding_size=0.12",
                                fc=color, ec="none"))
    ax.text(0.675, y + H / 2, label, ha="center", va="center", fontsize=15, fontweight="bold", color="white")
    for i, (title, lines) in enumerate(steps):
        x = X0 + i * (W + GAP)
        box(ax, x, y, title, lines, color, fill, head, strong=(i == strong_idx))
        if i:
            arrow(ax, x - GAP + 0.06, y + H / 2, x - 0.06, y + H / 2)


def main():
    fig, ax = plt.subplots(figsize=(20, 9.2))
    ax.set_xlim(0, X0 + 5 * W + 4 * GAP + 0.2)
    ax.set_ylim(0.2, 8.6)
    ax.axis("off")

    row(ax, "rag", "RAG", RAG, RAG_FILL, RAG_HEAD, [
        ("질문", ["수치가 포함된", "구어체 질문"]),
        ("문서 검색", ["질문 임베딩 → 벡터 DB", "유사 문단 상위 5개"]),
        ("프롬프트 구성", ["질문 + 검색 문단", "(+ 흙토람 처방)"]),
        ("LLM이 판정", ["문서 기준을 직접 해석", "조건 비교·계산 수행"]),
        ("답변", ["판정 · 근거 수치", "출처 문서"]),
    ], strong_idx=3)

    row(ax, "mcp", "MCP", MCP, MCP_FILL, MCP_HEAD, [
        ("질문", ["수치가 포함된", "구어체 질문"]),
        ("LLM이 도구 선택", ["질문에서 값 추출", "필요한 도구 결정"]),
        ("MCP 서버", ["조회: 흙토람·기상청·", "데이터마트·문서 검색", "판정: 규칙 26개(코드)"]),
        ("LLM이 설명", ["규칙 판정 결과를", "바꾸지 않고 설명"]),
        ("답변", ["판정 · 근거 수치", "출처(rule_id·문서)"]),
    ], strong_idx=2)

    # MCP: LLM ↔ 서버 왕복(도구 호출과 결과 반환)
    xs, xe = X0 + 1 * (W + GAP), X0 + 2 * (W + GAP)
    yb = ROWS["mcp"]
    ax.annotate("", xy=(xs + W / 2, yb - 0.02), xytext=(xe + W / 2, yb - 0.02),
                arrowprops=dict(arrowstyle="-|>", color=MCP, lw=2, linestyle=(0, (4, 3)),
                                connectionstyle="arc3,rad=-0.35", mutation_scale=16))
    ax.text((xs + xe + W) / 2, yb - 1.05, "도구 호출 ↔ 결과 반환 (필요한 만큼 반복)", ha="center", va="center",
            fontsize=11, color=MCP, fontweight="bold")

    # 판정 주체 표시
    for key, idx, text, color in [("rag", 3, "판정 주체: LLM", RAG), ("mcp", 2, "판정 주체: 규칙(코드)", MCP)]:
        x = X0 + idx * (W + GAP)
        ax.text(x + W / 2, ROWS[key] + H + 0.28, text, ha="center", va="center", fontsize=11.5,
                fontweight="bold", color=color)

    ax.plot([0.15, ax.get_xlim()[1] - 0.2], [4.35, 4.35], color=LINE, lw=1, ls=(0, (2, 3)))
    OUT.mkdir(exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(OUT / f"rag_mcp_flow.{ext}", dpi=300, bbox_inches="tight", facecolor="white")
    print(OUT / "rag_mcp_flow.png")


if __name__ == "__main__":
    main()
