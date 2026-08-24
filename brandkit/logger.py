"""진행 로그와 오류 수집 (P1 소유) — PRD §4.3, §5.2, §9.3

두 가지 일을 합니다.
  1. 화면에 진행 상황을 찍는다 — LLM 호출은 3~10초라 아무것도 안 찍으면
     멈춘 것처럼 보입니다. 그래서 호출 "전에" 라벨을 먼저 찍습니다.
  2. errors 리스트에 실패를 표준 형식으로 쌓는다 — 화면 출력은 스크롤되면
     사라지지만, errors는 brand_result.json에 남아 나중에 확인할 수 있습니다.
"""

from __future__ import annotations

import datetime
import re
import unicodedata

LABEL_WIDTH = 42  # 결과 표시가 세로로 정렬되는 폭

_STATUS_RE = re.compile(r"\b(4\d\d|5\d\d)\b")

_line_open = False  # step_start로 열어둔 줄이 있는가
_pending: list[tuple[str, str]] = []  # 줄이 열린 동안 미뤄둔 안내 문구


# ── 화면 폭 계산 ──────────────────────────────────────────────────────
def _display_width(text: str) -> int:
    """한글은 터미널에서 두 칸을 차지한다.

    len()으로 맞추면 "[1/7] 브랜드 네이밍 생성 중..." 같은 줄이 제각각으로
    밀립니다. 동아시아 문자(W/F)만 2로 세면 정렬이 맞습니다.
    """
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text: str, width: int) -> str:
    """터미널 표시 폭 기준으로 오른쪽을 채운다 (한글 정렬용)."""
    return text + " " * max(1, width - _display_width(text))


_pad = pad  # 모듈 내부에서 쓰던 이름 유지


# ── 진행 로그 ────────────────────────────────────────────────────────
def step_start(label: str) -> None:
    """호출 직전에 라벨을 찍는다. 줄바꿈하지 않는다."""
    global _line_open
    print(_pad(label, LABEL_WIDTH), end="", flush=True)
    _line_open = True


def _finish(label: str, mark: str, text: str) -> None:
    global _line_open
    if not _line_open:  # step_start 없이 단독 호출된 경우 (예: 건너뜀)
        print(_pad(label, LABEL_WIDTH), end="")
    print(f"{mark} {text}".rstrip())
    _line_open = False
    _flush_pending()


def step_ok(label: str = "", detail: str = "") -> None:
    _finish(label, "✅", detail)


def step_fail(label: str = "", reason: str = "") -> None:
    _finish(label, "❌", f"실패 — {reason}" if reason else "실패")


def step_skip(label: str = "", reason: str = "") -> None:
    _finish(label, "⚠️ ", f"건너뜀 ({reason})" if reason else "건너뜀")


def _flush_pending() -> None:
    """단계 결과 줄 아래에 대기 중인 안내를 쏟아낸다."""
    for prefix, text in _pending:
        print(f"{prefix}{text}")
    _pending.clear()


def hint(text: str) -> None:
    """실패 다음 줄에 "그래서 뭘 해야 하는가"를 적는다.

    "401" 만으로는 사용자가 할 일을 알 수 없습니다. 원인만 알리고
    다음 행동을 안 알려주는 오류 메시지는 절반만 일한 것입니다.

    단계 진행 줄이 열려 있는 동안(step_start ~ step_ok/fail)에는 바로 찍지
    않고 모아둡니다. 그대로 찍으면 "[7/7] 로고 생성 중..." 뒤에 안내가 붙어
    결과 표시가 다음 줄로 밀려납니다.
    """
    if _line_open:
        _pending.append(("      └ ", text))
    else:
        print(f"      └ {text}")


def warn(text: str) -> None:
    if _line_open:
        _pending.append(("      └ ⚠️  ", text))
    else:
        print(f"⚠️  {text}")


def fatal(text: str, *hints: str) -> None:
    print(f"❌ {text}")
    for line in hints:
        print(f"   {line}")


# ── 오류 수집 ────────────────────────────────────────────────────────
def now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def record_error(errors: list, *, step: str, type_: str, message: str) -> None:
    """errors에 표준 형식으로 한 건 추가한다 (PRD §9.3).

    errors는 가변 객체라 여기서 append하면 호출한 쪽 리스트에 그대로
    반영됩니다. 그래서 return이 필요 없고, 모든 모듈이 같은 목록 하나를
    공유하게 됩니다.

    message에 예외 원문을 통째로 넣지 마십시오 — 요청 URL·헤더가 딸려와
    결과 파일에 남습니다 (PRD §11.4).
    """
    errors.append(
        {"step": step, "type": type_, "message": message, "at": now_iso()}
    )


def last_reason(errors: list, step: str, default: str = "원인 불명") -> str:
    """해당 단계에 기록된 가장 최근 오류 메시지 — 화면에 실패 사유를 찍을 때 씁니다."""
    for err in reversed(errors):
        if err.get("step") == step:
            return err.get("message", default)
    return default


def status_of(exc: BaseException) -> int | None:
    """예외에서 HTTP 상태 코드를 뽑는다 (llm.py와 image_client.py가 함께 씁니다).

    SDK 버전에 따라 예외 클래스 이름이 달라지므로 **타입이 아니라 상태 코드로**
    분기합니다. 속성이 없으면 메시지에서 3자리 코드를 찾습니다.
    """
    for attr in ("status_code", "code", "http_status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and 100 <= value < 600:
            return value
    match = _STATUS_RE.search(str(exc))
    return int(match.group(1)) if match else None


def safe_reason(exc: BaseException, limit: int = 120) -> str:
    """예외를 로그에 쓸 수 있는 짧은 문자열로 줄인다.

    전체 메시지에는 요청 URL이나 키 일부가 섞여 있을 수 있으므로
    길이를 자르고 타입명을 앞에 붙입니다.
    """
    text = str(exc).replace("\n", " ").strip()
    if len(text) > limit:
        text = text[:limit] + "..."
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


# ── 마지막 요약 ──────────────────────────────────────────────────────
def print_summary(result: dict, out_dir: str, errors: list, elapsed: float) -> None:
    line = "-" * 60
    print()
    print(line)
    if errors:
        print(f"⚠️  {len(errors)}건의 오류가 있었지만 나머지 결과는 저장되었습니다.")
        for err in errors:
            print(f"   · [{err['step']}/{err['type']}] {err['message']}")
    else:
        print("✅ 모든 단계가 정상 완료되었습니다.")
    print(line)

    assets = result.get("assets") or {}
    saved = ["brand_result.json"]
    if assets.get("palette_image"):
        saved.append(assets["palette_image"])
    saved.extend(assets.get("logos") or [])
    for name in saved:
        print(f"📁 {out_dir.rstrip('/')}/{name}")
    print(f"소요 시간: {elapsed:.1f}초")
