#!/usr/bin/env python3
"""
输入层行为测试 —— 验证「没有识别到头的时候别乱动」。

这些全都是**可断言的行为**，不是感觉：

  · 短暂丢帧必须**冻结**输出（一点不变），不能衰减
  · 真正丢失必须**立即归零**，不能留"滑行"的尾巴
  · 检测闪烁时不能出现"往中间滑一下再弹回去"
  · 重新捕获那一帧的跳变必须受限（防假阳性把角色甩到一边）
  · 身体来源的动作键必须随身体识别状态门控（陈旧抬臂值不能一直按键）
  · 手部丢检后重新捕获，一直握着不能误触发捏合
  · 大厅的"停留自动进入"必须随识别状态清零

跑法：
    .venv/bin/python tools/test_input.py
"""
from __future__ import annotations

import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from core import config as C  # noqa: E402
from core.inputs import (BodyController, FaceState, GameInput, HandController,  # noqa: E402
                         HandState, HeadController)

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


def _calibrated_head(cx: float = 0.5, cy: float = 0.45) -> HeadController:
    """建一个已完成中性位校准的头部控制器。"""
    h = HeadController(C)
    for _ in range(C.CALIB_FRAMES + 2):
        h.update(FaceState(found=True, cx=cx, cy=cy), DT)
    assert not h.calibrating, "校准没完成"
    return h


def _face(cx: float, cy: float = 0.45) -> FaceState:
    return FaceState(found=True, cx=cx, cy=cy)


# =========================================================================== #
def test_hold_freezes_then_zeroes() -> None:
    print("\n[1] 短暂丢帧冻结 / 真正丢失立即归零")
    h = _calibrated_head()
    # 推到满速右移
    for _ in range(40):
        h.update(_face(0.72), DT)
    drift = h.axis
    check("已建立稳定的横向量", drift > 0.9, f"axis={drift:.3f}")

    # 丢帧 4 次（4/30 = 0.133s ≤ HOLD_AFTER=0.15）→ 必须完全冻结
    frozen = []
    for _ in range(4):
        h.update(FaceState(found=False), DT)
        frozen.append((h.axis, h.up, h.head_y, h.yaw, h.jump))
    check("丢帧 4 帧内输出**完全不变**（冻结）", abs(frozen[-1][0] - drift) < 1e-12,
          f"axis {drift:.4f} → {frozen[-1][0]:.4f}")
    check("冻结期间 found 仍为可用（避免丢失计时被闪烁清零）", h.tracking)

    # 第 5 帧越过 HOLD_AFTER → 必须立即归零，且**不是**衰减
    h.update(FaceState(found=False), DT)
    check("越过 HOLD_AFTER 后横向量立即为 0（无滑行）", h.axis == 0.0,
          f"axis={h.axis:.6f}")
    check("同帧动作键立即清零", h.jump is False)
    check("同帧 up / head_y / yaw 立即为 0",
          h.up == 0.0 and h.head_y == 0.0 and h.yaw == 0.0)
    check("状态转为不可用", not h.tracking)


def test_flicker_no_jitter() -> None:
    print("\n[2] 检测闪烁不得产生抖动")
    h = _calibrated_head()
    for _ in range(40):
        h.update(_face(0.72), DT)
    base = h.axis
    worst = 0.0
    for i in range(60):
        # 有 / 无 交替，模拟最常见的检测闪烁
        h.update(_face(0.72) if i % 2 == 0 else FaceState(found=False), DT)
        if i % 2 == 0:
            worst = max(worst, abs(h.axis - base))
    check("闪烁 60 帧后横向量偏移极小", worst < 0.02,
          f"最大偏移 {worst:.5f}（旧实现会衰减到 0 再弹回 ≈{base:.2f}）")


def test_reacquire_step_limited() -> None:
    print("\n[3] 重新捕获时的跳变受限")
    h = _calibrated_head()
    for _ in range(40):
        h.update(_face(0.28), DT)          # 先到最左（axis≈-1）
    for _ in range(8):
        h.update(FaceState(found=False), DT)   # 彻底丢失 → 归零
    check("丢失后已归零", h.axis == 0.0)

    h.update(_face(0.28), DT)              # 重新捕获，位置在最左
    lim = C.REACQ_STEP
    check("重新捕获那一帧跳变 ≤ REACQ_STEP", abs(h.axis) <= lim + 1e-9,
          f"axis={h.axis:.4f}（不限制约为 -0.36，限制后 ≤{-lim * 0.36:.4f}）")
    for _ in range(40):
        h.update(_face(0.28), DT)
    check("之后正常收敛到满速", h.axis < -0.9, f"axis={h.axis:.3f}")


def test_body_action_gated() -> None:
    print("\n[4] 身体来源的动作键必须随识别状态门控")
    inp = GameInput()
    inp.arm_l, inp.arm_r, inp.hands_up = 0.95, 0.95, 2
    inp.body_found = False
    check("body_found=False 时抬起的手臂不产生动作键",
          not inp.action and not inp.action_l and not inp.action_r
          and not inp.arms_wide and not inp.crouching)
    inp.body_found = True
    check("body_found=True 时抬臂产生动作键",
          inp.action and inp.action_l and inp.action_r and inp.arms_wide)

    # 身体控制器：丢帧冻结、真丢归零
    b = BodyController(C)

    class _Center:
        ok = True
        x = 0.5

    class _P:
        found = True
        scale = 0.25
        crouch = 0.0
        torso_lean = 0.0
        body_center = _Center

        def lower_body_visible(self):
            return False

        def arm_raised(self, side):
            return 0.9

        def arm_extended(self, side):
            return 0.0

        def hands_up(self):
            return 1

    p = _P()
    for _ in range(C.CALIB_FRAMES + 2):
        b.update(p, DT)
    b.update(p, DT)
    check("身体动作量已建立", b.arm_l > 0.5, f"arm_l={b.arm_l:.3f}")
    for _ in range(4):
        b.update(None, DT)
    check("身体丢帧 4 帧内冻结", b.arm_l > 0.5 and b.tracking, f"arm_l={b.arm_l:.3f}")
    b.update(None, DT)
    check("身体真丢失后立即归零且状态不可用",
          b.arm_l == 0.0 and b.hands_up == 0 and not b.tracking)


def test_hand_pinch_needs_arm() -> None:
    print("\n[5] 手部重新捕获不得凭空捏合")
    hc = HandController(C)

    def hand(op: float) -> HandState:
        return HandState(found=True, x=0.5, y=0.5, open=op, area=0.05, span=0.2)

    # 正常流程：张开 → 握拢，必须触发一次捏合
    for _ in range(6):
        hc.update([hand(0.9)], DT)
    fired = 0
    for _ in range(4):
        hc.update([hand(0.1)], DT)
        fired += 1 if hc.pinch else 0
    check("正常「张开→握拢」触发一次捏合", fired == 1, f"触发 {fired} 次")

    # 手离开超过 HAND_LOST_AFTER
    for _ in range(int(C.HAND_LOST_AFTER / DT) + 4):
        hc.update([], DT)
    check("手离开后状态已解除", not hc.seen)
    # 重新捕获一只**一直握着**的手：不应触发捏合
    fired2 = 0
    for _ in range(20):
        hc.update([hand(0.1)], DT)
        fired2 += 1 if hc.pinch else 0
    check("重新捕获一直握着的手不误触发", fired2 == 0, f"误触发 {fired2} 次")


def test_menu_dwell_gated() -> None:
    print("\n[6] 大厅「停留自动进入」必须随识别状态清零")
    pygame.init()
    pygame.display.set_mode((320, 240))
    import games  # noqa: F401  导入即注册
    from core.menu import Menu

    m = Menu({"cam_ok": True, "hand_ok": True, "backend": "test",
              "hand_backend": "-", "fps": 60.0, "track": "lost"})

    # 没识别到头：跑满 3 倍 MENU_DWELL，绝不能自己进游戏
    dead = GameInput()
    dead.found = False
    for _ in range(int(C.MENU_DWELL * 3 / DT)):
        m.update(DT, dead)
    check("未识别到头时不会自动进入游戏", m.chosen is None, f"chosen={m.chosen!r}")
    check("未识别到头时停留计时被清零", m.dwell == 0.0, f"dwell={m.dwell:.2f}")

    # 没识别到头但抬头信号为真（假阳性）：也不能进
    fake = GameInput()
    fake.found = False
    fake.jump = True
    for _ in range(240):
        m.update(DT, fake)
    check("未识别到头时的假抬头信号不会误进入", m.chosen is None,
          f"chosen={m.chosen!r}")

    # 正常识别且停留够久 → 应当自动进入（原有演示便利保留）
    live = GameInput()
    live.found = True
    for _ in range(int((C.MENU_DWELL + 1.0) / DT)):
        m.update(DT, live)
    check("稳定识别 + 停留够久仍会自动进入（演示便利保留）",
          m.chosen is not None, f"chosen={m.chosen!r}")



def test_config_refs() -> None:
    """
    静态检查：代码里引用的配置项是否真的存在。

    这一项是刚才那个真 bug 逼出来的 —— `HandController` 里写着
    `C.SMOOTH_TAU`，但改名成 HAND_TAU 时漏了这一处。它只在"检测到手"
    这条分支上才会执行，所以一直没暴露：**一检测到手就崩**。
    这类引用错误静态就能查出来，不该等运行到才发现。
    """
    print("\n[7] 静态检查：配置项引用是否都存在")
    import pathlib
    import re
    from core import config as cfg

    root = pathlib.Path(__file__).resolve().parent.parent
    pat = re.compile(r"\b(?:C|cfg)\.([A-Z][A-Z0-9_]*)\b")
    missing = []
    total = 0
    for d in ("core", "games"):
        for f in sorted((root / d).rglob("*.py")):
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                for name in pat.findall(line):
                    total += 1
                    if not hasattr(cfg, name):
                        missing.append(f"{f.relative_to(root)}:{i} {name}")
    check(f"全部 {total} 处配置项引用都能在 config 找到", not missing,
          "  ".join(missing[:6]) if missing else "")


def main() -> int:
    print("=" * 68)
    print("输入层行为测试 · 「没有识别到头的时候别乱动」")
    print(f"参数：HOLD_AFTER={C.HOLD_AFTER}s  REACQ_STEP={C.REACQ_STEP}  "
          f"LOST_PAUSE_AFTER={C.LOST_PAUSE_AFTER}s  dt={DT:.4f}s")
    print("=" * 68)
    test_hold_freezes_then_zeroes()
    test_flicker_no_jitter()
    test_reacquire_step_limited()
    test_body_action_gated()
    test_hand_pinch_needs_arm()
    test_menu_dwell_gated()
    test_config_refs()
    print("\n" + "=" * 68)
    print(f"结果：{_ok} 通过 / {_fail} 失败")
    print("=" * 68)
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
