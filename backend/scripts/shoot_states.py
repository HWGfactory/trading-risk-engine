"""추가 상태 스크린샷: 빈 북, 로딩 스켈레톤, 입력 오류, 근거 추적 강조, 대사 결과.

실행 (backend 폴더에서, vite dev와 uvicorn이 떠 있는 상태로):
    .venv\\Scripts\\python -m scripts.shoot_states

shot.html의 ?act= 값으로 iframe 안 화면을 원하는 상태까지 몰고 간 뒤 찍는다.
빈 북과 로딩은 실제 서버를 건드리지 않도록 화면 쪽에서 상황을 만든다.
"""
from __future__ import annotations

import sys

from scripts.shoot_screenshots import CHROME, OUT, shoot_url

STATES: list[tuple[str, str, int, int, str]] = [
    # (파일명, shot.html 쿼리, 폭, 높이, 설명)
    ("state-book-empty", "route=/book&act=empty", 1280, 700, "빈 북"),
    ("state-loading-skeleton", "route=/book&act=loading", 1280, 620, "로딩 스켈레톤"),
    ("state-input-error", "route=/valuation&act=error", 1280, 900, "입력 오류"),
    ("state-trace-highlight", "route=/valuation&act=trace", 1280, 900, "근거 추적 강조"),
    ("state-reconciliation", "route=/book&act=recon&theme=dark", 1280, 620, "대사 일치"),
]


def main() -> int:
    if not CHROME.exists():
        print(f"Chrome을 찾지 못했습니다: {CHROME}")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    made = 0
    for name, query, w, h, label in STATES:
        theme = "dark" if "theme=dark" in query else "light"
        q = query if "theme=" in query else f"{query}&theme={theme}"
        ok = shoot_url(OUT / f"{name}.png", f"w={w}&h={h}&{q}", w, h)
        print(f"{'[찍음]' if ok else '[실패]'} {name:28} {w}x{h} {label}")
        made += int(ok)
    print(f"\n{made}/{len(STATES)}장을 {OUT}에 저장했습니다.")
    return 0 if made == len(STATES) else 1


if __name__ == "__main__":
    sys.exit(main())
