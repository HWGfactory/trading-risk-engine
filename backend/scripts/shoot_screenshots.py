"""문서용 스크린샷을 찍는다.

실행 (backend 폴더에서, vite dev와 uvicorn이 떠 있는 상태로):
    .venv\\Scripts\\python -m scripts.shoot_screenshots

왜 이런 구조인가
    Playwright를 설치하지 않고 이미 깔린 Chrome을 headless로 쓴다. 다만 Windows의
    Chrome은 뷰포트를 500px 미만으로 줄이지 못한다(--window-size=375를 줘도 500이 된다).
    그래서 앱을 정확한 크기의 iframe에 담는 보조 페이지(frontend/public/shot.html)를 띄우고,
    캡처한 이미지에서 그 영역만 잘라낸다. iframe은 그 자체가 뷰포트라 미디어쿼리가
    지정한 폭 그대로 적용된다.

    --force-prefers-reduced-motion을 주는 이유: 등장 애니메이션이 headless의 가상 시간에서
    끝나지 않아 요소가 투명한 채로 찍히기 때문이다. 앱이 감속 설정을 존중하므로
    이 옵션을 주면 모든 요소가 최종 상태로 렌더링된다.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

CHROME = Path(os.getenv("CHROME_PATH") or r"C:\Program Files\Google\Chrome\Application\chrome.exe")
BASE = os.getenv("TRE_WEB_BASE", "http://localhost:5174")
OUT = Path(__file__).resolve().parent.parent.parent / "docs" / "screenshots"

# Chrome이 창 테두리만큼 빼고 뷰포트를 잡는다. 실측값.
FRAME_W, FRAME_H = 16, 95
MIN_VIEWPORT = 500

DESKTOP = (1280, 900)
MOBILE = (375, 812)

# act는 화면을 어떤 상태까지 몰고 갈지 정한다(frontend/public/shot.html 참조).
# 평가 화면은 값이 채워진 상태로 찍는다. 빈 전표는 이 제품이 무엇을 하는지 보여주지 못한다.
SHOTS: list[tuple[str, str, int, int, str, str]] = []
for theme in ("light", "dark"):
    for name, route, tall, act in (("home", "/", 1760, ""),
                                   ("valuation", "/valuation", 1080, "filled"),
                                   ("book", "/book", 900, "")):
        SHOTS.append((f"{name}-desktop-{theme}", route, DESKTOP[0], tall, theme, act))
        mobile_h = {"home": 1500, "valuation": 1500}.get(name, 900)
        SHOTS.append((f"{name}-mobile-{theme}", route, MOBILE[0], mobile_h, theme, act))


def shoot(dest: Path, route: str, w: int, h: int, theme: str, act: str = "") -> bool:
    """shot.html을 띄워 잡고, iframe 영역(w x h)만 잘라 저장한다."""
    query = f"w={w}&h={h}&theme={theme}&route={route}"
    if act:
        query += f"&act={act}"
    return shoot_url(dest, query, w, h)


def shoot_url(dest: Path, query: str, w: int, h: int) -> bool:
    win_w = max(MIN_VIEWPORT, w) + FRAME_W
    win_h = h + FRAME_H
    url = f"{BASE}/shot.html?{query}"
    with tempfile.TemporaryDirectory() as profile:
        raw = Path(profile) / "raw.png"
        subprocess.run([
            str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--force-prefers-reduced-motion", f"--user-data-dir={profile}",
            f"--window-size={win_w},{win_h}", f"--screenshot={raw}",
            "--virtual-time-budget=9000", url,
        ], capture_output=True, timeout=180)
        if not raw.exists():
            return False
        with Image.open(raw) as im:
            im.crop((0, 0, min(w, im.width), min(h, im.height))).save(dest)
    return True


def main() -> int:
    if not CHROME.exists():
        print(f"Chrome을 찾지 못했습니다: {CHROME}")
        print("CHROME_PATH 환경 변수로 경로를 지정하세요.")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    # 이 스크립트가 다시 만들 파일만 지운다. shoot_states.py가 찍은 상태 스크린샷은 건드리지 않는다.
    for name, *_ in SHOTS:
        (OUT / f"{name}.png").unlink(missing_ok=True)

    made = 0
    for name, route, w, h, theme, act in SHOTS:
        ok = shoot(OUT / f"{name}.png", route, w, h, theme, act)
        print(f"{'[찍음]' if ok else '[실패]'} {name:30} {w}x{h} {theme}")
        made += int(ok)

    print(f"\n{made}/{len(SHOTS)}장을 {OUT}에 저장했습니다.")
    return 0 if made == len(SHOTS) else 1


if __name__ == "__main__":
    sys.exit(main())
