"""
core/vision/types.py
====================
跨平台骨骼规范：所有视觉后端都必须把结果翻译成这里定义的结构。

为什么要有这层
--------------
不同平台的"主流 SOTA"方案完全不同：

    macOS / iOS     Apple Vision      （19 点人体 + 21 点手，跑在 ANE 上）
    Windows / Linux MediaPipe         （33 点 BlazePose + 21 点手，TFLite）
    任何平台        ONNX Runtime      （RTMPose 17/133 点，可挂 CoreML/DirectML/CUDA EP）

如果游戏直接依赖某一家，就被绑死了。所以这里定一套**内部规范**，
各后端负责映射进来，游戏代码只认规范，换后端不改游戏：

    人体：COCO-17（业界最通用的 17 关键点定义）
    手部：21 点（每根手指 4 点 + 腕，与 MediaPipe / Vision 一致）

坐标系：**图像归一化坐标，左上角为原点，x 向右、y 向下**。
（Apple Vision 原生是左下原点，映射时翻转 y；MediaPipe 本来就是左上原点。）
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# COCO-17 —— 内部统一的人体骨架规范
# --------------------------------------------------------------------------- #
COCO17: Tuple[str, ...] = (
    "nose",
    "left_eye", "right_eye",
    "left_ear", "right_ear",
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
)

# COCO-17 的骨架连线（用于画火柴人）
COCO17_EDGES: Tuple[Tuple[str, str], ...] = (
    ("left_shoulder", "right_shoulder"),
    ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
    ("left_shoulder", "left_hip"), ("right_shoulder", "right_hip"),
    ("left_hip", "right_hip"),
    ("left_hip", "left_knee"), ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"), ("right_knee", "right_ankle"),
    ("nose", "left_eye"), ("nose", "right_eye"),
    ("left_eye", "left_ear"), ("right_eye", "right_ear"),
)

# 手部 21 点（与 MediaPipe Hand / Vision 的顺序一致）
HAND_JOINTS: Tuple[str, ...] = (
    "wrist",
    "thumb_cmc", "thumb_mcp", "thumb_ip", "thumb_tip",
    "index_mcp", "index_pip", "index_dip", "index_tip",
    "middle_mcp", "middle_pip", "middle_dip", "middle_tip",
    "ring_mcp", "ring_pip", "ring_dip", "ring_tip",
    "little_mcp", "little_pip", "little_dip", "little_tip",
)
HAND_EDGES: Tuple[Tuple[str, str], ...] = (
    ("wrist", "thumb_cmc"), ("thumb_cmc", "thumb_mcp"),
    ("thumb_mcp", "thumb_ip"), ("thumb_ip", "thumb_tip"),
    ("wrist", "index_mcp"), ("index_mcp", "index_pip"),
    ("index_pip", "index_dip"), ("index_dip", "index_tip"),
    ("wrist", "middle_mcp"), ("middle_mcp", "middle_pip"),
    ("middle_pip", "middle_dip"), ("middle_dip", "middle_tip"),
    ("wrist", "ring_mcp"), ("ring_mcp", "ring_pip"),
    ("ring_pip", "ring_dip"), ("ring_dip", "ring_tip"),
    ("wrist", "little_mcp"), ("little_mcp", "little_pip"),
    ("little_pip", "little_dip"), ("little_dip", "little_tip"),
    ("index_mcp", "middle_mcp"), ("middle_mcp", "ring_mcp"),
    ("ring_mcp", "little_mcp"),
)
FINGERS: Tuple[Tuple[str, str], ...] = (
    ("thumb", "thumb_tip"), ("index", "index_tip"),
    ("middle", "middle_tip"), ("ring", "ring_tip"), ("little", "little_tip"),
)

# 点可见性的置信度门槛：低于它视为"该关节不可见"
CONF_MIN = 0.28


# --------------------------------------------------------------------------- #
@dataclass
class Joint:
    """单个关节。坐标是图像归一化坐标（左上原点）。"""
    x: float = 0.5
    y: float = 0.5
    conf: float = 0.0

    @property
    def ok(self) -> bool:
        return self.conf >= CONF_MIN


def _mid(a: Joint, b: Joint) -> Tuple[float, float]:
    return ((a.x + b.x) * 0.5, (a.y + b.y) * 0.5)


def _dist(a: Joint, b: Joint) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


@dataclass
class PoseFrame:
    """
    一帧人体骨骼。

    除了 17 个原始关节，还预计算了体感游戏真正要用的**派生量** ——
    这些才是"动作"的语义层，游戏直接用它们，不用自己算几何。
    """
    found: bool = False
    joints: Dict[str, Joint] = field(default_factory=dict)
    source: str = "-"

    # ---------------- 基础访问 ----------------
    def get(self, name: str) -> Joint:
        return self.joints.get(name, Joint(conf=0.0))

    def has(self, *names: str) -> bool:
        return all(self.get(n).ok for n in names)

    # ---------------- 派生量 ----------------
    @property
    def head(self) -> Joint:
        """头部位置：优先鼻尖，其次双眼中点，再次双耳中点。"""
        n = self.get("nose")
        if n.ok:
            return n
        le, re = self.get("left_eye"), self.get("right_eye")
        if le.ok and re.ok:
            x, y = _mid(le, re)
            return Joint(x, y, min(le.conf, re.conf))
        le, re = self.get("left_ear"), self.get("right_ear")
        if le.ok and re.ok:
            x, y = _mid(le, re)
            return Joint(x, y, min(le.conf, re.conf))
        return Joint(conf=0.0)

    @property
    def shoulder_mid(self) -> Joint:
        a, b = self.get("left_shoulder"), self.get("right_shoulder")
        if a.ok and b.ok:
            x, y = _mid(a, b)
            return Joint(x, y, min(a.conf, b.conf))
        return a if a.ok else b

    @property
    def hip_mid(self) -> Joint:
        a, b = self.get("left_hip"), self.get("right_hip")
        if a.ok and b.ok:
            x, y = _mid(a, b)
            return Joint(x, y, min(a.conf, b.conf))
        return a if a.ok else b

    @property
    def body_center(self) -> Joint:
        """身体中心：优先肩髋中点，只有上半身时用肩中点。"""
        s, h = self.shoulder_mid, self.hip_mid
        if s.ok and h.ok:
            x, y = _mid(s, h)
            return Joint(x, y, min(s.conf, h.conf))
        return s if s.ok else (h if h.ok else self.head)

    @property
    def scale(self) -> float:
        """
        身体尺度参考（归一化）：肩宽优先，其次"肩到髋"距离。
        所有"位移多少算大动作"的判断都要除以它，否则远近不同的人手感完全不同。
        """
        ls, rs = self.get("left_shoulder"), self.get("right_shoulder")
        if ls.ok and rs.ok:
            d = _dist(ls, rs)
            if d > 0.02:
                return d
        s, h = self.shoulder_mid, self.hip_mid
        if s.ok and h.ok:
            d = _dist(s, h)
            if d > 0.02:
                return d
        return 0.22

    @property
    def torso_lean(self) -> float:
        """躯干前倾/侧倾：肩中点相对髋中点的水平偏移（除以身体尺度）。"""
        s, h = self.shoulder_mid, self.hip_mid
        if not (s.ok and h.ok):
            return 0.0
        return (s.x - h.x) / max(1e-4, self.scale)

    @property
    def head_yaw(self) -> float:
        """头部左右转 -1~1：鼻尖相对双眼中点的偏移。"""
        n = self.get("nose")
        le, re = self.get("left_eye"), self.get("right_eye")
        if not (n.ok and le.ok and re.ok):
            return 0.0
        ex, _ = _mid(le, re)
        eye_d = max(1e-4, _dist(le, re))
        return max(-1.0, min(1.0, (n.x - ex) / eye_d * 1.6))

    @property
    def head_roll(self) -> float:
        """头部倾斜（弧度）。"""
        le, re = self.get("left_eye"), self.get("right_eye")
        if not (le.ok and re.ok):
            return 0.0
        return math.atan2(re.y - le.y, max(1e-4, re.x - le.x))

    @property
    def head_pitch(self) -> float:
        """头部俯仰 -1(低头)~1(抬头)：鼻尖到眼线的距离相对眼-耳距离。"""
        n = self.get("nose")
        le, re = self.get("left_eye"), self.get("right_eye")
        if not (n.ok and le.ok and re.ok):
            return 0.0
        _, ey = _mid(le, re)
        eye_d = max(1e-4, _dist(le, re))
        k = (n.y - ey) / eye_d
        return max(-1.0, min(1.0, (0.62 - k) * 2.2))

    # ---------------- 手臂 ----------------
    def wrist(self, side: str) -> Joint:
        return self.get(f"{side}_wrist")

    def elbow(self, side: str) -> Joint:
        return self.get(f"{side}_elbow")

    def shoulder(self, side: str) -> Joint:
        return self.get(f"{side}_shoulder")

    def arm_raised(self, side: str) -> float:
        """
        举手程度 0~1：手腕高于肩部多少（按身体尺度归一）。
        0 = 手腕在肩以下，1 = 手腕比肩高一个肩宽。
        """
        w, s = self.wrist(side), self.shoulder(side)
        if not (w.ok and s.ok):
            return 0.0
        return max(0.0, min(1.0, (s.y - w.y) / max(1e-4, self.scale)))

    def arm_extended(self, side: str) -> float:
        """
        手臂伸展度 0~1：0 = 完全弯曲（手贴肩），1 = 完全伸直。
        用"腕到肩距离 / (上臂+前臂长度)"衡量。
        """
        s, e, w = self.shoulder(side), self.elbow(side), self.wrist(side)
        if not (s.ok and e.ok and w.ok):
            return 0.0
        full = _dist(s, e) + _dist(e, w)
        if full < 1e-4:
            return 0.0
        return max(0.0, min(1.0, _dist(s, w) / full))

    def arm_direction(self, side: str) -> Tuple[float, float]:
        """手臂指向（肩→腕的单位向量）。"""
        s, w = self.shoulder(side), self.wrist(side)
        if not (s.ok and w.ok):
            return (0.0, 0.0)
        dx, dy = w.x - s.x, w.y - s.y
        d = math.hypot(dx, dy) or 1.0
        return (dx / d, dy / d)

    def hands_up(self) -> int:
        """举起了几只手（手腕高于肩）。"""
        return sum(1 for s in ("left", "right") if self.arm_raised(s) > 0.18)

    def arms_spread(self) -> float:
        """双手水平张开度：两腕水平距离 / 身体尺度。"""
        l, r = self.get("left_wrist"), self.get("right_wrist")
        if not (l.ok and r.ok):
            return 0.0
        return abs(l.x - r.x) / max(1e-4, self.scale)

    # ---------------- 下半身 ----------------
    def leg_lifted(self, side: str) -> float:
        """
        抬腿程度 0~1：踝关节高于髋部多少（按身体尺度）。
        只有下半身入镜时才有意义。
        """
        a, h = self.get(f"{side}_ankle"), self.hip_mid
        if not (a.ok and h.ok):
            return 0.0
        return max(0.0, min(1.0, (h.y - a.y) / max(1e-4, self.scale * 1.6)))

    def leg_extended(self, side: str) -> float:
        h, k, a = self.get(f"{side}_hip"), self.get(f"{side}_knee"), self.get(f"{side}_ankle")
        if not (h.ok and k.ok and a.ok):
            return 0.0
        full = _dist(h, k) + _dist(k, a)
        if full < 1e-4:
            return 0.0
        return max(0.0, min(1.0, _dist(h, a) / full))

    @property
    def crouch(self) -> float:
        """
        下蹲程度 0~1（越大越蹲）。用"肩到髋距离 / 肩宽"衡量 ——
        比用绝对高度稳定，人靠近或远离摄像头都不受影响。
        """
        s, h = self.shoulder_mid, self.hip_mid
        if not (s.ok and h.ok):
            return 0.0
        torso = _dist(s, h) / max(1e-4, self.scale)
        # 直立时约 1.5~1.9，蹲下时会明显变小
        return max(0.0, min(1.0, (1.55 - torso) / 0.70))

    def lower_body_visible(self) -> bool:
        """下半身是否入镜（决定能不能做踢腿/跳跃类玩法）。"""
        return self.has("left_hip", "right_hip") and (
            self.has("left_knee", "right_knee") or
            self.has("left_ankle", "right_ankle"))

    def coverage(self) -> int:
        """可见关节数，用于判断整体检测质量。"""
        return sum(1 for j in self.joints.values() if j.ok)


@dataclass
class HandFrame:
    """一只手的 21 关键点 + 派生手势量。"""
    found: bool = False
    side: str = "?"                      # left / right / ?
    joints: Dict[str, Joint] = field(default_factory=dict)
    source: str = "-"
    # 有些后端（如 OpenCV 兜底）拿不到真实关键点，只能给一个整体的张开度估计。
    # 这里允许它们直接注入，>=0 时以它为准。
    open_hint: float = -1.0

    def get(self, name: str) -> Joint:
        return self.joints.get(name, Joint(conf=0.0))

    # ---------------- 尺度 ----------------
    @property
    def palm_width(self) -> float:
        """掌宽：食指根 → 小指根。所有手势阈值都以它为基准，天然与远近无关。"""
        a, b = self.get("index_mcp"), self.get("little_mcp")
        if a.ok and b.ok:
            return max(1e-4, _dist(a, b))
        w, m = self.get("wrist"), self.get("middle_mcp")
        if w.ok and m.ok:
            return max(1e-4, _dist(w, m) * 0.86)
        return 0.08

    @property
    def center(self) -> Joint:
        """掌心中心（用四个指根 + 腕的平均，比单点稳）。"""
        names = ("wrist", "index_mcp", "middle_mcp", "ring_mcp", "little_mcp")
        pts = [self.get(n) for n in names]
        pts = [p for p in pts if p.ok]
        if not pts:
            return Joint(conf=0.0)
        return Joint(sum(p.x for p in pts) / len(pts),
                     sum(p.y for p in pts) / len(pts),
                     min(p.conf for p in pts))

    # ---------------- 手势 ----------------
    @property
    def pinch(self) -> float:
        """捏合度 0~1：0 = 拇指与食指完全分开，1 = 完全捏住。除以掌宽做归一。"""
        t, i = self.get("thumb_tip"), self.get("index_tip")
        if not (t.ok and i.ok):
            return 0.0
        d = _dist(t, i) / self.palm_width
        return max(0.0, min(1.0, 1.0 - d / 1.15))

    def finger_extended(self, fin: str) -> bool:
        """
        某根手指是否伸直。判据是中国用户习惯的"指尖离腕更远 + 关节不够弯"，
        比单纯比长度稳（避免握拳时指尖仍然略远造成的误判）。
        """
        tip = self.get(f"{fin}_tip")
        pip = self.get(f"{fin}_pip")
        mcp = self.get(f"{fin}_mcp")
        if not (tip.ok and pip.ok):
            return False
        w = self.get("wrist")
        if w.ok:
            d_tip = _dist(tip, w)
            d_pip = _dist(pip, w)
            if d_tip < d_pip * 1.10:
                return False
        if mcp.ok:
            # 近端指节到指尖的方向应与掌面大致同向
            straight = _dist(pip, tip) / max(1e-4, _dist(mcp, pip))
            if straight < 0.72:
                return False
        return True

    @property
    def extended_count(self) -> int:
        return sum(1 for f, _ in FINGERS if f != "thumb" and self.finger_extended(f))

    @property
    def thumb_extended(self) -> bool:
        t, i = self.get("thumb_tip"), self.get("index_mcp")
        if not (t.ok and i.ok):
            return False
        return _dist(t, i) / self.palm_width > 1.05

    @property
    def openness(self) -> float:
        """
        张开度 0~1：张开的手 ≈1，握拳 ≈0。
        有真实关键点就用"伸直手指数"（最稳）；否则用后端注入的估计值。
        """
        if self.open_hint >= 0.0:
            return self.open_hint
        n = self.extended_count + (1 if self.thumb_extended else 0)
        return max(0.0, min(1.0, n / 5.0))

    @property
    def spread(self) -> float:
        """五指分叉角（弧度）的平均值，用于区分"并拢"和"张开成掌"。"""
        w = self.get("wrist")
        if not w.ok:
            return 0.0
        dirs = []
        for fin, tip_name in FINGERS:
            t = self.get(tip_name)
            if not t.ok:
                continue
            dirs.append(math.atan2(t.y - w.y, t.x - w.x))
        if len(dirs) < 3:
            return 0.0
        dirs.sort()
        return max(dirs) - min(dirs)

    @property
    def point_direction(self) -> Tuple[float, float]:
        """食指指向（腕→食指尖的单位向量），用于"指哪打哪"。"""
        t, w = self.get("index_tip"), self.get("wrist")
        if not (t.ok and w.ok):
            return (0.0, 0.0)
        dx, dy = t.x - w.x, t.y - w.y
        d = math.hypot(dx, dy) or 1.0
        return (dx / d, dy / d)

    def is_fist(self) -> bool:
        return self.extended_count <= 1 and not self.thumb_extended

    def is_open(self) -> bool:
        return self.extended_count >= 4

    def is_pointing(self) -> bool:
        return self.finger_extended("index") and self.extended_count <= 1

    def is_pinching(self) -> bool:
        return self.pinch > 0.72

    def as_names(self, names: Tuple[str, ...]) -> List[Tuple[float, float, float]]:
        return [(self.get(n).x, self.get(n).y, self.get(n).conf) for n in names]


# --------------------------------------------------------------------------- #
@dataclass
class VisionFrame:
    """一次检测的完整结果：人体 + 最多两只手。"""
    pose: PoseFrame = field(default_factory=PoseFrame)
    hands: List[HandFrame] = field(default_factory=list)
    source: str = "-"
    ms: float = 0.0

    @property
    def hand_l(self) -> Optional[HandFrame]:
        return next((h for h in self.hands if h.side == "left"), None)

    @property
    def hand_r(self) -> Optional[HandFrame]:
        return next((h for h in self.hands if h.side == "right"), None)

    def main_hand(self) -> Optional[HandFrame]:
        """主控手：取掌心离画面中心最近的那只（用户通常伸一只手过来）。"""
        if not self.hands:
            return None
        return min(self.hands, key=lambda h: math.hypot(h.center.x - 0.5, h.center.y - 0.55))
