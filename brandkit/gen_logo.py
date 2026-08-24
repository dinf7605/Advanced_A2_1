"""로고 시안 생성과 저장 (P5 소유) — PRD §7.8, 요건 7

여기가 **LLM API와 이미지 API가 만나는 지점**입니다.
LLM이 만든 브랜드명과 메인 컬러 HEX가 이미지 프롬프트의 재료가 됩니다.
다만 "의존"이 아니라 "재료"입니다 — 없으면 브리프만으로도 시안이 나옵니다
(소프트 의존). 네이밍 호출 한 번의 실패가 로고까지 연쇄로 날리지 않게 하려는
설계입니다.
"""

from __future__ import annotations

import os

from . import image_client, logger

STEP = "logo"
LABEL = "[7/7] 로고 시안 생성 중..."

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MIN_BYTES = 1000  # 이보다 작으면 이미지가 아니라 오류 본문일 가능성이 큽니다

# 2~3장을 완전히 같은 프롬프트로 요청하면 비슷한 그림이 나옵니다.
# 형식 키워드만 바꿔서 서로 다른 방향의 시안이 나오게 합니다.
VARIANTS = [
    "simple geometric symbol mark",
    "abstract monogram mark",
    "minimal emblem inside a circle",
]

# 이미지 모델은 대체로 영문 프롬프트에서 결과가 안정적입니다.
# 영문 재료(english)는 네이밍 호출에서 english_concept으로 함께 받아옵니다
# (gen_naming.SCHEMA 참고). 여기서 별도 호출을 하지 않는 이유는 요구사항이
# 요구하지 않는 LLM 호출을 늘리지 않기 위해서입니다. 없으면 한글을 그대로 씁니다.


def build_prompt(
    data: dict,
    *,
    naming: list | None = None,
    palette: dict | None = None,
    variant: str = VARIANTS[0],
    english: dict | None = None,
) -> str:
    english = english or {}
    industry = english.get("industry_en") or data["industry"]
    keywords = ", ".join(english.get("keywords_en") or data["keywords"])
    mood = english.get("tone_en") or data.get("tone") or "clean and modern"

    lines = [
        "A minimalist vector logo for a brand.",
        f"Industry: {industry}",
        f"Brand concept: {keywords}",
        f"Mood: {mood}",
    ]

    # ── 소프트 의존: 있으면 재료로 쓰고, 없으면 줄을 통째로 뺍니다 ──
    if naming:
        first = naming[0]
        name = first.get("name_en") or first.get("name_ko") or ""
        if name:
            lines.append(f"Brand concept name (for mood only, do not render it): {name}")
    if palette:
        lines.append(f"Primary color: {palette['main']['hex']}")
        accents = ", ".join(c["hex"] for c in (palette.get("subs") or []))
        if accents:
            lines.append(f"Accent colors: {accents}")

    lines.append(f"Style: flat vector, {variant}, centered, solid white background.")
    # ★ 이미지 모델은 글자를 자주 뭉갭니다. 브랜드명을 그려달라고 하면 철자가
    #   깨진 시안이 나옵니다. 심볼만 받고 글자는 나중에 얹는 것이 실무 방식이기도 합니다.
    lines.append("No text, no letters, no words, no numbers anywhere in the image.")
    return "\n".join(lines)


def _ensure_png(raw: bytes) -> bytes | None:
    """PNG 바이트인지 확인하고, 다른 이미지 형식이면 PNG로 바꿔본다.

    ★ 파일이 생겼다고 이미지가 아닙니다 ★
    API가 오류를 JSON 본문으로 돌려줬는데 그대로 .png로 저장하면 파일은
    만들어지지만 열리지 않습니다. 제출 직전에 발견하면 손 쓸 시간이 없습니다.
    """
    if len(raw) < MIN_BYTES:
        return None
    if raw[:8] == PNG_SIGNATURE:
        return raw

    # JPEG/WebP로 오는 제공자도 있습니다. Pillow가 있으면 변환하고, 없으면 포기합니다.
    try:
        import io

        from PIL import Image

        buffer = io.BytesIO()
        Image.open(io.BytesIO(raw)).convert("RGBA").save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:
        return None


def _save(raw: bytes, out_dir: str, index: int, *, errors: list) -> str | None:
    """PNG 한 장을 저장하고 파일명을 돌려준다. 검증에 실패하면 저장하지 않는다."""
    data = _ensure_png(raw)
    if data is None:  # E15
        logger.record_error(
            errors,
            step=STEP,
            type_="invalid",
            message=f"응답이 유효한 PNG가 아니어서 저장하지 않았습니다 ({len(raw)}바이트)",
        )
        return None

    # 번호는 요청 순서가 아니라 저장 순서입니다. 3장 중 2장만 성공하면
    # logo_1, logo_2로 저장합니다 — logo_1, logo_3처럼 번호가 비면
    # 사용자가 "2번은 어디 갔나" 하고 파일을 찾게 됩니다.
    name = f"logo_{index}.png"
    try:
        # 반드시 바이너리 모드. "w"로 열면 인코딩 변환이 일어나 파일이 깨집니다.
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(data)
    except OSError as e:
        logger.record_error(
            errors, step=STEP, type_="io", message=f"로고 저장 실패 — {logger.safe_reason(e)}"
        )
        return None
    return name


def generate(
    data: dict,
    out_dir: str,
    *,
    n: int = 2,
    naming: list | None = None,
    palette: dict | None = None,
    english: dict | None = None,
    errors: list,
) -> tuple[list[str], str | None]:
    """로고 시안을 만들어 저장하고 (파일명 리스트, 대표 프롬프트)를 돌려준다."""
    logger.step_start(f"{LABEL} ({n}장)")
    base_prompt = build_prompt(data, naming=naming, palette=palette, english=english)

    saved: list[str] = []
    for order in range(n):
        variant = VARIANTS[order % len(VARIANTS)]
        prompt = build_prompt(
            data, naming=naming, palette=palette, variant=variant, english=english
        )
        images = image_client.generate_images(prompt, 1, step=STEP, errors=errors)
        if not images:
            break  # 한 번 실패하면 남은 시안도 같은 이유로 실패합니다
        for raw in images:
            name = _save(raw, out_dir, len(saved) + 1, errors=errors)
            if name:
                saved.append(name)

    if not saved:
        logger.step_fail(LABEL, logger.last_reason(errors, STEP))
        return [], base_prompt

    if len(saved) < n:
        logger.step_ok(LABEL, f"{len(saved)}장 저장 (요청 {n}장 중 일부만 성공)")
    else:
        logger.step_ok(LABEL, f"{len(saved)}장 저장 — {', '.join(saved)}")
    return saved, base_prompt
