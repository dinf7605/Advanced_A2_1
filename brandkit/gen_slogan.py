"""슬로건 생성 (P3 소유) — PRD §7.3, 요건 4"""

from __future__ import annotations

from . import brief as brief_mod
from . import llm, logger

STEP = "slogan"
LABEL = "[2/7] 슬로건 생성 중..."

# angle을 스키마에 넣은 이유: 조건 없이 3개를 요청하면 비슷한 문장 3개가
# 나옵니다. 축을 미리 나눠주면 서로 다른 3개가 나옵니다.
# **프롬프트에서 다양성을 요구하는 것보다 스키마에서 슬롯을 나누는 편이
# 훨씬 안정적입니다.**
#
# tone_note는 요건 4의 "톤앤매너에 맞는 문구"를 증명하는 필드입니다.
# "맞는지"를 사람이 눈으로만 판단하면 검증이 안 되므로, 모델에게 근거를
# 같이 내게 해서 확인 가능하게 만듭니다.
SCHEMA = {
    "type": "object",
    "properties": {
        "slogans": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "angle": {"type": "string"},
                    "tone_note": {"type": "string"},
                },
                "required": ["text", "angle", "tone_note"],
            },
        }
    },
    "required": ["slogans"],
}


def build_prompt(data: dict, naming: list | None) -> str:
    # 네이밍은 "재료"이지 "의존"이 아닙니다. 없으면 이 줄을 통째로 뺍니다.
    naming_line = ""
    if naming:
        names = ", ".join(item["name_ko"] for item in naming[:5])
        naming_line = f"브랜드명 후보: {names}\n"

    return (
        "당신은 브랜드 카피라이터입니다.\n"
        "아래 브랜드에 어울리는 슬로건(태그라인) 3개를 제안하세요.\n\n"
        f"{naming_line}{brief_mod.base_block(data)}\n\n"
        "조건:\n"
        "- 각 슬로건은 20자 이내로 짧고 기억하기 쉬워야 합니다.\n"
        f'- 톤앤매너 "{brief_mod.tone_text(data)}"이(가) 문장의 어미와 어휘에서 드러나야 합니다.\n'
        "- 3개는 서로 다른 각도여야 합니다: 기능적 이점 / 감성적 가치 / 행동 유도.\n"
        "- angle 필드에는 기능, 감성, 행동유도 중 하나를 적습니다.\n"
        "- tone_note에는 그 문구가 톤앤매너를 어떻게 반영했는지 한 문장으로 적습니다."
    )


def _clean(items: list) -> list:
    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue
        cleaned.append(
            {
                "text": text,
                "angle": (item.get("angle") or "").strip() or "미분류",
                "tone_note": (item.get("tone_note") or "").strip(),
            }
        )
    return cleaned[:3]


def generate(data: dict, *, errors: list, naming: list | None = None) -> list | None:
    logger.step_start(LABEL)

    result = llm.generate_json(
        build_prompt(data, naming), SCHEMA, step=STEP, errors=errors, brief=data
    )
    if result is None:
        logger.step_fail(LABEL, logger.last_reason(errors, STEP))
        return None

    items = _clean(result.get("slogans") or [])
    if not items:
        logger.record_error(
            errors, step=STEP, type_="invalid", message="쓸 수 있는 슬로건이 없습니다"
        )
        logger.step_fail(LABEL, "쓸 수 있는 슬로건이 없습니다")
        return None

    if len(items) < 3:
        logger.record_error(
            errors,
            step=STEP,
            type_="invalid",
            message=f"슬로건이 {len(items)}개입니다 (요건 3개)",
        )

    logger.step_ok(LABEL, f'{len(items)}개 생성 — "{items[0]["text"]}" 외')
    return items
