"""이미지 생성 API 어댑터 (P5 소유) — PRD §7.7, 요건 7

★ 어댑터로 만든 이유 ★
과제 요건 7은 "이미지 생성 API(DALL-E **등**)"라고 열어두었습니다. 그런데
DALL·E는 유료라 5명 중 누가 결제할지 정해지지 않으면 팀 전체가 멈춥니다.
제공자를 갈아끼울 수 있게 해두면 키 발급이 막혀도 다른 것으로 계속 진행할 수
있습니다.

제공자마다 다른 것은 네 개뿐입니다:
    credentials / build_request / call / extract_images
타임아웃·재시도·오류 분기·로그는 공통 generate_images()에 한 번만 둡니다.
**제공자를 추가할 때 generate_images()를 고치지 마십시오.**

⚠️ 아래 모델명과 요청 형식은 Day 1에 실호출로 확인해야 하는 미검증 항목입니다
(PRD §7.7). A1-2에서 목록에 있는 모델이 호출하면 404가 난 사례가 있습니다.
"""

from __future__ import annotations

import base64

from . import config, logger, mock


class ImageProvider:
    """제공자 공통 인터페이스."""

    name = "?"
    key_env = "?"

    def credentials(self) -> str | None:
        """키가 없으면 필요한 환경변수 이름을, 있으면 None을 돌려준다."""
        raise NotImplementedError

    def build_request(self, prompt: str, n: int) -> dict:
        raise NotImplementedError

    def call(self, request: dict):
        raise NotImplementedError

    def extract_images(self, response) -> list[bytes]:
        raise NotImplementedError

    # 공통 유틸 — URL로 오는 응답을 바이트로 바꾼다
    @staticmethod
    def download(url: str) -> bytes | None:
        """URL 방식 응답을 내려받는다.

        URL은 대개 짧은 시간 뒤 만료되고 다운로드가 한 번 더 실패할 수 있는
        지점입니다. **네트워크 왕복이 하나 줄면 실패 지점도 하나 줍니다.**
        그래서 가능하면 base64 방식을 먼저 시도합니다.
        """
        try:
            import requests

            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.content
        except Exception:
            return None


class OpenAIImageProvider(ImageProvider):
    name = "openai"
    key_env = "OPENAI_API_KEY"

    def __init__(self) -> None:
        self.model = config.OPENAI_IMAGE_MODEL

    def credentials(self) -> str | None:
        return None if config.openai_key() else self.key_env

    def build_request(self, prompt: str, n: int) -> dict:
        request = {"model": self.model, "prompt": prompt, "n": n, "size": "1024x1024"}
        if self.model.startswith("dall-e"):
            # dall-e 계열만 response_format을 받습니다. gpt-image-1에 넣으면 오류가 납니다.
            request["response_format"] = "b64_json"
            request["n"] = 1  # dall-e-3는 요청당 1장만 허용합니다
        return request

    def call(self, request: dict):
        from openai import OpenAI  # 지연 import — SDK가 없어도 목업은 돌아야 합니다

        client = OpenAI(api_key=config.openai_key(), timeout=config.IMAGE_TIMEOUT_SEC)
        return client.images.generate(**request)

    def extract_images(self, response) -> list[bytes]:
        images: list[bytes] = []
        for item in getattr(response, "data", None) or []:
            encoded = getattr(item, "b64_json", None)
            if encoded:
                images.append(base64.b64decode(encoded))
                continue
            url = getattr(item, "url", None)
            if url:  # URL로 온 경우에만 다운로드가 한 단계 더 필요합니다
                downloaded = self.download(url)
                if downloaded:
                    images.append(downloaded)
        return images


class GeminiImageProvider(ImageProvider):
    name = "gemini"
    key_env = "GEMINI_API_KEY"

    def __init__(self) -> None:
        self.model = config.GEMINI_IMAGE_MODEL

    def credentials(self) -> str | None:
        return None if config.gemini_key() else self.key_env

    def build_request(self, prompt: str, n: int) -> dict:
        return {"model": self.model, "prompt": prompt}

    def call(self, request: dict):
        from google import genai

        client = genai.Client(api_key=config.gemini_key())
        return client.models.generate_content(
            model=request["model"], contents=request["prompt"]
        )

    def extract_images(self, response) -> list[bytes]:
        images: list[bytes] = []
        for candidate in getattr(response, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                inline = getattr(part, "inline_data", None)
                data = getattr(inline, "data", None) if inline else None
                if not data:
                    continue
                images.append(data if isinstance(data, bytes) else base64.b64decode(data))
        return images


IMAGE_PROVIDERS = {
    "openai": OpenAIImageProvider,
    "gemini": GeminiImageProvider,
}


def resolve() -> ImageProvider | None:
    factory = IMAGE_PROVIDERS.get(config.image_provider())
    return factory() if factory else None


def generate_images(prompt: str, n: int, *, step: str, errors: list) -> list[bytes]:
    """PNG 바이트 리스트를 돌려준다. 실패하면 빈 리스트 (예외 없음).

    부분 성공을 허용합니다 — n장 요청에 2장만 오면 2장을 돌려줍니다.
    호출자(gen_logo)는 시안마다 형식 키워드를 바꿔 n=1로 부르므로, 여기서
    부족한 장수를 채우려 재요청하지 않습니다.
    """
    if mock.enabled():
        reason = mock.failure_for(step)
        if reason:
            logger.record_error(errors, step=step, type_="network", message=reason)
            return []
        return mock.images(n)

    provider = resolve()
    if provider is None:
        logger.record_error(
            errors,
            step=step,
            type_="invalid",
            message=f"알 수 없는 IMAGE_PROVIDER입니다: {config.image_provider()!r}"
            f" (가능: {', '.join(IMAGE_PROVIDERS)})",
        )
        return []

    missing_key = provider.credentials()
    if missing_key:  # E5 — Degraded. 로고만 건너뛰고 나머지는 진행합니다.
        logger.record_error(
            errors,
            step=step,
            type_="auth",
            message=f"{missing_key}가 설정되지 않아 로고 단계를 건너뜁니다",
        )
        return []

    return _call_once(provider, prompt, n, step=step, errors=errors)[:n]


def _call_once(
    provider: ImageProvider, prompt: str, n: int, *, step: str, errors: list
) -> list[bytes]:
    try:
        request = provider.build_request(prompt, n)
    except Exception as e:
        logger.record_error(
            errors, step=step, type_="invalid", message=f"요청 조립 실패 — {logger.safe_reason(e)}"
        )
        return []

    try:
        # try 블록 안에는 SDK 호출만 둡니다 — 우리 쪽 오타까지 삼키지 않도록.
        response = provider.call(request)
    except ImportError:
        logger.record_error(
            errors,
            step=step,
            type_="auth",
            message=f"{provider.name} SDK가 설치되어 있지 않습니다",
        )
        logger.hint(f"pip install {'openai' if provider.name == 'openai' else 'google-genai'}")
        return []
    except Exception as e:
        status = logger.status_of(e)

        if status in (401, 403):  # E12
            logger.record_error(
                errors,
                step=step,
                type_="auth",
                message=f"이미지 API 인증 실패({status})",
            )
            logger.hint(f"`.env`의 {provider.key_env} 값을 확인하세요.")
        elif status == 429:  # E13 — 쿼터가 아니라 잔액 문제일 수 있습니다
            logger.record_error(
                errors,
                step=step,
                type_="quota",
                message="이미지 API 한도 초과(429)",
            )
            logger.hint("요청 한도 또는 남은 크레딧(결제 잔액)을 확인하세요.")
        elif status == 404:
            logger.record_error(
                errors,
                step=step,
                type_="invalid",
                message=f"이미지 모델을 찾을 수 없습니다({status}) — 모델명을 확인하세요",
            )
            logger.hint("환경변수 OPENAI_IMAGE_MODEL / GEMINI_IMAGE_MODEL로 바꿀 수 있습니다.")
        else:  # E14 — 네트워크·타임아웃 등
            logger.record_error(
                errors,
                step=step,
                type_="network",
                message=f"이미지 생성 실패 — {logger.safe_reason(e)}",
            )
        return []

    try:
        images = provider.extract_images(response)
    except Exception as e:
        logger.record_error(
            errors, step=step, type_="parse", message=f"이미지 응답 해석 실패 — {logger.safe_reason(e)}"
        )
        return []

    if not images:
        logger.record_error(
            errors, step=step, type_="empty", message="이미지 API가 이미지를 돌려주지 않았습니다"
        )
    return images
