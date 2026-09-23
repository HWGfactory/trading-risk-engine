"""배포 환경에서 바뀌는 값들. 전부 환경변수로 받는다.

기본값은 로컬 개발 기준이다. 환경변수를 하나도 주지 않으면 지금까지와 똑같이 동작한다.
"""
from __future__ import annotations

import os

# 로컬 개발에서 프론트가 뜨는 주소. 배포 시 ALLOWED_ORIGINS로 덮어쓴다.
DEFAULT_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")

# 데모 환경에서 포지션이 무한정 쌓이지 않도록 두는 상한.
DEFAULT_MAX_POSITIONS = 50


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def allowed_origins() -> list[str]:
    """CORS 허용 도메인. 쉼표로 구분한다.

    예: ALLOWED_ORIGINS="https://my-app.vercel.app,https://preview.vercel.app"
    """
    raw = os.getenv("ALLOWED_ORIGINS")
    if not raw or not raw.strip():
        return list(DEFAULT_ORIGINS)
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]


def demo_mode() -> bool:
    """데모 환경 여부.

    켜면 화면에 안내를 띄우고(/api/reference 응답의 demo_mode), 포지션 수에 상한을 건다.
    """
    return _flag("DEMO_MODE")


def max_positions() -> int:
    raw = os.getenv("DEMO_MAX_POSITIONS")
    try:
        value = int(raw) if raw else DEFAULT_MAX_POSITIONS
    except ValueError:
        value = DEFAULT_MAX_POSITIONS
    return max(1, value)


def auto_seed() -> bool:
    """시작할 때 DB가 비어 있으면 예시 북을 만들지 여부.

    Render 무료 플랜은 재시작마다 파일이 사라지므로, 켜 두면 늘 데모가 준비된 상태가 된다.
    DEMO_MODE가 켜져 있으면 기본으로 함께 켠다.
    """
    return _flag("AUTO_SEED", default=demo_mode())


def port() -> int:
    """Render 같은 플랫폼이 주입하는 포트."""
    raw = os.getenv("PORT")
    try:
        return int(raw) if raw else 8000
    except ValueError:
        return 8000
