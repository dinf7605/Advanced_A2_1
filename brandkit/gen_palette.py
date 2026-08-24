"""컬러 팔레트 생성과 HEX 검증 (P4 소유) — PRD §7.5, 요건 6

이 단계에서 가장 자주 깨지는 곳은 LLM 호출이 아니라 **HEX 검증**입니다.
스키마는 "타입이 문자열인지"만 봅니다. "deep green"도 완벽한 문자열이라
통과합니다. 그대로 matplotlib에 넘기면 거기서 예외가 나면서 PNG가 아예
안 만들어집니다. 그래서 정규식으로 한 번 더 걸러서, **잘못된 색만 기본값으로
바꾸고 나머지는 살립니다.**
"""

from __future__ import annotations

import re

from . import brief as brief_mod
from . import llm, logger

STEP = "palette"
LABEL = "[4/7] 컬러 팔레트 생성 중..."

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# 전부 실패했을 때 쓰는 기본 팔레트.
# palette.png는 요건 6의 필수 산출물이라, LLM이 실패했다고 PNG를 안 만들면
# 산출물 하나가 통째로 빕니다. 다만 기본 팔레트를 썼다는 사실을
# is_fallback=True로 반드시 남깁니다 — 결과물을 속이지 않는 것이 원칙입니다.
FALLBACK_PALETTE = {
    "main": {"hex": "#2F3E46", "name": "차콜 그레이", "usage": "로고·본문"},
    "subs": [
        {"hex": "#84A98C", "name": "세이지 그린", "usage": "강조"},
        {"hex": "#CAD2C5", "name": "라이트 세이지", "usage": "배경"},
    ],
    "rationale": "LLM 응답을 쓸 수 없어 사용한 기본 팔레트입니다.",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "palette": {
            "type": "object",
            "properties": {
                "main": {
                    "type": "object",
                    "properties": {
                        "hex": {"type": "string"},
                        "name": {"type": "string"},
                        "usage": {"type": "string"},
                    },
                    "required": ["hex", "name", "usage"],
                },
                # maxItems 없음 — 4개가 오면 generate()가 앞 3개만 취해
                # 요건("서브 2~3개")을 충족합니다. 검증으로 탈락시키면
                # 기본 팔레트로 떨어져 LLM이 준 색을 전부 버리게 됩니다.
                "subs": {
                    "type": "array",
                    "minItems": 2,
                    "items": {
                        "type": "object",
                        "properties": {
                            "hex": {"type": "string"},
                            "name": {"type": "string"},
                            "usage": {"type": "string"},
                        },
                        "required": ["hex", "name", "usage"],
                    },
                },
                "rationale": {"type": "string"},
            },
            "required": ["main", "subs"],
        }
    },
    "required": ["palette"],
}


def build_prompt(data: dict) -> str:
    return (
        "당신은 브랜드 아이덴티티 디자이너입니다.\n"
        "아래 브랜드에 어울리는 컬러 팔레트를 제안하세요.\n\n"
        f"{brief_mod.base_block(data)}\n\n"
        "조건:\n"
        "- 메인 컬러 1개와 서브 컬러 3개를 제안합니다.\n"
        "- 색상은 반드시 #RRGGBB 형식의 6자리 HEX 코드로만 표기합니다.\n"
        "- 색 이름은 한글로, 사용처는 예를 들어 로고·배경·강조처럼 적습니다.\n"
        "- 메인 컬러는 흰 글자를 얹어도 읽히도록 충분히 어두워야 합니다.\n"
        "- rationale에는 이 조합을 고른 이유를 한두 문장으로 적습니다."
    )


def normalize_hex(value) -> str | None:
    """HEX 코드를 표준형(#RRGGBB 대문자)으로 고친다. 못 고치면 None.

    실제로 자주 오는 형태들:
        "1B4332"      → "#" 누락        → 붙여서 사용
        "#1B4"        → 3자리 축약형     → 6자리로 확장
        "deep green"  → 색 이름          → None (기본값으로 대체)
        "#1B43322"    → 7자리            → None
    """
    text = str(value or "").strip()
    if not text:
        return None
    if not text.startswith("#"):
        text = "#" + text
    if len(text) == 4:  # #ABC → #AABBCC
        text = "#" + "".join(ch * 2 for ch in text[1:])
    return text.upper() if HEX_RE.match(text) else None


def _fix_color(raw, fallback: dict, *, slot: str, errors: list) -> dict:
    """색 하나를 검증해 돌려준다. 못 쓰면 기본값으로 대체하고 표시를 남긴다."""
    raw = raw if isinstance(raw, dict) else {}
    fixed = normalize_hex(raw.get("hex"))
    color = {
        "hex": fixed or fallback["hex"],
        "name": (raw.get("name") or "").strip() or fallback["name"],
        "usage": (raw.get("usage") or "").strip() or fallback["usage"],
    }
    if fixed is None:
        color["substituted"] = True  # 대체했다는 사실을 결과물에 남깁니다
        logger.record_error(
            errors,
            step=STEP,
            type_="invalid",
            message=f"{slot} 색상이 HEX 형식이 아니어서 기본값으로 대체했습니다"
            f" (받은 값: {str(raw.get('hex'))[:20]!r})",
        )
    return color


def generate(data: dict, *, errors: list) -> dict:
    """팔레트를 돌려준다. 실패해도 None이 아니라 기본 팔레트를 돌려준다.

    다른 단계와 달리 None을 돌려주지 않는 이유: palette.png가 요건 6의
    필수 산출물이기 때문입니다. 대신 is_fallback으로 출처를 밝힙니다.
    """
    logger.step_start(LABEL)

    result = llm.generate_json(
        build_prompt(data), SCHEMA, step=STEP, errors=errors, brief=data
    )

    if result is None:
        palette = {
            "main": dict(FALLBACK_PALETTE["main"]),
            "subs": [dict(c) for c in FALLBACK_PALETTE["subs"]],
            "rationale": FALLBACK_PALETTE["rationale"],
            "is_fallback": True,
        }
        logger.step_fail(LABEL, logger.last_reason(errors, STEP))
        logger.hint("기본 팔레트로 대체합니다 (결과 JSON의 is_fallback=true).")
        return palette

    raw = result.get("palette") or {}
    main = _fix_color(raw.get("main"), FALLBACK_PALETTE["main"], slot="메인", errors=errors)

    subs, raw_subs = [], raw.get("subs") or []
    for index, item in enumerate(raw_subs[:3]):
        fallback = FALLBACK_PALETTE["subs"][index % len(FALLBACK_PALETTE["subs"])]
        subs.append(_fix_color(item, fallback, slot=f"서브 {index + 1}", errors=errors))

    while len(subs) < 2:  # 요건은 서브 2~3개 — 모자라면 기본값으로 채웁니다
        subs.append(dict(FALLBACK_PALETTE["subs"][len(subs)]))
        logger.record_error(
            errors, step=STEP, type_="invalid", message="서브 컬러가 부족해 기본값으로 채웠습니다"
        )

    palette = {
        "main": main,
        "subs": subs,
        "rationale": (raw.get("rationale") or "").strip(),
        "is_fallback": False,
    }
    logger.step_ok(LABEL, f"메인 {main['hex']} + 서브 {len(subs)}")
    return palette
