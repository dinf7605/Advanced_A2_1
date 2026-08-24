"""출력 폴더 준비와 결과 저장 (P1 소유) — PRD §9, 요건 8"""

from __future__ import annotations

import json
import os
import sys

from . import logger

# 요건 8에 파일명이 지정되어 있습니다. 바꾸지 마십시오.
RESULT_FILENAME = "brand_result.json"


def prepare(out_dir: str) -> str:
    """출력 폴더를 만들고 쓰기 가능한지 확인한다. 실패하면 종료한다 (E16, Fatal).

    여기가 Fatal인 이유: 저장할 곳이 없으면 산출물이 하나도 남지 않습니다.
    다른 실패는 "결과 일부가 빈다"지만, 이건 "결과가 0개"입니다.
    """
    try:
        os.makedirs(out_dir, exist_ok=True)
        # 폴더가 생겼다고 쓸 수 있는 것은 아닙니다 (권한·읽기전용 매체).
        probe = os.path.join(out_dir, ".write_check")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("")
        os.remove(probe)
    except OSError as e:
        logger.fatal(
            f"출력 폴더를 준비할 수 없습니다: {out_dir}",
            f"원인: {logger.safe_reason(e)}",
            "쓰기 권한이 있는 다른 경로를 입력하세요.",
        )
        sys.exit(1)
    return out_dir


def save_json(result: dict, out_dir: str) -> str | None:
    """결과를 brand_result.json으로 저장한다.

    ★ 이 함수는 if도 try도 없이 무조건 호출됩니다 (main.py). 여섯 단계가
    전부 실패해도 브리프 원본과 errors가 담긴 파일은 남습니다.
    "무엇이 왜 실패했는지 적힌 파일"이 파일이 없는 것보다 낫습니다.
    """
    path = os.path.join(out_dir, RESULT_FILENAME)
    try:
        with open(path, "w", encoding="utf-8") as f:
            # ensure_ascii=False가 없으면 한글이 이음 형태로 저장돼
            # 사람이 열어볼 수 없습니다. 제출물로서 가치가 떨어집니다.
            json.dump(result, f, ensure_ascii=False, indent=2)
    except OSError as e:
        # 여기서 실패하면 errors에 기록해도 남길 파일이 없으므로 화면에만 알립니다.
        logger.fatal(
            f"결과 저장에 실패했습니다: {path}",
            f"원인: {logger.safe_reason(e)}",
        )
        return None
    return path
