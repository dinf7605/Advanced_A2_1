"""설정·API 키 로딩 (P2 소유) — PRD §11

요건 10: API 키를 코드에 직접 쓰지 않는다. `.env` 또는 OS 환경변수에서만 읽는다.
이 파일에는 키의 "이름"만 존재하고 값은 존재하지 않습니다.
"""

from __future__ import annotations

import os

try:
    from dotenv import load_dotenv

    load_dotenv()  # .env가 없어도 조용히 넘어간다 (OS 환경변수만으로도 동작)
except ImportError:  # python-dotenv 미설치 — OS 환경변수는 여전히 읽힌다
    pass


# ── 모델 ─────────────────────────────────────────────────────────────
# A1-2에서 실호출로 검증된 모델. 환경변수로 덮어쓸 수 있게 열어둔다.
LLM_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()

# 이미지 모델은 Day 1 실호출로 확인해야 하는 미검증 항목 (PRD §7.7)
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1").strip()
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3-pro-image").strip()

LLM_TIMEOUT_SEC = 60  # 없으면 멈춘 것처럼 보인다 (A1-2에서 실제로 겪음)
IMAGE_TIMEOUT_SEC = 120  # 이미지 생성은 텍스트보다 오래 걸린다


def _clean(name: str) -> str | None:
    """환경변수를 읽되 빈 문자열은 없는 것으로 취급한다.

    `.env.example`을 복사하면 `GEMINI_API_KEY=` 처럼 값이 빈 줄이 남는데,
    이걸 "설정됨"으로 보면 키가 있는 줄 알고 호출했다가 401이 납니다.
    """
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def gemini_key() -> str | None:
    return _clean("GEMINI_API_KEY")


def openai_key() -> str | None:
    return _clean("OPENAI_API_KEY")


def image_provider() -> str:
    """이미지 생성 제공자. PRD §0에서 어댑터로 교체 가능하게 확정."""
    return (_clean("IMAGE_PROVIDER") or "openai").lower()


def mock_mode() -> str:
    """USE_MOCK 값 그대로. 미설정이면 "0" (실호출)."""
    return _clean("USE_MOCK") or "0"


def is_mock() -> bool:
    return mock_mode().lower() not in ("0", "false", "no", "off")
