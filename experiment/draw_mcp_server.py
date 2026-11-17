"""포스터용 모식도: MCP 서버 구성 (기관 로고 활용, 글자 최소화).  python experiment/draw_mcp_server.py
→ figures/mcp_server.png (300dpi), figures/mcp_server.svg
로고 파일: figures/흙토람로고.png, 기상청로고.jpg, 스마트팜데이터마트로고.jpg, 농사로 로고.png
"""
import logging
from pathlib import Path

import matplotlib
import numpy as np
from PIL import Image

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Arc, Ellipse, FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
plt.rcParams["font.family"] = ["Malgun Gothic", "AppleGothic", "NanumGothic", "sans-serif"]
plt.rcParams["svg.fonttype"] = "none"

FIG = Path(__file__).resolve().parent.parent / "figures"
NAVY, MUTED, LINE = "#2E3A4D", "#5B6573", "#C9D1DC"
MCP, MCP_FILL, MCP_SOFT = "#1E9A72", "#EEF9F4", "#CDEEDF"
API, DOC, RULE = "#3F6CB0", "#7A5AA6", "#1E9A72"


def logo(name: str) -> np.ndarray:
    """흰 여백을 잘라낸 로고 이미지."""
    im = Image.open(FIG / name).convert("RGBA")
    rgb = np.asarray(im.convert("RGB")).astype(int)
    mask = (np.abs(255 - rgb).sum(axis=2) > 30) & (np.asarray(im)[:, :, 3] > 20)
    ys, xs = np.where(mask)
    pad = 6
    return np.asarray(im.crop((max(xs.min() - pad, 0), max(ys.min() - pad, 0),
                               min(xs.max() + pad, im.width), min(ys.max() + pad, im.height))))


def put(ax, img, cx, cy, max_w, max_h):
    h, w = img.shape[:2]
    s = min(max_w / w, max_h / h)
    ax.imshow(img, extent=(cx - w * s / 2, cx + w * s / 2, cy - h * s / 2, cy + h * s / 2), zorder=4,
              interpolation="lanczos")


def rbox(ax, x, y, w, h, ec=LINE, fc="white", lw=1.5, r=0.18, z=2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw, zorder=z))


def tag(ax, x, y, text, color):
    ax.text(x, y, text, ha="center", va="center", fontsize=12.5, fontweight="bold", color="white", zorder=6,
            bbox=dict(boxstyle="round,pad=0.38,rounding_size=0.5", fc=color, ec="none"))


def link(ax, p1, p2, color, both=False, lw=2.2, ls="-", z=1):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="<|-|>" if both else "-|>", mutation_scale=17, lw=lw,
                                 color=color, linestyle=ls, zorder=z, shrinkA=0, shrinkB=0))


def cylinder(ax, cx, cy, w, h, color):
    e = h * 0.18
    ax.add_patch(Rectangle((cx - w / 2, cy - h / 2), w, h, fc="white", ec="none", zorder=3))
    for y in (cy - h / 2, cy - h / 6, cy + h / 6):  # 몸통 띠는 아래쪽 반원만
        ax.add_patch(Arc((cx, y), w, e * 2, theta1=180, theta2=360, ec=color, lw=2, zorder=4))
    ax.add_patch(Ellipse((cx, cy + h / 2), w, e * 2, fc=MCP_SOFT, ec=color, lw=2, zorder=4))
    ax.plot([cx - w / 2, cx - w / 2], [cy - h / 2, cy + h / 2], color=color, lw=2, zorder=4)
    ax.plot([cx + w / 2, cx + w / 2], [cy - h / 2, cy + h / 2], color=color, lw=2, zorder=4)


def main():
    fig, ax = plt.subplots(figsize=(15, 9.6))
    ax.set_xlim(0, 14.2)
    ax.set_ylim(0, 9.2)
    ax.set_aspect("equal")
    ax.axis("off")

    # MCP 서버 (중앙 허브)
    hx, hy, hw, hh = 5.9, 3.85, 3.8, 1.6
    rbox(ax, hx, hy, hw, hh, ec=MCP, fc=MCP_FILL, lw=3, r=0.3)
    ax.text(hx + hw / 2, hy + hh / 2 + 0.22, "MCP 서버", ha="center", va="center", fontsize=22, fontweight="bold", color=NAVY, zorder=5)
    ax.text(hx + hw / 2, hy + hh / 2 - 0.38, "조회 · 검색 · 판정 도구", ha="center", va="center", fontsize=12.5, color=MUTED, zorder=5)

    # LLM (왼쪽)
    lx, ly, lw_, lh = 0.4, 3.85, 3.0, 1.6
    rbox(ax, lx, ly, lw_, lh, ec=NAVY, fc="white", lw=2.2, r=0.3)
    ax.text(lx + lw_ / 2, ly + lh / 2 + 0.2, "LLM", ha="center", va="center", fontsize=20, fontweight="bold", color=NAVY)
    ax.text(lx + lw_ / 2, ly + lh / 2 - 0.38, "GPT-5.4-mini", ha="center", va="center", fontsize=12, color=MUTED)
    link(ax, (lx + lw_ + 0.08, hy + hh / 2 + 0.33), (hx - 0.08, hy + hh / 2 + 0.33), MCP)
    link(ax, (hx - 0.08, hy + hh / 2 - 0.33), (lx + lw_ + 0.08, hy + hh / 2 - 0.33), MCP)
    ax.text((lx + lw_ + hx) / 2, hy + hh / 2 + 0.68, "도구 호출", ha="center", fontsize=12, color=MCP, fontweight="bold")
    ax.text((lx + lw_ + hx) / 2, hy + hh / 2 - 0.82, "판정 · 근거 반환", ha="center", fontsize=12, color=MCP, fontweight="bold")

    # 위: 외부 데이터 연계 (API)
    cw, ch, cy0 = 3.3, 2.05, 6.55
    cards = [("흙토람로고.png", "필지별 비료 처방", 4.1),
             ("기상청로고.jpg", "기상 예보 · 실황", 7.8),
             ("스마트팜데이터마트로고.jpg", "토마토 농가 27곳\n온 · 습도 기록", 11.5)]
    tag(ax, 7.8, cy0 + ch + 0.45, "외부 데이터 연계 (API)", API)
    for file, cap, cx in cards:
        rbox(ax, cx - cw / 2, cy0, cw, ch, ec=API, lw=1.8)
        put(ax, logo(file), cx, cy0 + ch * 0.62, cw * 0.78, ch * 0.5)
        ax.text(cx, cy0 + 0.36, cap, ha="center", va="center", fontsize=12, color=NAVY, zorder=5, linespacing=1.2)
        link(ax, (cx, cy0 - 0.06), (min(max(cx, hx + 0.4), hx + hw - 0.4), hy + hh + 0.06), API, both=True)

    # 아래 왼쪽: 문서 검색
    dx, dy, dw, dh = 2.6, 0.55, 4.6, 2.3
    tag(ax, dx + dw / 2, dy + dh + 0.42, "재배 지침 검색", DOC)
    rbox(ax, dx, dy, dw, dh, ec=DOC, lw=1.8)
    put(ax, logo("농사로 로고.png"), dx + 1.25, dy + dh / 2 + 0.25, 1.9, 1.35)
    ax.text(dx + 1.25, dy + 0.33, "재배 지침 · 논문 5종", ha="center", va="center", fontsize=11.5, color=NAVY)
    link(ax, (dx + 2.35, dy + dh / 2 + 0.2), (dx + 3.1, dy + dh / 2 + 0.2), DOC, z=5)
    cylinder(ax, dx + 3.75, dy + dh / 2 + 0.3, 1.0, 1.05, DOC)
    ax.text(dx + 3.75, dy + 0.33, "벡터 DB", ha="center", va="center", fontsize=11.5, color=NAVY)
    link(ax, (dx + dw * 0.72, dy + dh + 0.06), (hx + 0.6, hy - 0.06), DOC, both=True)

    # 아래 오른쪽: 규칙 판정
    rx, ry, rw, rh = 8.6, 0.55, 4.6, 2.3
    tag(ax, rx + rw / 2, ry + rh + 0.42, "규칙 판정", RULE)
    rbox(ax, rx, ry, rw, rh, ec=RULE, lw=1.8)
    ax.text(rx + rw / 2, ry + rh - 0.62, "판정 규칙 26개", ha="center", va="center", fontsize=17, fontweight="bold", color=NAVY)
    ax.text(rx + rw / 2, ry + rh - 1.12, "문서 기준을 코드로 구현", ha="center", va="center", fontsize=11.5, color=MUTED)
    ax.text(rx + rw / 2, ry + 0.5, "환경제어 · 양액 · 시비 · 기상대응 · 작업관리", ha="center", va="center",
            fontsize=11.5, color=RULE, fontweight="bold", zorder=5,
            bbox=dict(boxstyle="round,pad=0.35,rounding_size=0.3", fc=MCP_FILL, ec="none"))
    link(ax, (rx + rw * 0.28, ry + rh + 0.06), (hx + hw - 0.6, hy - 0.06), RULE, both=True)

    for ext in ("png", "svg"):
        fig.savefig(FIG / f"mcp_server.{ext}", dpi=300, bbox_inches="tight", facecolor="white")
    print(FIG / "mcp_server.png")


if __name__ == "__main__":
    main()
