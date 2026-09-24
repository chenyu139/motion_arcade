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
    """一帧单只手的结果。坐标为镜像后的归一化值。"""
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

    # 屏幕映射辅助：把归一化手部坐标映射到设计坐标系
    def hand_screen(self, w: float, h: float, invert_y: bool = False):
        y = (1.0 - self.hy) if invert_y else self.hy
        return (self.hx * w, y * h)


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

    def update(self, st: FaceState) -> None:
        C = self.cfg
        self.found = st.found
        if not st.found:
            self.axis *= 0.6
            self.up *= 0.8
            self.head_y *= 0.8
            self.yaw *= 0.8
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
        self.axis += C.SMOOTH * (raw - self.axis)

        up_raw = ncy - st.cy                      # 正值 = 抬头
        self.up = max(0.0, min(1.0, up_raw / 0.28))
        self.head_y = max(-1.0, min(1.0, up_raw / 0.22))
        self.yaw += 0.22 * (max(-1.0, min(1.0, st.yaw)) - self.yaw)
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
            return

        self.lost_t = 0.0
        h = max(hands, key=lambda z: z.area)
        k = C.HAND_SMOOTH
        self.sx += k * (h.x - self.sx)
        self.sy += k * (h.y - self.sy)
        self.sopen += k * (h.open - self.sopen)
        self.seen = True

        closed = self.sopen < C.HAND_CLOSE_THRESHOLD
        if closed:
            self._closed_frames += 1
            if self._closed_frames == 2 and not self._was_closed:
                self.pinch = True
            self._was_closed = True
        else:
            self._closed_frames = 0
            if self._was_closed and self.sopen > C.HAND_OPEN_THRESHOLD:
                self.release = True
                self._was_closed = False

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
