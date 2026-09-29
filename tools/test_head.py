#!/usr/bin/env python3
"""
头部控制行为测试 —— 验证「左右摇头 / 抬头」的映射是否正确。

背景：用户反馈"左右摇头和抬头经常识别错误"。查出三个设计层面的根因
（不是调参问题），这里每一条都配一个**可断言的测试**锁住：

  1. 控制量曾用「画面比例」作单位 → 灵敏度随坐姿远近翻倍变化
     → 测试「同一物理位移，远近距离下输出一致」
  2. 摇头（yaw）曾完全没进横向控制 → 转头时角色不动
     → 测试「脸框中心不动、只摇头，也要产生轴量」
  3. 抬头曾只看脸框中心位移 → 往后靠 / 耸肩 / 坐姿下滑都会误触发动作键
     → 测试「只改变纵向位移、俯仰不变时，动作键不得触发」
  4. 姿态量在侧脸时退化，却仍被当作有效读数
     → 测试「姿态不可信时退回位移路径，不产生虚假转向」

另外测试纯函数的几何不变量：歪头（roll）不得污染 yaw / pitch 读数。

跑法：
    .venv/bin/python tools/test_head.py
"""
from __future__ import annotations

import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from core import config as C            # noqa: E402
from core.inputs import FaceState, HeadController   # noqa: E402

DT = 1.0 / 30.0
_ok = 0
_fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  ✓ {name}")
    else:
        _fail += 1
        print(f"  ✗ {name}   {detail}")


def face(cx=0.5, cy=0.5, w=0.20, h=0.26, yaw=0.0, pitch=0.0, pose_ok=True):
    """构造一帧人脸结果。cx/cy/w/h 都是归一化画面坐标。"""
    return FaceState(found=True, cx=cx, cy=cy, w=w, h=h,
                     yaw=yaw, pitch=pitch, pose_ok=pose_ok)


def calibrated(**kw) -> HeadController:
    """跑完校准，返回一个处于 TRACKING 的控制器。"""
    hc = HeadController(C)
    for _ in range(C.CALIB_FRAMES + 2):
        hc.update(face(**kw), DT)
    return hc


def settle(hc: HeadController, f, n=60):
    for _ in range(n):
        hc.update(f, DT)
    return hc


# --------------------------------------------------------------------------- #
def test_distance_invariance() -> None:
    """
    单位必须是「人脸尺度」而不是「画面比例」。

    同一句"把头挪一个脸宽"，在坐得很近（脸宽 0.30）和坐得很远（脸宽 0.12）
    时，输出必须一致。旧实现在这两种情况下输出的差距是数倍 ——
    这就是"有时太灵、有时推不动"。
    """
    print("\n[1] 平移灵敏度必须与坐姿距离无关")
    out = {}
    for tag, fw in (("近", 0.30), ("中", 0.20), ("远", 0.12)):
        hc = calibrated(w=fw, h=fw * 1.3)
        # 平移 0.8 个脸宽
        hc = settle(hc, face(cx=0.5 + 0.8 * fw, w=fw, h=fw * 1.3), 90)
        out[tag] = hc.axis
    spread = max(out.values()) - min(out.values())
    print(f"      近={out['近']:+.3f}  中={out['中']:+.3f}  远={out['远']:+.3f}")
    check("三种距离下输出一致（极差 < 0.03）", spread < 0.03, f"极差 {spread:.3f}")
    check("0.8 个脸宽已被识别（不落入死区）", min(out.values()) > 0.15,
          f"最小输出 {min(out.values()):.3f}")


def _axis_for_yaw(y: float) -> float:
    hc = calibrated()
    hc = settle(hc, face(cx=0.5, yaw=y), 120)
    return hc.axis


def _axis_peak(y: float, secs: float = 0.5) -> float:
    """
    **瞬时**转头（持续 secs 秒）里 |axis| 的峰值。

    为什么还要这个：持续转头会被中性位自适应吸收（见下文），
    所以 `_axis_for_yaw` 那种"settle 120 帧"只能反映稳态。
    而玩家在游戏/大厅里的转头都是短促的（0.2~0.6 秒），
    手感由这段瞬态决定 —— 灵敏度回归必须测这一段。
    """
    hc = calibrated()
    peak = 0.0
    for _ in range(int(secs / DT)):
        hc.update(face(cx=0.5, yaw=y), DT)
        peak = max(peak, abs(hc.axis))
    return peak


def test_yaw_controls_axis() -> None:
    """
    摇头必须能控制横向 —— 转头时脸框中心几乎不动。

    同时锁住**灵敏度标定**。真机实测第一版的教训：阈值拍小了
    （满速 0.50 ≈ 转头 12°），轻轻一偏头轴量就打到 -0.98。
    "太灵"和"不灵"一样会被用户感知成"识别错误"，所以三个档位都要断言：
        微动（≈6° 以内）→ 不产生输出
        自然转头        → 产生明显但不饱和的输出
        大幅转头        → 接近满速

    上界（原 0.75）在用户两次反馈"灵敏度不够"之后**有意放宽到 0.85**。
    放宽的依据是"死区没动"：噪声地板一点没变（微动仍为 0.000），
    饱和点仍在 25° 附近，而 12° 的瞬时输出只有 0.25 —— 
    离第一版"12° 就打满 0.98"的病态还差得远，所以这条放宽是安全的。
    """
    print("\n[2] 只摇头（脸框中心不动）也要产生横向控制量，且灵敏度要合理")
    small = _axis_for_yaw(0.16)          # ≈ 4.3°，呼吸/说话级别的微动
    mid = _axis_for_yaw(0.70)            # ≈ 19°，舒适的自然转头
    big = _axis_for_yaw(1.40)            # ≈ 41°，大幅转头
    flick12 = _axis_peak(0.44, 0.5)      # ≈ 12°，短促一偏
    print(f"      yaw 0.16(≈4°) → {small:+.3f}")
    print(f"      yaw 0.70(≈19°) → {mid:+.3f}")
    print(f"      yaw 1.40(≈41°) → {big:+.3f}")
    print(f"      yaw 0.44(≈12°) 甩 0.5 秒 → 峰值 {flick12:+.3f}")
    check("微动被死区挡住（< 0.05）", abs(small) < 0.05, f"{small:+.3f}")
    check("自然转头有明显输出（0.35~0.85）", 0.35 < mid < 0.85, f"{mid:+.3f}")
    check("12° 的短促偏头不得打满（< 0.55）", flick12 < 0.55, f"{flick12:+.3f}")

    check("大幅转头接近满速（> 0.85）", big > 0.85, f"{big:+.3f}")
    check("方向相反", _axis_for_yaw(-0.70) < -0.35, f"{_axis_for_yaw(-0.70):+.3f}")

    hc3 = calibrated()
    hc3 = settle(hc3, face(cx=0.5, yaw=0.0), 90)
    check("正脸不动时轴量为零", abs(hc3.axis) < 1e-6, f"axis={hc3.axis:.4f}")


def test_move_controls_axis() -> None:
    """平移也要能控制横向（不能因为加了摇头把原来的一路弄丢）。"""
    print("\n[3] 平移仍要能控制横向")
    for fw in (0.30, 0.12):
        hc = calibrated(w=fw, h=fw * 1.3)
        hc = settle(hc, face(cx=0.5 + 1.0 * fw, w=fw, h=fw * 1.3), 90)
        print(f"      脸宽 {fw} 平移 1.0 脸宽 → axis={hc.axis:+.3f}")
        check(f"脸宽 {fw} 时平移产生轴量（> 0.5）", hc.axis > 0.5,
              f"axis={hc.axis:+.3f}")


def test_pitch_triggers_action() -> None:
    """抬头必须触发动作键（俯仰是主信号）。"""
    print("\n[4] 抬头触发动作键")
    hc = calibrated()
    hc = settle(hc, face(pitch=0.42), 20)
    print(f"      pitch=0.42 → up={hc.up:.2f} jump={hc.jump}")
    check("抬头后动作键按下", hc.jump)
    check("连续 up 量明显抬升（> 0.5）", hc.up > 0.5, f"up={hc.up:.3f}")

    hc2 = calibrated()
    hc2 = settle(hc2, face(pitch=0.0), 40)
    check("不抬头时动作键关闭", not hc2.jump)

    hc3 = calibrated()
    hc3 = settle(hc3, face(pitch=-0.35), 40)
    print(f"      低头 pitch=-0.35 → up={hc3.up:.2f} jump={hc3.jump}")
    check("低头不触发动作键", not hc3.jump)


def test_no_false_jump_on_lean_back() -> None:
    """
    **这条是用户抱怨的核心。**

    往后靠 / 坐姿下滑 / 耸肩 → 脸框中心纵向移动，但头部俯仰没变。
    旧实现只看位移，于是会误触发动作键（"没抬头也跳了"）。
    现在动作键只认俯仰，位移不得触发它。
    """
    print("\n[5] 只往后靠（俯仰不变）不得触发动作键")
    for tag, dy in (("缓慢下滑", 0.06), ("明显后靠", 0.13)):
        hc = calibrated()
        # cy 下移 = 后靠/下滑（画面里脸变低），pitch 保持 0
        hc = settle(hc, face(cy=0.5 + dy, pitch=0.0), 60)
        print(f"      {tag}：cy +{dy} → up={hc.up:.2f} jump={hc.jump}")
        check(f"{tag} 不触发动作键", not hc.jump, "误触发")
    check("后靠时轴量仍为零（不该横向乱动）",
          abs(hc.axis) < 1e-6, f"axis={hc.axis:.4f}")


def test_jump_hysteresis() -> None:
    """
    阈值附近抖动时不能连发。

    真实俯仰读数抖动幅度约 ±0.05，正好落在阈值上 ——
    裸阈值会让一次抬头连发好几下。迟滞 + 最短按住/松开时长解决它。
    """
    print("\n[6] 阈值抖动不得连发动作键")
    hc = calibrated()
    fires = 0
    prev = False
    for i in range(90):
        p = 0.40 + 0.07 * (1 if i % 2 else -1)      # 在阈值上下抖
        hc.update(face(pitch=p), DT)
        if hc.jump and not prev:
            fires += 1
        prev = hc.jump
    print(f"      抖动 90 帧（3 秒）→ 触发 {fires} 次")
    check("最多只触发一次", fires <= 1, f"触发了 {fires} 次")

    # 真实的"抬头 → 保持 → 放下"必须只触发一次
    hc2 = calibrated()
    fires2 = 0
    prev2 = False
    seq = [0.0] * 10 + [0.55] * 45 + [0.0] * 30
    for p in seq:
        hc2.update(face(pitch=p), DT)
        if hc2.jump and not prev2:
            fires2 += 1
        prev2 = hc2.jump
    print(f"      一次完整抬头 → 触发 {fires2} 次")
    check("一次完整抬头恰好触发一次", fires2 == 1, f"触发了 {fires2} 次")


def test_scale_jump_guard() -> None:
    """检测跳变（脸框突然收缩）在尺度归一化后会被放大，必须挡住。"""
    print("\n[7] 脸框尺度骤变不得把轴量甩出去")
    hc = calibrated(w=0.20)
    hc = settle(hc, face(w=0.20), 30)
    before = hc.axis
    for _ in range(3):
        hc.update(face(cx=0.95, w=0.09, h=0.12), DT)      # 框缩到一半、中心跳到边上
    print(f"      axis {before:+.3f} → {hc.axis:+.3f}")
    check("轴量没有跳变（变化 < 0.12）", abs(hc.axis - before) < 0.12,
          f"变化 {abs(hc.axis - before):.3f}")


def test_neutral_drift_absorbed() -> None:
    """
    坐姿缓慢漂移必须被中性位吸收。

    否则人往后靠 20 秒，脸框中心持续偏移会被当成"一直抬着头"：
    动作键常亮、角色一直在动。自适应只在接近中性时生效。
    """
    print("\n[8] 缓慢坐姿漂移要被中性位吸收")
    hc = calibrated()
    # 6 秒内缓慢下移 0.05（真实的后靠/下滑）
    for i in range(180):
        k = i / 179.0
        hc.update(face(cy=0.5 + 0.05 * k, pitch=-0.05 * k), DT)
    print(f"      6 秒漂移后 → axis={hc.axis:+.3f} up={hc.up:.2f} jump={hc.jump}")
    check("漂移后轴量仍在零附近（< 0.10）", abs(hc.axis) < 0.10,
          f"axis={hc.axis:+.3f}")
    check("漂移后动作键未常亮", not hc.jump)


def test_hold_behavior_intact() -> None:
    """改动不能破坏上一轮的失检语义（短暂丢帧冻结、真丢失归零）。"""
    print("\n[9] 失检语义仍须保持（回归）")
    hc = calibrated()
    hc = settle(hc, face(cx=0.62, yaw=0.3), 60)
    held = (hc.axis, hc.up)
    for _ in range(3):
        hc.update(FaceState(found=False), DT)
    check("丢 3 帧内输出冻结不变",
          abs(hc.axis - held[0]) < 1e-12 and abs(hc.up - held[1]) < 1e-12,
          f"{hc.axis:.5f} vs {held[0]:.5f}")
    for _ in range(30):
        hc.update(FaceState(found=False), DT)
    check("真丢失后立即归零",
          hc.axis == 0.0 and hc.up == 0.0 and hc.jump is False)


def test_pose_gate() -> None:
    """姿态不可信（侧脸退化）时不得产生虚假转向，且要退回位移路径。"""
    print("\n[10] 姿态不可信时的降级行为")
    hc = calibrated()
    # pose_ok=False 但 yaw 读数很夸张（侧脸时典型）
    hc = settle(hc, face(cx=0.5, yaw=0.95, pose_ok=False), 60)
    print(f"      侧脸 pose_ok=False, yaw=0.95 → axis={hc.axis:+.3f}")
    check("姿态不可信时摇头读数被忽略（轴量 < 0.05）", abs(hc.axis) < 0.05,
          f"axis={hc.axis:+.3f}")

    hc2 = calibrated()
    hc2 = settle(hc2, face(pitch=0.0, pose_ok=False), 10)
    check("姿态不可信时不会凭空按下动作键", not hc2.jump)

    hc3 = calibrated()
    fw = 0.20
    hc3 = settle(hc3, face(cx=0.5 + fw, pose_ok=False), 90)
    print(f"      姿态不可信但平移 1 个脸宽 → axis={hc3.axis:+.3f}")
    check("姿态不可信时位移路径仍然工作", hc3.axis > 0.4, f"axis={hc3.axis:+.3f}")


def test_geometry_roll_invariance() -> None:
    """
    纯几何不变量：把整张脸的 5 个关键点**整体旋转**（歪头），
    yaw / pitch 的读数应当基本不变。

    旧版 yaw 用 `|鼻尖−左眼| − |鼻尖−右眼|`，歪头时两个距离同时变化，
    读数会出现明显漂移 —— 而歪头在真实使用里几乎每帧都在发生。
    """
    print("\n[11] 歪头（roll）不得污染 yaw / pitch")
    from core.tracker import FaceBackendYuNet as B

    # 构造一张正脸的关键点（单位：像素，脸宽 100）
    eye_l = (40.0, 40.0)
    eye_r = (60.0, 40.0)
    nose = (50.0, 52.0)
    mouth_l = (44.0, 66.0)
    mouth_r = (56.0, 66.0)
    y0 = B._yaw(nose, eye_r, eye_l)
    p0 = B._pitch(nose, eye_l, eye_r, mouth_r, mouth_l)
    print(f"      正脸      yaw={y0:+.4f}  pitch={p0:+.4f}")

    worst_y = worst_p = 0.0
    for ang in (-25, -15, 15, 25):
        a = math.radians(ang)
        ca, sa = math.cos(a), math.sin(a)

        def rot(pt, cx=50.0, cy=52.0):
            dx, dy = pt[0] - cx, pt[1] - cy
            return (cx + dx * ca - dy * sa, cy + dx * sa + dy * ca)

        y = B._yaw(rot(nose), rot(eye_r), rot(eye_l))
        p = B._pitch(rot(nose), rot(eye_l), rot(eye_r), rot(mouth_r), rot(mouth_l))
        worst_y = max(worst_y, abs(y - y0))
        worst_p = max(worst_p, abs(p - p0))
        print(f"      歪头 {ang:+3d}° yaw={y:+.4f}  pitch={p:+.4f}")

    check("歪头时 yaw 漂移 < 0.02", worst_y < 0.02, f"最大漂移 {worst_y:.4f}")
    check("歪头时 pitch 漂移 < 0.02", worst_p < 0.02, f"最大漂移 {worst_p:.4f}")


def test_geometry_yaw_direction() -> None:
    """yaw 的正负号必须与"画面里往右"一致（否则摇头方向会反向）。"""
    print("\n[12] yaw 方向约定（镜像画面里向右转应为正）")
    from core.tracker import FaceBackendYuNet as B

    eye_l, eye_r = (40.0, 40.0), (60.0, 40.0)
    y_right = B._yaw((58.0, 52.0), eye_r, eye_l)     # 鼻尖偏右
    y_left = B._yaw((42.0, 52.0), eye_r, eye_l)      # 鼻尖偏左
    print(f"      鼻尖偏右 yaw={y_right:+.3f}   鼻尖偏左 yaw={y_left:+.3f}")
    check("鼻尖偏右 → yaw 为正", y_right > 0.05, f"{y_right:+.3f}")
    check("鼻尖偏左 → yaw 为负", y_left < -0.05, f"{y_left:+.3f}")


def test_pitch_direction() -> None:
    """pitch 的正负号：抬头为正、低头为负。"""
    print("\n[13] pitch 方向约定")
    from core.tracker import FaceBackendYuNet as B

    eye_l, eye_r = (40.0, 40.0), (60.0, 40.0)
    mouth_l, mouth_r = (44.0, 66.0), (56.0, 66.0)
    # 抬头：下半脸透视压缩 → 鼻尖更靠近眼线
    up = B._pitch((50.0, 44.0), eye_l, eye_r, mouth_r, mouth_l)
    dn = B._pitch((50.0, 60.0), eye_l, eye_r, mouth_r, mouth_l)
    print(f"      鼻尖靠眼线(抬头) pitch={up:+.3f}   鼻尖靠嘴线(低头) pitch={dn:+.3f}")
    check("抬头 → pitch 为正", up > 0.05, f"{up:+.3f}")
    check("低头 → pitch 为负", dn < -0.05, f"{dn:+.3f}")



def test_odd_displacement_guard() -> None:
    """
    静止假阳性必须被持续挡住，不能只挡第一帧。

    墙上的图案、画框、抱枕这类误检是**静止的**，会每帧都出现 ——
    如果保护只在"单帧尺度跳变"上，第二帧尺度就稳定了、保护失效，
    于是 cx 落在画面边缘的假脸照样能把轴量打满。

    但要留一条出路：如果这种状态**持续**存在，那说明是用户真的挪了位置，
    这时必须重建基线而不是一直冻结（否则用户会觉得"游戏死住了"）。
    """
    print("\n[15] 静止假阳性要持续挡住，但持续过久要重建基线")
    hc = calibrated(w=0.20, h=0.26)
    hc = settle(hc, face(w=0.20, h=0.26), 30)
    before = hc.axis
    for _ in range(10):                       # 10 帧 = 0.33s，未到重建阈值
        hc.update(face(cx=0.95, w=0.09, h=0.12), DT)
    print(f"      假阳性 0.33s → axis {before:+.3f} → {hc.axis:+.3f}")
    check("持续假阳性期间轴量未被甩出", abs(hc.axis - before) < 0.12,
          f"变化 {abs(hc.axis - before):.3f}")

    for _ in range(30):                       # 累计超过 FACE_ODD_HOLD
        hc.update(face(cx=0.95, w=0.09, h=0.12), DT)
    print(f"      继续 1.0s → axis={hc.axis:+.3f}  新基线 nw={hc.nw:.3f}")
    check("持续过久后重建了基线（脸宽基线跟着更新）",
          abs(hc.nw - 0.09) < 0.02, f"nw={hc.nw:.3f}")
    check("重建后输出为零（不输出荒唐值）", abs(hc.axis) < 1e-6,
          f"axis={hc.axis:.4f}")

    # 重建后，真实的小幅动作必须能正常控制
    for _ in range(90):
        hc.update(face(cx=0.95 + 0.09, w=0.09, h=0.12), DT)
    print(f"      重建后平移 1 个脸宽 → axis={hc.axis:+.3f}")
    check("重建后仍能正常控制（不是死住）", hc.axis > 0.5, f"axis={hc.axis:+.3f}")




def test_yaw_pitch_decoupling() -> None:
    """
    转头不得连带触发动作键。

    真机实测：yaw -0.43 时俯仰读数被顶到 +0.32，而动作键阈值是 0.42 ——
    只差一点就会"一转头发动机就跳"。原因是 2D 人脸关键点在侧脸时会往
    眼线方向漂移，把俯仰读数抬起来。所以要按 yaw 的量做耦合补偿。
    """
    print("\n[16] 转头不得连带触发动作键")
    axes = {}
    for y in (0.45, -0.45, 0.85, -0.85):
        hc = calibrated()
        # 关键点俯仰读数随 yaw 被顶起来（真机实测的耦合量 0.32/0.43 ≈ 0.74）
        coupled_pitch = 0.74 * y
        hc = settle(hc, face(cx=0.5, yaw=y, pitch=coupled_pitch), 60)
        axes[y] = hc.axis
        print(f"      yaw{y:+.2f} 附带俯仰{coupled_pitch:+.2f} → "
              f"轴量{hc.axis:+.2f} 键值{hc._debug.get('jump_sig', 0):+.2f} "
              f"动作键{'开' if hc.jump else '关'}")
        check(f"yaw{y:+.2f} 时动作键未被连带触发", not hc.jump)
    check("大幅度转向仍然被完整尊重（不会被当成休息位学掉）",
          abs(axes[0.85]) > 0.4 and abs(axes[-0.85]) > 0.4,
          f"{axes[0.85]:+.3f} / {axes[-0.85]:+.3f}")




def test_baseline_self_heal() -> None:
    """
    **这是"乱动"最隐蔽的一个来源，也是真机上实际发生过的。**

    现象：校准那 1.3 秒里用户在看终端（头转向别处，yaw 实测 +0.53），
    之后转回屏幕面对摄像头（真实 yaw ≈ 0）—— 但基线偏差 0.53 一直在扣，
    于是"正对摄像头"被算成"头往一边转"，角色一直停在偏位不动。

    修法：自适应门限必须**大于**这种校准偏差，否则角色永远回不到中位。
    这里模拟完整过程，断言基线能在几秒内自愈。
    """
    print("\n[17] 校准采歪了基线，必须能自愈回中位")
    hc = HeadController(C)
    for _ in range(C.CALIB_FRAMES + 2):          # 校准时头转向了别处
        hc.update(face(cx=0.5, yaw=0.53), DT)
    print(f"      校准后基线 yaw={hc.nyaw:+.3f}（用户其实在看别处）")

    # 用户转回来面对摄像头
    for _ in range(60):                          # 2 秒
        hc.update(face(cx=0.5, yaw=0.0), DT)
    early = hc.axis
    for _ in range(180):                         # 再 6 秒
        hc.update(face(cx=0.5, yaw=0.0), DT)
    print(f"      转回正前方 2s → 轴量{early:+.3f}   8s → 轴量{hc.axis:+.3f}"
          f"   基线 yaw={hc.nyaw:+.3f}")
    check("8 秒内轴量回到中位（|axis| < 0.05）", abs(hc.axis) < 0.05,
          f"axis={hc.axis:+.3f}")
    check("基线跟着收敛到真实朝向", abs(hc.nyaw) < 0.10, f"nyaw={hc.nyaw:+.3f}")

    # 反向的情况同样要能自愈
    hc2 = HeadController(C)
    for _ in range(C.CALIB_FRAMES + 2):
        hc2.update(face(cx=0.5, yaw=-0.60), DT)
    for _ in range(240):
        hc2.update(face(cx=0.5, yaw=0.0), DT)
    check("反向校准偏差同样能自愈", abs(hc2.axis) < 0.05, f"axis={hc2.axis:+.3f}")


def test_adapt_channels_independent() -> None:
    """
    自适应必须**逐通道独立**。

    真机踩过：几个通道共用一个门限时，俯仰偏离 0.75 会把横向基线的收敛
    一起卡死 —— 明明在转头，基线却动不了，角色一直停在偏位。
    """
    print("\n[18] 自适应逐通道独立（俯仰偏大不得卡死横向基线收敛）")
    hc = HeadController(C)
    for _ in range(C.CALIB_FRAMES + 2):
        hc.update(face(yaw=0.53), DT)
    # 用户转回正前方，但同时低头看键盘（俯仰偏离很大，超出俯仰门限）
    for _ in range(300):
        hc.update(face(yaw=0.0, pitch=-0.75), DT)
    print(f"      俯仰偏离 -0.75 时 → 轴量{hc.axis:+.3f}  基线 yaw={hc.nyaw:+.3f}"
          f"  基线 pitch={hc.npitch:+.3f}")
    check("摇头基线仍然收敛了", abs(hc.nyaw) < 0.10, f"nyaw={hc.nyaw:+.3f}")
    check("横向轴量回到中位", abs(hc.axis) < 0.05, f"axis={hc.axis:+.3f}")




# --------------------------------------------------------------------------- #
# 传感器噪声
# --------------------------------------------------------------------------- #
def _noisy_run(yaw_mean: float, sigma: float, secs: float = 8.0, seed: int = 3):
    """喂一段带噪声的静止序列，返回逐帧的 axis 序列。"""
    rng = np.random.default_rng(seed)
    hc = calibrated()
    out = []
    n = int(secs / DT)
    for _ in range(n):
        y = yaw_mean + rng.normal(0.0, sigma)
        hc.update(face(cx=0.5, yaw=y), DT)
        out.append(hc.axis)
    return out


def _stats(seq):
    flips = 0
    on = False
    for v in seq:
        cur = abs(v) > 1e-9
        if cur != on:
            flips += 1
            on = cur
    return flips, max(abs(v) for v in seq)


def test_noise_does_not_chatter() -> None:
    """
    **传感器噪声不得变成控制量。**

    这是真机事故："头没动，选游戏的地方一直不停在左右选择"。

    原因：摇头读数 = 鼻尖相对双眼中点的位移 ÷ 半眼距，而检测图只有 320 宽 ——
    脸宽 ≈64px、眼距 ≈27px，**半眼距只有 13px**。也就是说
        · 鼻尖抖动 1px → yaw 噪声 0.07
        · 鼻尖抖动 3px → yaw 噪声 0.22（正好等于死区）
    摇头在接进横向控制之前，这点噪声无害；接进来之后就**直接变成控制量**。
    第一版测试全用干净合成信号，所以完全没抓到 —— 噪声必须进测试。

    三条修法各自断言：重低通、死区迟滞、起振门限。
    """
    print("\n[19] 静止 + 传感器噪声不得产生控制量（真机事故回归）")
    for tag, mean, sigma in (("无偏置", 0.0, 0.15), ("小偏置", 0.12, 0.15),
                             ("大偏置", 0.20, 0.18), ("极端噪声", 0.0, 0.28)):
        seq = _noisy_run(mean, sigma)
        flips, peak = _stats(seq)
        over = sum(1 for v in seq if abs(v) > C.MENU_SWITCH_TH)
        print(f"      {tag:6s} 均值{mean:+.2f} σ={sigma:.2f} → "
              f"抖动翻转 {flips:3d} 次  峰值 {peak:.2f}  超过大厅阈值 {over} 帧")
        check(f"{tag}：输出不在 0 与非 0 之间反复跳（翻转 ≤ 2）", flips <= 2,
              f"翻转 {flips} 次")
        check(f"{tag}：不会跨过大厅切换阈值", over == 0, f"{over} 帧越界")


def test_noise_keeps_responsiveness() -> None:
    """抗抖动不能把真实操作一起滤掉 —— 那会变成"怎么动都没反应"。"""
    print("\n[20] 加了抗抖动之后，真实摇头仍要跟得上")
    rng = np.random.default_rng(11)
    for tag, yaw, lo, hi in (("自然转头", 0.70, 0.30, 0.80),
                             ("大幅转头", 1.40, 0.80, 1.05),
                             ("反向转头", -0.70, 0.30, 0.80)):
        hc = calibrated()
        for _ in range(int(1.2 / DT)):                 # 1.2 秒持续转头
            hc.update(face(cx=0.5, yaw=yaw + rng.normal(0, 0.12)), DT)
        val = abs(hc.axis)
        print(f"      {tag}：yaw{yaw:+.2f} → |axis|={val:.3f}")
        check(f"{tag} 输出落在预期区间 [{lo}, {hi}]", lo <= val <= hi,
              f"{val:.3f}")
    # 起振延迟必须短到感觉不到
    hc = calibrated()
    t = 0.0
    for i in range(120):
        hc.update(face(cx=0.5, yaw=1.20), DT)
        t += DT
        if abs(hc.axis) > 0.30:
            break
    print(f"      从静止到输出 0.30 用时 {t * 1000:.0f} ms")
    check("起振延迟 < 220ms（感觉不到）", t < 0.22, f"{t * 1000:.0f} ms")


def test_single_spike_rejected() -> None:
    """单个尖峰（一次误检 / 一次关键点跳变）必须被完全丢掉。"""
    print("\n[21] 单帧尖峰必须被起振门限吃掉")
    hc = calibrated()
    for _ in range(60):
        hc.update(face(cx=0.5, yaw=0.0), DT)
    peak = 0.0
    for i in range(30):
        spike = 0.95 if i == 15 else 0.0        # 孤立一帧的假读数
        hc.update(face(cx=0.5, yaw=spike), DT)
        peak = max(peak, abs(hc.axis))
    print(f"      孤立尖峰 yaw=0.95 → 之后轴量峰值 {peak:.3f}")
    check("尖峰没有产生任何输出", peak < 1e-9, f"峰值 {peak:.4f}")

    # 连续两帧也不行（起振门限是 90ms，两帧只有 66ms）
    hc2 = calibrated()
    for _ in range(60):
        hc2.update(face(cx=0.5, yaw=0.0), DT)
    peak2 = 0.0
    for i in range(30):
        spike = 0.95 if i in (15, 16) else 0.0
        hc2.update(face(cx=0.5, yaw=spike), DT)
        peak2 = max(peak2, abs(hc2.axis))
    # 两帧尖峰经低通后会有几帧"尾巴"悬在迟滞阈值之上，所以这里**不断言
    # "严格为 0"** —— 那是过度承诺。改成断言远小于可感知量：
    # 大厅阈值是 0.52，这里必须低于满量的 2%。
    check("两帧尖峰的影响可忽略（< 满量的 2%）", peak2 < 0.02,
          f"峰值 {peak2:.4f}")

    # 但要确认"持续的转头"不会被误杀（这是起振门限的代价边界）
    hc3 = calibrated()
    for _ in range(90):
        hc3.update(face(cx=0.5, yaw=0.95), DT)
    check("持续转头不被误杀（输出 > 0.5）", abs(hc3.axis) > 0.5,
          f"axis={hc3.axis:+.3f}")


def test_menu_selection_stable() -> None:
    """
    大厅是最不能抖的地方 —— 抖一格就是"我刚才明明没动"。

    这里把「控制器 + 大厅」串起来跑一段带噪声的静止序列，
    断言**一次都不会切**。
    """
    print("\n[22] 端到端：静止 + 噪声时大厅不得切换")
    import pygame

    import games          # noqa: F401  导入即注册（大厅要读游戏清单）
    from core.menu import Menu

    if pygame.display.get_surface() is None:
        pygame.display.set_mode((320, 240))
    rng = np.random.default_rng(5)
    menu = Menu({"cam_ok": True, "hand_ok": True, "backend": "YuNet",
                 "hand_backend": "Vision", "fps": 60.0, "track": "track"})
    menu.reset()
    hc = calibrated()
    seq = []
    for _ in range(300):                        # 10 秒
        y = 0.10 + rng.normal(0.0, 0.17)
        hc.update(face(cx=0.5, yaw=y), DT)
        inp = hc.game_input()
        inp.found = True
        menu.update(DT, inp)
        seq.append(menu.sel)
    changed = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
    print(f"      10 秒静止 → 选中项变化 {changed} 次（期望 0）")
    check("静止时大厅选中项不变", changed == 0, f"变化 {changed} 次")

    # 真实摇头必须能切（否则就是把交互也滤掉了）
    hc2 = calibrated()
    menu.reset()
    seq2 = []
    for i in range(240):
        y = 0.90 if (i // 30) % 2 == 0 else -0.90   # 每 1 秒换一次方向
        hc2.update(face(cx=0.5, yaw=y), DT)
        inp = hc2.game_input()
        inp.found = True
        menu.update(DT, inp)
        seq2.append(menu.sel)
    changed2 = sum(1 for a, b in zip(seq2, seq2[1:]) if a != b)
    print(f"      持续左右摇头 8 秒 → 选中项变化 {changed2} 次")
    check("真实摇头仍能正常切换（≥ 3 次）", changed2 >= 3, f"变化 {changed2} 次")

    # ---- "切一格要转多少度" —— 这才是用户感知到的灵敏度 ----
    # 用户两次反馈"偏头灵敏度不够"，指的就是这个数。用二分找出
    # "甩 0.6 秒刚好能切换"的临界转头角度，把上下界都钉住：
    # 太小 → 误触；太大 → 用户觉得转不动。
    def _needs_change(yaw: float, secs: float = 0.6) -> bool:
        hc = calibrated()
        m = Menu({"cam_ok": True, "hand_ok": True, "backend": "YuNet",
                  "hand_backend": "Vision", "fps": 60.0, "track": "track"})
        m.reset()
        first = m.sel
        for _ in range(int(secs / DT)):
            hc.update(face(cx=0.5, yaw=yaw), DT)
            inp = hc.game_input()
            inp.found = True
            m.update(DT, inp)
        return m.sel != first

    lo, hi = 0.0, 1.40
    for _ in range(20):
        mid_y = (lo + hi) / 2
        if _needs_change(mid_y):
            hi = mid_y
        else:
            lo = mid_y
    deg = math.degrees(math.asin(min(1.0, hi / 2.14)))
    print(f"      甩 0.6 秒切一格所需的转头角度 ≈ {deg:.1f}°")
    check("不算太迟钝：≤ 18° 就能切一格", deg <= 18.0, f"{deg:.1f}°")
    check("也不算太灵：≥ 10° 才切（防误触）", deg >= 10.0, f"{deg:.1f}°")



def test_held_look_up_not_learned() -> None:
    """
    抬头保持期间，俯仰基线不得被自适应学走 —— 否则"游戏里再也抬不起头"。

    这条是**灵敏度调高之后才出现的危险带**。按下动作键所需的抬头幅度
    从 p_raw 0.27 降到 0.23（PITCH_FULL_SCALE 0.52→0.43），
    而俯仰自适应门限仍是 0.30 —— 也就是说"刚好能按下动作键"的那一段
    现在落在了门限**以内**。若没有"动作键按住就冻结基线"这条，
    玩家保持抬头 3 秒，基线就会被学成新的休息位。

    同时反向断言：不触发动作键的小幅抬头**仍然要被吸收**（自愈不能被一起关掉）。
    """
    print("\n[23] 抬头保持期间基线不得被学走（新灵敏度的危险带）")
    # 取一个**可靠按下**动作键的幅度（阈值 +0.10 余量；刚好卡在 0.42 上会因
    # 浮点与迟滞而时灵时不灵，那不是这条要测的东西）
    hold = C.PITCH_DEADZONE + (C.JUMP_ON + 0.10) * (C.PITCH_FULL_SCALE - C.PITCH_DEADZONE)
    band = "落在门限内 → 全靠『按住就冻结基线』保护" \
        if hold < C.NEUTRAL_ADAPT_GATE_P else "高于门限，本就不会被吸收"
    print(f"      保持 p_raw={hold:.3f}（自适应门限 {C.NEUTRAL_ADAPT_GATE_P}，{band}）")
    hc = calibrated()
    hc = settle(hc, face(pitch=hold), int(3.0 / DT))
    print(f"      保持 3 秒 → 基线 pitch={hc.npitch:+.3f}　"
          f"jump={'按住' if hc.jump else '松开'}")
    check("抬头保持 3 秒后基线未被学走（|Δ| < 0.03）", abs(hc.npitch) < 0.03,
          f"{hc.npitch:+.3f}")
    check("保持期间动作键一直在按住", hc.jump)

    hc = settle(hc, face(pitch=0.0), int(1.0 / DT))       # 松手回落
    hc = settle(hc, face(pitch=hold), 20)                 # 再抬头
    check("松手之后再抬头仍能触发", hc.jump)

    hc2 = calibrated()
    hc2 = settle(hc2, face(pitch=0.16), int(3.0 / DT))
    print(f"      不触发动作键的 p_raw=0.16 → 基线 pitch={hc2.npitch:+.3f}（应被吸收）")
    check("不触发动作键的小幅抬头仍被当作休息位吸收（自愈仍有效）",
          hc2.npitch > 0.05, f"{hc2.npitch:+.3f}")


def test_repeated_jump_same_effort() -> None:
    """
    **真机症状回归：第一次抬头容易，后续非常难触发。**

    根因：按下动作键所需 p_raw(≈0.21) **小于** 俯仰自适应门限(0.30) ——
    于是 0.21~0.30 这段"能触发第一跳、却不够门限"的抬头会被基线当休息位
    学走，第二跳要抬得更高，越玩越费劲。
    修复：_adapt 里加"抬头意图门"（jump_sig > JUMP_INTENT_TH 期间不学俯仰）。
    这里断言：**固定幅度的抬头，连续三次的触发结果必须一致**，
    且基线不得漂移；同时反向断言无意图的噪声级偏置仍要被吸收。
    """
    print("\n[24] 连续抬头：每次所需努力不得递增（意图门回归）")
    amp = C.PITCH_DEADZONE + (C.JUMP_ON + 0.05) * (C.PITCH_FULL_SCALE - C.PITCH_DEADZONE)
    hc = calibrated()
    fires, bases = [], []
    for n in range(3):
        hc = settle(hc, face(pitch=amp), 30)
        fires.append(hc.jump)
        bases.append(hc.npitch)
        hc = settle(hc, face(pitch=0.0), 30)      # 放下
    print(f"      固定幅度 {amp:.3f} 三连跳: {fires}  基线 {[f'{b:+.3f}' for b in bases]}")
    check("三连跳全部触发", all(fires), f"{fires}")
    check("俯仰基线未被学走（|Δ| < 0.03）",
          max(abs(b) for b in bases) < 0.03, f"{bases}")

    # 反向：无意图的噪声级偏置（坐姿漂移）仍要被吸收 —— 意图门不能把自愈关死
    hc2 = calibrated()
    rng = np.random.default_rng(3)
    for _ in range(240):                          # 8 秒
        hc2.update(face(pitch=0.10 + rng.normal(0, 0.03)), DT)
    print(f"      无意图偏置 0.10 → 基线 {hc2.npitch:+.3f}（应被吸收到 ≈0.10）")
    check("无意图的坐姿漂移仍被吸收", abs(hc2.npitch - 0.10) < 0.05,
          f"npitch={hc2.npitch:+.3f}")



    """静态检查：代码里引用的配置项是否都存在（含本轮新增的）。"""
    print("\n[14] 静态检查：配置项引用")
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent
    pat = re.compile(r"\b(?:C|cfg)\.([A-Z][A-Z0-9_]*)\b")
    missing = []
    total = 0
    for d in ("core", "games"):
        for f in sorted((root / d).rglob("*.py")):
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                for name in pat.findall(line):
                    total += 1
                    if not hasattr(C, name):
                        missing.append(f"{f.relative_to(root)}:{i} {name}")
    check(f"全部 {total} 处配置引用都有效", not missing, " ".join(missing[:6]))


def main() -> int:
    print("=" * 66)
    print("头部控制行为测试")
    print("=" * 66)
    test_distance_invariance()
    test_yaw_controls_axis()
    test_move_controls_axis()
    test_pitch_triggers_action()
    test_no_false_jump_on_lean_back()
    test_jump_hysteresis()
    test_scale_jump_guard()
    test_neutral_drift_absorbed()
    test_hold_behavior_intact()
    test_pose_gate()
    test_odd_displacement_guard()
    test_yaw_pitch_decoupling()
    test_held_look_up_not_learned()
    test_repeated_jump_same_effort()
    test_baseline_self_heal()
    test_adapt_channels_independent()
    test_noise_does_not_chatter()
    test_noise_keeps_responsiveness()
    test_single_spike_rejected()
    test_menu_selection_stable()
    test_geometry_roll_invariance()
    test_geometry_yaw_direction()
    test_pitch_direction()
    print("\n" + "=" * 66)
    print(f"通过 {_ok} 项，失败 {_fail} 项")
    print("=" * 66)
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
