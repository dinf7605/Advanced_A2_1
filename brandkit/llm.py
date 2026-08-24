"""LLM 호출 래퍼 (P2 소유) — PRD §4.3, §7.1

★ 이 파일이 Gemini API를 아는 유일한 파일입니다. ★
gen_* 모듈은 프롬프트 문자열과 스키마 딕셔너리만 만들어 여기로 넘깁니다.
그래서 모델을 바꾸거나 재시도 정책을 고칠 때 고칠 파일이 하나입니다.

동결된 계약:
    generate_json(prompt, schema, *, step, errors, max_retry=1, brief=None)
        성공 → 검증을 통과한 dict
        실패 → None (+ errors에 기록)
    ★ 어떤 경우에도 예외를 호출자에게 던지지 않는다 ★

이 계약 하나가 요건 9("실패해도 다음 단계 계속 진행")를 개인의 주의력이 아니라
구조로 보장합니다. 호출하는 쪽(main.py)에는 try가 하나도 없습니다.
"""

from __future__ import annotations

import json
import time

from . import config, logger, mock

MODEL = config.LLM_MODEL

# 창의성이 필요한 단계는 높게, 사실 기반 분석은 낮게 (PRD §7.1)
TEMPERATURE = {
    "naming": 0.9,
    "slogan": 0.9,
    "story": 0.7,
    "palette": 0.7,
    "competitor": 0.4,
}

# E8 — 키가 틀렸거나 한도가 소진되면 남은 LLM 단계를 미리 접는다.
# 다음 네 번의 호출도 100% 같은 이유로 실패할 텐데, 사용자를 40초 더
# 기다리게 할 이유가 없습니다.
_disabled_reason: str | None = None


def disabled() -> str | None:
    return _disabled_reason


def reset() -> None:
    """테스트에서 상태를 초기화한다."""
    global _disabled_reason
    _disabled_reason = None


def _disable(reason: str) -> None:
    global _disabled_reason
    if _disabled_reason is None:
        _disabled_reason = reason


# ── 클라이언트 ───────────────────────────────────────────────────────
_client_cache = None


def _client(api_key: str):
    """google-genai 클라이언트를 지연 생성한다.

    import를 파일 상단에 두지 않는 이유: SDK가 없어도 목업 모드는 돌아가야
    하고, 테스트와 다른 단계가 import 실패로 함께 죽으면 안 됩니다.
    """
    global _client_cache
    if _client_cache is not None:
        return _client_cache
    try:
        from google import genai
    except ImportError:
        return None
    try:
        _client_cache = genai.Client(api_key=api_key)
    except Exception as e:  # 키 형식 오류 등 — 여기서 죽이지 않는다
        logger.hint(f"LLM 클라이언트 생성 실패: {logger.safe_reason(e)}")
        return None
    return _client_cache


# ── 응답 정리와 검증 ─────────────────────────────────────────────────
def strip_fence(text: str) -> str:
    """```json 으로 감싸 온 응답에서 코드블록 껍질을 벗긴다 (방어 2단).

    response_mime_type으로 강제해도 감싸 오는 경우가 있습니다.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    parts = stripped.split("```")
    if len(parts) < 2:
        return stripped
    return parts[1].removeprefix("json").removeprefix("JSON").strip()


_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def validate(data, schema: dict, path: str = "응답") -> str | None:
    """스키마 위반 사유를 문자열로 돌려준다. 통과하면 None (방어 3단).

    ★ 파싱 성공 ≠ 검증 성공 ★
    json.loads는 `{}` 도 통과시킵니다. 네이밍을 4개 요청했는데 0개가 온
    응답도 문법적으로는 완벽한 JSON입니다. 개수·키·타입을 따로 봅니다.
    """
    expected = schema.get("type")
    if expected and expected in _TYPE_MAP:
        # bool은 int의 하위 타입이라 순서를 조심해야 합니다.
        if expected in ("integer", "number") and isinstance(data, bool):
            return f"{path}: 숫자가 필요한데 boolean 입니다"
        if not isinstance(data, _TYPE_MAP[expected]):
            return f"{path}: {expected}가 필요한데 {type(data).__name__} 입니다"

    if expected == "object":
        for key in schema.get("required", []):
            if key not in data:
                return f"{path}: 필수 키 '{key}'가 없습니다"
        for key, sub in (schema.get("properties") or {}).items():
            if key in data:
                problem = validate(data[key], sub, f"{path}.{key}")
                if problem:
                    return problem

    if expected == "array":
        low, high = schema.get("minItems"), schema.get("maxItems")
        if low is not None and len(data) < low:
            return f"{path}: 항목이 {len(data)}개뿐입니다 (최소 {low}개)"
        if high is not None and len(data) > high:
            return f"{path}: 항목이 {len(data)}개입니다 (최대 {high}개)"
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(data):
                problem = validate(item, item_schema, f"{path}[{index}]")
                if problem:
                    return problem

    return None


def _shorten(prompt: str) -> str:
    """재시도용으로 프롬프트를 축약한다 (E6).

    같은 프롬프트를 그대로 다시 던지면 같은 결과가 올 확률이 높습니다.
    조건 목록을 덜어내고 "JSON 하나만" 지시를 강조합니다.
    """
    head = prompt.split("조건:")[0].strip()
    return head + "\n\n형식이 잘못되어 다시 요청합니다. 설명 없이 JSON 객체 하나만 출력하세요."


# ── 본체 ─────────────────────────────────────────────────────────────
def generate_json(
    prompt: str,
    schema: dict,
    *,
    step: str,
    errors: list,
    max_retry: int = 1,
    brief: dict | None = None,
) -> dict | None:
    """LLM에 JSON 응답을 요청한다. 실패하면 None을 돌려준다 (예외 없음).

    brief는 목업이 읽기 좋은 응답을 만들 때만 씁니다 (실호출에서는 무시).
    """
    if mock.enabled():
        reason = mock.failure_for(step)
        if reason:
            logger.record_error(errors, step=step, type_="network", message=reason)
            return None
        return mock.response(step, brief or {})

    if _disabled_reason:
        logger.record_error(
            errors,
            step=step,
            type_="skipped",
            message=f"LLM 호출을 중단한 상태입니다 ({_disabled_reason})",
        )
        return None

    api_key = config.gemini_key()
    if not api_key:  # E4 — Fatal이 아니라 Degraded입니다
        _disable("GEMINI_API_KEY 미설정")
        logger.record_error(
            errors,
            step=step,
            type_="auth",
            message="GEMINI_API_KEY가 설정되지 않았습니다",
        )
        return None

    client = _client(api_key)
    if client is None:
        _disable("google-genai 미설치 또는 클라이언트 생성 실패")
        logger.record_error(
            errors,
            step=step,
            type_="auth",
            message="LLM 클라이언트를 만들 수 없습니다 (pip install google-genai)",
        )
        return None

    current = prompt
    for attempt in range(max_retry + 1):
        text = _call(client, current, schema, step=step, errors=errors)
        if text is None:
            return None  # 전송 계층 실패 — _call이 이미 기록했습니다

        try:
            data = json.loads(strip_fence(text))
        except (ValueError, TypeError):
            problem = "응답을 JSON으로 파싱할 수 없습니다"
        else:
            problem = validate(data, schema)
            if problem is None:
                return data

        if attempt < max_retry:
            logger.record_error(
                errors,
                step=step,
                type_="parse",
                message=f"{problem} — 프롬프트를 축약해 1회 재시도합니다",
            )
            current = _shorten(prompt)
            continue

        logger.record_error(errors, step=step, type_="parse", message=problem)
        return None

    return None


def _call(client, prompt: str, schema: dict, *, step: str, errors: list) -> str | None:
    """실제 호출 1건. 503만 백오프 재시도하고 나머지는 즉시 판정한다."""
    try:
        from google.genai import types
    except ImportError:
        logger.record_error(
            errors, step=step, type_="auth", message="google-genai를 불러올 수 없습니다"
        )
        return None

    kwargs = {
        "response_mime_type": "application/json",
        "response_schema": schema,
        "temperature": TEMPERATURE.get(step, 0.7),
    }
    try:  # 타임아웃 옵션은 SDK 버전에 따라 이름이 다를 수 있습니다
        kwargs["http_options"] = types.HttpOptions(timeout=config.LLM_TIMEOUT_SEC * 1000)
    except Exception:
        pass
    generate_config = types.GenerateContentConfig(**kwargs)

    for tries in range(3):
        try:
            # SDK 예외 계층이 버전마다 달라서 타입이 아니라 상태 코드로 분기합니다.
            # try 블록 안에는 SDK 호출만 두어 우리 쪽 오타까지 삼키지 않게 합니다.
            response = client.models.generate_content(
                model=MODEL, contents=prompt, config=generate_config
            )
        except Exception as e:
            status = logger.status_of(e)

            if status in (401, 403):  # E8
                _disable(f"인증 오류 {status}")
                logger.record_error(
                    errors,
                    step=step,
                    type_="auth",
                    message=f"LLM 인증 실패({status}) — 남은 LLM 단계를 건너뜁니다",
                )
                logger.hint("`.env`의 GEMINI_API_KEY 값을 확인하세요.")
                return None

            if status == 429:  # E7-b — 재시도해도 그날은 풀리지 않습니다
                _disable("무료 한도 초과 (429)")
                logger.record_error(
                    errors,
                    step=step,
                    type_="quota",
                    message="LLM 무료 한도를 초과했습니다(429) — 남은 LLM 단계를 건너뜁니다",
                )
                logger.hint("내일 다시 시도하거나 GEMINI_MODEL을 다른 모델로 바꾸세요.")
                return None

            if status == 503 and tries < 2:  # E7-a — 일시적 과부하
                time.sleep(2 * (2**tries))  # 2초 → 4초
                continue

            logger.record_error(
                errors,
                step=step,
                type_="network",
                message=f"LLM 호출 실패 — {logger.safe_reason(e)}",
            )
            return None

        text = getattr(response, "text", None)
        if not text:
            logger.record_error(
                errors, step=step, type_="empty", message="LLM이 빈 응답을 돌려주었습니다"
            )
            return None
        return text

    logger.record_error(
        errors, step=step, type_="network", message="LLM 서버 과부하(503)가 계속되었습니다"
    )
    return None
