"""경쟁사 분석 (P1 소유) — PRD §7.6, 보너스 B1

브리프에 competitors가 있을 때만 실행합니다 (main.py에서 판단).

⚠️ LLM은 실존 기업에 대해 사실이 아닌 내용을 자신 있게 씁니다.
온도를 0.4로 낮추고 "모르면 모른다고 쓰라"는 지시를 넣지만, 그래도
결과물에 "AI 추정이며 사실 확인 필요"라는 문구를 함께 남깁니다.
이건 기술 문제가 아니라 정직성 문제입니다.
"""

from __future__ import annotations

from . import brief as brief_mod
from . import llm, logger

STEP = "competitor"
LABEL = "[5/7] 경쟁사 분석 중..."
SKIP_LABEL = "[5/7] 경쟁사 분석"  # 건너뛸 때는 "분석 중..."이 어색합니다

DISCLAIMER = "AI가 공개 정보를 바탕으로 추정한 결과이며 사실 확인이 필요합니다."

SCHEMA = {
    "type": "object",
    "properties": {
        "competitors": {
            "type": "object",
            "properties": {
                "analysis": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "positioning": {"type": "string"},
                            "strength": {"type": "string"},
                        },
                        "required": ["name", "positioning", "strength"],
                    },
                },
                # 과제 요건 B1은 개수를 지정하지 않습니다("차별화 포인트를 제안한다").
                # 프롬프트로 3개를 요청하되, 2개가 와도 요건은 충족되므로
                # 검증으로 탈락시키지 않습니다. 초과분만 generate()에서 자릅니다.
                "differentiation": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "point": {"type": "string"},
                            "why": {"type": "string"},
                            "linked_keyword": {"type": "string"},
                        },
                        "required": ["point", "why", "linked_keyword"],
                    },
                },
            },
            "required": ["analysis", "differentiation"],
        }
    },
    "required": ["competitors"],
}


def build_prompt(data: dict) -> str:
    return (
        "당신은 브랜드 전략 분석가입니다.\n"
        "아래 브랜드의 경쟁사를 분석하고 차별화 포인트를 제안하세요.\n\n"
        f"{brief_mod.base_block(data)}\n"
        f"경쟁사: {brief_mod.competitors_text(data)}\n\n"
        "조건:\n"
        "- 각 경쟁사에 대해 추정되는 포지셔닝과 강점을 각각 한 문장으로 정리합니다.\n"
        "- 확인되지 않은 매출·점유율 같은 수치를 지어내지 않습니다.\n"
        '  모르면 "공개 정보 부족"이라고 씁니다.\n'
        "- 마지막에 이 브랜드가 취할 차별화 포인트 3개를 제안합니다.\n"
        f"- 각 차별화 포인트는 브리프의 키워드({brief_mod.keywords_text(data)}) 중\n"
        "  최소 하나와 연결되어야 하며, linked_keyword에 그 키워드를 적습니다."
    )


def generate(data: dict, *, errors: list) -> dict | None:
    logger.step_start(LABEL)

    result = llm.generate_json(
        build_prompt(data), SCHEMA, step=STEP, errors=errors, brief=data
    )
    if result is None:
        logger.step_fail(LABEL, logger.last_reason(errors, STEP))
        return None

    payload = dict(result.get("competitors") or {})
    analysis = [a for a in (payload.get("analysis") or []) if isinstance(a, dict)]
    points = [d for d in (payload.get("differentiation") or []) if isinstance(d, dict)][:3]

    if not analysis and not points:
        logger.record_error(
            errors, step=STEP, type_="invalid", message="분석 결과가 비어 있습니다"
        )
        logger.step_fail(LABEL, "분석 결과가 비어 있습니다")
        return None

    logger.step_ok(LABEL, f"경쟁사 {len(analysis)}곳 · 차별화 포인트 {len(points)}개")
    return {"analysis": analysis, "differentiation": points, "disclaimer": DISCLAIMER}
