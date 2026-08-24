"""브리프 로드와 검증 (P1 소유) — PRD §6, 요건 2

여기서 걸리는 실패는 전부 Fatal입니다 (E2·E3). 브리프가 없으면 이후 모든
단계의 입력이 사라지기 때문입니다 — 다른 곳의 실패가 전부 Degraded인 것과
대비되는 지점입니다.

가장 중요한 점: **파싱 성공과 검증 성공은 다릅니다.**
`json.load`는 문법만 봅니다. `{}` 도 통과합니다. 필수 필드가 없는 채로
프롬프트에 들어가면 "업종: , 타겟: " 이 되는데 **에러가 나지 않습니다.**
에러가 나는 것보다 이게 더 위험합니다.
"""

from __future__ import annotations

import json
import sys

from . import logger

REQUIRED_FIELDS = ("industry", "target", "keywords")

# 선택 필드는 타입이 틀려도 종료하지 않습니다. 없어도 프로그램이 돌아가므로
# "없는 것으로 간주하고 진행"하는 편이 요건 9의 정신에 맞습니다.
OPTIONAL_TYPES = {"tone": str, "competitors": list, "notes": str}

FIELD_LABELS = {
    "industry": "업종",
    "target": "타겟",
    "keywords": "키워드",
    "tone": "톤앤매너",
    "competitors": "경쟁사",
    "notes": "추가 요청",
}


def load_and_validate(path: str) -> dict:
    """브리프를 읽고 검증해 돌려준다. 실패하면 안내 후 종료한다 (Fatal)."""
    # ── E2: 파싱 ──────────────────────────────────────────────────
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        # JSONDecodeError는 위치 정보를 갖고 있습니다. 버리지 말고 보여줍니다.
        logger.fatal(
            f"JSON 형식 오류 — {e.lineno}번째 줄 {e.colno}번째 칸: {e.msg}",
            "쉼표 누락이나 따옴표 짝이 맞는지 확인하세요.",
        )
        sys.exit(1)
    except UnicodeDecodeError:
        logger.fatal(
            "브리프 파일을 UTF-8로 읽을 수 없습니다.",
            "메모장에서 '다른 이름으로 저장 > 인코딩: UTF-8'로 다시 저장하세요.",
        )
        sys.exit(1)
    except OSError as e:
        logger.fatal(f"브리프 파일을 열 수 없습니다: {logger.safe_reason(e)}")
        sys.exit(1)

    # ── E3: 구조 ──────────────────────────────────────────────────
    if not isinstance(data, dict):
        logger.fatal(
            f"브리프 최상위는 객체({{...}})여야 합니다. 지금은 {type(data).__name__} 입니다.",
        )
        sys.exit(1)

    # 없는 키를 하나씩 알려주지 말고 한 번에 모아서 보여줍니다.
    missing = [k for k in REQUIRED_FIELDS if k not in data]
    if missing:
        logger.fatal(
            f"브리프에 필수 항목이 없습니다: {', '.join(missing)}",
            "필수: industry(업종), target(타겟), keywords(키워드 리스트)",
        )
        sys.exit(1)

    for key in ("industry", "target"):
        if not isinstance(data[key], str) or not data[key].strip():
            logger.fatal(f"{key}({FIELD_LABELS[key]})는 비어 있지 않은 문자열이어야 합니다.")
            sys.exit(1)

    keywords = data["keywords"]
    if isinstance(keywords, str):  # 흔한 실수 — 문자열 하나로 준 경우는 살려줍니다
        data["keywords"] = [k.strip() for k in keywords.split(",") if k.strip()]
        keywords = data["keywords"]
    if not isinstance(keywords, list) or not keywords:
        logger.fatal(
            "keywords(키워드)는 비어 있지 않은 리스트여야 합니다.",
            '예: "keywords": ["지속가능", "미니멀"]',
        )
        sys.exit(1)
    data["keywords"] = [str(k).strip() for k in keywords if str(k).strip()]

    # ── 선택 필드: 타입이 틀리면 경고 후 버리고 계속 (Degraded) ────
    for key, expected in OPTIONAL_TYPES.items():
        if key in data and not isinstance(data[key], expected):
            logger.warn(
                f"{key}({FIELD_LABELS[key]})의 형식이 올바르지 않아 무시합니다 "
                f"(기대: {expected.__name__}, 실제: {type(data[key]).__name__})"
            )
            data.pop(key)

    return data


def print_summary(data: dict) -> None:
    """읽어들인 브리프를 요약해 보여준다 — 잘못된 파일을 골랐는지 여기서 알아챈다."""
    # 한글은 터미널에서 두 칸을 차지하므로 len() 기준으로 맞추면 어긋납니다.
    width = 10
    print("\n✅ 브리프 로드 완료")
    for key in ("industry", "target"):
        print(f"   {logger.pad(FIELD_LABELS[key], width)}: {data[key]}")
    print(f"   {logger.pad(FIELD_LABELS['keywords'], width)}: {', '.join(data['keywords'])}")
    for key in ("tone", "competitors", "notes"):
        if data.get(key):
            value = data[key]
            text = ", ".join(value) if isinstance(value, list) else value
            print(f"   {logger.pad(FIELD_LABELS[key], width)}: {text}")


# ── 프롬프트 조립을 돕는 함수 (모든 gen_* 모듈이 함께 씁니다) ──────────
def keywords_text(data: dict) -> str:
    return ", ".join(data.get("keywords") or [])


def tone_text(data: dict) -> str:
    return data.get("tone") or "지정 없음"


def notes_text(data: dict) -> str:
    return data.get("notes") or "없음"


def competitors_text(data: dict) -> str:
    return ", ".join(data.get("competitors") or []) or "없음"


def base_block(data: dict) -> str:
    """모든 프롬프트가 공유하는 브리프 요약 블록.

    다섯 개 프롬프트가 각자 브리프를 문자열로 만들면, 나중에 필드를 하나
    추가할 때 다섯 군데를 고쳐야 합니다. 한 곳에 모아둡니다.
    """
    return (
        f"업종: {data['industry']}\n"
        f"타겟: {data['target']}\n"
        f"키워드: {keywords_text(data)}\n"
        f"톤앤매너: {tone_text(data)}\n"
        f"추가 요청: {notes_text(data)}"
    )
