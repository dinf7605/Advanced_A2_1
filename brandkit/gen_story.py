"""브랜드 스토리 생성 (P3 소유) — PRD §7.4, 요건 5"""

from __future__ import annotations

from . import brief as brief_mod
from . import llm, logger

STEP = "story"
LABEL = "[3/7] 브랜드 스토리 생성 중..."

MIN_CHARS, MAX_CHARS = 250, 400  # 이 범위를 벗어나면 기록만 하고 진행합니다

# background / philosophy / vision을 따로 받는 이유:
# 요건 5가 "탄생 배경, 철학, 비전을 포함한다"고 명시했는데, 산문 한 덩어리로
# 받으면 세 요소가 들어갔는지 확인할 방법이 없습니다. 필드로 나눠 받으면
# 기계적으로 확인할 수 있습니다.
SCHEMA = {
    "type": "object",
    "properties": {
        "story": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "background": {"type": "string"},
                "philosophy": {"type": "string"},
                "vision": {"type": "string"},
            },
            "required": ["text", "background", "philosophy", "vision"],
        }
    },
    "required": ["story"],
}


def build_prompt(data: dict) -> str:
    return (
        "당신은 브랜드 스토리텔러입니다.\n"
        "아래 브랜드의 스토리를 작성하세요.\n\n"
        f"{brief_mod.base_block(data)}\n\n"
        "조건:\n"
        "- 300자 내외(270~330자)의 한국어 산문 한 편으로 작성합니다.\n"
        "- 반드시 세 가지를 포함합니다: 탄생 배경 / 브랜드 철학 / 비전.\n"
        "- 소제목·불릿·번호를 쓰지 않고 이어지는 문단으로 씁니다.\n"
        "- 통계나 수상 이력처럼 검증할 수 없는 사실을 지어내지 않습니다.\n"
        "- background, philosophy, vision 필드에는 각 요소를 한 줄로 요약합니다."
    )


def generate(data: dict, *, errors: list) -> dict | None:
    logger.step_start(LABEL)

    result = llm.generate_json(
        build_prompt(data), SCHEMA, step=STEP, errors=errors, brief=data
    )
    if result is None:
        logger.step_fail(LABEL, logger.last_reason(errors, STEP))
        return None

    story = dict(result.get("story") or {})
    text = (story.get("text") or "").strip()
    if not text:
        logger.record_error(
            errors, step=STEP, type_="invalid", message="스토리 본문이 비어 있습니다"
        )
        logger.step_fail(LABEL, "본문이 비어 있습니다")
        return None

    story["text"] = text
    story["char_count"] = len(text)  # 요건의 숫자는 결과물에 기록으로 남아야 확인됩니다

    # 글자 수가 어긋나도 재시도하지 않습니다. "300자 내외"는 품질 기준이지
    # 정합성 기준이 아닙니다. 340자짜리 좋은 스토리를 버리고 재호출하면
    # 쿼터만 쓰고 결과가 나빠질 수 있습니다. 기록은 남기되 진행합니다.
    if not MIN_CHARS <= story["char_count"] <= MAX_CHARS:
        logger.record_error(
            errors,
            step=STEP,
            type_="length",
            message=f"스토리가 {story['char_count']}자입니다 (권장 300자 내외)",
        )

    logger.step_ok(LABEL, f"{story['char_count']}자")
    return story
