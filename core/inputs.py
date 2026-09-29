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

from .filters import OneEuroFilter, RateLimiter, lowpass_towards


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
    pose_ok: bool = False      # yaw/pitch 这一帧是否可信（关键点齐全且眼距够）
    mouth_open: float = 0.0    # 0~1，仅 MediaPipe 后端
    box: Optional[Tuple[int, int, int, int]] = None
    landmarks: Optional[List[Tuple[float, float]]] = None
    nose: Optional[Tuple[float, float]] = None
    backend: str = "-"
    score: float = 1.0         # 检测器自身的置信度 0~1（只有部分后端会给）


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

    # ── 识别质量（供 UI 提示与降级；普通游戏逻辑不必关心）──────────────
    confidence: float = 1.0   # 检测器置信度 0~1
    quality: str = "good"     # good / far / poor / angle / lost
    hint: str = ""            # 给用户看的具体建议文案（已按 quality 取好）

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

    def _arm_flags(self) -> Tuple[bool, bool]:
        """
        手臂是否抬起。

        **必须"身体当前确实在识别中"才算数** —— 姿态模型隔帧跑、
        丢检时还会退避，如果只看 arm_l/arm_r 的数值，那一两帧的陈旧值
        会让角色在没有人做动作时继续"按键"（这正是"没识别到头却还在乱动"）。
        """
        if not self.body_found:
            return (False, False)
        return (self.arm_l > 0.32, self.arm_r > 0.32)

    @property
    def _hands_up_now(self) -> bool:
        """举手同样来自身体姿态，必须一起门控。"""
        return self.body_found and self.hands_up > 0

    @property
    def action(self) -> bool:
        """
        动作键：抬头 / 举手 / 张嘴 任一触发。

        举手是最自然的体感动作（拍球、击鼓、抓握），
        所以只要有一只手明显举过肩就当成"按下动作键"。
        """
        l, r = self._arm_flags()
        return bool(self.jump or self._hands_up_now or l or r)

    @property
    def action_l(self) -> bool:
        """左臂独立的动作键（双手游戏用）。"""
        l, r = self._arm_flags()
        return bool(l or (self.jump and not r))

    @property
    def action_r(self) -> bool:
        l, r = self._arm_flags()
        return bool(r or (self.jump and not l))

    @property
    def crouching(self) -> bool:
        """是否处于下蹲状态（下半身或躯干可见时才有效）。"""
        return self.body_found and self.crouch > 0.45

    @property
    def arms_wide(self) -> bool:
        """双臂是否大幅张开（守门、接物类用）。"""
        if not self.body_found:
            return False
        return bool(self.hands_up >= 2 or (self.arm_l > 0.5 and self.arm_r > 0.5))


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
    把头部动作映射为游戏控制。

    映射规则（本轮重做）
    --------------------
        · 横向平移（脸框中心位移，**以脸宽为单位**） ┐
        · 左右摇头（关键点估出的 yaw）              ┴→ 软最大融合 → axis
        · 抬头（关键点估出的 pitch 为主 + 纵向位移为辅） → up / head_y / jump

    为什么是这三个改动（对应"摇头和抬头经常识别错误"）：

    1. **单位从"画面比例"改成"人脸尺度"。**
       旧实现用 `cx - 中性x` 再除以画面宽 —— 于是灵敏度随坐姿远近翻倍变化
       （坐近太灵、坐远推不动）。除以脸宽/脸高之后就与距离无关了。

    2. **摇头并入横向控制。**
       转头时脸框中心几乎不动（侧脸还会让框收缩、中心反向偏），所以旧实现里
       "摇头"几乎不产生控制量。yaw 来自鼻尖相对眼线的偏移，是尺度无关的，
       正好补上这一路。两路归一化后做软最大融合：谁信号强就听谁的。

    3. **抬头改用俯仰为主。**
       旧实现只看脸框中心的 cy 位移，而 cy 同时受"前后移动 / 坐姿下滑 / 耸肩"
       影响。俯仰由鼻尖在"眼线→嘴线"上的相对位置算出，对这些干扰免疫得多。

    另外还加了：姿态置信门（侧脸时关键点退化，就这一帧不用姿态量）、
    动作键迟滞（防阈值抖动连发）、中性位自适应（防坐姿缓慢漂移被当成一直抬头）。
    """

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        C = self.cfg
        # 校准采样：(cx, cy, w, h, yaw, pitch, pose_ok)
        self._samples: List[Tuple[float, ...]] = []
        self.neutral: Optional[Tuple[float, float]] = None   # 兼容：仅 (cx, cy)
        self.nw = 0.18           # 中性地脸宽（归一化）
        self.nh = 0.22           # 中性时脸高（归一化）
        self.nyaw = 0.0          # 中性时的 yaw 读数（正脸对着镜头不等于读数为 0）
        self.npitch = 0.0        # 中性时的 pitch 读数
        self.axis = 0.0
        self.jump = False
        self.up = 0.0
        self.head_y = 0.0
        self.yaw = 0.0
        self.pitch = 0.0
        self.found = False
        self.tracking = False          # 迟滞后的"可用"状态（见 update）
        self.quality = "good"          # 识别质量分级（good/far/poor/angle/lost）
        self.confidence = 1.0          # 当前 detector 置信度（0~1）
        self._q_raw = "good"           # 逐帧原始判定（未经迟滞）
        self._q_t = 0.0                # 判定已持续多久（迟滞用）
        self.lost_t = 99.0             # 连续丢检时长
        self.calibrating = True
        self.progress = 0.0
        self._jump_t = 0.0             # 动作键已按住时长
        self._gap_t = 99.0             # 距上次松开时长
        self._prev_w = 0.0
        self._odd_t = 0.0              # "位移与尺度不自洽"已持续的时长
        # ---- 抗抖动状态 ----
        self._yaw_lp = 0.0             # 摇头信号的低通值（现在是 One Euro 的输出）
        # One Euro 自适应滤波：静止时重滤波锁住噪声，移动时按速度抬高截止频率、减少滞后。
        # beta=0 即退回原来的固定低通，所以这一层是"可回退的增益"，不是替换。
        self._yaw_of = OneEuroFilter(C.YAW_MIN_CUTOFF, C.YAW_EURO_BETA,
                                     C.YAW_EURO_DCUT, C.YAW_EURO_SPEED_DEAD)
        self._axis_of = OneEuroFilter(C.AXIS_MIN_CUTOFF, C.AXIS_EURO_BETA,
                                      C.AXIS_EURO_DCUT, C.AXIS_EURO_SPEED_DEAD)
        # 速率上限（运动学约束）：先把"只在一帧里离群"的尖峰削幅，再送进滤波。
        # 顺序不能反 —— 先滤波的话，尖峰的瞬时速度会先把 One Euro 的截止顶上去，
        # 这层限制就失去意义了。
        self._yaw_rl = RateLimiter(C.YAW_MAX_RATE)
        self._arm_t = 0.0              # "想离开死区"已持续的时长（起振门限用）
        self._axis_on = False          # 上一次横向输出是否非零
        self._move_on = False          # 平移那一路是否已在死区外（迟滞用）
        self._yaw_on = False           # 摇头那一路是否已在死区外（迟滞用）
        self._settled_t = 0.0          # 校准完成后经过的时长（前几秒基线收敛更快）
        self._calib_pose_frames = 0    # 校准里姿态可信的帧数（用于提示用户）
        self._debug: dict = {}         # 给诊断用：各路原始信号

    def _zero(self) -> None:
        """进入 LOST：**立即**归零，不做缓慢衰减。"""
        self.axis = 0.0
        self.up = 0.0
        self.head_y = 0.0
        self.yaw = 0.0
        self.pitch = 0.0
        self.jump = False
        # 滤波器状态必须跟着一起作废。它内部保存着"上一次的输出与速度"，
        # 只把输出置 0 而不清状态的话，重新捕获时滤波器会从旧状态往追，
        # 既产生滞后，又可能在换了基线之后甩出一次反向跳动。
        self._yaw_lp = 0.0
        self._yaw_rl.reseed(0.0)
        self._yaw_of.reseed(0.0)
        self._axis_of.reseed(0.0)

    # ------------------------------------------------------------------ 主循环
    def update(self, st: FaceState, dt: float) -> None:
        """
        三段状态机（TRACKING / HOLD / LOST）。

        关键取舍：短暂丢检时**冻结**输出而不是衰减 ——
        检测闪烁时"衰减"会让角色随每次漏检往中间滑一下再弹回去，
        看起来就是它自己在乱动；冻结则完全没有可见变化。
        真正丢失之后就立即归零，不留"滑行"的尾巴。
        """
        C = self.cfg
        self.found = st.found
        self._assess(st, dt)

        if not st.found:
            self.lost_t += dt
            if self.lost_t <= C.HOLD_AFTER:
                return                     # HOLD：保持上一帧的有效输出，一点不变
            self._zero()                   # LOST：立即停住
            self.tracking = False
            self._prev_w = 0.0
            return

        was_lost = self.lost_t > C.HOLD_AFTER
        self.lost_t = 0.0
        self.tracking = True

        if self.calibrating:
            self._samples.append((st.cx, st.cy, st.w, st.h, st.yaw, st.pitch,
                                  1.0 if st.pose_ok else 0.0))
            self.progress = min(1.0, len(self._samples) / C.CALIB_FRAMES)
            self.axis = self.up = self.head_y = self.yaw = self.pitch = 0.0
            self.jump = False
            if len(self._samples) >= C.CALIB_FRAMES:
                self._settle_neutral()
                self.calibrating = False
            self._prev_w = st.w
            return

        # ---- 尺度突变保护：单帧跳变 ----
        # 检测跳变（换了一张脸、框突然收缩到一半）在**尺度归一化之后会被放大**：
        # 分母小了，同样的位移算出来是好几倍。一帧就足以把角色甩到边上。
        if self._prev_w > 1e-4 and st.w > 1e-4:
            ratio = st.w / self._prev_w
            if ratio < 0.55 or ratio > 1.80:
                self._prev_w = st.w
                return
        self._prev_w = st.w

        ncx, ncy = self.neutral  # type: ignore[misc]

        # ---- 位移与尺度不自洽保护 ----
        # 只挡单帧跳变是不够的：如果假阳性连续出现（墙上的图案是静止的，
        # 它会**每帧都出现**），第二帧起尺度就"稳定"了，保护失效，
        # 于是 cx 落在画面边缘的假脸照样能把轴量打满。
        #
        # 判据是自洽性：真人移动时位置与大小是**耦合**的 —— 横向挪不到一个
        # 身位，脸的大小不会同时变一半。所以"离中性位很远"且"大小也和校准
        # 时差很多"同时成立，基本可以断定这不是同一个人的头。
        if (abs(st.cx - ncx) > C.FACE_JUMP_REL
                and abs(st.w / max(1e-4, self.nw) - 1.0) > C.FACE_SCALE_TOL):
            self._odd_t += dt
            if self._odd_t < C.FACE_ODD_HOLD:
                return                      # 冻结输出（安全的失败方向）
            # 持续超过阈值 → 那不是假阳性，是用户真的挪了位置/换了人。
            # 这时正确做法是重建基线，而不是继续按旧基线输出一个荒唐的值。
            self._rebuild_baseline(st)
            return
        self._odd_t = 0.0

        # ---- 全部换成"人脸尺度"为单位（与坐姿距离无关）----
        fw = max(0.03, self.nw)
        fh = max(0.03, self.nh)
        dx_face = (st.cx - ncx) / fw
        dy_face = (ncy - st.cy) / fh             # 正值 = 抬高

        # ---- 横向：平移 + 摇头，软最大融合 ----
        # ⚠ 摇头必须先做**重低通**再进死区。
        #   摇头 = 鼻尖相对双眼中点的位移 ÷ 半眼距，而检测图上脸宽只有 ~64px、
        #   半眼距只有 ~13px —— **鼻尖 1px 的定位抖动就等于 yaw 噪声 0.07**。
        #   平移那一路量的是 64px 尺度上的位移，信噪比高得多，同一个时间常数够用；
        #   摇头不是。不滤波的话这点噪声会直接变成控制量，现象就是
        #   "头没动，选游戏的地方却一直不停左右选"。
        yaw_raw = (st.yaw - self.nyaw) * C.YAW_SIGN if st.pose_ok else 0.0
        # ① 速率上限：孤立尖峰在这里就被削到阈值以下（真实运动无损）
        # ② One Euro：速度大时抬高截止频率减少滞后，静止时回到重滤波锁噪声
        # ONE_EURO_ENABLE=False 时走原来的固定时间常数，行为分毫不变。
        if C.ONE_EURO_ENABLE:
            self._yaw_lp = self._yaw_of.filter(self._yaw_rl.filter(yaw_raw, dt), dt)
        else:
            self._yaw_lp = lowpass_towards(self._yaw_lp, yaw_raw, C.YAW_TAU, dt)
        yaw_sig = self._yaw_lp if st.pose_ok else 0.0

        # 死区带迟滞：已经在"有控制"状态时用更低的退出阈值，
        # 否则信号停在边界上会被噪声反复推出去、又退回来。
        a_move = _deadzone(dx_face,
                           C.DEADZONE_FACE * (C.AXIS_EXIT if self._move_on else 1.0),
                           C.FULL_SCALE_FACE)
        a_yaw = (_deadzone(yaw_sig,
                           C.YAW_DEADZONE * (C.AXIS_EXIT if self._yaw_on else 1.0),
                           C.YAW_FULL_SCALE) if st.pose_ok else 0.0)
        self._move_on = a_move != 0.0
        self._yaw_on = a_yaw != 0.0

        wm = abs(a_move) * C.MOVE_WEIGHT
        wy = abs(a_yaw) * C.YAW_WEIGHT
        raw = (a_move * wm + a_yaw * wy) / (wm + wy) if (wm + wy) > 1e-6 else 0.0

        # 起振门限：从"静止"进入"有控制"必须持续 AXIS_ARM 秒。
        # 单帧尖峰（一次误检、一次关键点跳变）到这里就被吃掉了 ——
        # 它永远不会变成一个让角色动一下、或者让大厅跳一格的输出。
        if raw != 0.0 and not self._axis_on:
            self._arm_t += dt
            if self._arm_t < C.AXIS_ARM:
                raw = 0.0
        else:
            self._arm_t = 0.0
        self._axis_on = raw != 0.0

        if was_lost:
            # 刚重新捕获：限制单帧跳变。假阳性（墙上的图案、路过的反光）
            # 往往只出现一两帧，限制住就不会把角色一下甩到边上。
            step = C.REACQ_STEP
            raw = max(self.axis - step, min(self.axis + step, raw))

        # 基于时间的平滑：帧率变化时跟随手感保持一致（见 config 里的说明）。
        # 这一路也交给 One Euro —— 它是**最终输出**，其滞后玩家感知最直接：
        # 静止时压住残余抖动，大幅转头时不再拖泥带水。
        if C.ONE_EURO_ENABLE:
            self.axis = self._axis_of.filter(raw, dt)
        else:
            self.axis = lowpass_towards(self.axis, raw, C.HEAD_TAU, dt)
        ky = 1.0 - math.exp(-dt / 0.10)
        self.yaw += ky * (max(-1.0, min(1.0, yaw_sig)) - self.yaw)

        # ---- 纵向：俯仰为主，位移为辅 ----
        # 置信度衰减：低头/侧脸时 2D 关键点的俯仰读数会明显失真（真机实测
        # 转头会把俯仰顶到 +0.32，逼近动作键阈值）。转向越大，俯仰越不可信。
        # 衰减而不是"减掉一个耦合量"：不依赖耦合的符号，失效方向也安全
        # （"转着头时抬头没反应" ≫ "一转头发动机就跳"）。
        p_raw = (st.pitch - self.npitch) if st.pose_ok else 0.0
        if st.pose_ok:
            # 用**原始** st.yaw 而不是减掉基线后的量：这个衰减描述的是
            # "检测器在画面上看到的偏转角有多大"，与基线准不准无关。
            # 基线一旦采歪，用差值去算会把衰减算得过轻，保护失效。
            conf = 1.0 - min(C.PITCH_YAW_SHRINK_MAX,
                             abs(st.yaw) * C.PITCH_YAW_SHRINK)
            p_sig = p_raw * max(0.0, conf)
        else:
            p_sig = 0.0
        b_pitch = (_deadzone(p_sig, C.PITCH_DEADZONE, C.PITCH_FULL_SCALE)
                   if st.pose_ok else 0.0)
        b_move = _deadzone(dy_face, C.DEADZONE_FACE_Y, C.FULL_SCALE_FACE_Y)
        if st.pose_ok:
            # 连续量（瞄准用）留一点位移权重：姿态置信在真假之间切来切去时，
            # 单一来源会让"抬起"这个数突然跳一下。小权重兼作过渡。
            lift = C.PITCH_WEIGHT * b_pitch + C.LIFT_MOVE_WEIGHT * b_move
            jump_sig = b_pitch
        else:
            # 没有可信姿态（Haar 后端 / 侧脸 / 关键点退化）：退回纯位移。
            lift = b_move
            jump_sig = b_move
        self.pitch += (1.0 - math.exp(-dt / 0.09)) * (p_sig - self.pitch)
        self.up = max(0.0, min(1.0, lift))
        self.head_y = max(-1.0, min(1.0, lift))

        # 动作键**只认单一来源**，绝不用融合信号：
        # 融合信号里带着"纵向位移"，而往后靠、耸一下肩、坐姿下滑都会产生位移 ——
        # 那就是"没抬头也触发了动作"的来源。抬头是俯仰变化，位移不是。
        self._settled_t += dt          # 校准后开始计时（基线收敛速度用）
        self._update_jump(jump_sig, st, dt)
        self._adapt(dt, st, a_move, a_yaw, yaw_raw, p_raw,
                    dx_face, dy_face)

        self._debug = {
            "dx_face": round(dx_face, 3), "dy_face": round(dy_face, 3),
            "a_move": round(a_move, 3), "a_yaw": round(a_yaw, 3),
            "yaw": round(st.yaw, 3), "yaw_raw": round(yaw_raw, 3),
            "yaw_sig": round(yaw_sig, 3),
            "pitch_raw": round(p_raw, 3),
            "pitch": round(p_sig, 3),
            "b_pitch": round(b_pitch, 3), "b_move": round(b_move, 3),
            "lift": round(lift, 3), "jump_sig": round(jump_sig, 3),
            "pose_ok": st.pose_ok, "face_w": round(st.w, 3),
            # One Euro 的自适应量：静止时应贴近 min_cutoff，快速转头时明显抬高
            "yaw_cut": round(self._yaw_of.cutoff_now, 2),
            "yaw_spd": round(self._yaw_of.speed, 2),
            "ax_cut": round(self._axis_of.cutoff_now, 2),
        }

    # ------------------------------------------------------------------ 基线重建
    def _rebuild_baseline(self, st: FaceState) -> None:
        """
        把当前这一帧当作新的中性位，并把输出清零。

        用于"位移与尺度持续不自洽"的情况 —— 那通常意味着用户大幅挪了位置、
        换了坐姿，或者镜头前换人了。继续按旧基线输出只会给出一个荒唐的控制量；
        重建基线 + 清零是唯一诚实的选择。用户会看到角色停一下然后恢复正常，
        比被甩到屏幕边上要好得多。
        """
        self.neutral = (st.cx, st.cy)
        self.nw = max(0.04, st.w)
        self.nh = max(0.05, st.h)
        self.nyaw = st.yaw if st.pose_ok else 0.0
        self.npitch = st.pitch if st.pose_ok else 0.0
        self._zero()
        self._odd_t = 0.0

    # ------------------------------------------------------------------ 质量
    _QUALITY_RANK = {"good": 0, "far": 1, "angle": 1, "poor": 2, "lost": 3}

    def _assess(self, st: FaceState, dt: float) -> None:
        """
        给当前识别结果分级，供 UI 提示与降级使用。

        迟滞的方向是刻意的：**变坏要快、变好要慢**。
        · 变差立刻反映（Quality 掉下去时用户需要马上知道为什么不好使）；
        · 恢复要稳定一段更长时间才认可 —— 否则每隔一两帧就good/poor 来回切，
          屏幕上的提示会闪，而玩家根本没觉得中间断过。

        HOLD 期间（短暂丢帧）不算丢失：那只是检测闪烁，与 tracking 的语义一致。
        """
        C = self.cfg
        if not C.QUALITY_ENABLE:
            self.quality, self.confidence = "good", 1.0
            return

        if not st.found:
            conf = 0.0
            raw = "lost" if self.lost_t > C.HOLD_AFTER else self._q_raw
        else:
            conf = max(0.0, min(1.0, st.score))
            # 顺序有意义：脸太小是物理层面的不可靠，比置信度本身更根本
            if st.w < C.QUALITY_MIN_FACE_W:
                raw = "far"
            elif conf < C.QUALITY_MIN_SCORE:
                raw = "poor"
            elif st.pose_ok and abs(st.yaw) > C.QUALITY_MAX_YAW:
                raw = "angle"
            else:
                raw = "good"

        self.confidence = conf
        self._q_raw = raw
        if raw == self.quality:
            self._q_t = 0.0
            return
        self._q_t += dt
        worse = self._QUALITY_RANK.get(raw, 0) > \
            self._QUALITY_RANK.get(self.quality, 0)
        if self._q_t >= (C.QUALITY_POOR_T if worse else C.QUALITY_RECOVER_T):
            self.quality = raw
            self._q_t = 0.0

    # ------------------------------------------------------------------ 动作键
    def _update_jump(self, lift: float, st: FaceState, dt: float) -> None:
        """
        动作键（抬头）的迟滞触发。

        裸阈值 + 噪声 = 阈值附近疯狂抖动，一次抬头会连发好几下 ——
        用户看到的就是"抬头识别错误"。所以进入用高阈值、退出用低阈值，
        并给"按下 / 松开"各自一个最短时长。
        """
        C = self.cfg
        mouth = st.mouth_open > C.MOUTH_OPEN_THRESHOLD
        self._gap_t += dt
        if not self.jump:
            # 质量很差时不再接受**新的**按下。
            # 误触发跳跃是体感里最糟的失败（角色自己跑了），而"暂时不响应"
            # 远比"乱响应"安全；已经按住的不受影响 —— 那会变成
            # "按着按着突然松开"，同样是事故。
            if C.QUALITY_POOR_SUPPRESS_JUMP and self.quality in ("poor", "lost"):
                return
            if mouth or (lift > C.JUMP_ON and self._gap_t >= C.JUMP_MIN_GAP):
                self.jump = True
                self._jump_t = 0.0
        else:
            self._jump_t += dt
            if self._jump_t >= C.JUMP_MIN_HOLD and not mouth and lift < C.JUMP_OFF:
                self.jump = False
                self._gap_t = 0.0

    # ------------------------------------------------------------------ 中性位
    def _settle_neutral(self) -> None:
        """
        从校准采样里取中位数作为中性位，**并剔除离群帧**。

        只取中位数是不够的：真机上出现过"校准时用户在看终端"，24 帧采到的
        yaw 是 +0.53；之后用户转回屏幕（真实 yaw ≈ 0）时，这个 0.53 的基线
        偏差一直在扣 —— 明明正对摄像头，轴量却停在 -0.26，看起来就是"乱动"。
        长窗口 + 按中位数绝对偏差（MAD）剔除离群帧后，这种"校准期间瞥了一眼
        别处"能被滤掉。

        yaw / pitch 只取 `pose_ok` 的样本 —— 校准期间难免有几帧侧脸或模糊，
        把它们的退化读数当基线，之后所有转向都会带一个恒定偏差。
        """
        # 丢掉开头几帧：人刚坐下、位置还在动
        pool = self._samples[self.cfg.CALIB_TRIM:] or self._samples

        def median(vals: List[float]) -> float:
            v = sorted(vals)
            return v[len(v) // 2]

        def inliers(idx: int, rows) -> List[float]:
            vals = [r[idx] for r in rows]
            if len(vals) < 5:
                return vals
            m = median(vals)
            dev = sorted(abs(v - m) for v in vals)
            mad = dev[len(dev) // 2]
            tol = max(1e-6, self.cfg.CALIB_MAD_K * mad * 1.4826)
            keep = [v for v in vals if abs(v - m) <= tol]
            return keep or vals

        good = [r for r in pool if r[6] > 0.5]
        pose_pool = good or pool

        self.neutral = (median(inliers(0, pool)), median(inliers(1, pool)))
        self.nw = max(0.04, median(inliers(2, pool)))
        self.nh = max(0.05, median(inliers(3, pool)))
        self.nyaw = median(inliers(4, pose_pool))
        self.npitch = median(inliers(5, pose_pool))
        # 校准用了多少帧是可信的 —— 太少说明采集期间姿态一直不可信
        self._calib_pose_frames = len(good)

    def _adapt(self, dt: float, st: FaceState, a_move: float, a_yaw: float,
               yaw_gate: float, p_raw: float, dx_face: float, dy_face: float) -> None:
        """
        中性位自适应漂移（**逐通道独立**）。

        启动时只标定一次是不够的：人往后靠、身体下滑 20 秒，脸框中心就会
        持续偏移，被当成"一直抬着头" —— 动作键常亮、角色一直在动。

        两个关键设计：

        1. **门限逐通道独立。** 之前用一个总门限，俯仰偏离 0.75 时连横向基线的
           收敛都被卡死了 —— 明明在转头，基线却动不了，角色一直停在偏位。
        2. **校准后头几秒用更快的时间常数。** 校准那 1.3 秒里用户可能在瞥别处，
           基线会带上偏差；让它在用户坐定的头几秒里尽快落到真实休息位。

        门限的语义是"这个量还没有明显表现出操作意图" —— 落在门内的当作休息位
        吸收掉，超出说明玩家是在**故意**保持某个方向，那就绝不能学
        （否则会变成"怎么动都不响应"）。
        """
        C = self.cfg
        # 冷却用的是 `_gap_t`（距上次**松开**动作键的时长，初值 99 秒），
        # 不是 `_jump_t`（已按住时长，从没按过时恒为 0）。
        # 用错计时器的后果很隐蔽：条件恒成立 → 每帧提前返回 →
        # **整个自适应功能变成空操作**，校准歪掉的基线永远回不到中位。
        if self.jump or self._gap_t < C.NEUTRAL_ADAPT_COOLDOWN:
            return
        tau = (C.NEUTRAL_ADAPT_TAU_FAST if self._settled_t < C.NEUTRAL_FAST_WINDOW
               else C.NEUTRAL_ADAPT_TAU)
        k = 1.0 - math.exp(-dt / max(0.3, tau))
        ncx, ncy = self.neutral  # type: ignore[misc]

        # 横向平移：位置与脸宽一起跟随
        if abs(dx_face) < C.NEUTRAL_ADAPT_GATE:
            ncx += k * (st.cx - ncx)
            self.nw += k * (st.w - self.nw)
        # 摇头。门限必须判**原始**读数而不是低通后的值 ——
        # 用低通值会形成反馈环：滤波值从 0 缓慢上升，一开始总是"小于门限"，
        # 于是基线在起振阶段就开始吸收这次转头；基线一动，差值就更小，
        # 环就锁死了。实测后果是"持续转头 4 秒后输出衰减到 0.03"——
        # 玩家会以为"转一会儿就没反应了"。判原始值就没有这个环。
        if st.pose_ok and abs(yaw_gate) < C.NEUTRAL_ADAPT_GATE_YAW:
            self.nyaw += k * (st.yaw - self.nyaw)
        # 纵向平移：位置与脸高一起跟随
        if abs(dy_face) < C.NEUTRAL_ADAPT_GATE:
            ncy += k * (st.cy - ncy)
            self.nh += k * (st.h - self.nh)
        # 俯仰
        if st.pose_ok and abs(p_raw) < C.NEUTRAL_ADAPT_GATE_P:
            self.npitch += k * (st.pitch - self.npitch)

        self.neutral = (ncx, ncy)

    def game_input(self) -> GameInput:
        # found 传的是**迟滞后的**状态：短暂丢帧期间仍然是 True，
        # 这样 shell 的"丢失计时"不会被检测闪烁反复清零。
        return GameInput(axis=self.axis, jump=self.jump, up=self.up,
                         head_y=self.head_y, yaw=self.yaw, found=self.tracking,
                         confidence=self.confidence, quality=self.quality,
                         hint=self.cfg.QUALITY_TIPS.get(self.quality, ""))


# =========================================================================== #
# 手部 → 控制量（ID 跟踪架构，本轮整体重构）
# =========================================================================== #
class _HandTrack:
    """一只被持续跟踪的手（跨帧身份 + 独立滤波）。"""
    __slots__ = ("tid", "x", "y", "open", "area", "miss", "fx", "fy",
                 "_of_x", "_of_y", "_rl_x", "_rl_y", "_seen")

    _NEXT = [1]

    def __init__(self, h: "HandState") -> None:
        self.tid = _HandTrack._NEXT[0]
        _HandTrack._NEXT[0] += 1
        self.x, self.y, self.open, self.area = h.x, h.y, h.open, max(1e-6, h.area)
        self.miss = 0
        self._seen = 1
        C = HandController.cfg_ref
        self._of_x = OneEuroFilter(C.HAND_EURO_MIN_CUT, C.HAND_EURO_BETA,
                                   C.HAND_EURO_DCUT, C.HAND_EURO_SPEED_DEAD)
        self._of_y = OneEuroFilter(C.HAND_EURO_MIN_CUT, C.HAND_EURO_BETA,
                                   C.HAND_EURO_DCUT, C.HAND_EURO_SPEED_DEAD)
        self._rl_x = RateLimiter(C.HAND_MAX_STEP)
        self._rl_y = RateLimiter(C.HAND_MAX_STEP)
        self.fx, self.fy = self._of_x.filter(h.x, 1 / 30.0), self._of_y.filter(h.y, 1 / 30.0)

    def update(self, h: "HandState", dt: float) -> None:
        """喂入观测，更新滤波输出。x/y 更新为原始观测（关联用），fx/fy 为滤波值。"""
        self.x, self.y = h.x, h.y
        self.open = h.open
        self.area = max(1e-6, h.area)
        self.miss = 0
        self._seen += 1
        self.fx = self._of_x.filter(self._rl_x.filter(h.x, dt), dt)
        self.fy = self._of_y.filter(self._rl_y.filter(h.y, dt), dt)


class HandController:
    """
    手部控制的整体架构（重构后）：

        检测流（每帧一串无身份的 HandState）
            ↓ ① 数据关联：贪心最近邻把观测挂到已有 track 上
            ↓ ② track 维护：丢失计数、过期回收
            ↓ ③ 控制权：主手 = 一份**带迟滞的所有权**（挑战者要连续 N 帧
                面积达 M 倍才夺权；闪烁冻结不衰减；真丢失才交还）
            ↓ ④ 输出：主手的 One Euro 滤波坐标（快挥跟手、静止稳定）
                + 张合度边沿（pinch / release）

    为什么必须这么改（旧架构的病灶）：
        旧实现每帧独立"选一只主手"。快速挥动时 21 点检测必然闪烁，
        `HAND_LOST_AFTER=0.6s` 一到就清空主手记忆 → 下一次检测回来重新选
        → 光标跳走。**挥得越快、跟得越错** —— 切水果这类快速挥动游戏
        直接不可用，这就是用户看到的"完全对不上"。
        头部那套 TRACKING/HOLD/LOST 的迟滞语义在这里同样成立，
        只不过它从来没被搬到手上。
    """

    cfg_ref = None      # _HandTrack 构造时需要 config；由 __init__ 注入

    def __init__(self, cfg) -> None:
        HandController.cfg_ref = cfg
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        C = self.cfg
        self.sx = 0.5
        self.sy = 0.5
        self.sopen = 0.0
        self.seen = False
        self.lost_t = 99.0
        # 手势边沿（语义与旧版一致，游戏代码无需改）
        self.pinch = False
        self.release = False
        self._closed_frames = 0
        self._was_closed = False
        self._pinch_fired = False
        self._armed = False
        # ID 跟踪状态
        self._tracks: List[_HandTrack] = []
        self._main: Optional[_HandTrack] = None     # 控制权持有者
        self._chall: Optional[Tuple[_HandTrack, int]] = None
        self._hold_t = 0.0                          # 主手连续未观测时长
        self._debug: dict = {}

    # ------------------------------------------------------------------ 关联
    _ASSOC_DIST = 0.28      # 观测与 track 的常规关联半径（画面比例）
    _ASSOC_HARD = 0.55      # 硬上限：超过这个距离绝不当成同一只手

    def _associate(self, hands: List[HandState], dt: float) -> None:
        """
        贪心最近邻关联：把每帧观测挂到跨帧 track 上。

        两档门限（血泪教训：只有一档会丢目标）：
          · 常规档 0.28：正常情况，多候选时按此判"谁是谁"；
          · 追赶档：唯一的候选离 track 较远（0.28~0.55）时**仍然关联** ——
            快速挥动一步跨 0.3+ 是真实存在的，若当作"新手"另起 track，
            主手就永远停在原地（上一版"轨迹对不上"的变体）。
            只有当画面里**同时**出现多个候选、或距离超过硬上限时，
            才放弃追赶 —— 那多半真的是另一只手。
        """
        C = self.cfg
        obs = [(h, i) for i, h in enumerate(hands)]
        pairs: List[Tuple[float, _HandTrack, int]] = []
        alone = len(hands) == 1
        for tr in self._tracks:
            for h, i in obs:
                d = math.hypot(h.x - tr.x, h.y - tr.y)
                if d <= self._ASSOC_DIST or (alone and d <= self._ASSOC_HARD):
                    pairs.append((d, tr, i))
        pairs.sort(key=lambda p: p[0])
        used_t: set = set()
        used_o: set = set()
        for d, tr, i in pairs:
            if id(tr) in used_t or i in used_o:
                continue
            used_t.add(id(tr))
            used_o.add(i)
            tr.update(hands[i], dt)
        # 未关联上的观测 → 新 track（可能是新手，也可能是闪烁后回归的老手
        # —— 由"谁先赢得控制权"决定，不在这里猜身份）
        for h, i in obs:
            if i not in used_o:
                self._tracks.append(_HandTrack(h))
        # 未观测到的 track：丢失计数 + 位置冻结（不外推 —— 手不像头有惯性可借）
        for tr in self._tracks:
            if id(tr) not in used_t:
                tr.miss += 1

    def _gc_tracks(self) -> None:
        """回收长时间没有观测的 track。"""
        C = self.cfg
        keep = []
        for tr in self._tracks:
            if tr.miss > int(C.HAND_LOST_AFTER * 30):
                if self._main is tr:
                    self._main = None
                continue
            keep.append(tr)
        self._tracks = keep

    # ------------------------------------------------------------------ 控制权
    def _update_owner(self) -> None:
        """
        主手 = 控制权（带迟滞）。

        三条规则：
          ① 没有现任 → 选取"观测最连续"的（面积只作平手判据）。
          ② 有现任 → 现任享有优势；挑战者必须连续 HAND_TAKEOVER_FRAMES 帧
             面积达 HAND_TAKEOVER_RATIO 倍才夺权。
          ③ 现任连续 HAND_LOST_AFTER 没被观测 → 控制权交还（手真的离开了）。
        """
        C = self.cfg
        live = [t for t in self._tracks if t.miss == 0]
        stale_ok = [t for t in self._tracks if t.miss <= int(C.HAND_LOST_AFTER * 30)]

        # ③ 现任彻底消失
        if self._main is not None and self._main not in stale_ok:
            self._main = None
            self._chall = None

        # ① 选取新任
        if self._main is None:
            if live:
                # 观测最连续者优先（_seen 大 = 稳定出现），面积平手判据
                self._main = max(live, key=lambda t: (t._seen, t.area))
                self._chall = None
            return

        # ② 挑战者判定（只在现任也活着的时候比，闪烁期不夺权）
        if live and self._main.miss == 0:
            cand = max(live, key=lambda t: t.area)
            if (cand is not self._main
                    and cand.area > self._main.area * C.HAND_TAKEOVER_RATIO):
                if self._chall is not None and self._chall[0] is cand:
                    n = self._chall[1] + 1
                else:
                    n = 1
                self._chall = (cand, n)
                if n >= C.HAND_TAKEOVER_FRAMES:
                    self._main = cand
                    self._chall = None
            else:
                self._chall = None

    # ------------------------------------------------------------------ 主循环
    def update(self, hands: List[HandState], dt: float) -> None:
        C = self.cfg
        self.pinch = False
        self.release = False

        self._associate(hands, dt)
        self._gc_tracks()
        self._update_owner()

        main = self._main
        if main is None:
            self.lost_t += dt
            if self.lost_t > C.HAND_LOST_AFTER:
                self.seen = False
                # 手真的离开了：把**边沿状态全部复位**。
                # 只解除 _armed 是不够的（血泪教训）：一次没走完的捏合流程
                # 留下的 _closed_frames/_was_closed/_pinch_fired 若不清掉，
                # 重新捕获一只一直握着的手时会凭空补触发一次捏合 ——
                # 玩家根本没做"张开→握拢"的动作。
                self._armed = False
                self._was_closed = False
                self._closed_frames = 0
                self._pinch_fired = False
                self.sopen = 0.0          # 张合度也归零：新手的第一个观测
                                              # 必须从头建立，不吃旧平滑值
            return

        # HOLD / LOST：与头部同一套迟滞语义。
        # 闪烁期间（主手短暂没观测到）**冻结**输出 —— 绝不衰减：
        # 衰减会让光标往中间滑，闪烁恢复又弹回，正是抖动的来源。
        if main.miss > 0:
            self._hold_t += dt
            if self._hold_t <= C.HAND_HOLD_AFTER:
                self.seen = True          # HOLD：保持上一帧输出不变
                return
            # 超过 HOLD 还没回来 → 按"手已离开"处理。
            # 边沿状态一并复位（理由同 main is None 分支）：
            # 一段没走完的捏合流程 + 之后重新出现的手 = 凭空触发。
            # ⚠ _armed 也必须解：它守的是"先观察到张开，才允许捏合边沿"，
            # 而丢失本身就是这个语义链的断裂。只清其他三个、留着 _armed，
            # 重新捕获一只一直握着的手照样凭空触发（实测踩过）。
            if self.seen:
                self._armed = False
                self._was_closed = False
                self._closed_frames = 0
                self._pinch_fired = False
            self.seen = False
            self.lost_t += dt
            return
        self._hold_t = 0.0
        self.lost_t = 0.0

        # 正常输出：主手的滤波坐标（One Euro + 速率限制）
        self.sx, self.sy = main.fx, main.fy
        k = 1.0 - math.exp(-dt / max(1e-3, C.HAND_TAU))
        self.sopen += k * (main.open - self.sopen)
        self.seen = True

        if self.sopen > C.HAND_OPEN_THRESHOLD:
            self._armed = True

        closed = self.sopen < C.HAND_CLOSE_THRESHOLD
        if closed:
            self._closed_frames += 1
            if self._armed and self._closed_frames >= 2 and not self._pinch_fired:
                self.pinch = True
                self._pinch_fired = True
            self._was_closed = True
        else:
            self._closed_frames = 0
            if self._was_closed and self.sopen > C.HAND_OPEN_THRESHOLD:
                self.release = True
                self._was_closed = False
            self._pinch_fired = False

        self._debug = {
            "tid": main.tid, "miss": main.miss, "hold": round(self._hold_t, 2),
            "tracks": len(self._tracks),
            "raw": (round(main.x, 3), round(main.y, 3)),
        }

    @property
    def grab_hold(self) -> bool:
        return self._was_closed

    # ------------------------------------------------------------------ 应用
    def apply(self, inp: GameInput, hands: List[HandState] = None) -> GameInput:
        """
        把主手状态写进 GameInput。

        hands 参数保留兼容（旧签名），但主手选择已在 update 里完成，
        这里**绝不再重选** —— 否则又回到"坐标跟 A、状态取 B"的错位。
        """
        inp.hands = hands or []
        if hands:
            hs = sorted(hands, key=lambda h: h.x)
            inp.hand_l = hs[0]
            inp.hand_r = hs[-1] if len(hs) > 1 else hs[0]
            # 手指计数用现任主手（与坐标同源，避免错位）
            if self._main is not None and self._main.miss == 0:
                m = next((h for h in hands
                          if math.hypot(h.x - self._main.x, h.y - self._main.y) < 0.05),
                         None)
                inp.fingers = m.fingers if m else 0
        inp.hand_found = self.seen
        inp.hx, inp.hy = self.sx, self.sy
        inp.hand_open = self.sopen
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
        self.tracking = False
        self.lost_t = 99.0
        self.lb_visible = False
        self.calibrating = True
        self.progress = 0.0

    def _zero(self) -> None:
        self.body_x = 0.0
        self.crouch = 0.0
        self.arm_l = self.arm_r = 0.0
        self.arm_l_ext = self.arm_r_ext = 0.0
        self.lean = 0.0
        self.hands_up = 0

    def update(self, pose, dt: float) -> None:
        C = self.cfg
        ok = pose is not None and getattr(pose, "found", False)
        self.found = bool(ok)
        if not ok:
            # 与头部同一套迟滞逻辑：短暂丢帧冻结（姿态模型本来就隔帧跑，
            # 逐帧判定会让动作在"有/无"之间抖），真丢了才立即归零。
            self.lost_t += dt
            if self.lost_t <= C.HOLD_AFTER:
                return
            self._zero()
            self.tracking = False
            return

        was_lost = self.lost_t > C.HOLD_AFTER
        self.lost_t = 0.0
        self.tracking = True

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
        if was_lost:
            step = C.REACQ_STEP
            raw = max(self.body_x - step, min(self.body_x + step, raw))
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
        # 传迟滞后的状态：HOLD 期间仍是"有身体"，LOST 之后立刻变成"没有"，
        # 否则 GameInput.xc 会拿着冻结的陈旧 body_x 让角色继续横移。
        inp.body_found = self.tracking
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
