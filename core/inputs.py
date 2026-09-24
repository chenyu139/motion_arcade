"""
core/inputs.py
==============
统一输入模型：把"摄像头看到的身体信息"翻译成游戏能用的控制量。

三个层次
--------
  FaceState   一帧人脸检测结果（含 yaw/pitch/roll 头部朝向估计）
  HandState   一帧单只手的结果（掌心、张合度、伸展手指数）
  GameInput   所有游戏共用的最终输入（头部 + 手部 + 边沿触发）

为什么要有"边沿触发"
--------------------
张开手掌、握拳这类手势是**离散动作**（点的语义），若直接传连续值，
游戏里会变成"一直按住"。因此控制器负责把连续量做边沿检测，
输出 pinch / fist / open_trig 三个只在触发那一帧为 True 的信号。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# =========================================================================== #
@dataclass
class FaceState:
    """一帧人脸检测结果。坐标均已归一化到 0~1（且已水平镜像，与预览一致）。"""
    found: bool = False
    cx: float = 0.5            # 脸框中心 x
    cy: float = 0.5            # 脸框中心 y
    w: float = 0.2             # 脸框宽（归一化）
    h: float = 0.2
    yaw: float = 0.0           # 头部左右转 -1(左) ~ +1(右)，由鼻尖相对脸框偏移估计
    pitch: float = 0.0         # 头部俯仰 -1(低头) ~ +1(抬头)
    roll: float = 0.0          # 头部倾斜（弧度）
    mouth_open: float = 0.0    # 0~1，仅 MediaPipe 后端
    box: Optional[Tuple[int, int, int, int]] = None
    landmarks: Optional[List[Tuple[float, float]]] = None
    nose: Optional[Tuple[float, float]] = None
    backend: str = "-"


@dataclass
class HandState:
    """
    一帧单只手的结果（兼容层）。

    这是给"只关心掌心 + 张合度"的老游戏用的简化结构；
    新游戏建议直接用 core.vision.HandFrame（21 个关键点、捏合、伸出手指数、指向）。
    HandState.pose 就是那只手的 HandFrame，需要精细手势时取它。
    """
    found: bool = False
    x: float = 0.5             # 掌心 x（0 左 → 1 右）
    y: float = 0.5             # 掌心 y（0 上 → 1 下）
    open: float = 0.0          # 张合度：0 = 完全握拳，1 = 五指张开
    fingers: int = 0           # 估计的伸展手指数（0~5）
    area: float = 0.0          # 手的归一化面积（相对画面），可用于判断远近
    span: float = 0.0          # 手的包围盒宽度（归一化）
    angle: float = 0.0         # 手的朝向（弧度），由轮廓主轴给出
    bbox: Optional[Tuple[int, int, int, int]] = None
    contour: Optional[object] = None   # 调试用：原始轮廓点
    palm_r: float = 0.0        # 掌心内切圆半径（归一化）
    pose: Optional[object] = None      # core.vision.HandFrame（有的话）


@dataclass
class GameInput:
    """
    所有游戏统一接收的输入结构。

    ── 头部 ──────────────────────────────────────────────
      axis      头部水平控制量 -1 ~ +1（以校准中性位为原点）
      up        抬头幅度 0~1
      head_y    头部纵向连续量 -1(低头) ~ +1(抬头)
      yaw       头部转向 -1 ~ +1（头不移动只转头也能产生）
      jump      动作键（抬头超过阈值 或 张嘴），持续为 True
      mouth     张嘴程度 0~1

    ── 手部 ──────────────────────────────────────────────
      hand_found  是否看到手
      hx, hy      主手掌心归一化坐标（实际使用时请用 cursor_* 映射到屏幕）
      hand_open   主手张合度 0~1
      fingers     主手伸展手指数
      hands       所有检测到的手（左→右排序）
      hand_l/hand_r  明确区分左右手（可能为 None）
      pinch       捏合/握拳触发（边沿，仅触发帧为 True）
      release     张开触发（边沿，握拳→张开的那一刻）
      grab_hold   "保持收拢"状态（连续）

    ── 通用 ──────────────────────────────────────────────
      found       是否检测到头部
    """
    axis: float = 0.0
    up: float = 0.0
    head_y: float = 0.0
    yaw: float = 0.0
    jump: bool = False
    mouth: float = 0.0
    found: bool = False

    hand_found: bool = False
    hx: float = 0.5
    hy: float = 0.5
    hand_open: float = 0.0
    fingers: int = 0
    hands: List[HandState] = field(default_factory=list)
    hand_l: Optional[HandState] = None
    hand_r: Optional[HandState] = None
    pinch: bool = False
    release: bool = False
    grab_hold: bool = False

    # ── 全身（来自 core.vision.PoseFrame，需要身体入镜）─────────────
    #  这些量都已经过"中性位校准 + 身体尺度归一"，所以对不同身高、
    #  不同远近的人都直接可用，游戏里不用再做换算。
    body_found: bool = False
    body_x: float = 0.0        # 身体横向偏移 -1(左) ~ +1(右)
    crouch: float = 0.0        # 下蹲 0(站直) ~ 1(蹲到底)
    arm_l: float = 0.0         # 左手举起 0~1（手腕高出肩膀的相对量）
    arm_r: float = 0.0
    arm_l_ext: float = 0.0     # 左臂伸展 0(弯曲) ~ 1(伸直)
    arm_r_ext: float = 0.0
    hands_up: int = 0          # 举起了几只手
    lean: float = 0.0          # 躯干侧倾 -1~1
    lb_visible: bool = False   # 下半身是否入镜（决定能否做踢腿/跳跃玩法）
    pose: object = None        # 原始 PoseFrame，想自己算几何时用

    # 屏幕映射辅助：把归一化手部坐标映射到设计坐标系
    def hand_screen(self, w: float, h: float, invert_y: bool = False):
        y = (1.0 - self.hy) if invert_y else self.hy
        return (self.hx * w, y * h)

    # ── 通道融合：让同一份游戏代码同时吃"头部"和"全身" ──────────────
    #  这是支持体感玩法的关键：游戏里把 inp.axis 换成 inp.xc、
    #  inp.jump 换成 inp.action，就自动同时支持三种玩法，
    #  而且用户在摄像头前怎么动都行 —— 哪种动作幅度大就用哪种。

    @property
    def xc(self) -> float:
        """
        横向控制量 -1~1：取「头部平移」与「身体横移」中更明显的那个。

        身体没入镜（body_found=False）时等价于 inp.axis，
        所以老游戏改用它不会有任何行为变化。
        """
        if self.body_found and abs(self.body_x) > abs(self.axis):
            return self.body_x
        return self.axis

    @property
    def action(self) -> bool:
        """
        动作键：抬头 / 举手 / 张嘴 任一触发。

        举手是最自然的体感动作（拍球、击鼓、抓握），
        所以只要有一只手明显举过肩就当成"按下动作键"。
        """
        return bool(self.jump or self.hands_up > 0
                    or self.arm_l > 0.32 or self.arm_r > 0.32)

    @property
    def action_l(self) -> bool:
        """左臂独立的动作键（双手游戏用）。"""
        return bool(self.arm_l > 0.32 or (self.jump and self.arm_r <= 0.32))

    @property
    def action_r(self) -> bool:
        return bool(self.arm_r > 0.32 or (self.jump and self.arm_l <= 0.32))

    @property
    def crouching(self) -> bool:
        """是否处于下蹲状态（下半身或躯干可见时才有效）。"""
        return self.body_found and self.crouch > 0.45

    @property
    def arms_wide(self) -> bool:
        """双臂是否大幅张开（守门、接物类用）。"""
        return self.hands_up >= 2 or (self.arm_l > 0.5 and self.arm_r > 0.5)


# =========================================================================== #
# 头部 → 控制量
# =========================================================================== #
def _deadzone(v: float, dz: float, full: float) -> float:
    if abs(v) <= dz:
        return 0.0
    sign = 1.0 if v > 0 else -1.0
    span = max(1e-6, full - dz)
    return sign * min(1.0, (abs(v) - dz) / span)


class HeadController:
    """
    把头部位置映射为游戏控制：
      · 头部左右平移 → axis（相对校准中性位，带死区与平滑）
      · 头部抬高     → jump / up
      · 张嘴         → jump（仅 MediaPipe 后端可用）
      · 头部转向     → yaw（由鼻尖偏移估计，做细腻控制时可用）

    启动时先采集若干帧建立"中性位"，以适配不同坐姿与摄像头位置。
    """

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self._samples: List[Tuple[float, float]] = []
        self.neutral: Optional[Tuple[float, float]] = None
        self.axis = 0.0
        self.jump = False
        self.up = 0.0
        self.head_y = 0.0
        self.yaw = 0.0
        self.found = False
        self.calibrating = True
        self.progress = 0.0

    def update(self, st: FaceState, dt: float) -> None:
        C = self.cfg
        self.found = st.found
        if not st.found:
            k = 1.0 - math.exp(-dt / 0.14)
            self.axis += k * (0.0 - self.axis)
            self.up *= (1.0 - k)
            self.head_y *= (1.0 - k)
            self.yaw *= (1.0 - k)
            self.jump = False
            return

        if self.calibrating:
            self._samples.append((st.cx, st.cy))
            self.progress = min(1.0, len(self._samples) / C.CALIB_FRAMES)
            self.axis = self.up = self.head_y = self.yaw = 0.0
            self.jump = False
            if len(self._samples) >= C.CALIB_FRAMES:
                xs = sorted(s[0] for s in self._samples)
                ys = sorted(s[1] for s in self._samples)
                self.neutral = (xs[len(xs) // 2], ys[len(ys) // 2])
                self.calibrating = False
            return

        ncx, ncy = self.neutral  # type: ignore[misc]
        raw = _deadzone(st.cx - ncx, C.DEADZONE_X, C.FULL_SCALE_X)
        # 基于时间的平滑：帧率变化时跟随手感保持一致（见 config 里的说明）
        k = 1.0 - math.exp(-dt / max(1e-3, C.HEAD_TAU))
        self.axis += k * (raw - self.axis)

        up_raw = ncy - st.cy                      # 正值 = 抬头
        self.up = max(0.0, min(1.0, up_raw / 0.28))
        self.head_y = max(-1.0, min(1.0, up_raw / 0.22))
        self.yaw += (1.0 - math.exp(-dt / 0.10)) * (max(-1.0, min(1.0, st.yaw)) - self.yaw)
        # 张嘴或抬头都算"动作键"
        self.jump = (up_raw > C.JUMP_DY) or (st.mouth_open > C.MOUTH_OPEN_THRESHOLD)

    def game_input(self) -> GameInput:
        return GameInput(axis=self.axis, jump=self.jump, up=self.up,
                         head_y=self.head_y, yaw=self.yaw, found=self.found)


# =========================================================================== #
# 手部 → 控制量（含边沿检测）
# =========================================================================== #
class HandController:
    """
    手部平滑 + 手势边沿检测。

    · 主手选择：优先取"画面中面积最大的手"，避免远处置景（如脸旁边的墙）
      被误判为主控手。
    · pinch：open 连续低于 CLOSE 阈值并维持 2 帧 → 触发一次
    · release：pinch 之后 open 升回 OPEN 阈值 → 触发一次
    · grab_hold：当前是否处于"收拢"状态
    """

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self.sx = 0.5
        self.sy = 0.5
        self.sopen = 0.0
        self.seen = False
        self.lost_t = 99.0
        self._closed_frames = 0
        self._was_closed = False
        self._pinch_fired = False
        self.pinch = False
        self.release = False

    def update(self, hands: List[HandState], dt: float) -> None:
        C = self.cfg
        self.pinch = False
        self.release = False

        if not hands:
            self.lost_t += dt
            if self.lost_t > C.HAND_LOST_AFTER:
                self.seen = False
            self._was_closed = False
            self._closed_frames = 0
            self._pinch_fired = False
            return

        self.lost_t = 0.0
        h = max(hands, key=lambda z: z.area)
        # 基于时间的平滑：帧率变化时跟随手感保持一致
        k = 1.0 - math.exp(-dt / max(1e-3, C.SMOOTH_TAU))
        self.sx += k * (h.x - self.sx)
        self.sy += k * (h.y - self.sy)
        self.sopen += k * (h.open - self.sopen)
        self.seen = True

        closed = self.sopen < C.HAND_CLOSE_THRESHOLD
        if closed:
            self._closed_frames += 1
            # 用独立的 _pinch_fired 记录"本次收拢是否已经触发过"。
            # 之前用 _was_closed 判断，而它在前一帧就被置 True 了，
            # 导致 `_closed_frames == 2 and not _was_closed` 永远为假 —— pin
            # 一次都不会触发。
            if self._closed_frames >= 2 and not self._pinch_fired:
                self.pinch = True
                self._pinch_fired = True
            self._was_closed = True
        else:
            self._closed_frames = 0
            if self._was_closed and self.sopen > C.HAND_OPEN_THRESHOLD:
                self.release = True
                self._was_closed = False
            self._pinch_fired = False

    @property
    def grab_hold(self) -> bool:
        return self._was_closed

    def apply(self, inp: GameInput, hands: List[HandState]) -> GameInput:
        inp.hands = hands
        if hands:
            hs = sorted(hands, key=lambda h: h.x)
            inp.hand_l = hs[0]
            inp.hand_r = hs[-1] if len(hs) > 1 else hs[0]
            main = max(hands, key=lambda h: h.area)
            inp.hx, inp.hy = self.sx, self.sy
            inp.hand_open = self.sopen
            inp.fingers = main.fingers
        inp.hand_found = self.seen
        inp.pinch = self.pinch
        inp.release = self.release
        inp.grab_hold = self.grab_hold
        return inp


class NullController:
    """无摄像头（键盘模式）时使用，保证游戏代码无需判空。"""

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.progress = 0.0
        self.calibrating = False
        self.neutral = None

    def update(self, *a, **k) -> None:
        pass

    def reset(self) -> None:
        pass

    def game_input(self) -> GameInput:
        return GameInput()

    def apply(self, inp: GameInput, hands=None) -> GameInput:
        return inp


# =========================================================================== #
# 全身 → 控制量
# =========================================================================== #
class BodyController:
    """
    把 COCO-17 骨骼翻译成体感游戏的语义量。

    三件关键的事：
      1) **中性位校准**：启动时记录你正常坐姿的身体中心，之后所有横向位移
         都相对它计算，站着/坐着都能用。
      2) **身体尺度归一**：所有位移除以肩宽（或肩髋距），
         这样离摄像头远近、个子高矮都不会改变手感。
      3) **时间常数平滑**：与头部一致，帧率变化不影响跟随速度。
    """

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self._samples: List[float] = []
        self.neutral_x: Optional[float] = None
        self.body_x = 0.0
        self.crouch = 0.0
        self.arm_l = self.arm_r = 0.0
        self.arm_l_ext = self.arm_r_ext = 0.0
        self.lean = 0.0
        self.hands_up = 0
        self.found = False
        self.lb_visible = False
        self.calibrating = True
        self.progress = 0.0

    def update(self, pose, dt: float) -> None:
        C = self.cfg
        ok = pose is not None and getattr(pose, "found", False)
        self.found = bool(ok)
        if not ok:
            k = 1.0 - math.exp(-dt / 0.18)
            self.body_x += k * (0.0 - self.body_x)
            self.arm_l += k * (0.0 - self.arm_l)
            self.arm_r += k * (0.0 - self.arm_r)
            self.crouch += k * (0.0 - self.crouch)
            self.lean += k * (0.0 - self.lean)
            self.hands_up = 0
            return

        center = pose.body_center
        scale = max(0.06, pose.scale)
        self.lb_visible = pose.lower_body_visible()

        if self.calibrating:
            if center.ok:
                self._samples.append(center.x)
                self.progress = min(1.0, len(self._samples) / C.CALIB_FRAMES)
                if len(self._samples) >= C.CALIB_FRAMES:
                    xs = sorted(self._samples)
                    self.neutral_x = xs[len(xs) // 2]
                    self.calibrating = False
            return

        nx = self.neutral_x if self.neutral_x is not None else 0.5
        # 横向位移：以肩宽为单位，死区 0.25 个肩宽 → 满速 1.1 个肩宽
        raw = _deadzone((center.x - nx) / scale, 0.25, 1.10)
        k = 1.0 - math.exp(-dt / max(1e-3, C.BODY_TAU))
        self.body_x += k * (raw - self.body_x)

        # 姿态量：直接平滑跟随（它们本身已经做了尺度归一）
        kc = 1.0 - math.exp(-dt / 0.12)
        self.crouch += kc * (pose.crouch - self.crouch)
        self.lean += kc * (max(-1.5, min(1.5, pose.torso_lean)) - self.lean)
        self.arm_l += kc * (pose.arm_raised("left") - self.arm_l)
        self.arm_r += kc * (pose.arm_raised("right") - self.arm_r)
        self.arm_l_ext += kc * (pose.arm_extended("left") - self.arm_l_ext)
        self.arm_r_ext += kc * (pose.arm_extended("right") - self.arm_r_ext)
        self.hands_up = pose.hands_up()

    def apply(self, inp: GameInput, pose) -> GameInput:
        inp.pose = pose
        inp.body_found = self.found
        inp.body_x = self.body_x
        inp.crouch = self.crouch
        inp.arm_l = self.arm_l
        inp.arm_r = self.arm_r
        inp.arm_l_ext = self.arm_l_ext
        inp.arm_r_ext = self.arm_r_ext
        inp.hands_up = self.hands_up
        inp.lean = self.lean
        inp.lb_visible = self.lb_visible
        return inp
