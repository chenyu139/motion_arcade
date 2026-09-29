#!/usr/bin/env python3
"""
视觉鲁棒性测试 —— 多人目标稳定 / 置信度过滤 / 光照自适应。

背景（用户第一点要求里的三个具体场景）
------------------------------------
  · 多人场景      → 原来是"每帧取面积最大的框"，多个人时目标会来回跳
  · 部分遮挡      → 短暂丢失后应当立刻认回同一个人，而不是重走一遍完整丢失流程
  · 暗光 / 逆光    → 检测器对光照很敏感，需要在**检测之前**把画面规整好

这三条都做成可断言的测试：它们不像"灵敏度"那样需要真机手感，
是能确定性验证的。**黑箱改不动这些** —— 例如把 selector 换成"取最大"，
第 1、3 条会立刻失败。

跑法：
    .venv/bin/python tools/test_vision.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np

from core import config as C                                    # noqa: E402
from core.inputs import FaceState, HeadController               # noqa: E402
from core.tracker import (FaceTargetSelector, IlluminationGuard,  # noqa: E402
                          _face_score)

DT = 1.0 / 30.0
W, H = 320, 240
_ok = 0
_fail = 0


def face(cx=0.5, cy=0.5, w=0.20, h=0.26, yaw=0.0, pitch=0.0,
         pose_ok=True, score=1.0):
    """构造一帧人脸结果（含新的置信度字段）。"""
    return FaceState(found=True, cx=cx, cy=cy, w=w, h=h, yaw=yaw, pitch=pitch,
                     pose_ok=pose_ok, score=score)


def calibrated(**kw) -> HeadController:
    hc = HeadController(C)
    for _ in range(C.CALIB_FRAMES + 2):
        hc.update(face(**kw), DT)
    return hc


def check(name: str, cond: bool, detail: str = "") -> None:
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  ✓ {name}")
    else:
        _fail += 1
        print(f"  ✗ {name}   {detail}")


def cand(x: float, y: float, bw: float, bh: float, score: float = 0.9):
    """
    构造一行 YuNet 输出（15 列：x,y,w,h + 5 个关键点×2 + 置信度）。

    之所以不 mock 整个检测器：要验的是**候选到决策**这一段，
    检测器内部的 numpy 行为本来就是确定的，mock 它只会把测试变脆。
    """
    row = np.zeros(15, dtype=np.float32)
    row[0], row[1], row[2], row[3] = x, y, bw, bh
    row[14] = score
    return row


# --------------------------------------------------------------------------- #
def test_multi_face_stability() -> None:
    """
    两个人的脸框面积此消彼长（另一个人小幅度前后移动），
    旧实现每帧取最大 —— 目标就会在两人之间被来回甩。
    """
    print("\n[1] 多人同框：主目标不得被来回抢走")
    sel = FaceTargetSelector()
    me = cand(60, 60, 90, 110)
    picks = []
    for i in range(120):
        # 另一个人的框在 ±6% 之间来回 — 足以让"取最大"每隔几帧就翻一次
        wob = 1.0 + 0.06 * np.sin(i / 3.0)
        other = cand(180, 60, 88 * wob, 108 * wob)
        picks.append(sel.pick([me, other], W, H))
    changes = sum(1 for a, b in zip(picks, picks[1:]) if a != b)
    print(f"      120 帧 → 目标切换 {changes} 次（旧实现会 >10 次）")
    check("主目标保持稳定（切换 ≤ 1 次）", changes <= 1, f"{changes} 次")
    check("主目标锁在原来的玩家上（下标 0）", picks[-1] == 0, f"最后选中 {picks[-1]}")


def test_clear_takeover() -> None:
    """但也不能僵住：有人明显坐到镜头前来，必须允许接管。"""
    print("\n[2] 明显更近的人要能接管（不能僵死在旧目标上）")
    sel = FaceTargetSelector()
    sel.pick([cand(60, 60, 70, 86)], W, H)
    nearer = cand(140, 60, 150, 180)
    idx = 0
    for _ in range(30):
        idx = sel.pick([cand(60, 60, 70, 86), nearer], W, H)
    print(f"      30 帧后选中下标 {idx}（1 = 新人）")
    check("明显更大的人最终接管", idx == 1, f"idx={idx}")


def test_occlusion_recall() -> None:
    """
    手挡脸 / 低头这类**短暂遮挡**之后，要立刻认回同一个人。

    关键点：检测器输出的候选顺序是不稳定的（换 cv2 版本、框数量变化都会变），
    所以这里刻意把候选顺序**交换**后再喂回去 —— 如果只记下标就会选错人。
    """
    print("\n[3] 短暂遮挡（5 帧）后要认回同一人，且不受候选顺序影响")
    sel = FaceTargetSelector()
    me = cand(60, 60, 90, 110)
    other = cand(200, 60, 80, 100)
    sel.pick([me, other], W, H)
    for _ in range(5):
        sel.note_missing()
    idx = sel.pick([other, me], W, H)            # 顺序与第一次相反
    print(f"      候选顺序交换后选中下标 {idx}（下标 1 = 原来的人）")
    check("按位置连续性认回原来的人", idx == 1, f"idx={idx}")


def test_missing_expiry() -> None:
    """丢失太久不能永远记着旧目标 —— 换人了要能重新初始化，否则会再次追错人。"""
    print("\n[4] 丢失超过记忆窗口后要清空记忆")
    sel = FaceTargetSelector()
    sel.pick([cand(60, 60, 90, 110)], W, H)
    for _ in range(C.FACE_TRACK_MISS + 5):
        sel.note_missing()
    check("超时后记忆被清空（不再锁死旧坐标）", sel._cx is None,
          f"cx={sel._cx}")


def test_score_filter() -> None:
    """检测置信度：低分框必须被过滤，且取值失败时安全降级而不是全丢。"""
    print("\n[5] 置信度过滤与安全降级")
    good = cand(60, 60, 90, 110, 0.92)
    bad = cand(60, 60, 200, 240, 0.31)
    keep = [f for f in (good, bad) if _face_score(f) >= C.FACE_MIN_SCORE]
    check("低分框被过滤", len(keep) == 1, f"剩 {len(keep)} 个")

    short = np.zeros(10, dtype=np.float32)       # 列数不足（模型/版本差异）
    check("列数异常时不崩且降级为 1.0", abs(_face_score(short) - 1.0) < 1e-6)
    nan_row = cand(60, 60, 90, 110, float("nan"))
    check("NaN 分数同样降级为 1.0", abs(_face_score(nan_row) - 1.0) < 1e-6)
    # 关键：降级方向必须是"少一层过滤"，绝不能变成"丢掉所有候选"
    check("降级后候选不会被误杀（1.0 ≥ 阈值）", _face_score(short) >= C.FACE_MIN_SCORE)


def test_illumination() -> None:
    """暗光要被提亮、低对比要被增强；正常光照下一帧都不许多动。"""
    print("\n[6] 光照自适应")

    def gray(im):
        return cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)

    # ---- 暗光 ----
    rng = np.random.default_rng(7)
    dark = np.clip(rng.normal(38, 8, (H, W, 3)), 0, 255).astype(np.uint8)
    g = IlluminationGuard()
    out, mode = g.ensure(dark)
    m1, m2 = float(gray(dark).mean()), float(gray(out).mean())
    s1, s2 = float(gray(dark).std()), float(gray(out).std())
    print(f"      暗图     mode={mode}  亮度 {m1:.0f}→{m2:.0f}  对比 {s1:.1f}→{s2:.1f}")
    check("暗光被正确识别", mode == "dark", f"mode={mode}")
    check("亮度被提亮", m2 > m1 + 5, f"{m1:.0f}→{m2:.0f}")
    check("局部对比被增强", s2 > s1, f"{s1:.1f}→{s2:.1f}")

    # ---- 正常光照：必须完全不动手 ----
    normal = np.clip(rng.normal(140, 55, (H, W, 3)), 0, 255).astype(np.uint8)
    g2 = IlluminationGuard()
    out2, mode2 = g2.ensure(normal)
    std = float(gray(normal).std())
    print(f"      正常光   mode={mode2}  对比 {std:.1f}")
    check("正常光照判定为 normal", mode2 == "normal", f"mode={mode2}")
    check("正常光照画面未被改动", np.array_equal(out2, normal))


def test_illum_hysteresis() -> None:
    """
    迟滞：判定之后必须锁定一段时间。

    否则每帧独立判断时，刚好卡在阈值附近的画面会呈现出
    "亮一帧暗一帧"的周期性闪烁 —— 那比不增强更难看。
    """
    print("\n[7] 光照判定必须带迟滞（不逐帧翻转）")
    g = IlluminationGuard()
    rng = np.random.default_rng(11)
    dark = np.clip(rng.normal(38, 8, (H, W, 3)), 0, 255).astype(np.uint8)
    # mid 是"光照恢复正常"的画面：对比度必须明显回到正常区间（std > 阈值），
    # 否则它自己也会被判成 flat —— 那样测出来的不是迟滞，是"一直都在增强"。
    mid = np.clip(rng.normal(130, 60, (H, W, 3)), 0, 255).astype(np.uint8)
    g.ensure(dark)                                   # 触发增强
    modes = [g.ensure(mid)[1] for _ in range(C.ILLUM_HYST_FRAMES - 2)]
    still = all("normal" not in m for m in modes)
    check("迟滞窗口内保持增强状态", still, f"modes={set(modes)}")
    # 窗口走完之后应当能退出
    modes2 = [g.ensure(mid)[1] for _ in range(6)]
    check("迟滞结束后能退出增强", any("normal" in m for m in modes2),
          f"modes={set(modes2)}")


# --------------------------------------------------------------------------- #
# 识别质量与降级
# --------------------------------------------------------------------------- #
def test_quality_grading() -> None:
    """正常/太远/低置信/角度过大要能被正确分级，并给出可读提示。"""
    print("\n[8] 识别质量分级与提示")
    hc = calibrated()
    check("正常状态为 good", hc.quality == "good", f"{hc.quality}")
    check("good 时无提示", hc.game_input().hint == "", f"'{hc.game_input().hint}'")

    hc2 = calibrated(w=0.05, h=0.07)
    for _ in range(int(1.0 / DT)):
        hc2.update(face(w=0.05, h=0.07), DT)
    print(f"      脸宽 0.05 → quality={hc2.quality}  提示='{hc2.game_input().hint}'")
    check("脸太小判为 far", hc2.quality == "far", f"{hc2.quality}")
    check("far 给出具体建议（而非笼统的'未识别'）", bool(hc2.game_input().hint))

    hc3 = calibrated()
    for _ in range(int(1.0 / DT)):
        hc3.update(face(score=0.30), DT)
    print(f"      置信度 0.30 → quality={hc3.quality}")
    check("低置信判为 poor", hc3.quality == "poor", f"{hc3.quality}")

    hc4 = calibrated()
    for _ in range(int(1.0 / DT)):
        hc4.update(face(yaw=1.0, pitch=0.0), DT)
    check("角度过大判为 angle", hc4.quality == "angle", f"{hc4.quality}")


def test_quality_hysteresis() -> None:
    """
    变差要快、恢复要慢。

    两个方向用同一个时长的话，会在边界上反复横跳 —— 屏幕上的提示
    会跟着闪，而玩家其实中间并没有"断过"。恢复更慢是刻意的。
    """
    print("\n[9] 质量判定迟滞：变差快、恢复慢")
    hc = calibrated()
    n_short = int(C.QUALITY_POOR_T * 0.5 / DT)     # 还没到升级所需时长
    for _ in range(n_short):
        hc.update(face(score=0.30), DT)
    still = hc.quality
    for _ in range(int(C.QUALITY_POOR_T / DT)):     # 超过所需时长
        hc.update(face(score=0.30), DT)
    went = hc.quality
    print(f"      {C.QUALITY_POOR_T * 0.5:.2f}s → {still}   "
          f"{C.QUALITY_POOR_T * 1.5:.2f}s → {went}")
    check("短时间内不急着降级（不全抖闪）", still == "good", f"{still}")
    check("持续恶化后才降级", went == "poor", f"{went}")

    # 恢复：必须更久
    n_part = int(C.QUALITY_RECOVER_T * 0.6 / DT)
    for _ in range(n_part):
        hc.update(face(), DT)
    check("恢复需要更长时间（不立刻回 good）", hc.quality == "poor", f"{hc.quality}")
    for _ in range(int(C.QUALITY_RECOVER_T / DT)):
        hc.update(face(), DT)
    check("稳定足够久后恢复 good", hc.quality == "good", f"{hc.quality}")


def test_poor_suppresses_jump() -> None:
    """
    质量很差时**不再接受新的动作键触发** —— 这是唯一会改行为的降级。

    误触发跳跃是体感里最糟的失败（角色自己跑了，"没抬头却跳了"），
    而"暂时不响应"远比"乱响应"安全。已经按住的不受影响。
    """
    print("\n[10] 质量差时抑制新的动作键触发")
    hc = calibrated()
    for _ in range(int(1.0 / DT)):
        hc.update(face(score=0.30), DT)
    check("已进入 poor", hc.quality == "poor", f"{hc.quality}")
    for _ in range(int(1.0 / DT)):
        hc.update(face(score=0.30, pitch=0.60), DT)      # 大幅抬头
    check("poor 期间抬头不得触发动作键", not hc.jump, "误触发")

    # 恢复之后必须能正常玩（降级不能变成永久禁用）
    for _ in range(int(C.QUALITY_RECOVER_T / DT) + 10):
        hc.update(face(), DT)
    check("恢复后回到 good", hc.quality == "good", f"{hc.quality}")
    for _ in range(int(1.0 / DT)):
        hc.update(face(pitch=0.60), DT)
    check("恢复后动作键恢复正常", hc.jump, "仍不能触发（降级没解除）")

    # 反向断言：far（坐得远）不应禁用操作 —— 那样会让游戏"突然不能玩"
    hc2 = calibrated(w=0.05, h=0.07)
    for _ in range(int(1.2 / DT)):
        hc2.update(face(w=0.05, h=0.07, pitch=0.60), DT)
    check("far 只提示、不禁用动作键", hc2.jump, "被误禁用了")


def _boom():                       # 取不到屏幕信息（某些无头/虚拟环境）
    raise RuntimeError("no display")


def test_window_size_adaptive() -> None:
    """
    多分辨率自适应：窗口模式必须按屏幕可用空间挑尺寸。

    这条不改设计坐标系（所有游戏都用 1920×1080 绝对坐标），
    验的是"实际窗口装不装得下、会不会把画面拉变形"。
    """
    print("\n[11] 窗口尺寸自适应（小屏不溢出 / 大屏用原生 / 恒定 16:9）")
    import pygame

    from core.shell import Shell

    if pygame.display.get_surface() is None:
        pygame.display.set_mode((320, 240))
    shell = Shell.__new__(Shell)            # 绕开 __init__：这里只测这个纯计算
    ar = C.DESIGN_W / float(C.DESIGN_H)
    orig = pygame.display.Info

    class _Info:
        def __init__(self, w: int, h: int) -> None:
            self.current_w, self.current_h = w, h

    try:
        for tag, sw, sh in (("小屏", 1366, 768), ("笔记本", 1440, 900),
                            ("4K", 3840, 2160)):
            pygame.display.Info = lambda w=sw, h=sh: _Info(w, h)   # noqa: B023
            w_, h_ = shell._available_window_size()
            aw, ah = int(sw * 0.92), int(sh * 0.86)
            native = (w_, h_) == (C.DESIGN_W, C.DESIGN_H)
            fit = native or (w_ <= aw + 1 and h_ <= ah + 1)
            print(f"      {tag:4s} 屏幕 {sw}×{sh} → 窗口 {w_}×{h_}"
                  f"（可用 {aw}×{ah}）")
            check(f"{tag} 窗口不超出可用空间", fit, f"{w_}×{h_}")
            check(f"{tag} 保持 16:9 不变形", abs(w_ / h_ - ar) < 0.01,
                  f"ar={w_ / h_:.3f}")
        pygame.display.Info = lambda: _Info(3840, 2160)           # noqa: B023
        check("屏幕够大时直接用原生 1920×1080",
              shell._available_window_size() == (C.DESIGN_W, C.DESIGN_H))
    finally:
        pygame.display.Info = orig

    pygame.display.Info = _boom
    try:
        check("取不到屏幕信息时安全回退到设计尺寸",
              shell._available_window_size() == (C.DESIGN_W, C.DESIGN_H))
    finally:
        pygame.display.Info = orig


def main() -> int:
    print("=" * 66)
    print("视觉鲁棒性测试（多人 / 遮挡 / 光照 / 置信度）")
    print("=" * 66)
    test_multi_face_stability()
    test_clear_takeover()
    test_occlusion_recall()
    test_missing_expiry()
    test_score_filter()
    test_illumination()
    test_illum_hysteresis()
    test_quality_grading()
    test_quality_hysteresis()
    test_poor_suppresses_jump()
    test_window_size_adaptive()
    print("\n" + "=" * 66)
    print(f"通过 {_ok} 项，失败 {_fail} 项")
    print("=" * 66)
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
