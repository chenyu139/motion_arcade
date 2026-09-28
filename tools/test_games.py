#!/usr/bin/env python3
"""
游戏层不变量测试 —— 「静止时受控物不得自作主张」。

为什么单开一个文件：外壳层的测试（test_input / test_feedback）盯的是输入与反馈链路，
**看不到游戏自己的自动行为**。而这里踩过一个从整轮 UI 重构里活下来的 bug：

    川超足球在"玩家没操作"时，让瞄准点以 250px/s 自动来回扫
    （注释写着"不操作时缓慢自动扫动，避免玩家完全不参与"）。

玩家看到的是"头一动没动，瞄准点在球门里自己滑来滑去"，直接读成
"识别飘了 / 乱动" —— 原话是「头没动球也在动」。
这和已修掉的两处是同一个立场问题：大厅"停留自动进入"、头部 LOST 后的衰减尾巴。
**静止时任何受控物都不许自作主张**，所以要在每个游戏上也断言一次，
并且配上反向断言（别把真实操作一起删掉）。

断言：
  · 川超足球：头部静止 3 秒 → 瞄准点不动、不会自己射门
  · 川超足球：平移仍能驱动瞄准；抬头仍能射门（防止"连交互一起删掉"）
  · 20 款游戏在「无识别」和「静止识别」两种输入下各跑 2 秒，不抛异常

跑法：
    .venv/bin/python tools/test_games.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

import games  # noqa: E402,F401  导入即注册全部游戏
from core import base as B  # noqa: E402
from core.inputs import GameInput  # noqa: E402

_ok = 0
_fail = 0
DT = 1.0 / 60.0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  ✓ {name}" + (f"　{detail}" if detail else ""))
    else:
        _fail += 1
        print(f"  ✗ {name}" + (f"　{detail}" if detail else ""))


STILL = GameInput(found=True)          # 检测到人，但一动不动（轴量恒为 0）


def _run(game, inp: GameInput, secs: float, surf=None, draw_every: int = 5) -> None:
    n = int(secs / DT)
    for i in range(n):
        game.tick(DT, inp)
        if surf is not None and i % draw_every == 0:
            game.draw(surf)


# --------------------------------------------------------------------- 回归
def test_football_idle_no_drift() -> None:
    """川超足球：头部静止时，瞄准点必须一动不动。"""
    print("\n[1] 川超足球：头部静止时瞄准点不得自己移动（真机回归）")
    cls = next(c for c in B.all_games() if c.KEY == "football")
    g = cls()
    g.reset()
    x0 = g.aim_x
    _run(g, STILL, 3.0)
    drift = abs(g.aim_x - x0)
    print(f"      静止 3 秒 → 瞄准点位移 {drift:.2f}px（朝向 {g.phase}）")
    check("瞄准点没有自己漂移（< 0.5px）", drift < 0.5, f"{drift:.2f}px")
    check("也没有自己射门", g.phase == "aim" and g.shot_i == 0, f"phase={g.phase}")

    # 换个角度：静止但"有人路过"（未识别）同样不许动
    g2 = cls()
    g2.reset()
    x1 = g2.aim_x
    _run(g2, GameInput(found=False), 2.0)
    check("未识别到时瞄准点同样不动", abs(g2.aim_x - x1) < 0.5,
          f"{abs(g2.aim_x - x1):.2f}px")


def test_football_input_still_works() -> None:
    """反向断言：删掉自动扫动之后，真实操作必须仍然有效。"""
    print("\n[2] 川超足球：平移仍能瞄准、抬头仍能射门（防止连交互一起删掉）")
    cls = next(c for c in B.all_games() if c.KEY == "football")

    g = cls()
    g.reset()
    x0 = g.aim_x
    _run(g, GameInput(found=True, axis=1.0), 0.5)
    moved = g.aim_x - x0
    print(f"      向右满偏 0.5 秒 → 瞄准点右移 {moved:.0f}px")
    check("平移能驱动瞄准点（> 300px）", moved > 300, f"{moved:.0f}px")

    g2 = cls()
    g2.reset()
    up = GameInput(found=True, up=1.0, jump=True)
    _run(g2, up, 0.2)
    check("抬头／动作键仍能射门", g2.phase in ("shoot", "result"), f"phase={g2.phase}")


# ------------------------------------------------------------------ 全量跑
def test_all_games_still_input() -> None:
    """20 款游戏在两种静止输入下各跑 2 秒（含绘制），全部不得抛异常。"""
    print("\n[3] 20 款游戏 × 静止/未识别输入 × 各 2 秒")
    surf = pygame.Surface((1920, 1080))
    bad = []
    for cls in B.all_games():
        for tag, inp in (("静止", STILL), ("未识别", GameInput(found=False))):
            try:
                g = cls()
                g.reset()
                _run(g, inp, 2.0, surf=surf)
            except Exception as e:                                  # noqa: BLE001
                bad.append(f"{cls.KEY}/{tag}: {e!r}")
    check(f"全部 {len(B.all_games())} 款游戏跑通（两种输入 × 2 秒）",
          not bad, " ".join(bad[:4]) if bad else "无异常")


def main() -> int:
    pygame.init()
    # 必须建一个显示表面：美术层大量用 convert_alpha()，
    # 没有视频模式时它直接抛 "No video mode has been set"。
    # dummy 驱动下 set_mode 也能正常返回（见技能里"无头验证"那节）。
    pygame.display.set_mode((320, 240))
    test_football_idle_no_drift()
    test_football_input_still_works()
    test_all_games_still_input()
    print("\n" + "=" * 68)
    print(f"结果：{_ok} 通过 / {_fail} 失败")
    print("=" * 68)
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
