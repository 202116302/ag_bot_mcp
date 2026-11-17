"""포스터용 그림: RAG(윗줄)와 MCP(아랫줄)의 기술 구성.  python experiment/draw_flow_rows.py
→ figures/rag_mcp_flow_detail.png (300dpi), figures/rag_mcp_flow_detail.svg

각 단계의 실제 구성 요소(모델, DB, 통신 방식, 설정값)와 두 조건이 공유하는 벡터 DB,
MCP 서버 내부(조회·판정 도구, 외부 API, 규칙표), 실험 사례(ENV-GH-003)의 실제 호출 값을 표시한다.
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
MONO = ["Consolas", "Malgun Gothic", "monospace"]

NAVY, MUTED, LINE, GREY_FILL = "#2E3A4D", "#5B6573", "#C9D1DC", "#F4F6F9"
RAG, RAG_FILL, RAG_HEAD = "#E07B24", "#FFF5EA", "#FCE3C8"
MCP, MCP_FILL, MCP_HEAD = "#1E9A72", "#EEF9F4", "#CDEEDF"
DB, DB_FILL = "#3F6CB0", "#EEF3FB"
OUT = Path(__file__).resolve().parent.parent / "figures"


def rbox(ax, x, y, w, h, ec=LINE, fc="white", lw=1.4, r=0.14, z=2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw, zorder=z))


def card(ax, x, y, w, h, title, lines, head, ec=LINE, fc="white", lw=1.4, mono_from=99):
    """제목 띠 + 본문 줄. mono_from 이후 줄은 고정폭(코드·값)."""
    rbox(ax, x, y, w, h, ec=ec, fc=fc, lw=lw)
    rbox(ax, x + 0.1, y + h - 0.56, w - 0.2, 0.46, ec="none", fc=head, r=0.08, z=3)
    ax.text(x + w / 2, y + h - 0.33, title, ha="center", va="center", fontsize=12.5, fontweight="bold", color=NAVY, zorder=4)
    for i, line in enumerate(lines):
        mono = i >= mono_from
        ax.text(x + w / 2, y + h - 0.88 - i * 0.33, line, ha="center", va="center", zorder=4,
                fontsize=9.6 if mono else 10.3, color=NAVY if mono else MUTED, family=MONO if mono else None)


def arrow(ax, p1, p2, color=NAVY, lw=2.0, ls="-", rad=0.0, both=False):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="<|-|>" if both else "-|>", mutation_scale=16, lw=lw, color=color,
                                 linestyle=ls, zorder=1, shrinkA=0, shrinkB=0, connectionstyle=f"arc3,rad={rad}"))


def code(ax, x, y, text, color, ha="center", size=9.4):
    ax.text(x, y, text, ha=ha, va="center", fontsize=size, family=MONO, color=color, zorder=5,
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=color, lw=0.8))


def pill(ax, y, label, color):
    rbox(ax, 0.15, y - 0.36, 1.15, 0.72, ec="none", fc=color, r=0.12)
    ax.text(0.725, y, label, ha="center", va="center", fontsize=15, fontweight="bold", color="white")


def main():
    fig, ax = plt.subplots(figsize=(24, 14.5))
    ax.set_xlim(0, 24.2)
    ax.set_ylim(-0.5, 14.6)
    ax.axis("off")

    # ---------------------------------------------------------------- RAG (윗줄)
    yR, hR, w, gap = 10.9, 2.55, 3.05, 0.55
    xs = [1.6 + i * (w + gap) for i in range(6)]
    pill(ax, yR + hR / 2, "RAG", RAG)
    rag_cards = [
        ("① 질문 입력", ["수치가 포함된 구어체 질문", "시나리오 25개 × 10회"], -1),
        ("② 질문 임베딩", ["OpenAI Embeddings API", "text-embedding-3-small", "1536차원 벡터"], 1),
        ("③ 벡터 검색", ["Chroma · 코사인 유사도", "top-k = 5 문단", "doc_id · page 메타데이터"], 1),
        ("④ 프롬프트 조립", ["지시문 + [현재 상황]", "+ [참고 문서 5개] + 질문", "흙토람 처방은 텍스트로 삽입"], 99),
        ("⑤ LLM 판정 (1회 호출)", ["GPT-5.4-mini · Responses API", "문서 기준 해석·계산·판정", "도구 없음"], 99),
        ("⑥ 구조화 응답", ["JSON Schema (strict)", "answer · decision · key_values", "basis · sources"], 1),
    ]
    for i, (t, lines, m) in enumerate(rag_cards):
        strong = i == 4
        card(ax, xs[i], yR, w, hR, t, lines, RAG_HEAD, ec=RAG if strong else LINE, fc=RAG_FILL if strong else "white",
             lw=2.6 if strong else 1.4, mono_from=m if m >= 0 else 99)
        if i:
            arrow(ax, (xs[i] - gap + 0.05, yR + hR / 2), (xs[i] - 0.05, yR + hR / 2))
    ax.text(xs[4] + w / 2, yR + hR + 0.3, "판정 주체: LLM", ha="center", fontsize=12, fontweight="bold", color=RAG)
    code(ax, xs[2] + w / 2 + (w + gap) / 2, yR - 0.55, "NONGSARO-073, NONGSARO-108, … JEJU-059", RAG)
    code(ax, xs[5] + w / 2, yR - 0.55, "\"짧게 환기하세요\"  → 5/10 정답", RAG)

    # ---------------------------------------------------------------- 공유 자원: 벡터 DB
    yD, hD = 8.05, 1.25
    xD, wD = xs[1], xs[3] + w - xs[1]
    rbox(ax, xD, yD, wD, hD, ec=DB, fc=DB_FILL, lw=1.8)
    ax.text(xD + 0.25, yD + hD - 0.36, "공유 자원 · 참고 문서 벡터 DB (두 조건 동일)", fontsize=12, fontweight="bold", color=DB, va="center")
    ax.text(xD + 0.25, yD + 0.38, "문서 5종 → 683개 문단 (약 700자, 200자 중첩)  ·  Chroma 컬렉션  ·  임베딩 text-embedding-3-small",
            fontsize=10.3, color=NAVY, va="center")
    arrow(ax, (xs[2] + w / 2, yD + hD + 0.05), (xs[2] + w / 2, yR - 0.05), color=DB, both=True)
    ax.text(xD + wD + 0.25, yD + hD / 2, "규칙 26개의 근거 문구가\n모두 이 DB 안에 있는지\n자동 테스트로 확인", fontsize=10, color=MUTED, va="center")

    # ---------------------------------------------------------------- MCP (아랫줄)
    yM, hM = 0.95, 5.75
    pill(ax, yM + hM / 2 + 0.2, "MCP", MCP)
    q_x, llm_x, srv_x = xs[0], xs[1], xs[1] + w + 2.75
    srv_w, out_x = 24.0 - 3.35 - srv_x - 0.45, 24.0 - 3.35
    ymid = yM + hM / 2 + 0.2
    card(ax, q_x, ymid - 1.27, w, 2.55, "① 질문 입력", ["수치가 포함된 구어체 질문", "(값은 질문 안에만 존재)"], MCP_HEAD)
    card(ax, llm_x, ymid - 1.6, w, 3.2, "② LLM 도구 선택", ["GPT-5.4-mini · Responses API", "function calling", "도구 13개 JSON 스키마 노출",
                                                         "질문에서 인자 값 추출", "최대 8회 왕복"], MCP_HEAD)
    arrow(ax, (q_x + w + 0.05, ymid), (llm_x - 0.05, ymid))

    # MCP 서버 (큰 상자)
    rbox(ax, srv_x, yM, srv_w, hM, ec=MCP, fc=MCP_FILL, lw=2.6)
    ax.text(srv_x + srv_w / 2, yM + hM - 0.34, "③ MCP 서버  (Python FastMCP · stdio JSON-RPC)", ha="center", va="center",
            fontsize=13, fontweight="bold", color=NAVY)
    cw = (srv_w - 0.6) / 2
    cx1, cx2 = srv_x + 0.2, srv_x + 0.4 + cw
    ax.text(cx2 + cw / 2, yM + hM + 0.3, "판정 주체: 규칙(코드)", ha="center", fontsize=12, fontweight="bold", color=MCP)
    ctop = yM + hM - 0.75
    # 조회 도구
    rbox(ax, cx1, yM + 0.25, cw, ctop - yM - 0.25, ec=LINE, fc="white")
    ax.text(cx1 + cw / 2, ctop - 0.3, "조회 도구 8개 → 데이터 출처", ha="center", fontsize=11.5, fontweight="bold", color=NAVY)
    look = [("get_fertilizer_prescription", "흙토람 비료처방 API"), ("get_weather", "기상청 예보·실황 API"),
            ("get_farm_reference", "스마트팜 데이터마트 (27농가)"), ("search_guideline", "벡터 DB (공유 자원)"),
            ("get_crop_status 외 4개", "시나리오·작물 정보")]
    for i, (fn, src) in enumerate(look):
        yy = ctop - 0.85 - i * 0.78
        ax.text(cx1 + 0.2, yy + 0.15, fn, fontsize=10, family=MONO, color=NAVY, va="center")
        ax.text(cx1 + 0.2, yy - 0.17, "→ " + src, fontsize=10, color=MUTED, va="center")
    # 판정 도구
    rbox(ax, cx2, yM + 0.25, cw, ctop - yM - 0.25, ec=MCP, fc="white", lw=1.6)
    ax.text(cx2 + cw / 2, ctop - 0.3, "판정 도구 5개 → 규칙표 (rules.yaml)", ha="center", fontsize=11.5, fontweight="bold", color=NAVY)
    judge = ["climate_control_decision", "nutrient_decision", "fertilizer_schedule", "weather_risk_decision", "task_decision"]
    for i, fn in enumerate(judge):
        ax.text(cx2 + 0.2, ctop - 0.8 - i * 0.36, fn, fontsize=10, family=MONO, color=NAVY, va="center")
    ax.text(cx2 + 0.2, ctop - 2.75, "규칙 26개: 임계값·경계 처리·우선순위", fontsize=10.2, color=MUTED, va="center")
    ax.text(cx2 + 0.2, ctop - 3.08, "각 규칙 = rule_id ↔ doc_id ↔ 원문 문구", fontsize=10.2, color=MUTED, va="center")
    ax.text(cx2 + 0.2, ctop - 3.6, "출력: result · basis · rule_ids · sources", fontsize=9.0, family=MONO, color=NAVY, va="center")
    ax.text(cx2 + 0.2, ctop - 3.92, "      inputs_used · missing_inputs · status", fontsize=9.0, family=MONO, color=NAVY, va="center")
    # search_guideline ↔ 벡터 DB
    arrow(ax, (cx1 + cw / 2, yM + hM + 0.05), (cx1 + cw / 2, yD - 0.05), color=DB, both=True)
    ax.text(cx1 + cw / 2 + 0.15, (yM + hM + yD) / 2, "search_guideline", fontsize=9.6, family=MONO, color=DB, va="center")

    # LLM ⇄ 서버 (실제 호출 예: ENV-GH-003)
    ax_y1, ax_y2 = ymid + 0.55, ymid - 0.55
    arrow(ax, (llm_x + w + 0.05, ax_y1), (srv_x - 0.05, ax_y1), color=MCP)
    arrow(ax, (srv_x - 0.05, ax_y2), (llm_x + w + 0.05, ax_y2), color=MCP)
    gx = (llm_x + w + srv_x) / 2
    code(ax, gx, ax_y1 + 0.62, "climate_control_decision(\n temp=16, rh=85,\n outdoor=8, time=night)", MCP, size=9)
    code(ax, gx, ax_y2 - 0.62, "{decision: \"송풍 필요\",\n rule_ids: [ENV-06, ENV-08],\n status: decided}", MCP, size=9)
    ax.text(gx, ymid, "도구 호출 ⇄ 결과", ha="center", va="center", fontsize=10.5, fontweight="bold", color=MCP)

    # ④ 최종 응답: LLM에서 아래로 돌아 오른쪽 끝
    card(ax, out_x, ymid - 1.6, 3.35, 3.2, "④ LLM 설명 · 응답", ["도구 판정은 바꾸지 않고 설명", "같은 JSON Schema 출력",
                                                           "출처 = rule_id · doc_id", "다른 농가 참고 한두 문장"], MCP_HEAD)
    yr = yM - 0.4
    ax.plot([llm_x + w / 2, llm_x + w / 2, out_x + 3.35 / 2], [ymid - 1.65, yr, yr], color=NAVY, lw=2, zorder=1,
            solid_capstyle="round", solid_joinstyle="round")
    arrow(ax, (out_x + 3.35 / 2, yr), (out_x + 3.35 / 2, ymid - 1.65))
    ax.text((llm_x + out_x + 3.35) / 2, yr - 0.28, "도구 결과를 받은 뒤 최종 답변 생성", ha="center", va="center",
            fontsize=10.5, color=NAVY)
    code(ax, out_x + 3.35 / 2, ymid + 2.05, "\"환기보다 송풍\"  → 9/10 정답", MCP)

    ax.plot([0.15, 24.0], [7.62, 7.62], color=LINE, lw=1, ls=(0, (2, 3)), zorder=0)
    ax.text(24.0, -0.35, "예시 값: 시나리오 ENV-GH-003 \"11월 밤 10시, 하우스 습도 85%, 16℃, 바깥 8℃. 환기할까?\" (v3.3 실험)",
            ha="right", fontsize=10, color=MUTED)

    OUT.mkdir(exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(OUT / f"rag_mcp_flow_detail.{ext}", dpi=300, bbox_inches="tight", facecolor="white")
    print(OUT / "rag_mcp_flow_detail.png")


if __name__ == "__main__":
    main()
