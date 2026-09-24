"""
tools/perf.py
=============
测量每个游戏 update+draw 的单帧耗时，找出性能瓶颈。

时间目标：单帧总预算 16.7ms（60fps）。任一游戏超过 ~10ms 就需要优化
（因为真机上还有摄像头预览、HUD、缩放合成等开销）。
"""
from __future__ import annotations

import os
import statistics
import sys
import time

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
from core import base as B  # noqa: E402
from tools.bot import bot_input  # noqa: E402
import games  # noqa: E402

U.init_font()

WARM = 60
MEASURE = 180


def bench(key: str):
    cls = next((c for c in B.all_games() if c.KEY == key), None)
    if cls is None:
        return None
    g = cls()
    surf = pygame.Surface((1920, 1080))
    dt = 1 / 60
    for i in range(WARM):
        inp = bot_input(g, i, WARM + MEASURE)
        g.tick(dt, inp)
        g.draw(surf)
    ts = []
    for i in range(MEASURE):
        inp = bot_input(g, WARM + i, WARM + MEASURE)
        t0 = time.perf_counter()
        g.tick(dt, inp)
        g.draw(surf)
        ts.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(ts), max(ts), len(U._bake_cache), len(U._rr_cache)


def main():
    keys = sys.argv[1:] or [c.KEY for c in B.all_games()]
    print(f"{'游戏':<14}{'中位':>8}{'最差':>8}{'烘焙缓存':>10}{'圆角缓存':>10}")
    worst = 0.0
    for k in keys:
        r = bench(k)
        if r is None:
            print(f"{k:<14}  (未注册)")
            continue
        med, mx, bc, rc = r
        flag = "  ⚠ 偏慢" if med > 8 else ""
        print(f"{k:<14}{med:7.2f}ms{mx:7.2f}ms{bc:10d}{rc:10d}{flag}")
        worst = max(worst, med)
    print(f"\n最慢中位耗时：{worst:.2f}ms（预算 16.7ms）")


if __name__ == "__main__":
    main()
