"""
tools/shots.py
==============
无头（headless）渲染每个游戏的一帧画面，用于快速目视检查。

用法：
    python tools/shots.py              # 全部游戏，每个 1 张
    python tools/shots.py mario tennis # 只渲染指定的
输出到 screenshots/。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((1920, 1080), pygame.SCALED)

from core import theme as U  # noqa: E402
from core.inputs import GameInput  # noqa: E402
from core import base as B  # noqa: E402
from tools.bot import bot_input  # noqa: E402
import games  # noqa: E402  （导入即注册）

U.init_font()
OUT = os.path.join(ROOT, "screenshots")
os.makedirs(OUT, exist_ok=True)


def run(key: str, frames: int = 240):
    cls = None
    for c in B.all_games():
        if c.KEY == key:
            cls = c
            break
    if cls is None:
        print(f"  ? 未知游戏 {key}")
        return False
    g = cls()
    surf = pygame.Surface((1920, 1080))
    dt = 1 / 60
    shots = []
    try:
        for i in range(frames):
            inp = bot_input(g, i, frames)
            g.tick(dt, inp)
            g.draw(surf)
            if i > 40 and i % 60 == 0:
                shots.append(surf.copy())
            if g.is_over() and i > 60:
                g.reset()
        g.draw(surf)
        shots.append(surf.copy())
        # 主图 + 两个过程帧
        pygame.image.save(shots[-1], os.path.join(OUT, f"{key}.png"))
        if len(shots) >= 3:
            pygame.image.save(shots[len(shots) // 3], os.path.join(OUT, f"{key}_b.png"))
        if len(shots) >= 2:
            pygame.image.save(shots[len(shots) * 2 // 3], os.path.join(OUT, f"{key}_c.png"))
        print(f"  ✓ {key:12s} {cls.TITLE}  →  screenshots/{key}.png")
        return True
    except Exception as e:                                          # noqa: BLE001
        import traceback
        print(f"  ✗ {key:12s} 渲染失败：{type(e).__name__}: {e}")
        traceback.print_exc()
        return False


def main():
    keys = sys.argv[1:] or [c.KEY for c in B.all_games()]
    print(f"共 {len(B.all_games())} 个游戏，渲染 {len(keys)} 个：")
    ok = sum(run(k) for k in keys)
    print(f"完成：{ok}/{len(keys)}")


if __name__ == "__main__":
    main()
