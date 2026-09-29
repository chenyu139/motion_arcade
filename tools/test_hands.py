#!/usr/bin/env python3
"""
手部跟踪行为测试 —— 第二版（最近邻跟随 + HOLD/LOST + skin 永不竞争）。

第一版"ID 跟踪 + 控制权夺权"被实测证伪（用户真机"完全不跟"）：
skin 误检块先建立主手后，真手永远夺不回控制权 —— 锁得越稳，跟得越死。
第二版的核心断言全部围绕这个失败模式设计。

跑法：
    .venv/bin/python tools/test_hands.py
"""
from __future__ import annotations

import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config as C                                    # noqa: E402
from core.inputs import HandController, HandState               # noqa: E402

DT = 1.0 / 30.0
_ok = 0
_fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  ✓ {name}" + (f"　{detail}" if detail else ""))
    else:
        _fail += 1
        print(f"  ✗ {name}" + (f"　{detail}" if detail else ""))


def hand(x=0.5, y=0.5, open_v=0.9, area=0.05, fingers=5, pose=None):
    return HandState(found=True, x=x, y=y, open=open_v, area=area,
                     fingers=fingers, pose=pose)


def vhand(x=0.5, y=0.5, **kw):
    """Vision 的手（pose 挂着 HandFrame 标记）。"""
    return hand(x=x, y=y, pose=object(), **kw)


def settled(x=0.5, y=0.5, **kw) -> HandController:
    hc = HandController(C)
    for _ in range(30):
        hc.update([vhand(x=x, y=y, **kw)], DT)
    return hc


# --------------------------------------------------------------------------- #
def test_false_positive_cannot_lock() -> None:
    """
    **第一版的致命伤，第二版的存在理由。**

    skin 误检块（面积 0.06，固定在画面一角）先建立主手，
    Vision 真手（面积 0.02）持续出现 —— 光标必须跟到真手。
    """
    print("\n[1] 误检大块不得永久锁死光标（第一版失败模式回归）")
    hc = HandController(C)
    # 只有 skin 误检在画面里（模拟 Vision 尚无手部输出的最初几秒）
    for _ in range(90):
        hc.update([hand(x=0.25, y=0.30, area=0.06)], DT)
    print(f"      误检先建立主手：光标=({hc.sx:.2f},{hc.sy:.2f}) src={hc.hand_src}")
    # 真手出现并持续挥动 —— 最近邻规则下，离上一帧更近者赢
    for i in range(120):
        x = 0.45 + 0.2 * math.sin(i / 8)
        hc.update([hand(x=0.25, y=0.30, area=0.06), vhand(x=x, y=0.50, area=0.02)], DT)
    print(f"      真手挥动 4 秒后：光标=({hc.sx:.2f},{hc.sy:.2f})")
    near_hand = abs(hc.sx - 0.45) < 0.25 and abs(hc.sy - 0.50) < 0.15
    check("光标已跟到真手附近（未被误检锁死）", near_hand,
          f"({hc.sx:.2f},{hc.sy:.2f})")


def test_nearest_neighbor_tracking() -> None:
    """最近邻跟随：多候选时抗返回顺序抖动，且始终跟移动的那只。"""
    print("\n[2] 最近邻跟随 + 顺序无关性")
    hc = settled(x=0.40, y=0.50)
    # 双候选 + 顺序每帧交换：输出必须稳定
    xs = []
    for i in range(120):
        a, b = vhand(x=0.40, y=0.50), vhand(x=0.78, y=0.52)
        hc.update([a, b] if i % 2 == 0 else [b, a], DT)
        xs.append(hc.sx)
    spread = max(xs) - min(xs)
    check("双候选 + 顺序交换：输出稳定（极差 < 0.03）", spread < 0.03,
          f"极差 {spread:.3f}")
    check("仍跟原来的那只", abs(hc.sx - 0.40) < 0.06, f"sx={hc.sx:.3f}")


def test_follow_moving_hand() -> None:
    """单手连续移动：光标全程跟随（这就是"跟手"的基本盘）。"""
    print("\n[3] 连续移动全程跟随")
    hc = settled(x=0.20, y=0.50)
    errs = []
    for i in range(180):
        x = 0.20 + 0.6 * (i / 179.0)          # 6 秒从 0.20 匀速移到 0.80
        hc.update([vhand(x=x, y=0.50)], DT)
        errs.append(abs(hc.sx - x))
    print(f"      匀速横移全程最大误差 {max(errs):.3f}")
    check("匀速跟随误差 < 0.06", max(errs) < 0.06, f"最大 {max(errs):.3f}")


def test_fast_swipe() -> None:
    """快速挥动（切水果核心动作）：滞后必须远小于可感知量。"""
    print("\n[4] 快速挥动滞后")
    hc = settled(x=0.20, y=0.50)
    for i in range(int(0.4 / DT)):
        hc.update([vhand(x=min(0.92, 0.20 + 3.0 * i * DT), y=0.50)], DT)
    lag = 0.92 - hc.sx
    print(f"      0.4s 横挥 ~1.2 画面 → 输出 {hc.sx:.3f}，滞后 {lag:.3f}")
    check("快挥滞后 < 0.15", lag < 0.15, f"滞后 {lag:.3f}")


def test_hold_freeze_and_lost() -> None:
    """闪烁冻结 / 真丢失清零 + 边沿完整复位（第二版保留的头部语义）。"""
    print("\n[5] HOLD 冻结 / LOST 清零")
    hc = settled(x=0.30, y=0.40, open_v=0.9)
    held = (hc.sx, hc.sy)
    for _ in range(8):                        # 0.27s < HAND_HOLD_AFTER
        hc.update([], DT)
    check("闪烁 0.27s 输出完全冻结",
          abs(hc.sx - held[0]) < 1e-12 and abs(hc.sy - held[1]) < 1e-12)
    check("冻结期间 seen 保持", hc.seen)
    for _ in range(int(C.HAND_LOST_AFTER / DT) + 6):
        hc.update([], DT)
    check("真丢失后 seen=False 且主手记忆清空",
          not hc.seen and hc._px is None)


def test_reacquire_no_ghost_pinch() -> None:
    """丢失后重新捕获一只一直握着的手：不得凭空触发捏合。"""
    print("\n[6] 重捕获不产生幽灵捏合")
    hc = settled(x=0.5, y=0.5, open_v=0.9)
    fired = 0
    for _ in range(5):
        hc.update([vhand(open_v=0.1)], DT)
        fired += 1 if hc.pinch else 0
    check("正常捏合触发一次", fired == 1, f"{fired} 次")
    for _ in range(int(C.HAND_LOST_AFTER / DT) + 6):
        hc.update([], DT)
    fired2 = 0
    for _ in range(20):
        hc.update([vhand(open_v=0.1)], DT)    # 一直握着的手回来
        fired2 += 1 if hc.pinch else 0
    check("重捕获握着的手不误触发", fired2 == 0, f"误触发 {fired2} 次")


def test_skin_source_degradation() -> None:
    """skin 降级：只在没有 Vision 手时提供坐标；Vision 恢复立即让位。"""
    print("\n[7] skin 降级与让位")
    hc = settled(x=0.40, y=0.45)
    # Vision 手消失（tracker 在 Vision 缺席 HANDSKIN_AFTER 后才会递 skin，
    # 这里直接模拟递入 skin 的手）
    for _ in range(10):
        hc.update([hand(x=0.42, y=0.47, area=0.03, open_v=0.6, fingers=0)], DT)
    check("skin 降级时光标仍在原处附近", abs(hc.sx - 0.42) < 0.08, f"sx={hc.sx:.3f}")
    check("来源标记为 skin", hc.hand_src == "skin", hc.hand_src)
    # Vision 恢复（同帧只有 Vision 的手）→ 立即让位
    for _ in range(6):
        hc.update([vhand(x=0.60, y=0.50)], DT)
    check("Vision 恢复后立即接管", hc.hand_src == "vision", hc.hand_src)
    check("光标跟到 Vision 的手", abs(hc.sx - 0.60) < 0.08, f"sx={hc.sx:.3f}")


def test_takeover_when_target_gone() -> None:
    """主手消失后能换到另一只手（不能死锁）。"""
    print("\n[8] 主手消失后换目标")
    hc = settled(x=0.30, y=0.50)
    for _ in range(int(C.HAND_LOST_AFTER / DT) + 6):
        hc.update([], DT)
    for _ in range(30):
        hc.update([vhand(x=0.70, y=0.50)], DT)
    check("新手接管且光标到位", abs(hc.sx - 0.70) < 0.08, f"sx={hc.sx:.3f}")


def main() -> int:
    print("=" * 66)
    print("手部跟踪行为测试（第二版：最近邻跟随）")
    print(f"参数：HOLD={C.HAND_HOLD_AFTER}s  LOST={C.HAND_LOST_AFTER}s  "
          f"MAX_STEP={C.HAND_MAX_STEP}/s  SKIN_AFTER={C.HANDSKIN_AFTER}s")
    print("=" * 66)
    test_false_positive_cannot_lock()
    test_nearest_neighbor_tracking()
    test_follow_moving_hand()
    test_fast_swipe()
    test_hold_freeze_and_lost()
    test_reacquire_no_ghost_pinch()
    test_skin_source_degradation()
    test_takeover_when_target_gone()
    print("\n" + "=" * 66)
    print(f"通过 {_ok} 项，失败 {_fail} 项")
    print("=" * 66)
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
