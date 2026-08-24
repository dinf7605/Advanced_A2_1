"""컬러 팔레트 시각화 (P4 소유) — PRD §8, 요건 6

LLM이 준 HEX를 matplotlib 사각형으로 그려 PNG로 저장합니다.
그리는 것 자체는 간단하고, 실제 난관은 두 가지입니다.
  1. 한글 폰트 — matplotlib 기본 폰트에 한글 글리프가 없어 전부 □□□로 나옴
  2. 글자 대비 — 어두운 칸에 검은 글씨를 쓰면 안 보임
"""

from __future__ import annotations

import os

from . import logger

FILENAME = "palette.png"

# 팀원 5명의 OS가 다릅니다. Windows는 Malgun Gothic, macOS는 AppleGothic이
# 기본으로 있습니다. 한 사람의 PC에서만 되는 코드는 팀 프로젝트에서 버그와
# 같으므로, 후보를 순회하며 설치된 것을 찾습니다.
FONT_CANDIDATES = [
    "Malgun Gothic",
    "AppleGothic",
    "NanumGothic",
    "Noto Sans CJK KR",
    "NanumBarunGothic",
    "Gulim",
]

_font_ready = False


def _setup_font() -> str | None:
    """한글 폰트를 지정한다. 못 찾으면 경고만 하고 진행한다 (E10).

    없어도 HEX 코드(영문·숫자)는 정상 출력되므로, 여기서 멈추는 것보다
    깨진 한글이라도 PNG를 만드는 쪽이 요건 6에 가깝습니다.
    """
    global _font_ready
    from matplotlib import font_manager, rcParams

    if _font_ready:
        return rcParams.get("font.family", [None])[0]

    installed = {f.name for f in font_manager.fontManager.ttflist}
    chosen = next((name for name in FONT_CANDIDATES if name in installed), None)
    if chosen:
        rcParams["font.family"] = chosen
    else:
        logger.warn("한글 폰트를 찾지 못했습니다. 팔레트 이미지의 한글이 깨질 수 있습니다.")

    # 마이너스 기호가 □로 나오는 것을 막습니다 (한글 폰트로 바꾸면 자주 발생)
    rcParams["axes.unicode_minus"] = False
    _font_ready = True
    return chosen


def text_color_for(hex_code: str) -> str:
    """배경 밝기에 따라 흰 글자와 검은 글자 중 하나를 고른다.

    가중치가 균등하지 않은 이유: 같은 값의 순수 초록(#00FF00)과 순수
    파랑(#0000FF)을 나란히 두면 초록이 훨씬 밝아 보입니다. 단순 평균
    (r+g+b)/3을 쓰면 남색 칸에 검은 글씨가 얹혀 안 보입니다.
    **"밝기"는 물리량이 아니라 지각량**이라 채널마다 가중치가 다릅니다.
    """
    r, g, b = (int(hex_code[i : i + 2], 16) / 255 for i in (1, 3, 5))
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#000000" if luminance > 0.55 else "#FFFFFF"


def save(palette: dict, out_dir: str, *, title: str, errors: list) -> str | None:
    """팔레트를 PNG로 저장하고 파일명을 돌려준다. 실패하면 None."""
    step = "palette_image"
    label = "[6/7] 팔레트 이미지 저장 중..."
    logger.step_start(label)

    try:
        import matplotlib

        # ★ pyplot import보다 먼저 ★ 기본 백엔드는 창을 띄우려 시도해서
        # GUI가 없는 환경에서는 멈추거나 경고가 납니다. 파일만 만들 것이므로
        # 창을 띄우지 않는 백엔드를 명시합니다. 순서가 바뀌면 적용되지 않습니다.
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError:
        logger.record_error(
            errors, step=step, type_="io", message="matplotlib이 설치되어 있지 않습니다"
        )
        logger.step_fail(label, "matplotlib 미설치")
        logger.hint("pip install matplotlib 후 다시 실행하세요.")
        return None

    _setup_font()

    swatches = [("MAIN", palette["main"], 1.5)]
    swatches += [(f"SUB {i}", c, 1.0) for i, c in enumerate(palette.get("subs") or [], 1)]

    gap = 0.14
    total = sum(w for _, _, w in swatches) + gap * (len(swatches) - 1)

    fig, ax = plt.subplots(figsize=(max(8.0, total * 1.9), 4.0), dpi=150)
    ax.set_xlim(0, total)
    ax.set_ylim(-0.34, 1.40)
    ax.axis("off")  # 눈금·테두리 제거 — 차트가 아니라 그림입니다

    ax.text(total / 2, 1.24, title, ha="center", va="center", fontsize=15, weight="bold")
    if palette.get("is_fallback"):
        ax.text(
            total / 2,
            1.06,
            "※ LLM 응답을 쓸 수 없어 기본 팔레트로 대체된 결과입니다",
            ha="center",
            va="center",
            fontsize=8.5,
            color="#B00020",
        )

    x = 0.0
    for tag, color, width in swatches:
        hex_code = color["hex"]
        fg = text_color_for(hex_code)
        ax.add_patch(Rectangle((x, 0), width, 1.0, facecolor=hex_code, edgecolor="none"))

        center = x + width / 2
        ax.text(center, 0.82, tag, ha="center", va="center", fontsize=8.5, color=fg, alpha=0.75)
        ax.text(
            center,
            0.52,
            hex_code,
            ha="center",
            va="center",
            fontsize=12,
            color=fg,
            family="monospace",
            weight="bold",
        )
        ax.text(center, 0.30, color.get("name", ""), ha="center", va="center", fontsize=10, color=fg)
        if color.get("substituted"):  # 대체된 색은 그림에서도 표시합니다
            ax.text(center, 0.13, "(기본값 대체)", ha="center", va="center", fontsize=7.5, color=fg, alpha=0.8)

        ax.text(center, -0.16, color.get("usage", ""), ha="center", va="center", fontsize=9, color="#444444")
        x += width + gap

    path = os.path.join(out_dir, FILENAME)
    try:
        fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    except OSError as e:  # E11 — 권한·경로 문제. PNG 없이 계속 진행합니다.
        logger.record_error(
            errors, step=step, type_="io", message=f"팔레트 이미지 저장 실패 — {logger.safe_reason(e)}"
        )
        logger.step_fail(label, "저장 실패")
        return None
    finally:
        plt.close(fig)  # 닫지 않으면 반복 실행 시 메모리에 figure가 쌓입니다

    logger.step_ok(label, f"{out_dir.rstrip('/')}/{FILENAME}")
    return FILENAME
