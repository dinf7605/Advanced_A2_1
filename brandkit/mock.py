"""목업 응답 (P2 소유) — PRD §12

USE_MOCK이 켜지면 네트워크를 타지 않고 고정 응답을 돌려줍니다.

이 파일이 푸는 문제는 네 가지입니다.
  1. 병렬 개발 — LLM 실구현이 없어도 나머지 팀원이 자기 모듈을 완성할 수 있다
  2. 쿼터 절약 — 5명이 각자 개발하면 무료 한도가 오전에 끝난다
  3. 오류 테스트 — ★ 실제 API로는 401을 마음대로 만들 수 없다 ★
  4. 시연 안전망 — 발표 당일 네트워크가 막혀도 돌아간다

세 번째가 핵심입니다. 요건 9는 "실패해도 계속 진행한다"인데,
**실패를 만들 수 없으면 그 요건을 만족했는지 증명할 수 없습니다.**
"""

from __future__ import annotations

import struct
import zlib

from . import config

MODES = {
    "1": "전 단계 정상 응답",
    "fail_naming": "네이밍만 실패 → 나머지는 정상 (요건 9 증명)",
    "fail_llm": "LLM 전체 실패 → 로고와 저장만 진행 (E4 재현)",
    "fail_image": "이미지만 실패 → 텍스트·팔레트는 정상 (E12 재현)",
    "bad_hex": "HEX에 색 이름을 반환 → 기본 팔레트 대체 확인 (E9 재현)",
}

LLM_STEPS = ("naming", "slogan", "story", "palette", "competitor")


def enabled() -> bool:
    return config.is_mock()


def mode() -> str:
    return config.mock_mode().lower()


def failure_for(step: str) -> str | None:
    """이 단계를 실패시켜야 하면 사유를, 아니면 None을 돌려준다."""
    current = mode()
    if current == "fail_llm" and step in LLM_STEPS:
        return "목업 fail_llm — LLM 전체 실패를 재현합니다"
    if current == "fail_naming" and step == "naming":
        return "목업 fail_naming — 네이밍 단계 실패를 재현합니다"
    if current == "fail_image" and step == "logo":
        return "목업 fail_image — 이미지 API 실패를 재현합니다"
    return None


# ── LLM 목업 응답 ────────────────────────────────────────────────────
def response(step: str, brief: dict) -> dict | None:
    """단계별 고정 응답. 브리프의 업종·키워드만 섞어 넣어 읽기 좋게 만든다."""
    industry = brief.get("industry", "브랜드")
    keywords = brief.get("keywords") or ["가치"]
    first_kw = keywords[0]

    if step == "naming":
        return {
            "naming": [
                {
                    "name_ko": "이음",
                    "name_en": "Ieum",
                    "meaning": "'잇다'의 명사형. 끊긴 흐름을 다시 잇는다는 뜻.",
                    "rationale": f"키워드 '{first_kw}'를 한 단어로 압축했습니다.",
                },
                {
                    "name_ko": "다시봄",
                    "name_en": "Dasibom",
                    "meaning": "'다시 봄(春)'과 '다시 보다'의 중의적 표현.",
                    "rationale": f"{industry}의 순환적 성격을 계절에 빗댔습니다.",
                },
                {
                    "name_ko": "온담",
                    "name_en": "Ondam",
                    "meaning": "'온기'와 '담다'의 결합. 따뜻함을 담는 그릇.",
                    "rationale": "톤앤매너의 따뜻함을 이름 자체에 담았습니다.",
                },
                {
                    "name_ko": "무늬",
                    "name_en": "Munui",
                    "meaning": "반복되어 하나의 결을 이루는 무늬.",
                    "rationale": "일상의 반복이 곧 브랜드의 태도라는 관점.",
                },
            ],
            # 로고 프롬프트에 넣을 영문 재료. 별도 호출이 아니라 이 응답에 함께 옵니다.
            "english_concept": {
                "industry_en": "eco-friendly refill household goods",
                "keywords_en": ["sustainable", "minimal", "circular", "everyday"],
                "tone_en": "warm and understated",
            },
        }

    if step == "slogan":
        return {
            "slogans": [
                {
                    "text": "다시 쓰는 하루",
                    "angle": "감성",
                    "tone_note": "형용사를 덜어내고 명사로 마무리해 담백한 톤을 유지했습니다.",
                },
                {
                    "text": "덜어내면 남는 것",
                    "angle": "기능",
                    "tone_note": "설교하지 않고 결과만 제시하는 문장 구조입니다.",
                },
                {
                    "text": "오늘부터 한 번 더",
                    "angle": "행동유도",
                    "tone_note": "명령형 대신 청유의 여지를 남겨 부드럽게 유도합니다.",
                },
            ]
        }

    if step == "story":
        # 요건 5가 "300자 내외"이므로 목업도 그 범위(270~330자)를 맞춥니다.
        # 목업 결과가 요건을 벗어나면 시연 화면에 "250자"가 찍혀 요건을
        # 못 지킨 것처럼 보입니다.
        text = (
            f"{industry}은(는) 늘 같은 자리에서 시작됩니다. 쓰고 버리는 일이 너무 쉬워진 "
            "시대에, 우리는 한 번 더 쓰는 일이 왜 이렇게 번거로워졌는지 묻는 것에서 "
            f"출발했습니다. 우리가 믿는 것은 단순합니다. {first_kw}은(는) 특별한 결심이 "
            "아니라 손에 익은 습관이어야 한다는 것. 그래서 우리는 더 크게 외치는 대신 "
            "더 쓰기 쉬운 물건을 만듭니다. 담는 그릇을 가볍게, 다시 채우는 걸음을 짧게, "
            "고르는 순간을 덜 고민스럽게. 언젠가 이 선택이 선택이라고 불리지 않는 날, "
            "그날을 위해 오늘의 번거로움을 우리가 대신 짊어지려 합니다."
        )
        return {
            "story": {
                "text": text,
                "background": "쓰고 버리는 일이 너무 쉬워진 시대에 대한 문제의식",
                "philosophy": f"{first_kw}은(는) 결심이 아니라 습관이어야 한다",
                "vision": "지속가능한 선택이 특별하지 않게 되는 날",
            }
        }

    if step == "palette":
        # bad_hex 모드 — LLM이 색 이름을 돌려주는 상황을 재현합니다.
        main_hex = "deep green" if mode() == "bad_hex" else "#1B4332"
        return {
            "palette": {
                "main": {"hex": main_hex, "name": "딥 포레스트", "usage": "로고·주요 버튼"},
                "subs": [
                    {"hex": "#84A98C", "name": "세이지 그린", "usage": "강조·아이콘"},
                    {"hex": "#CAD2C5", "name": "라이트 세이지", "usage": "배경"},
                    {"hex": "#F4F1DE", "name": "크림", "usage": "여백·카드"},
                ],
                "rationale": "자연에서 온 저채도 그린 계열로 담백한 톤을 유지했습니다.",
            }
        }

    if step == "competitor":
        names = brief.get("competitors") or ["경쟁사 A"]
        return {
            "competitors": {
                "analysis": [
                    {
                        "name": name,
                        "positioning": "가치 소비를 앞세운 오프라인 중심 브랜드로 추정됩니다.",
                        "strength": "공개 정보 부족 — 커뮤니티 기반의 인지도로 보입니다.",
                    }
                    for name in names
                ],
                "differentiation": [
                    {
                        "point": "구매가 아니라 반복을 설계한다",
                        "why": "첫 구매보다 두 번째 사용을 쉽게 만드는 데 집중합니다.",
                        "linked_keyword": first_kw,
                    },
                    {
                        "point": "설교하지 않는 언어",
                        "why": "죄책감 대신 편의를 근거로 설득합니다.",
                        "linked_keyword": keywords[-1],
                    },
                    {
                        "point": "일상 동선 안의 접점",
                        "why": "특별한 방문이 아니라 지나는 길에 들르게 만듭니다.",
                        "linked_keyword": first_kw,
                    },
                ],
            }
        }

    return None


# ── 이미지 목업 ──────────────────────────────────────────────────────
def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _make_png(size: int, fg: tuple[int, int, int]) -> bytes:
    """의존성 없이 유효한 PNG 바이트를 만든다 (흰 배경 + 가운데 원).

    Pillow를 쓰지 않는 이유: 목업 때문에 필수 의존성을 늘리고 싶지 않습니다.
    또 여기서 만든 바이트가 gen_logo의 PNG 검증(매직 넘버·크기)을 실제로
    통과해야 하므로, 진짜 PNG 구조를 그대로 만듭니다.
    """
    center = size / 2
    radius = size * 0.32
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # 필터 타입 0 (None)
        dy2 = (y - center) ** 2
        for x in range(size):
            inside = (x - center) ** 2 + dy2 <= radius * radius
            raw.extend(fg if inside else (250, 250, 248))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8bit truecolor
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )


_MOCK_COLORS = [(27, 67, 50), (132, 169, 140), (47, 62, 70)]


def images(n: int) -> list[bytes]:
    return [_make_png(384, _MOCK_COLORS[i % len(_MOCK_COLORS)]) for i in range(n)]
