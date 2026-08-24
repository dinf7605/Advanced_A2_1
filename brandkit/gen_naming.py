"""브랜드 네이밍 생성 (P3 소유) — PRD §7.2, 요건 3 + 보너스 B2

이 파일이 갖는 것은 프롬프트 문자열과 스키마 딕셔너리, 그리고 후처리뿐입니다.
API를 아는 파일은 llm.py 하나입니다.
"""

from __future__ import annotations

from . import brief as brief_mod
from . import llm, logger

STEP = "naming"
LABEL = "[1/7] 브랜드 네이밍 생성 중..."

# 보너스 B2(다국어)를 "추가 호출"이 아니라 "스키마 확장"으로 처리합니다.
# 영문 네이밍을 따로 호출하면 한글명과 무관한 이름이 나와서 "같은 브랜드의
# 두 표기"가 되지 않습니다. 한 번의 호출에서 쌍으로 받아야 의미가 이어집니다.
#
# english_concept도 같은 이유로 여기에 얹었습니다. 이미지 모델은 영문 프롬프트에서
# 결과가 안정적이라 로고 단계에 영문 재료가 필요한데, 그걸 별도 호출로 받으면
# 요구사항이 요구하지 않는 여섯 번째 LLM 호출이 생깁니다. 무료 한도가 하루
# 20회라면 실행 3회분과 4회분의 차이입니다. required에 넣지 않았으므로
# 없어도 검증을 통과하고, 로고는 한글 브리프로 진행합니다.
#
# ★ maxItems를 일부러 넣지 않았습니다 ★
# 넣으면 6개가 온 응답이 검증에서 탈락해 재시도로 이어지고, 2회째도 6개면
# 네이밍이 통째로 null이 됩니다. 그런데 초과분은 _clean()이 잘라내면 요건
# "3~5개"를 충족합니다. **후처리로 고칠 수 있으면 고치고, 없으면 재시도**가
# 원칙이므로 부족(minItems)만 검증에 맡깁니다.
SCHEMA = {
    "type": "object",
    "properties": {
        "naming": {
            "type": "array",
            "minItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "name_ko": {"type": "string"},
                    "name_en": {"type": "string"},
                    "meaning": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["name_ko", "name_en", "meaning"],
            },
        },
        "english_concept": {
            "type": "object",
            "properties": {
                "industry_en": {"type": "string"},
                "keywords_en": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                "tone_en": {"type": "string"},
            },
            "required": ["industry_en", "keywords_en"],
        },
    },
    "required": ["naming"],
}


def build_prompt(data: dict) -> str:
    # 프롬프트에 예시 JSON을 넣지 않습니다 — 모델이 예시를 먼저 출력하고 진짜
    # 답을 이어 붙여 JSON 객체가 2개가 됩니다 (A1-2 실측: 5건 중 4건 실패).
    # 구조는 SCHEMA가 강제하므로 여기서는 조건만 산문으로 씁니다.
    return (
        "당신은 브랜드 네이밍 전문가입니다.\n"
        "아래 브리프에 맞는 브랜드명 후보를 4개 제안하세요.\n\n"
        f"{brief_mod.base_block(data)}\n\n"
        "조건:\n"
        "- 한글 이름과 그에 대응하는 영문 표기를 함께 제안합니다.\n"
        "- 영문 표기는 한글 이름의 음차이거나 같은 의미의 영어 단어여야 합니다.\n"
        "- 각 이름에 대해 어원·의미를 한 문장으로 설명합니다.\n"
        "- 이름은 2~5음절로 부르기 쉬워야 하며, 서로 뚜렷하게 달라야 합니다.\n"
        "- 실존하는 유명 브랜드명과 같은 이름은 제안하지 않습니다.\n"
        "- english_concept에는 위 업종·키워드·톤앤매너를 이미지 생성 프롬프트에\n"
        "  넣을 영어 표현으로 옮겨 적습니다. 문장이 아니라 짧은 명사구로만 씁니다."
    )


def _clean(items: list) -> list:
    """후처리 — 후처리로 고칠 수 있으면 고치고, 없으면 재시도가 원칙입니다.

    개수 초과는 잘라내면 요건(3~5개)을 만족하지만, 개수 부족은 어떤 후처리로도
    만들어낼 수 없습니다. 그래서 초과는 여기서 자르고(SCHEMA에 maxItems가 없는
    이유), 부족은 SCHEMA의 minItems가 걸러 llm.py가 재시도합니다.
    """
    seen, cleaned = set(), []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = (item.get("name_ko") or "").strip()
        meaning = (item.get("meaning") or "").strip()
        if not name or not meaning or name in seen:
            continue
        seen.add(name)
        cleaned.append(
            {
                "name_ko": name,
                "name_en": (item.get("name_en") or "").strip(),
                "meaning": meaning,
                "rationale": (item.get("rationale") or "").strip(),
            }
        )
    return cleaned[:5]  # 초과분은 잘라냅니다 (재시도하지 않음 — 요건은 충족됨)


def _english_concept(result: dict) -> dict | None:
    """로고 프롬프트에 쓸 영문 재료를 꺼낸다. 없으면 None (로고는 한글로 진행)."""
    concept = result.get("english_concept")
    if not isinstance(concept, dict):
        return None
    industry = (concept.get("industry_en") or "").strip()
    keywords = [str(k).strip() for k in (concept.get("keywords_en") or []) if str(k).strip()]
    if not industry or not keywords:
        return None
    return {
        "industry_en": industry,
        "keywords_en": keywords,
        "tone_en": (concept.get("tone_en") or "").strip(),
    }


def generate(data: dict, *, errors: list) -> tuple[list | None, dict | None]:
    """(네이밍 후보 리스트, 영문 컨셉)을 돌려준다. 실패하면 (None, None).

    영문 컨셉을 함께 돌려주는 이유는 SCHEMA 주석 참고 — 로고 단계의 영문 재료를
    별도 LLM 호출 없이 이 호출 하나로 확보하기 위해서입니다.
    """
    logger.step_start(LABEL)

    result = llm.generate_json(
        build_prompt(data), SCHEMA, step=STEP, errors=errors, brief=data
    )
    if result is None:
        logger.step_fail(LABEL, logger.last_reason(errors, STEP))
        return None, None

    items = _clean(result.get("naming") or [])
    if not items:
        logger.record_error(
            errors, step=STEP, type_="invalid", message="쓸 수 있는 네이밍 후보가 없습니다"
        )
        logger.step_fail(LABEL, "쓸 수 있는 후보가 없습니다")
        return None, _english_concept(result)

    if len(items) < 3:  # 중복 제거로 3개 아래가 된 경우 — 버리지 않고 기록만
        logger.record_error(
            errors,
            step=STEP,
            type_="invalid",
            message=f"중복 제거 후 후보가 {len(items)}개입니다 (요건 3~5개)",
        )

    first = items[0]
    label = f"{first['name_ko']}({first['name_en']})" if first["name_en"] else first["name_ko"]
    logger.step_ok(LABEL, f"{len(items)}개 생성 — {label} 외")
    return items, _english_concept(result)
