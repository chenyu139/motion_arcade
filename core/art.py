"""
core/art.py
===========
高清美术库：把"角色/球/场地"这类反复出现的美术资产统一在这里生成。

设计要点
--------
1. **卡通着色（cel-ish shading）**：任何立体物都不是单色填充，而是
   高光 → 中间调 → 暗部 → 边缘光 四层叠加，这是"看起来更精细"的主因。
2. **超采样烘焙**：全部走 theme.bake()，以 2~4 倍分辨率作画后缩小，
   轮廓天然抗锯齿，1920×1080 下不再有锯齿毛边。
3. **姿态参数化**：人物用骨架（髋/膝/肩/肘角度）描述，一个函数画出
   跑、跳、挥拍、扑救、踢球等所有动作，避免每个游戏各画一套。
4. **零外部素材**：不依赖任何 PNG/3D 模型文件，全部程序化生成，
   既保证可移植，也避免版权问题。
"""
from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pygame

from . import theme as U

Color = Tuple[int, ...]
Point = Tuple[float, float]

TAU = math.tau


# =========================================================================== #
# 卡通着色基础
# =========================================================================== #
def shade_ball(
    r: float,
    color: Sequence[int],
    light: Point = (-0.42, -0.50),
    spec: float = 0.72,
    rim: float = 0.45,
    ss: int = 3,
) -> pygame.Surface:
    """
    生成一颗"有立体感"的球（返回边长 2r 的 Surface）。

    光照模型：平行光 + 高光点 + 边缘光 + 环境遮蔽（底部压暗）。
    这是所有球类运动（足球/网球/篮球/乒乓球）的共用资产。
    """
    r = max(3, int(r))
    size = r * 2

    def _d(s):
        rr = r * ss
        c = (rr, rr)
        # 球体本体：用同心圆近似径向光照
        steps = max(18, int(rr * 0.9))
        base = np.array(color[:3], dtype=np.float32)
        lx, ly = light
        for i in range(steps, 0, -1):
            t = i / steps                                  # 1 外 → 0 内
            rad = rr * t
            # 归一化的"到光心距离"
            px = -lx * (1 - t)
            py = -ly * (1 - t)
            k = 1.0 - math.sqrt(px * px + py * py) * 1.15
            k = U.clamp(k, 0.0, 1.0)
            shade = 0.62 + 0.66 * k * k                     # 暗部 0.62 → 高光 1.28
            col = np.clip(base * shade, 0, 255)
            a = 255
            pygame.draw.circle(s, (int(col[0]), int(col[1]), int(col[2]), a),
                               (int(c[0] + lx * rr * 0.10 * (1 - t)),
                                int(c[1] + ly * rr * 0.10 * (1 - t))), int(rad))
        # 高光
        if spec > 0:
            hx = c[0] + lx * rr * 0.62
            hy = c[1] + ly * rr * 0.62
            hr = max(2, int(rr * 0.26))
            hi = pygame.Surface((hr * 2, hr * 2), pygame.SRCALPHA)
            for i in range(hr, 0, -1):
                a = int(spec * 200 * (1 - i / hr) ** 1.5)
                pygame.draw.circle(hi, (255, 255, 255, a), (hr, hr), i)
            s.blit(hi, (int(hx - hr), int(hy - hr)))
        # 边缘光（背光侧的冷色轮廓，让球从背景里"跳"出来）
        if rim > 0:
            pygame.draw.circle(s, (255, 255, 255, int(rim * 74)), (rr, rr), rr, max(1, int(rr * 0.045)))
            pygame.draw.circle(s, (255, 255, 255, int(rim * 120)), (rr, rr), rr, 1)

    return U.bake(("ball", int(r), tuple(color[:3]), light, spec, rim), (size, size), _d, ss)


def shade_capsule(
    w: float,
    h: float,
    color: Sequence[int],
    light: Point = (-0.55, -0.35),
    round_top: bool = True,
    round_bottom: bool = True,
    ss: int = 3,
) -> pygame.Surface:
    """带横向光照的胶囊/圆柱体（画四肢与躯干）。"""
    w, h = max(2, int(w)), max(2, int(h))

    def _d(s):
        W, H = w * ss, h * ss
        rect = pygame.Rect(0, 0, W, H)
        rad = int(W / 2) if (round_top and round_bottom) else int(W / 2)
        pygame.draw.rect(s, U._safe(color), rect, border_radius=rad)
        # 横向明暗：左亮右暗（光从左上）
        base = np.array(color[:3], dtype=np.float32)
        band = max(1, W // 12)
        for i in range(0, W, band):
            u = i / max(1, W - 1)
            k = 0.60 + 0.72 * math.exp(-((u - 0.30) ** 2) / 0.055)
            col = np.clip(base * k, 0, 255)
            s.fill((int(col[0]), int(col[1]), int(col[2]), 255),
                   (i, int(H * 0.12), band, int(H * 0.76)))
        # 高光条
        gl = max(1, int(W * 0.10))
        s.fill((255, 255, 255, 52), (int(W * 0.22), int(H * 0.16), gl, int(H * 0.52)))

    return U.bake(("cap", w, h, tuple(color[:3]), light), (w, h), _d, ss)


def shade_panel(
    w: float,
    h: float,
    color: Sequence[int],
    radius: int = 10,
    top_light: float = 1.16,
    bottom_light: float = 0.78,
    ss: int = 3,
) -> pygame.Surface:
    """上亮下暗的立体面板（看台、箱体、墙体）。"""
    w, h = max(3, int(w)), max(3, int(h))

    def _d(s):
        W, H = w * ss, h * ss
        base = np.array(color[:3], dtype=np.float32)
        band = max(1, H // 22)
        for y in range(0, H, band):
            u = y / max(1, H - 1)
            k = top_light + (bottom_light - top_light) * u
            col = np.clip(base * k, 0, 255)
            s.fill((int(col[0]), int(col[1]), int(col[2]), 255), (0, y, W, band))
        # 顶部高光边
        s.fill((255, 255, 255, 46), (0, 0, W, max(1, int(H * 0.05))))
        # 抠圆角
        mask = pygame.Surface((W, H), pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255, 255), (0, 0, W, H), border_radius=radius * ss)
        out = pygame.Surface((W, H), pygame.SRCALPHA)
        out.blit(s, (0, 0))
        out.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        s.fill((0, 0, 0, 0))
        s.blit(out, (0, 0))

    return U.bake(("panel", w, h, tuple(color[:3]), radius, top_light, bottom_light),
                  (w, h), _d, ss)


# =========================================================================== #
# 球类
# =========================================================================== #
_BALL_STYLE = {
    "football": {"base": (250, 250, 252), "patch": (26, 28, 36), "kind": "patches"},
    "tennis": {"base": (216, 236, 78), "patch": (252, 252, 240), "kind": "tennis"},
    "basketball": {"base": (226, 122, 54), "patch": (72, 36, 20), "kind": "basket"},
    "pingpong": {"base": (255, 250, 236), "patch": (226, 150, 120), "kind": "plain"},
    "volley": {"base": (248, 246, 240), "patch": (58, 110, 208), "kind": "volley"},
    "bill": {"base": (238, 70, 74), "patch": (255, 255, 255), "kind": "plain"},
}


def ball_sprite(r: float, kind: str = "football", ss: int = 3) -> pygame.Surface:
    """预烘焙球体（带项目特定纹样）。r 为半径。"""
    r = max(4, int(r))
    st = _BALL_STYLE.get(kind, _BALL_STYLE["football"])
    b = shade_ball(r, st["base"], ss=ss)

    def _patches(s):
        # 先把已着色的球体放大铺底，再叠加纹样 —— 否则只剩纹样、球体是透明的
        s.blit(pygame.transform.smoothscale(b, s.get_size()), (0, 0))
        rr = r * ss
        c = rr
        patch = st["patch"]
        k = st["kind"]
        if k == "patches":
            # 足球：中心五边形 + 5 个边缘六边形斑块
            for i in range(5):
                a = -math.pi / 2 + i * TAU / 5
                px = c + math.cos(a) * rr * 0.52
                py = c + math.sin(a) * rr * 0.52
                pr = rr * 0.30
                pts = [(px + math.cos(a + j * TAU / 5 + 0.3) * pr,
                        py + math.sin(a + j * TAU / 5 + 0.3) * pr) for j in range(5)]
                pygame.draw.polygon(s, patch, pts)
            pc = rr * 0.34
            pygame.draw.polygon(s, patch, [
                (c + math.cos(-math.pi / 2 + j * TAU / 5) * pc,
                 c + math.sin(-math.pi / 2 + j * TAU / 5) * pc) for j in range(5)])
        elif k == "tennis":
            # 网球：两条对称的白色弧线
            for sgn in (-1, 1):
                pts = []
                for i in range(24):
                    th = -0.9 + i * 1.8 / 23
                    pts.append((c + sgn * rr * 0.62, c + th * rr * 0.92))
                pygame.draw.lines(s, patch, False, pts, max(2, int(rr * 0.13)))
        elif k == "basket":
            pygame.draw.line(s, patch, (c - rr, c), (c + rr, c), max(2, int(rr * 0.11)))
            pygame.draw.line(s, patch, (c, c - rr), (c, c + rr), max(2, int(rr * 0.11)))
            for sgn in (-1, 1):
                pts = [(c + sgn * rr * 0.86, c + (i / 14 - 0.5) * 2 * rr * 0.72) for i in range(15)]
                pygame.draw.lines(s, patch, False, pts, max(2, int(rr * 0.10)))
        elif k == "volley":
            for sgn in (-1, 1):
                for band in range(3):
                    y0 = c + sgn * rr * (0.22 + band * 0.42)
                    pygame.draw.arc(s, patch,
                                    pygame.Rect(int(c - rr * 0.95), int(y0 - rr * 0.30),
                                                int(rr * 1.9), int(rr * 0.60)),
                                    0, math.pi, max(2, int(rr * 0.12)))
        elif k == "plain":
            pass                     # 纯色球（乒乓球/台球），不加纹样

    return U.bake(("ballp", r, kind), (r * 2, r * 2), _patches, ss)


_ball_rot_cache: Dict[Tuple, pygame.Surface] = {}


def _ball_rot(r: int, kind: str, deg: float) -> pygame.Surface:
    d = int(deg) % 360
    key = (r, kind, d)
    s = _ball_rot_cache.get(key)
    if s is None:
        s = pygame.transform.rotate(ball_sprite(r, kind), d)
        if len(_ball_rot_cache) > 500:
            _ball_rot_cache.clear()
        _ball_rot_cache[key] = s
    return s


def draw_ball(surf: pygame.Surface, cx: float, cy: float, r: float, kind: str = "football",
              rot: float = 0.0, shadow: float = 0.0, ground_y: Optional[float] = None) -> None:
    """
    画一颗球。rot 为自转角（拍面击球/滚动时旋转）。
    shadow>0 时在 ground_y 处画一个椭圆投影（增强空间感）。
    """
    if shadow > 0 and ground_y is not None:
        sw = r * 2.1
        sh = max(3, r * 0.56)
        a = int(U.clamp(shadow, 0, 1) * 110)
        U.aa_ellipse(surf, (int(cx - sw / 2), int(ground_y - sh / 2), int(sw), int(sh)),
                     (0, 0, 0, a), 0, ss=2)
    sp = ball_sprite(r, kind) if not rot else _ball_rot(int(r), kind, math.degrees(rot))
    surf.blit(sp, (int(cx - sp.get_width() / 2), int(cy - sp.get_height() / 2)))


# =========================================================================== #
# 人物：骨架 + 姿态
# =========================================================================== #
class FigureStyle:
    """一套配色即可定义一名球员/角色。"""

    def __init__(
        self,
        shirt: Sequence[int] = (78, 132, 232),
        shirt2: Optional[Sequence[int]] = None,
        pants: Sequence[int] = (34, 42, 66),
        skin: Sequence[int] = (240, 196, 162),
        hair: Sequence[int] = (36, 30, 34),
        shoes: Sequence[int] = (245, 245, 250),
        sock: Optional[Sequence[int]] = None,
        number: str = "",
        num_color: Sequence[int] = (255, 255, 255),
        hair_style: str = "short",
        outline: Optional[Sequence[int]] = (18, 22, 34),
    ):
        self.shirt = tuple(shirt)
        self.shirt2 = tuple(shirt2 if shirt2 is not None else U.shade(shirt, 0.72))
        self.pants = tuple(pants)
        self.skin = tuple(skin)
        self.hair = tuple(hair)
        self.shoes = tuple(shoes)
        self.sock = tuple(sock if sock is not None else shoes)
        self.number = str(number)
        self.num_color = tuple(num_color)
        self.hair_style = hair_style
        self.outline = tuple(outline) if outline else None


# 姿态：各关节角度（弧度）。0 = 竖直向下，正值 = 向前摆。
def pose(**kw) -> Dict[str, float]:
    p = {
        "lean": 0.0,          # 躯干前倾（正 = 前倾）
        "crouch": 0.0,        # 下蹲 0~1
        "arm_l": 0.0, "arm_l2": 0.0,     # 左肩、左肘
        "arm_r": 0.0, "arm_r2": 0.0,     # 右肩、右肘
        "leg_l": 0.0, "leg_l2": 0.0,     # 左髋、左膝
        "leg_r": 0.0, "leg_r2": 0.0,     # 右髋、右膝
        "head": 0.0,          # 头部俯仰
        "flip": 1,            # 1 面向右，-1 面向左
        "squash": 1.0,        # 纵向压缩（落地/挤压）
    }
    for k in list(kw):
        if k not in p:
            raise KeyError(f"未知姿态参数：{k}")
    p.update(kw)
    return p


STAND = pose()


def _limb(s, p0: Point, a1: float, l1: float, a2: float, l2: float,
          w1: float, w2: float, c1: Sequence[int], c2: Sequence[int],
          foot: Optional[Sequence[int]] = None, foot_r: float = 0.0,
          outline: Optional[Sequence[int]] = None, ss: int = 3) -> Point:
    """画一条两段肢体（大腿+小腿 / 上臂+前臂），返回末端点。"""
    x0, y0 = p0
    x1 = x0 + math.sin(a1) * l1
    y1 = y0 + math.cos(a1) * l1
    x2 = x1 + math.sin(a1 + a2) * l2
    y2 = y1 + math.cos(a1 + a2) * l2
    for (ax, ay, bx, by, ww, cc) in ((x0, y0, x1, y1, w1, c1), (x1, y1, x2, y2, w2, c2)):
        if outline:
            pygame.draw.line(s, outline, (int(ax * ss), int(ay * ss)), (int(bx * ss), int(by * ss)),
                             int((ww + 5) * ss))
        pygame.draw.line(s, tuple(cc), (int(ax * ss), int(ay * ss)), (int(bx * ss), int(by * ss)),
                         int(ww * ss))
        pygame.draw.circle(s, tuple(cc), (int(bx * ss), int(by * ss)), int(ww * ss / 2))
    if foot is not None:
        fr = max(2.0, foot_r)
        pygame.draw.circle(s, tuple(foot), (int(x2 * ss), int(y2 * ss)), int(fr * ss))
    return (x2, y2)


def figure(
    height: float,
    style: FigureStyle,
    p: Optional[Dict[str, float]] = None,
    ss: int = 3,
    pad: int = 26,
) -> pygame.Surface:
    """
    生成一个人物精灵。

    以身高 height（设计像素）为准，返回的 Surface 已含 pad 边距，
    人物脚底位于 (W/2, H-pad)，便于按"站在地面上"的方式贴图。
    """
    p = p or STAND
    h = float(height)
    # 留足空间：张开手臂时水平可达 ±0.48h，举手时垂直可达 1.05h
    W = int(h * 1.30 + pad * 2)
    H = int(h * 1.34 + pad * 2)
    base_x = W / 2.0
    base_y = H - pad                          # 脚底
    flip = p.get("flip", 1)

    def _d(s):
        # ---- 比例（相对身高的卡通写实混合，约 5.5 头身）----
        crouch = U.clamp(p["crouch"], 0.0, 1.0)
        hip_y = base_y - h * (0.500 - 0.085 * crouch)
        sh_y = base_y - h * (0.800 - 0.020 * crouch)
        neck_y = base_y - h * 0.832
        head_r = h * 0.091
        thigh = h * 0.230 * (1.0 - 0.20 * crouch)
        shin = h * 0.225 * (1.0 - 0.14 * crouch)
        upper = h * 0.172
        fore = h * 0.162
        torso_w = h * 0.252
        limb_w = h * 0.076
        sh_w = h * 0.306
        arms = [(p["arm_l"], p["arm_l2"], -1), (p["arm_r"], p["arm_r2"], 1)]
        legs = [(p["leg_l"], p["leg_l2"]), (p["leg_r"], p["leg_r2"])]

        lean = p["lean"] * flip
        outline = style.outline

        # ---- 后腿/后臂（先画，形成前后层次）----
        order = [(0, 1.0), (1, 0.0)] if flip > 0 else [(1, 1.0), (0, 0.0)]
        for idx, front in order:
            la, lb = legs[idx]
            col = style.pants if front else U.shade(style.pants, 0.74)
            _limb(s, (base_x + (idx * 2 - 1) * h * 0.052, hip_y), la, thigh, lb, shin,
                  limb_w * 1.10, limb_w * 0.94, col, U.shade(style.sock, 1.0 if front else 0.78),
                  style.shoes if front else U.shade(style.shoes, 0.78),
                  limb_w * 0.62, outline, ss)
        for idx, front in order:
            aa, ab, sgn = arms[idx]
            col = style.shirt if front else U.shade(style.shirt, 0.74)
            sx = base_x + sgn * sh_w * 0.44
            _limb(s, (sx, sh_y), aa * sgn, upper, ab * sgn, fore,
                  limb_w * 0.92, limb_w * 0.80, col, 
                  style.skin if front else U.shade(style.skin, 0.80),
                  style.skin if front else U.shade(style.skin, 0.80),
                  limb_w * 0.52, outline, ss)

        # ---- 躯干 ----
        tx = base_x + math.sin(lean) * h * 0.06
        body_w = torso_w * (1.0 + 0.06 * crouch)
        body_h = (hip_y - sh_y) * 1.22
        cx, cy = tx, (hip_y + sh_y) / 2.0 - h * 0.012
        if outline:
            pygame.draw.ellipse(s, outline,
                                pygame.Rect(int((cx - body_w / 2 - 3) * ss), int((cy - body_h / 2 - 3) * ss),
                                            int((body_w + 6) * ss), int((body_h + 6) * ss)))
        pts = []
        n = 22
        for i in range(n):
            a = i / n * TAU - math.pi / 2
            rx = body_w / 2 * (1.0 - 0.18 * max(0.0, math.cos(a)))
            ry = body_h / 2
            pts.append((int((cx + math.cos(a) * rx) * ss), int((cy + math.sin(a) * ry) * ss)))
        pygame.draw.polygon(s, tuple(style.shirt), pts)
        # 球衣下摆的撞色条 + 胸口号码
        stripe = pygame.Rect(int((cx - body_w / 2) * ss), int((cy + body_h * 0.16) * ss),
                             int(body_w * ss), int(body_h * 0.16 * ss))
        pygame.draw.rect(s, tuple(style.shirt2), stripe)
        pygame.draw.polygon(s, tuple(style.shirt2), [
            (int(cx * ss), int((cy - body_h * 0.46) * ss)),
            (int((cx - body_w * 0.20) * ss), int((cy - body_h * 0.10) * ss)),
            (int(cx * ss), int((cy + body_h * 0.05) * ss)),
            (int((cx + body_w * 0.20) * ss), int((cy - body_h * 0.10) * ss))])
        # 躯干高光
        hi = pygame.Surface((int(body_w * ss), int(body_h * ss)), pygame.SRCALPHA)
        pygame.draw.ellipse(hi, (255, 255, 255, 44),
                            pygame.Rect(0, 0, int(body_w * 0.42 * ss), int(body_h * 0.78 * ss)))
        s.blit(hi, (int((cx - body_w * 0.46) * ss), int((cy - body_h * 0.44) * ss)))

        # ---- 头 ----
        hx = cx + math.sin(lean) * h * 0.055
        hy = neck_y - head_r * 1.02
        if outline:
            pygame.draw.circle(s, outline, (int(hx * ss), int((hy + 2) * ss)), int((head_r + 3) * ss))
        # 脖子
        pygame.draw.rect(s, tuple(U.shade(style.skin, 0.88)),
                         (int((hx - h * 0.026) * ss), int(hy * ss),
                          int(h * 0.052 * ss), int(head_r * 0.9 * ss)))
        pygame.draw.circle(s, tuple(style.skin), (int(hx * ss), int(hy * ss)), int(head_r * ss))
        # 面部阴影（背光侧）
        sh_ = pygame.Surface((int(head_r * 2 * ss), int(head_r * 2 * ss)), pygame.SRCALPHA)
        pygame.draw.circle(sh_, (0, 0, 0, 44), (int(head_r * ss), int(head_r * ss)), int(head_r * ss))
        pygame.draw.circle(sh_, (0, 0, 0, 0), (int(head_r * 0.66 * ss), int(head_r * 0.86 * ss)),
                           int(head_r * 1.0 * ss))
        s.blit(sh_, (int((hx - head_r) * ss), int((hy - head_r) * ss)))
        # 头发
        hs = style.hair_style
        if hs == "short":
            pygame.draw.arc(s, tuple(style.hair),
                            pygame.Rect(int((hx - head_r * 1.06) * ss), int((hy - head_r * 1.12) * ss),
                                        int(head_r * 2.12 * ss), int(head_r * 2.00 * ss)),
                            0.15, math.pi - 0.15, int(head_r * 0.72 * ss))
        elif hs == "pony":   # 马尾
            pygame.draw.arc(s, tuple(style.hair),
                            pygame.Rect(int((hx - head_r * 1.08) * ss), int((hy - head_r * 1.14) * ss),
                                        int(head_r * 2.16 * ss), int(head_r * 2.04 * ss)),
                            0.10, math.pi - 0.10, int(head_r * 0.80 * ss))
            pygame.draw.circle(s, tuple(style.hair),
                               (int((hx - head_r * 1.0 * flip) * ss), int((hy - head_r * 0.10) * ss)),
                               int(head_r * 0.52 * ss))
        elif hs == "bun":    # 丸子头
            pygame.draw.arc(s, tuple(style.hair),
                            pygame.Rect(int((hx - head_r * 1.08) * ss), int((hy - head_r * 1.14) * ss),
                                        int(head_r * 2.16 * ss), int(head_r * 2.04 * ss)),
                            0.10, math.pi - 0.10, int(head_r * 0.78 * ss))
            pygame.draw.circle(s, tuple(style.hair), (int(hx * ss), int((hy - head_r * 1.30) * ss)),
                               int(head_r * 0.52 * ss))
        elif hs == "helm":   # 头盔
            pygame.draw.circle(s, tuple(style.hair), (int(hx * ss), int((hy - head_r * 0.12) * ss)),
                               int(head_r * 1.04 * ss))
            pygame.draw.rect(s, tuple(style.hair),
                             (int((hx - head_r * 1.06) * ss), int((hy - head_r * 0.16) * ss),
                              int(head_r * 0.30 * ss), int(head_r * 0.5 * ss)))
        # 眼睛（朝向影响位置）
        eye_dx = head_r * 0.34 * flip
        for k in (0.0, 1.0):
            ex = hx + eye_dx + k * head_r * 0.46 * flip
            pygame.draw.circle(s, (255, 255, 255), (int(ex * ss), int((hy - head_r * 0.10) * ss)),
                               int(head_r * 0.155 * ss))
            pygame.draw.circle(s, (28, 30, 44), (int((ex + head_r * 0.05 * flip) * ss),
                                                 int((hy - head_r * 0.10) * ss)),
                               int(head_r * 0.088 * ss))
        # 号码
        if style.number:
            fnt = U.font(max(9, int(h * 0.115 * ss)), True)
            img = fnt.render(style.number, True, style.num_color)
            s.blit(img, (int(cx * ss - img.get_width() / 2),
                         int(cy * ss + body_h * 0.30 * ss - img.get_height() / 2)))

    return U.bake_raw(("fig", int(height), style_key(style), tuple(sorted(p.items())), pad),
                      (W, H), _d, ss)


def style_key(st: FigureStyle):
    return (st.shirt, st.shirt2, st.pants, st.skin, st.hair, st.shoes, st.sock,
            st.number, st.num_color, st.hair_style, st.outline)


def figure_cached(height: float, style: FigureStyle, p: Optional[Dict[str, float]] = None,
                  ss: int = 3, quant: float = 0.14) -> pygame.Surface:
    """
    姿态量化 + 缓存的版本（游戏热路径用）。
    角度按 quant 弧度取整，避免连续动作产生海量缓存条目。
    """
    p = p or STAND

    def q(v):
        return round(float(v) / quant) * quant
    pk = (q(p.get("lean", 0)), q(p.get("crouch", 0)), q(p.get("arm_l", 0)), q(p.get("arm_l2", 0)),
          q(p.get("arm_r", 0)), q(p.get("arm_r2", 0)), q(p.get("leg_l", 0)), q(p.get("leg_l2", 0)),
          q(p.get("leg_r", 0)), q(p.get("leg_r2", 0)), q(p.get("head", 0)),
          1 if p.get("flip", 1) > 0 else -1, round(float(p.get("squash", 1.0)), 1))
    return _fig_cached(int(height), style, p, pk, ss)


_fig_cache: Dict[Tuple, pygame.Surface] = {}


def _fig_cached(height: int, style: FigureStyle, p, pk, ss) -> pygame.Surface:
    ck = (height, style_key(style), pk)
    s = _fig_cache.get(ck)
    if s is None:
        s = figure(height, style, dict(zip(
            ["lean", "crouch", "arm_l", "arm_l2", "arm_r", "arm_r2", "leg_l", "leg_l2",
             "leg_r", "leg_r2", "head", "flip", "squash"], pk)), ss)
        if len(_fig_cache) > 900:
            _fig_cache.clear()
        _fig_cache[ck] = s
    return s


def draw_figure(surf: pygame.Surface, spr: pygame.Surface, x: float, foot_y: float,
                pad: int = 26) -> None:
    """把人物精灵按"脚底对齐"贴到 (x, foot_y)。"""
    surf.blit(spr, (int(x - spr.get_width() / 2), int(foot_y - spr.get_height() + pad)))


# =========================================================================== #
# 场景：看台 / 草坪 / 硬地 / 天空
# =========================================================================== #
def crowd_stand(w: int, h: int, seed: int = 11, base: Sequence[int] = (30, 36, 56),
                rows: int = 9, shirt_palette: Optional[List] = None,
                density: float = 0.86, lit: float = 0.0) -> pygame.Surface:
    """
    程序化生成看台人群：一排排小人 + 座席条带 + 顶部阴影。
    因为是静态背景，只在切换游戏时生成一次，然后一直 blit。
    配色刻意压暗压灰，避免"糖果色噪点"抢占前景。
    """
    pal = shirt_palette or [(164, 74, 68), (66, 96, 158), (170, 140, 70), (86, 148, 126),
                            (140, 100, 152), (196, 196, 204), (52, 58, 80), (176, 108, 78)]

    def _d(s):
        ss = 1                    # 看台尺寸本就很大，无需超采样
        s.fill((0, 0, 0, 0))
        rng = random.Random(seed)
        W, H = w, h
        # 底色（座位区）
        for y in range(H):
            u = y / max(1, H - 1)
            k = 0.86 + 0.34 * u
            c = U.shade(base, k)
            s.fill((c[0], c[1], c[2], 255), (0, y, W, 1))
        row_h = H / rows
        for r in range(rows):
            y0 = r * row_h
            depth = 0.52 + 0.48 * (r / max(1, rows - 1))     # 越靠前越大、越亮
            # 座席横条
            seat = U.shade(base, 1.16 + 0.2 * depth)
            s.fill((seat[0], seat[1], seat[2], 255), (0, int(y0 * ss + row_h * 0.86 * ss),
                                                       W * ss, max(1, int(row_h * 0.16 * ss))))
            n = int(W / (row_h * 0.62) * density)
            for i in range(n):
                cx = (i + rng.uniform(-0.32, 0.32)) * (W / max(1, n))
                cy = y0 + row_h * rng.uniform(0.24, 0.56)
                hr = row_h * (0.20 + 0.08 * depth)
                col = rng.choice(pal)
                col = U.shade(col, 0.62 + 0.5 * depth + lit)
                # 身体（梯形）+ 头
                bw = hr * 1.85
                bh = hr * 1.5
                pts = [(int((cx - bw / 2) * ss), int((cy - bh * 0.45) * ss)),
                       (int((cx + bw / 2) * ss), int((cy - bh * 0.45) * ss)),
                       (int((cx + bw / 2 * 1.12) * ss), int((cy + bh * 0.75) * ss)),
                       (int((cx - bw / 2 * 1.12) * ss), int((cy + bh * 0.75) * ss))]
                pygame.draw.polygon(s, col, pts)
                sk = U.shade(rng.choice([(238, 196, 164), (214, 166, 130), (176, 126, 96)]),
                             0.6 + 0.5 * depth + lit)
                pygame.draw.circle(s, sk, (int(cx * ss), int((cy - bh * 0.82) * ss)), int(hr * 0.72 * ss))
                # 举起的手臂（点缀，制造"人浪"感）
                if rng.random() < 0.13:
                    pygame.draw.line(s, sk, (int((cx - bw * 0.44) * ss), int((cy - bh * 0.35) * ss)),
                                     (int((cx - bw * 0.72) * ss), int((cy - bh * 1.5) * ss)),
                                     max(1, int(hr * 0.34 * ss)))
                    pygame.draw.line(s, sk, (int((cx + bw * 0.44) * ss), int((cy - bh * 0.35) * ss)),
                                     (int((cx + bw * 0.72) * ss), int((cy - bh * 1.5) * ss)),
                                     max(1, int(hr * 0.34 * ss)))
        # 顶部（远处）压暗
        top = pygame.Surface((W * ss, max(1, int(H * 0.22 * ss))), pygame.SRCALPHA)
        for y in range(top.get_height()):
            a = int(120 * (1 - y / max(1, top.get_height() - 1)))
            top.fill((6, 8, 18, a), (0, y, W * ss, 1))
        s.blit(top, (0, 0))

    return U.bake_raw(("crowd", w, h, seed, tuple(base), rows, density, round(lit, 2)),
                      (w, h), _d, ss=1)


def noise_texture(w: int, h: int, seed: int = 5, amount: int = 12,
                  scale: int = 3, base_alpha: int = 0) -> pygame.Surface:
    """细颗粒材质叠加层（草地/沙地/水泥），提升"高清"观感。"""
    key = ("noise", w, h, seed, amount, scale)
    s = U._grad_cache.get(key)
    if s is None:
        rng = np.random.default_rng(seed)
        small = rng.integers(128 - amount, 128 + amount, (max(2, h // scale), max(2, w // scale), 1))
        small = np.repeat(small, 3, axis=2).astype(np.uint8)
        s = pygame.surfarray.make_surface(small.swapaxes(0, 1))
        s = pygame.transform.smoothscale(s, (w, h))
        s.set_alpha(255 if base_alpha == 0 else base_alpha)
        U._grad_cache[key] = s
    return s


def grass_pitch(w: int, h: int, top: Sequence[int] = (52, 132, 72),
                bottom: Sequence[int] = (34, 96, 56), stripes: int = 10,
                seed: int = 7) -> pygame.Surface:
    """草坪：条纹 + 渐变 + 颗粒 + 轻微明暗不均，避免"塑料绿"。"""
    key = ("grass", w, h, tuple(top[:3]), tuple(bottom[:3]), stripes)
    s = U._grad_cache.get(key)
    if s is None:
        arr = np.zeros((h, w, 3), dtype=np.float32)
        k = np.linspace(0.0, 1.0, h, dtype=np.float32).reshape(h, 1)
        for i in range(3):
            arr[..., i] = top[i] + (bottom[i] - top[i]) * k
        # 横向条纹（模拟割草机纹路）
        band = max(4, h // stripes)
        for y in range(0, h, band):
            if (y // band) % 2 == 0:
                continue
            arr[y:y + band] *= 1.075
        # 纵向轻微不均
        vx = (np.sin(np.linspace(0, 7.5, w)) * 0.012 + 1.0).astype(np.float32)
        arr *= vx.reshape(1, -1, 1)
        s = pygame.surfarray.make_surface(np.clip(arr, 0, 255).astype(np.uint8).swapaxes(0, 1))
        n = noise_texture(w, h, seed, 16, 2)
        n = n.copy()
        n.set_alpha(26)
        s.blit(n, (0, 0))
        U._grad_cache[key] = s
    return s


def hard_court(w: int, h: int, top: Sequence[int] = (44, 96, 156),
               bottom: Sequence[int] = (30, 68, 122)) -> pygame.Surface:
    """硬地球场：色带 + 颗粒。"""
    key = ("court", w, h, tuple(top[:3]), tuple(bottom[:3]))
    s = U._grad_cache.get(key)
    if s is None:
        s = U.vgrad(w, h, top, bottom).copy()
        n = noise_texture(w, h, 9, 14, 2).copy()
        n.set_alpha(22)
        s.blit(n, (0, 0))
        U._grad_cache[key] = s
    return s


def stadium_bg(w: int, h: int, sky_top: Sequence[int] = (10, 16, 44),
               sky_bottom: Sequence[int] = (26, 40, 82), seed: int = 4) -> pygame.Surface:
    """夜空渐变 + 星点 + 城市轮廓（夜景球场背景）。"""
    key = ("stad", w, h, tuple(sky_top[:3]), tuple(sky_bottom[:3]), seed)
    s = U._grad_cache.get(key)
    if s is None:
        base = U.vgrad(w, h, sky_top, sky_bottom).copy()
        rng = random.Random(seed)
        for _ in range(int(w * h / 14000)):
            x = rng.uniform(0, w)
            y = rng.uniform(0, h * 0.55)
            a = rng.randint(40, 170)
            r = rng.choice([1, 1, 1, 2])
            base.fill((255, 255, 255, a), (int(x), int(y), r, r))
        skyline = pygame.Surface((w, h), pygame.SRCALPHA)
        x = 0
        while x < w:
            bw = rng.randint(40, 130)
            bh = rng.randint(int(h * 0.10), int(h * 0.28))
            skyline.fill((12, 18, 38, 235), (x, h - bh, bw, bh))
            for wy in range(h - bh + 10, h - 10, 22):
                for wx in range(x + 8, x + bw - 8, 18):
                    if rng.random() < 0.42:
                        c = rng.choice([(255, 226, 150), (255, 244, 210), (180, 214, 255)])
                        skyline.fill((c[0], c[1], c[2], rng.randint(70, 170)), (wx, wy, 5, 7))
            x += bw + rng.randint(2, 10)
        base.blit(skyline, (0, 0))
        s = base
        U._grad_cache[key] = s
    return s


def stadium_lights(surf: pygame.Surface, positions: Sequence[float], y: float,
                   height: float, color: Sequence[int] = (255, 248, 218),
                   cone_to: Optional[float] = None) -> None:
    """球场泛光灯柱 + 光晕 + 可选光锥。"""
    for i, x in enumerate(positions):
        # 灯柱
        U.aa_line(surf, (x, y + height), (x, y), U.shade(color, 0.42), 9)
        U.aa_line(surf, (x, y + height), (x, y), U.shade(color, 0.62), 4)
        # 灯板（用带明暗的面板，而不是单色圆角框）
        bw, bh = 108, 34
        surf.blit(shade_panel(bw, bh, U.shade(color, 0.80), 7),
                  (int(x - bw / 2), int(y - bh / 2)))
        for k in range(4):
            for j in range(2):
                surf.blit(U.glow_surface(26, color, 120, 6),
                          (int(x - bw / 2 + 16 + k * 26 - 26), int(y - bh / 2 + 9 + j * 16 - 26)))
        # 光晕
        surf.blit(U.glow_surface(150, color, 78, 9), (int(x - 150), int(y - 150)))
        if cone_to is not None:
            ch = cone_to - y
            if ch > 10:
                surf.blit(U.light_cone(int(ch * 1.35), int(ch), color, 0.34, 30, key=i),
                          (int(x - ch * 1.35 / 2), int(y)))


# =========================================================================== #
# 通用道具
# =========================================================================== #
def coin_sprite(r: float = 22, ss: int = 3) -> pygame.Surface:
    return U.bake(("coin", int(r)), (int(r * 2), int(r * 2)),
                  lambda s: pygame.draw.circle(s, (255, 208, 64), (int(r * ss), int(r * ss)), int(r * ss)), ss)


def star_sprite(r: float = 26, color=(255, 216, 88), ss: int = 3) -> pygame.Surface:
    size = int(r * 2.2)

    def _d(s):
        c = size * ss / 2
        pts = U.star_points(c, c, r * ss, r * 0.44 * ss, 5)
        pygame.draw.polygon(s, U._safe(color), pts)
        pygame.draw.polygon(s, tuple(U.shade(color, 0.72)), pts, max(1, int(r * 0.09 * ss)))
        hi = U.star_points(c - r * 0.14 * ss, c - r * 0.16 * ss, r * 0.58 * ss, r * 0.24 * ss, 5)
        pygame.draw.polygon(s, (255, 252, 226), hi)
    return U.bake_raw(("star", int(r), U._safe(color)), (size, size), _d, ss)


def arrow_marker(surf: pygame.Surface, x: float, y: float, size: float,
                 color, direction: float = -math.pi / 2, alpha: int = 230) -> None:
    """指示箭头（用于引导玩家看某处）。"""
    pts = [(x + math.cos(direction + i * TAU / 3 + math.pi) * size,
            y + math.sin(direction + i * TAU / 3 + math.pi) * size) for i in range(3)]
    c = (color[0], color[1], color[2], alpha)
    U.aa_poly(surf, pts, c, 0, ss=3)


def ring_marker(surf: pygame.Surface, x: float, y: float, r: float, color,
                width: int = 4, alpha: int = 220) -> None:
    U.aa_circle(surf, (x, y), r, (color[0], color[1], color[2], alpha), width, ss=3)
