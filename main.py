"""브랜드 아이덴티티 생성기 (Brand Kit Generator) — 2026 AI활용학습 A2-1

브랜드 브리프(JSON)를 받아 LLM으로 네이밍·슬로건·스토리·컬러를 생성하고,
이미지 생성 API로 로고 시안을 만들어 JSON과 PNG로 저장하는 CLI 프로그램입니다.

명세: brand_kit_PRD.md   설계 근거: 설명가이드.md

실행:
    python main.py
"""

from __future__ import annotations

import os
import sys
import time

# cp949 콘솔에서 이모지·한글이 UnicodeEncodeError로 중단되는 것을 막습니다.
# stderr도 함께 고정해야 오류 안내까지 깨지지 않습니다. (A1-2에서 확인된 사항)
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from brandkit import (  # noqa: E402  (인코딩 재설정이 먼저여야 합니다)
    brief,
    config,
    gen_competitor,
    gen_logo,
    gen_naming,
    gen_palette,
    gen_slogan,
    gen_story,
    image_client,
    llm,
    logger,
    mock,
    storage,
    viz_palette,
)

DEFAULT_OUT_DIR = "./output"
DEFAULT_LOGO_COUNT = 2
MAX_PATH_ATTEMPTS = 3


# ── 1. 대화형 입력 (요건 1) ──────────────────────────────────────────
def ask_inputs() -> tuple[str, str, int]:
    print("=" * 60)
    print("  브랜드 아이덴티티 생성기 (Brand Kit Generator)")
    print("=" * 60)

    # 필수 입력은 통과할 때까지 반복합니다. 선택 입력은 빈 값이 곧
    # "기본값 사용"이라는 유효한 답이므로 한 번만 묻습니다.
    path = ""
    for attempt in range(1, MAX_PATH_ATTEMPTS + 1):
        raw = _ask("\n브랜드 브리프 JSON 파일 경로를 입력하세요: ")
        # Windows 탐색기의 "경로로 복사"는 "C:\...\a.json" 처럼 큰따옴표를
        # 붙여서 복사합니다. 그대로 넘기면 무조건 파일을 못 찾습니다.
        raw = raw.strip().strip('"').strip("'")
        if not raw:
            print("  ⚠️  경로는 반드시 입력해야 합니다.")
        elif not os.path.isfile(raw):
            print(f"  ❌ 파일을 찾을 수 없습니다: {raw}")
            print("     예시: briefs/sample_brief.json")
        else:
            path = raw
            break
        if attempt == MAX_PATH_ATTEMPTS:
            print(f"\n❌ {MAX_PATH_ATTEMPTS}회 모두 실패해 종료합니다.")
            sys.exit(1)

    out_dir = _ask(f"결과를 저장할 폴더 (Enter={DEFAULT_OUT_DIR}): ").strip().strip('"')
    out_dir = out_dir or DEFAULT_OUT_DIR

    logo_n = DEFAULT_LOGO_COUNT
    raw_n = _ask(f"로고 시안 개수 (2~3, Enter={DEFAULT_LOGO_COUNT}): ").strip()
    if raw_n:
        if raw_n.isdigit() and 2 <= int(raw_n) <= 3:
            logo_n = int(raw_n)
        else:
            print(f"  ⚠️  2 또는 3만 가능합니다. 기본값 {DEFAULT_LOGO_COUNT}장으로 진행합니다.")

    return path, out_dir, logo_n


def _ask(prompt: str) -> str:
    """input()을 감싸 Ctrl+C와 EOF를 조용히 처리한다."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print("\n\n입력이 중단되어 종료합니다.")
        sys.exit(1)


# ── 2. 환경 점검 (요건 9의 "키가 없거나 잘못된 경우 안내") ───────────
def check_environment() -> None:
    if mock.enabled():
        mode = config.mock_mode()
        print(f"\n🧪 목업 모드 [{mode}] — {mock.MODES.get(mode, '사용자 지정')}")
        print("   실제 API를 호출하지 않습니다. 결과 JSON의 meta.mock=true 로 남습니다.")
        return

    if not config.gemini_key():
        logger.warn("GEMINI_API_KEY가 없습니다 — 텍스트 생성 단계를 건너뜁니다.")
        print("   .env 파일에 GEMINI_API_KEY=발급받은_키 를 넣으세요 (.env.example 참고).")

    provider = image_client.resolve()
    if provider is None:
        logger.warn(
            f"IMAGE_PROVIDER 값이 올바르지 않습니다: {config.image_provider()!r} "
            f"(가능: {', '.join(image_client.IMAGE_PROVIDERS)})"
        )
    elif provider.credentials():
        logger.warn(f"{provider.credentials()}가 없습니다 — 로고 단계를 건너뜁니다.")


def pick_title(result: dict) -> str:
    """팔레트 이미지 제목 — 네이밍 1번 후보를 쓰고, 없으면 업종을 쓴다."""
    naming = result.get("naming") or []
    if naming:
        first = naming[0]
        english = first.get("name_en")
        base = first["name_ko"] + (f" ({english})" if english else "")
        return f"{base} — 브랜드 컬러 팔레트"
    return f"{result['brief']['industry']} — 브랜드 컬러 팔레트"


# ── 3. 파이프라인 ────────────────────────────────────────────────────
def main() -> None:
    brief_path, out_dir, logo_n = ask_inputs()

    data = brief.load_and_validate(brief_path)  # 실패하면 내부에서 종료 (Fatal)
    storage.prepare(out_dir)  # E16 — 저장할 곳이 없으면 종료
    brief.print_summary(data)
    check_environment()

    started = time.perf_counter()
    errors: list = []  # ★ 모든 모듈이 공유하는 오류 목록 (가변 객체)
    result = {
        "generated_at": logger.now_iso(),
        "brief": data,
        # 실패한 섹션은 키를 빼지 않고 null로 둡니다. 키를 빼면 읽는 쪽이
        # KeyError를 만나므로, "키는 있고 값이 null"이 안전합니다.
        "naming": None,
        "slogans": None,
        "story": None,
        "palette": None,
        "competitors": None,
        "assets": {"palette_image": None, "logos": [], "logo_prompt": None},
        "errors": errors,
        "meta": {
            "llm_model": llm.MODEL,
            "image_provider": config.image_provider(),
            "mock": mock.enabled(),
            "mock_mode": config.mock_mode() if mock.enabled() else None,
        },
    }

    print()
    # ── 아래 여섯 단계는 서로 연결되어 있지 않습니다. 그래서 try가 없습니다.
    #    각 함수는 실패하면 예외 대신 None을 돌려주고 errors에 기록합니다.
    #    이 계약 하나가 요건 9를 구조로 보장합니다. (PRD §4.3)
    # 네이밍 호출은 후보 목록과 함께 "로고 프롬프트용 영문 재료"도 돌려줍니다.
    # 영문 변환을 별도 호출로 두면 요구사항이 요구하지 않는 여섯 번째 LLM
    # 호출이 생기므로, 스키마를 확장해 한 번에 받습니다 (gen_naming.SCHEMA).
    result["naming"], english_concept = gen_naming.generate(data, errors=errors)
    result["slogans"] = gen_slogan.generate(data, errors=errors, naming=result["naming"])
    result["story"] = gen_story.generate(data, errors=errors)
    result["palette"] = gen_palette.generate(data, errors=errors)

    if data.get("competitors"):  # 보너스 B1 — 브리프에 있을 때만 실행
        result["competitors"] = gen_competitor.generate(data, errors=errors)
    else:
        logger.step_skip(gen_competitor.SKIP_LABEL, "브리프에 competitors 없음")
        logger.record_error(
            errors,
            step="competitor",
            type_="skipped",
            message="브리프에 competitors가 없어 경쟁사 분석을 건너뛰었습니다",
        )

    if result["palette"]:  # 하드 의존 — 색이 없으면 그릴 수 없습니다
        result["assets"]["palette_image"] = viz_palette.save(
            result["palette"], out_dir, title=pick_title(result), errors=errors
        )

    logos, logo_prompt = gen_logo.generate(
        data,
        out_dir,
        n=logo_n,
        naming=result["naming"],  # 소프트 의존 — None이어도 됩니다
        palette=result["palette"],
        english=english_concept,
        errors=errors,
    )
    result["assets"]["logos"] = logos
    result["assets"]["logo_prompt"] = logo_prompt

    # ★ if도 try도 없이 무조건 실행됩니다.
    #   여섯 단계가 전부 실패해도 브리프 원본과 errors가 담긴 파일은 남습니다.
    result_path = storage.save_json(result, out_dir)
    logger.print_summary(
        result, out_dir, errors, time.perf_counter() - started, result_path=result_path
    )

    # 저장 실패는 요건 8의 유일한 필수 산출물이 없다는 뜻이므로 실패로 끝냅니다.
    # 여기까지 왔으면 "계속 진행"할 다음 단계도 남아 있지 않습니다.
    if result_path is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
