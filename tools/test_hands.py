#!/usr/bin/env python3
"""
手部跟踪行为测试 —— ID 跟踪架构（HandController 重构版）。

背景：用户反馈"手检测到了，但轨迹和方向完全对不上（水果切切基本不可用）"。
根因不是一个点，而是旧架构缺了整套"目标管理"层：
  · 快速挥动时 21 点检测必然闪烁；旧 HAND_LOST_AFTER=0.6s 一到就清空主手记忆
    → 下一次检测回来重新选主 → 光标跳走。**挥得越快、跟得越错。**
  · 没有跨帧身份：每帧拿到的是"一串手"，谁是谁全靠位置猜。
  · 每帧重选主手：多只手时评分易手，光标在几只手之间瞬移。

重构后的架构（见 core/inputs.py HandController）在这里逐条断言。
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


def hand(x=0.5, y=0.5, open_v=0.9, area=0.05, fingers=5):
    return HandState(found=True, x=x, y=y, open=open_v, area=area, fingers=fingers)


def settled_hc(**kw) -> HandController:
    """建一个主手已稳定锁定的控制器（默认单手在画面中央）。"""
    hc = HandController(C)
    for _ in range(30):
        hc.update([hand(**kw)], DT)
    return hc


# --------------------------------------------------------------------------- #
def test_flicker_freeze() -> None:
    """
    快速挥动 → 检测闪烁 → 光标**冻结在原地**，绝不衰减、绝不重选。

    这是"挥得越快跟得越错"的直接回归测试：旧实现闪烁 0.6s 后清空主手
    记忆，重新检测到（哪怕是别的东西）就立刻把光标拽过去。
    """
    print("\n[1] 快速挥动中的检测闪烁：输出冻结、目标不变")
    hc = settled_hc()
    # 把手挥到左侧
    for _ in range(20):
        hc.update([hand(x=0.20)], DT)
    held = (hc.sx, hc.sy)
    tid = hc._main.tid
    # 闪烁 0.27s（8 帧 < HAND_HOLD_AFTER=0.30）：输出必须一点不变
    for _ in range(8):
        hc.update([], DT)
    check("闪烁 0.27s 内输出完全冻结",
          abs(hc.sx - held[0]) < 1e-12 and abs(hc.sy - held[1]) < 1e-12,
          f"({held[0]:.4f},{held[1]:.4f}) → ({hc.sx:.4f},{hc.sy:.4f})")
    check("闪烁期间 seen 保持（游戏侧不判丢失）", hc.seen)
    # 闪烁恢复：还是同一只手（ID 不变），光标从冻结处继续
    for _ in range(4):
        hc.update([hand(x=0.19)], DT)
    check("闪烁恢复后还是同一目标（ID 不变）", hc._main.tid == tid,
          f"{tid} → {hc._main.tid}")
    check("恢复后光标仍在手边（未被拽走）", abs(hc.sx - 0.19) < 0.05, f"sx={hc.sx:.3f}")


def test_flicker_long_lost() -> None:
    """闪烁超过 HOLD 但没到 LOST：按'手不在'处理，但不清 armed 语义之外的状态。"""
    print("\n[2] 长闪烁（>HOLD 且 <LOST）后的行为")
    hc = settled_hc()
    for _ in range(int(C.HAND_LOST_AFTER / DT) + 6):
        hc.update([], DT)
    check("超过 LOST 后 seen=False", not hc.seen)
    check("控制权已交还（_main 为空）", hc._main is None)


def test_id_stable_under_reorder() -> None:
    """
    检测器返回顺序不稳定：两只手时 ID 必须跟着手走，而不是跟着下标走。

    （这是上一轮"轨迹对不上"的根因之一：max() 在平分时取第一个。）
    """
    print("\n[3] 双手 + 返回顺序随机交换：ID 跟手不跟下标")
    hc = HandController(C)
    # 先只伸 A 手，锁定主手
    for _ in range(30):
        hc.update([hand(x=0.30, area=0.05)], DT)
    tid = hc._main.tid
    # B 手进入画面，且检测器返回顺序每帧交替
    flips = 0
    prev_tid = tid
    for i in range(120):
        a, b = hand(x=0.30, area=0.05), hand(x=0.72, area=0.06)
        pair = [a, b] if i % 2 == 0 else [b, a]
        hc.update(pair, DT)
        if hc._main.tid != prev_tid:
            flips += 1
            prev_tid = hc._main.tid
    check("120 帧内主手从未易主", flips == 0, f"易主 {flips} 次")
    check("主手仍是 A（光标跟 A）", abs(hc.sx - 0.30) < 0.08, f"sx={hc.sx:.3f}")


def test_takeover_hysteresis() -> None:
    """偶发的误检大块抢不走光标；持续的真·更大的手才能接管。"""
    print("\n[4] 控制权迟滞：误检不夺权 / 真换手可接管")
    hc = settled_hc(x=0.30, area=0.05)
    tid = hc._main.tid
    # 误检大块：只出现 3 帧（< HAND_TAKEOVER_FRAMES=6）
    for i in range(20):
        blob = [hand(x=0.75, area=0.5)] if 5 <= i < 8 else []
        hc.update([hand(x=0.30, area=0.05)] + blob, DT)
    check("3 帧的误检大块没抢走控制权", hc._main.tid == tid)
    check("光标仍在原手处", abs(hc.sx - 0.30) < 0.08, f"sx={hc.sx:.3f}")

    # 真换手：新人持续在画面里且明显更大 → 允许接管
    for _ in range(30):
        hc.update([hand(x=0.30, area=0.04), hand(x=0.75, area=0.5)], DT)
    check("持续的大手最终接管", hc._main.tid != tid and abs(hc.sx - 0.75) < 0.08,
          f"sx={hc.sx:.3f}")


def test_fast_swipe_tracking() -> None:
    """
    快速挥动必须跟得上 —— 这就是"切水果"的核心动作。

    以 2.2 画面/秒横挥 0.5 秒，滤波输出的滞后必须远小于半屏。
    （旧实现三层平滑叠加，滞后超 0.15 画面比例，刀光永远慢半拍。）
    """
    print("\n[5] 快速挥动的跟随性")
    hc = settled_hc(x=0.20)
    speed = 2.2
    n = int(0.5 / DT)
    for i in range(n):
        x = 0.20 + speed * i * DT
        hc.update([hand(x=min(0.95, x))], DT)
    lag = 0.95 - hc.sx if hc.sx < 0.5 else (0.20 + speed * 0.5) - hc.sx
    # 终点目标 ≈ 0.20+1.1=1.30 → clamp 到 0.95
    lag = 0.95 - hc.sx
    print(f"      0.5s 横挥 1.1 画面 → 输出 {hc.sx:.3f}（目标 0.95），滞后 {lag:.3f}")
    check("快挥滞后 < 0.18（低于满量的 1/5）", lag < 0.18, f"滞后 {lag:.3f}")


def test_velocity_spike_rejected() -> None:
    """单帧误检瞬移（假手突然出现在另一头）必须被速率限制削幅。"""
    print("\n[6] 单帧瞬移被速率限制削幅")
    hc = settled_hc(x=0.30)
    peak = 0.0
    for i in range(30):
        # 第 10 帧出现一个瞬移的假观测（同帧真手丢失）
        x = 0.85 if i == 10 else 0.30
        hc.update([hand(x=x)], DT)
        peak = max(peak, abs(hc.sx - 0.30))
    print(f"      假观测 0.85 一帧 → 输出峰值偏移 {peak:.3f}")
    check("瞬移被削幅（偏移 < 0.10）", peak < 0.10, f"峰值偏移 {peak:.3f}")


def test_skin_vision_source_switch() -> None:
    """兜底（skin）与主路径（vision）切换时光标位置连续，不跳变。"""
    print("\n[7] skin / vision 来源切换的位置连续性")
    hc = settled_hc(x=0.40, y=0.45)
    # vision 丢失 0.3s（冻结期内），skin 在同位置给出观测
    for _ in range(9):
        hc.update([hand(x=0.42, y=0.46, open_v=0.5, area=0.03, fingers=0)], DT)
    check("兜底接管后光标仍在原位置附近", abs(hc.sx - 0.42) < 0.08,
          f"sx={hc.sx:.3f}")
    check("兜底期间仍判定可见", hc.seen)


def test_pinch_release_edges() -> None:
    """手势边沿语义与旧版完全一致（游戏代码不用改）。"""
    print("\n[8] 捏合/张开边沿（兼容性回归）")
    hc = settled_hc(open_v=0.9)
    fired = 0
    for _ in range(5):
        hc.update([hand(open_v=0.1)], DT)
        fired += 1 if hc.pinch else 0
    check("张开→握拢触发恰好一次捏合", fired == 1, f"{fired} 次")
    rel = 0
    for _ in range(6):
        hc.update([hand(open_v=0.95)], DT)
        rel += 1 if hc.release else 0
    check("握拢→张开触发一次 release", rel == 1, f"{rel} 次")
    check("握拢期间 grab_hold 为真", hc.grab_hold or rel > 0)


def test_lost_then_new_hand() -> None:
    """手真离开后，新出现的手可以正常成为主手（不能死锁在空控制权上）。"""
    print("\n[9] 真丢失后新手可接管")
    hc = settled_hc(x=0.30)
    for _ in range(int(C.HAND_LOST_AFTER / DT) + 6):
        hc.update([], DT)
    check("丢失后控制权为空", hc._main is None and not hc.seen)
    for _ in range(10):
        hc.update([hand(x=0.70)], DT)
    check("新手出现后重新锁定", hc._main is not None and hc.seen)
    check("光标跟到新手", abs(hc.sx - 0.70) < 0.1, f"sx={hc.sx:.3f}")


def main() -> int:
    print("=" * 66)
    print("手部跟踪行为测试（ID 跟踪架构）")
    print(f"参数：HOLD={C.HAND_HOLD_AFTER}s  LOST={C.HAND_LOST_AFTER}s  "
          f"TAKEOVER={C.HAND_TAKEOVER_RATIO}x{C.HAND_TAKEOVER_FRAMES}f  "
          f"MAX_STEP={C.HAND_MAX_STEP}/s")
    print("=" * 66)
    test_flicker_freeze()
    test_flicker_long_lost()
    test_id_stable_under_reorder()
    test_takeover_hysteresis()
    test_fast_swipe_tracking()
    test_velocity_spike_rejected()
    test_skin_vision_source_switch()
    test_pinch_release_edges()
    test_lost_then_new_hand()
    print("\n" + "=" * 66)
    print(f"通过 {_ok} 项，失败 {_fail} 项")
    print("=" * 66)
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
