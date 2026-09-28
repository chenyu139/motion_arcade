#!/usr/bin/env python3
"""
反馈层 / 绘制路径测试 —— 保证"好玩得起来"的那条链路不会一跑就炸。

为什么单独有这个文件：feedback.py 是**外壳级**模块，只有真的进游戏、HUD 数值
发生变化时才会被调到。之前 `_bump_combo` 里引用了不存在的 `amt`，静态跑测试
完全看不出来，一进游戏加分就 `NameError` 直接退出（run.log 里留过现场）。
所以这里把整条链路都压一遍，包含**每个游戏各跑若干帧**。

断言：
  · 加分 → 浮动数字 / 粒子 / 连击正确累加（且不抛异常）
  · 连击窗口过期后连击归零；扣分（delta<=0）不产生正反馈且断连击
  · NICE / PERFECT 阈值真的触发横幅，低分不触发
  · celebrate / fail / reset 后状态干净（不留残留数字与粒子）
  · 20 款游戏 × 进游戏 → HUD 数值变化 → 绘制，全部不抛异常

跑法：
    .venv/bin/python tools/test_feedback.py
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
from core.feedback import PERFECT_AT, Feedback  # noqa: E402

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


def _drawable() -> pygame.Surface:
    return pygame.Surface((1920, 1080))


# --------------------------------------------------------------------- 单元
def test_score_and_combo() -> None:
    print("\n[1] 加分 / 连击")
    f = Feedback()
    f.reset()
    f.set_accent((255, 80, 80))
    f.score(100, 100, 10, (255, 80, 80))
    check("首次得分连击 = 1", f.combo == 1, f"combo={f.combo}")
    check("产生了浮动数字", len(f.numbers) == 1)
    check("产生了粒子", len(f.particles.items) > 0, f"{len(f.particles.items)} 颗")

    for _ in range(3):
        f.score(100, 100, 10, (255, 80, 80))
    check("连续得分连击累加到 4", f.combo == 4, f"combo={f.combo}")
    check("最高连击被记录", f.max_combo == 4, f"max={f.max_combo}")

    # 超过连击窗口 → 归零
    for _ in range(int(3.0 / DT)):
        f.update(DT)
    check("超过连击窗口后连击归零", f.combo == 0, f"combo={f.combo}")

    n0 = len(f.numbers)
    f.score(100, 100, -5, (255, 80, 80))
    check("扣分不产生正反馈", len(f.numbers) == n0 and f.combo == 0)

    f.fail(100, 100)
    check("fail() 立即断连击", f.combo == 0)


def test_thresholds() -> None:
    print("\n[2] NICE / PERFECT 阈值")
    f = Feedback()
    f.reset()
    f.score(0, 0, 5, (255, 255, 255))
    check("低分不弹横幅", f.banner is None)
    f.score(0, 0, 20, (255, 255, 255))
    check("达到 NICE 弹横幅", f.banner is not None and f.banner["text"] == "NICE!")
    f.score(0, 0, PERFECT_AT, (255, 255, 255))
    check("达到 PERFECT 弹横幅并全屏脉冲",
          f.banner is not None and f.banner["text"] == "PERFECT!" and f.pulse > 0.0,
          f"pulse={f.pulse:.2f}")


def test_lifecycle_draw() -> None:
    print("\n[3] 全生命周期 + 绘制")
    f = Feedback()
    f.reset()
    for _ in range(6):
        f.score(300, 300, 30, (255, 200, 60))
    f.fail(300, 300)
    f.celebrate()
    s = _drawable()
    try:
        for _ in range(150):
            f.update(DT)
            f.draw(s)
        ok = True
        err = ""
    except Exception as e:                                          # noqa: BLE001
        ok, err = False, repr(e)
    check("加分/扣分/庆祝/绘制/衰减全程无异常", ok, err)
    check("数字最终飘完消失", len(f.numbers) == 0, f"剩 {len(f.numbers)} 个")

    f.reset()
    check("reset() 清空残留",
          not f.numbers and f.combo == 0 and f.banner is None and f.pulse == 0.0)


# ------------------------------------------------------------------ 端到端
def test_all_games_hud_path() -> None:
    """
    真·回归点：进游戏 → HUD 数值变化 → feedback.score → 绘制。

    之前就是这条路上 `NameError: name 'amt' is not defined`，一加分直接退出。
    """
    print("\n[4] 20 款游戏 × HUD 事件链路")
    from core.shell import Shell

    shell = Shell(vision="opencv", cam_index=0, no_cam=True, windowed=True,
                  start_game="menu")
    bad = []
    ran = []
    for cls in B.all_games():
        try:
            shell.start_game(cls.KEY)
            g = shell.game
            for _ in range(60):
                if hasattr(g, "score"):
                    g.score += 9           # 人为制造 HUD 数值变化
                shell._present()
            shell.back_to_menu()
            ran.append(cls.KEY)
        except Exception as e:                                      # noqa: BLE001
            bad.append(f"{cls.KEY}: {e!r}")
    check(f"全部 {len(B.all_games())} 款游戏跑通 HUD 事件链路",
          not bad and len(ran) == len(B.all_games()),
          " ".join(bad) if bad else " ".join(ran))


def main() -> int:
    pygame.init()
    test_score_and_combo()
    test_thresholds()
    test_lifecycle_draw()
    test_all_games_hud_path()
    print("\n" + "=" * 68)
    print(f"结果：{_ok} 通过 / {_fail} 失败")
    print("=" * 68)
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
