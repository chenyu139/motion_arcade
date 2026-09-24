"""
tools/shell_shots.py
====================
无头验证外壳：菜单 3 页 + 每个游戏带完整 HUD/预览的真实合成画面。

这是"最终交付形态"的截图 —— 之前 tools/shots.py 只渲染游戏本体，
这里的图才是玩家真正看到的画面。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("ARCADE_WINDOWED", "1")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

HERE_CORE = os.path.join(ROOT, "core")
import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((1920, 1080), pygame.SCALED)

from core import base as B  # noqa: E402
from core import theme as U  # noqa: E402
from core.shell import Shell  # noqa: E402
from tools.bot import bot_input  # noqa: E402
import games  # noqa: E402

U.init_font()
OUT = os.path.join(ROOT, "screenshots", "shell")
os.makedirs(OUT, exist_ok=True)


def build_shell() -> Shell:
    sh = Shell(vision="auto", cam_index=C_INDEX, no_cam=True, windowed=True)
    return sh


C_INDEX = 0


def shoot_menu() -> None:
    sh = build_shell()
    dt = 1 / 60
    for page in range(sh.menu.total_pages):
        sh.menu.page = page
        sh.menu.sel = page * 8 + min(2, len(sh.menu.games) - page * 8 - 1)
        sh.menu.sel_f = float(sh.menu.sel)
        sh.menu.enter_t = 2.0
        sh.menu._page_anim = 1.0
        for i in range(60):
            sh.menu.update(dt, bot_input(None, i, 60) if i > 5 else __import__(
                "core.inputs", fromlist=["GameInput"]).GameInput())
            sh.menu.draw(sh.canvas)
            sh._present()                     # 走真实合成路径，截图才和玩家看到的一致
            if i == 59:
                pygame.image.save(sh.screen, os.path.join(OUT, f"menu_p{page + 1}.png"))
    print(f"  ✓ 菜单 {sh.menu.total_pages} 页 → screenshots/shell/menu_p*.png")


def shoot_game(key: str) -> bool:
    sh = build_shell()
    sh.start_game(key)
    dt = 1 / 60
    try:
        for i in range(200):
            inp = bot_input(None, i, 200)
            # 复刻 run() 循环里的淡入/提示衰减，否则画面会一直蒙着进入时的白闪
            if sh.fade > 0:
                sh.fade = max(0.0, sh.fade - dt * 3.0)
            if sh.toast_t > 0:
                sh.toast_t = max(0.0, sh.toast_t - dt)
            sh.game.tick(dt, inp)
            sh.game.draw(sh.canvas)
            if sh.game.is_over() and i > 80:
                sh.game.reset()
                sh.game.draw(sh.canvas)
            if i == 199:
                sh._present()
        pygame.image.save(sh.screen, os.path.join(OUT, f"{key}.png"))
        print(f"  ✓ {key}")
        return True
    except Exception as e:                                          # noqa: BLE001
        import traceback
        print(f"  ✗ {key}: {type(e).__name__}: {e}")
        traceback.print_exc()
        return False


def main():
    keys = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not keys or "--menu" in sys.argv:
        shoot_menu()
    todo = keys or [c.KEY for c in B.all_games()]
    ok = sum(shoot_game(k) for k in todo)
    print(f"完成：{ok}/{len(todo)}")


if __name__ == "__main__":
    main()
