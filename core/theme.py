"""
ui_theme.py
-----------
统一视觉工具箱：渐变、抗锯齿圆角、柔和阴影、毛玻璃面板、光晕文字、粒子系统、缓动。

设计原则
  · 所有"每帧重复出现"的绘制都做缓存（Surface 复用），保证 60fps；
  · 缓存返回的 Surface 一律视为只读，绝不原地修改；
  · 颜色统一用 RGB / RGBA 元组，透明度用 SRCALPHA 表面承载。
"""
from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pygame

Color = Tuple[int, ...]


# =========================================================================== #
# 数学 / 缓动
# =========================================================================== #
def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def mix(c1: Sequence[int], c2: Sequence[int], t: float) -> Tuple[int, int, int]:
    t = clamp(t, 0.0, 1.0)
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def shade(c: Sequence[int], k: float) -> Tuple[int, int, int]:
    """k>1 变亮，k<1 变暗。"""
    return (int(clamp(c[0] * k, 0, 255)), int(clamp(c[1] * k, 0, 255)), int(clamp(c[2] * k, 0, 255)))


def ease_out_cubic(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return 1.0 - (1.0 - t) ** 3


def ease_in_cubic(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return t * t * t


def ease_in_out(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2


def ease_out_back(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


def ease_out_elastic(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    if t in (0.0, 1.0):
        return t
    c4 = (2 * math.pi) / 3
    return pow(2, -10 * t) * math.sin((t * 10 - 0.75) * c4) + 1


def pulse(t: float, speed: float = 2.0, lo: float = 0.0, hi: float = 1.0) -> float:
    """0~1 之间的正弦脉冲。"""
    return lo + (hi - lo) * (0.5 + 0.5 * math.sin(t * speed))


# =========================================================================== #
# 字体
# =========================================================================== #
FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]

_cjk_path: Optional[str] = None
_fonts: Dict[Tuple[int, bool], pygame.font.Font] = {}


def init_font() -> None:
    """定位一个能渲染中文的系统字体；找不到则回退英文界面。"""
    global _cjk_path
    try:
        pygame.font.init()
    except Exception:
        pass
    for p in FONT_CANDIDATES:
        if not os.path.exists(p):
            continue
        try:
            f = pygame.font.Font(p, 22)
            if f.render("头", True, (0, 0, 0)).get_width() > 3:
                _cjk_path = p
                return
        except Exception:
            continue
    try:
        f = pygame.font.SysFont("pingfangsc,hiraginosansgb,stheiti,notosanscjksc,arialunicode", 22)
        if f is not None and f.render("头", True, (0, 0, 0)).get_width() > 3:
            _cjk_path = "@sys"
            return
    except Exception:
        pass
    _cjk_path = None


def font(size: int, bold: bool = False) -> pygame.font.Font:
    key = (size, bold)
    if key not in _fonts:
        try:
            if _cjk_path == "@sys":
                f = pygame.font.SysFont("pingfangsc,hiraginosansgb,stheiti,notosanscjksc,arialunicode", size)
            elif _cjk_path:
                f = pygame.font.Font(_cjk_path, size)
            else:
                f = pygame.font.Font(None, size)
        except Exception:
            f = pygame.font.Font(None, size)
        if bold:
            try:
                f.set_bold(True)
            except Exception:
                pass
        _fonts[key] = f
    return _fonts[key]


def has_cjk() -> bool:
    return _cjk_path is not None


def T(zh: str, en: str) -> str:
    """有中文字体显示中文，否则回退英文。"""
    return zh if _cjk_path else en


# =========================================================================== #
# 文字（带缓存 + 阴影 + 光晕）
# =========================================================================== #
_txt_cache: Dict[Tuple, pygame.Surface] = {}
_glow_txt_cache: Dict[Tuple, pygame.Surface] = {}


def render_text(s: str, size: int, color: Color, bold: bool = False) -> pygame.Surface:
    key = (s, size, _safe(color), bold)
    surf = _txt_cache.get(key)
    if surf is None:
        surf = font(size, bold).render(s, True, tuple(color[:3]))
        if len(_txt_cache) > 3000:
            _txt_cache.clear()
        _txt_cache[key] = surf
    return surf


def glow_text(s: str, size: int, color: Color, bold: bool, radius: int) -> pygame.Surface:
    """
    文字光晕：把文字画进一张带留白的surface，再缩小-放大做模糊，得到真正的柔和晕圈。
    （早期版本用"多偏移重绘"，大字号会把笔画糊成实心块，已废弃。）
    """
    key = (s, size, tuple(color[:3]), bold, radius)
    g = _glow_txt_cache.get(key)
    if g is not None:
        return g
    base = render_text(s, size, color, bold)
    w, h = base.get_size()
    pad = radius * 2
    big = pygame.Surface((w + pad * 2, h + pad * 2), pygame.SRCALPHA)
    big.blit(base, (pad, pad))
    f = max(2, radius // 2 + 1)
    sw, sh = max(1, big.get_width() // f), max(1, big.get_height() // f)
    g = pygame.transform.smoothscale(
        pygame.transform.smoothscale(big, (sw, sh)), big.get_size())
    if len(_glow_txt_cache) > 500:
        _glow_txt_cache.clear()
    _glow_txt_cache[key] = g
    return g


def text(
    surf: pygame.Surface,
    s: str,
    pos: Tuple[int, int],
    size: int,
    color: Color,
    center: bool = False,
    shadow: int = 0,
    shadow_color: Color = (0, 0, 0),
    glow: int = 0,
    glow_color: Optional[Color] = None,
    bold: bool = False,
    alpha: int = 255,
) -> pygame.Rect:
    """绘制文字。shadow=偏移像素；glow=光晕半径。返回占位 Rect。"""
    img = render_text(s, size, color, bold)
    r = img.get_rect()
    r.topleft = pos
    if center:
        r.center = pos

    if glow > 0:
        g = glow_text(s, size, glow_color or color, bold, glow)
        g.set_alpha(int(165 * (alpha / 255)))
        surf.blit(g, (r.x - glow * 2, r.y - glow * 2))

    if shadow:
        sh = render_text(s, size, shadow_color, bold)
        for dx, dy in ((shadow, shadow), (-shadow // 2, shadow)):
            surf.blit(sh, (r.x + dx, r.y + dy))

    if alpha < 255:
        img = img.copy()
        img.set_alpha(alpha)

    surf.blit(img, r)
    return r


# =========================================================================== #
# 渐变（带缓存）
# =========================================================================== #
_grad_cache: Dict[Tuple, pygame.Surface] = {}


def _grad_array(w: int, h: int, c1: Sequence[int], c2: Sequence[int], vertical: bool, c3: Optional[Sequence[int]] = None) -> np.ndarray:
    if vertical:
        k = np.linspace(0.0, 1.0, max(2, h)).reshape(-1, 1)
    else:
        k = np.linspace(0.0, 1.0, max(2, w)).reshape(1, -1)
    if c3 is None:
        arr = np.zeros((k.shape[0], k.shape[1], 3), dtype=np.float32)
        for i in range(3):
            arr[..., i] = c1[i] + (c2[i] - c1[i]) * k
    else:
        # 三段：c1 -> c2 -> c3
        k2 = np.clip(k * 2.0, 0, 1)
        k3 = np.clip(k * 2.0 - 1.0, 0, 1)
        arr = np.zeros((k.shape[0], k.shape[1], 3), dtype=np.float32)
        for i in range(3):
            arr[..., i] = (c1[i] + (c2[i] - c1[i]) * k2) * (1 - k3) + \
                          (c2[i] + (c3[i] - c2[i]) * k3) * k3
    img = np.repeat(arr.astype(np.uint8), h if not vertical else 1, axis=0)
    img = np.repeat(img, w if not vertical else 1, axis=1)
    return img


def vgrad(w: int, h: int, top: Sequence[int], bottom: Sequence[int]) -> pygame.Surface:
    """竖向渐变（缓存）。"""
    key = ("v", w, h, tuple(top[:3]), tuple(bottom[:3]))
    s = _grad_cache.get(key)
    if s is None:
        k = np.linspace(0.0, 1.0, max(2, h), dtype=np.float32).reshape(h, 1, 1)
        c1 = np.array(top[:3], dtype=np.float32).reshape(1, 1, 3)
        c2 = np.array(bottom[:3], dtype=np.float32).reshape(1, 1, 3)
        arr = (c1 + (c2 - c1) * k).astype(np.uint8)
        arr = np.repeat(arr, w, axis=1)
        s = pygame.surfarray.make_surface(arr.swapaxes(0, 1))
        _grad_cache[key] = s
    return s


def hgrad(w: int, h: int, left: Sequence[int], right: Sequence[int]) -> pygame.Surface:
    """横向渐变（缓存）。"""
    key = ("h", w, h, tuple(left[:3]), tuple(right[:3]))
    s = _grad_cache.get(key)
    if s is None:
        k = np.linspace(0.0, 1.0, max(2, w), dtype=np.float32).reshape(1, w, 1)
        c1 = np.array(left[:3], dtype=np.float32).reshape(1, 1, 3)
        c2 = np.array(right[:3], dtype=np.float32).reshape(1, 1, 3)
        arr = (c1 + (c2 - c1) * k).astype(np.uint8)
        arr = np.repeat(arr, h, axis=0)
        s = pygame.surfarray.make_surface(arr.swapaxes(0, 1))
        _grad_cache[key] = s
    return s


def vgrad3(w: int, h: int, a: Sequence[int], b: Sequence[int], c: Sequence[int]) -> pygame.Surface:
    """三段竖向渐变：a -> b -> c（缓存）。"""
    key = ("v3", w, h, tuple(a[:3]), tuple(b[:3]), tuple(c[:3]))
    s = _grad_cache.get(key)
    if s is None:
        k = np.linspace(0.0, 1.0, max(2, h), dtype=np.float32)
        ka = np.clip(k * 2.0, 0, 1).reshape(h, 1, 1)
        kb = np.clip(k * 2.0 - 1.0, 0, 1).reshape(h, 1, 1)
        ca = np.array(a[:3], dtype=np.float32).reshape(1, 1, 3)
        cb = np.array(b[:3], dtype=np.float32).reshape(1, 1, 3)
        cc = np.array(c[:3], dtype=np.float32).reshape(1, 1, 3)
        arr = ((ca + (cb - ca) * ka) * (1 - kb) + (cb + (cc - cb) * kb) * kb).astype(np.uint8)
        arr = np.repeat(arr, w, axis=1)
        s = pygame.surfarray.make_surface(arr.swapaxes(0, 1))
        _grad_cache[key] = s
    return s


# =========================================================================== #
# 圆角矩形 / 阴影 / 毛玻璃
# =========================================================================== #
_rr_cache: Dict[Tuple, pygame.Surface] = {}


def rr_surface(
    size: Tuple[int, int],
    radius: int,
    fill: Optional[Color] = None,
    border: Optional[Color] = None,
    border_w: int = 0,
) -> pygame.Surface:
    """抗锯齿圆角矩形（4x 超采样后缩放），带缓存。返回只读 Surface。"""
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    radius = int(min(radius, min(w, h) // 2))
    key = (w, h, radius, tuple(fill) if fill else None,
           tuple(border) if border else None, border_w)
    s = _rr_cache.get(key)
    if s is not None:
        return s

    S = 4
    big = pygame.Surface((w * S, h * S), pygame.SRCALPHA)
    rect = pygame.Rect(0, 0, w * S, h * S)
    r = radius * S
    if fill is not None:
        pygame.draw.rect(big, tuple(fill), rect, border_radius=r)
    if border is not None and border_w > 0:
        pygame.draw.rect(big, tuple(border), rect, border_w * S, border_radius=r)
    s = pygame.transform.smoothscale(big, (w, h))
    if len(_rr_cache) > 900:
        _rr_cache.clear()
    _rr_cache[key] = s
    return s


def rr(
    surf: pygame.Surface,
    rect: pygame.Rect,
    radius: int = 16,
    fill: Optional[Color] = None,
    border: Optional[Color] = None,
    border_w: int = 0,
) -> None:
    """在 surf 上绘制抗锯齿圆角矩形。"""
    s = rr_surface((rect.w, rect.h), radius, fill, border, border_w)
    surf.blit(s, (rect.x, rect.y))


_shadow_cache: Dict[Tuple, pygame.Surface] = {}


def shadow_surface(w: int, h: int, radius: int, spread: int = 18, alpha: int = 130) -> pygame.Surface:
    """柔和投影（多层递减 alpha 模拟模糊），带缓存。"""
    key = (w, h, radius, spread, alpha)
    s = _shadow_cache.get(key)
    if s is not None:
        return s
    pad = spread
    s = pygame.Surface((w + pad * 2, h + pad * 2), pygame.SRCALPHA)
    for i in range(spread, 0, -1):
        t = i / spread
        a = int(alpha * (1 - t) ** 2.2)
        if a <= 1:
            continue
        pygame.draw.rect(
            s, (0, 0, 0, a),
            pygame.Rect(pad - i, pad - i, w + i * 2, h + i * 2),
            border_radius=radius + i,
        )
    pygame.draw.rect(s, (0, 0, 0, alpha), pygame.Rect(pad, pad, w, h), border_radius=radius)
    if len(_shadow_cache) > 500:
        _shadow_cache.clear()
    _shadow_cache[key] = s
    return s


def soft_shadow(
    surf: pygame.Surface,
    rect: pygame.Rect,
    radius: int = 18,
    spread: int = 18,
    alpha: int = 130,
    offset: Tuple[int, int] = (0, 10),
) -> None:
    s = shadow_surface(rect.w, rect.h, radius, spread, alpha)
    surf.blit(s, (rect.x - spread + offset[0], rect.y - spread + offset[1]))


def glass(
    surf: pygame.Surface,
    rect: pygame.Rect,
    radius: int = 18,
    tint: Color = (255, 255, 255, 24),
    border: Color = (255, 255, 255, 64),
    border_w: int = 2,
    gloss: bool = True,
) -> None:
    """毛玻璃面板：半透明底 + 亮边 + 顶部高光。"""
    panel = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
    pygame.draw.rect(panel, tuple(tint), pygame.Rect(0, 0, rect.w, rect.h), border_radius=radius)
    if gloss:
        g = pygame.Surface((rect.w, max(2, rect.h // 2)), pygame.SRCALPHA)
        for y in range(g.get_height()):
            a = int(26 * (1 - y / max(1, g.get_height())))
            if a > 0:
                g.fill((255, 255, 255, a), (0, y, rect.w, 1))
        gn = pygame.Rect(0, 0, rect.w, g.get_height())
        pygame.draw.rect(g, (0, 0, 0, 0), gn, border_radius=radius)
        panel.blit(g, (0, 0))
    if border is not None and border_w > 0:
        pygame.draw.rect(panel, tuple(border), pygame.Rect(0, 0, rect.w, rect.h),
                         border_w, border_radius=radius)
    surf.blit(panel, (rect.x, rect.y))


# =========================================================================== #
# 光效
# =========================================================================== #
_glow_cache: Dict[Tuple, pygame.Surface] = {}


def glow_surface(radius: int, color: Sequence[int], max_alpha: int = 110, layers: int = 10) -> pygame.Surface:
    """径向光晕（同心圆递减），带缓存。"""
    key = (radius, tuple(color[:3]), max_alpha, layers)
    s = _glow_cache.get(key)
    if s is not None:
        return s
    d = radius * 2
    s = pygame.Surface((d, d), pygame.SRCALPHA)
    for i in range(layers, 0, -1):
        t = i / layers
        a = int(max_alpha * (1 - t) ** 1.8) + 3
        pygame.draw.circle(s, (color[0], color[1], color[2], a), (radius, radius), int(radius * t))
    if len(_glow_cache) > 400:
        _glow_cache.clear()
    _glow_cache[key] = s
    return s


def glow(surf: pygame.Surface, center: Tuple[int, int], radius: int,
         color: Sequence[int], max_alpha: int = 110, layers: int = 10,
         blend: int = pygame.BLEND_PREMULTIPLIED) -> None:
    s = glow_surface(radius, color, max_alpha, layers)
    surf.blit(s, (center[0] - radius, center[1] - radius))


# =========================================================================== #
# 粒子系统
# =========================================================================== #
class Particles:
    """
    通用粒子系统。粒子的 fields（默认值）：
      x, y, vx, vy, life, max_life, size, color, gravity, drag, shape
    支持 emit 时覆盖任意字段。
    """

    def __init__(self, cap: int = 900) -> None:
        self.items: List[dict] = []
        self.cap = cap

    def clear(self) -> None:
        self.items.clear()

    def emit(self, x: float, y: float, n: int = 12, **kw) -> None:
        import random as _r
        for _ in range(n):
            if len(self.items) >= self.cap:
                break
            life = kw.get("life", _r.uniform(0.45, 1.05))
            p = {
                "x": x + kw.get("dx", 0.0) * _r.uniform(-1, 1),
                "y": y + kw.get("dy", 0.0) * _r.uniform(-1, 1),
                "vx": kw.get("vx", 0.0) + kw.get("spread", 0.0) * _r.uniform(-1, 1),
                "vy": kw.get("vy", 0.0) + kw.get("spread", 0.0) * _r.uniform(-1, 1),
                "life": life,
                "max_life": life,
                "size": kw.get("size", _r.uniform(2.0, 4.5)),
                "color": kw.get("color", (255, 255, 255)),
                "gravity": kw.get("gravity", 900.0),
                "drag": kw.get("drag", 0.0),
                "shape": kw.get("shape", "circle"),
                "spin": kw.get("spin", 0.0),
                "angle": _r.uniform(0, math.tau),
                "fade": kw.get("fade", True),
            }
            self.items.append(p)

    def update(self, dt: float) -> None:
        alive: List[dict] = []
        for p in self.items:
            p["life"] -= dt
            if p["life"] <= 0:
                continue
            p["vy"] += p["gravity"] * dt
            if p["drag"]:
                k = max(0.0, 1.0 - p["drag"] * dt)
                p["vx"] *= k
                p["vy"] *= k
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["angle"] += p["spin"] * dt
            alive.append(p)
        self.items = alive

    def draw(self, surf: pygame.Surface) -> None:
        """全部粒子先画进一张 SRCALPHA 图层，再一次性合成 —— 避免逐粒子建面导致掉帧。"""
        if not self.items:
            return
        size = surf.get_size()
        layer = _particle_layer(size)
        for p in self.items:
            t = clamp(p["life"] / max(1e-6, p["max_life"]), 0.0, 1.0)
            a = int(255 * (t ** 0.6)) if p["fade"] else 255
            if a <= 2:
                continue
            c = p["color"]
            col = _safe((c[0], c[1], c[2], a))
            x, y = int(p["x"]), int(p["y"])
            if x < -30 or y < -30 or x > size[0] + 30 or y > size[1] + 30:
                continue
            r = max(1, int(p["size"] * (0.45 + 0.55 * t)))
            sh = p["shape"]
            if sh == "circle":
                pygame.draw.circle(layer, col, (x, y), r)
            elif sh == "square":
                pygame.draw.rect(layer, col, pygame.Rect(x - r, y - r, r * 2, r * 2))
            else:  # streak
                ln = r * 5
                dx = math.cos(p["angle"]) * ln
                dy = math.sin(p["angle"]) * ln
                pygame.draw.line(layer, col, (x - dx / 2, y - dy / 2), (x + dx / 2, y + dy / 2), r)
        surf.blit(layer, (0, 0))


_particle_layers: Dict[Tuple[int, int], pygame.Surface] = {}


def _particle_layer(size: Tuple[int, int]) -> pygame.Surface:
    """复用的全屏粒子图层（每帧清空）。"""
    s = _particle_layers.get(size)
    if s is None:
        s = pygame.Surface(size, pygame.SRCALPHA)
        _particle_layers[size] = s
    else:
        s.fill((0, 0, 0, 0))
    return s


# =========================================================================== #
# 背景装饰
# =========================================================================== #
class OrbField:
    """缓慢漂浮的柔光球，用于菜单/结算背景。"""

    def __init__(self, w: int, h: int, n: int = 9, seed: int = 7, colors: Optional[List] = None):
        import random as _r
        rng = _r.Random(seed)
        self.w, self.h = w, h
        self.orbs = []
        palette = colors or [(96, 148, 255), (255, 138, 92), (92, 220, 176), (198, 132, 255), (255, 208, 96)]
        for i in range(n):
            self.orbs.append({
                "x": rng.uniform(0, w),
                "y": rng.uniform(0, h),
                "r": rng.uniform(70, 190),
                "sx": rng.uniform(-14, 14),
                "sy": rng.uniform(-10, 10),
                "c": palette[i % len(palette)],
                "a": rng.randint(20, 44),
            })

    def update(self, dt: float) -> None:
        for o in self.orbs:
            o["x"] += o["sx"] * dt
            o["y"] += o["sy"] * dt
            if o["x"] < -o["r"]:
                o["x"] = self.w + o["r"]
            elif o["x"] > self.w + o["r"]:
                o["x"] = -o["r"]
            if o["y"] < -o["r"]:
                o["y"] = self.h + o["r"]
            elif o["y"] > self.h + o["r"]:
                o["y"] = -o["r"]

    def draw(self, surf: pygame.Surface) -> None:
        for o in self.orbs:
            r = int(o["r"])
            surf.blit(glow_surface(r, o["c"], o["a"], 8),
                      (int(o["x"] - r), int(o["y"] - r)))


class StarField:
    """轻微闪烁的星点背景。"""

    def __init__(self, w: int, h: int, n: int = 110, seed: int = 3):
        import random as _r
        rng = _r.Random(seed)
        self.stars = [(rng.uniform(0, w), rng.uniform(0, h),
                       rng.uniform(0.6, 1.9), rng.uniform(0, math.tau)) for _ in range(n)]

    def draw(self, surf: pygame.Surface, t: float) -> None:
        for x, y, s, ph in self.stars:
            a = int(90 + 130 * (0.5 + 0.5 * math.sin(t * 1.6 + ph)))
            r = max(1, int(s))
            surf.blit(glow_surface(r * 3, (255, 255, 255), a // 3, 4),
                      (int(x - r * 3), int(y - r * 3)))


# =========================================================================== #
# 高清渲染：超采样烘焙 / 抗锯齿图元 / 模糊
# --------------------------------------------------------------------------- #
# pygame 的 draw.* 全是硬边（无 AA），在 1920×1080 下极易看出锯齿，
# 尤其角色轮廓与球类圆形。这里统一用"超采样绘制 + 缩小"得到真 AA：
#   把图形画进 ss 倍的临时表面 → smoothscale 缩回目标尺寸。
# 由于是烘焙（每帧复用同一张缓存 Surface），成本只在第一次。
# =========================================================================== #
_bake_cache: Dict[Tuple, pygame.Surface] = {}
_BAKE_MAX_PIXELS = 52000     # 超过这个面积不进缓存（避免大背景图撑爆内存）
_BAKE_MAX_ENTRIES = 1200


def _safe(color) -> Tuple[int, ...]:
    """
    把颜色规整成 pygame 能接受的元组。

    主要是两件事：
      · clamp 到 0~255（游戏里算出来的 alpha 很容易越界成负数，
        pygame 会直接抛 `invalid color argument`，而且是在 draw 里报，很难定位）；
      · 允许传 list。
    """
    c = tuple(int(v) for v in color)
    if len(c) == 4:
        return (max(0, min(255, c[0])), max(0, min(255, c[1])),
                max(0, min(255, c[2])), max(0, min(255, c[3])))
    return (max(0, min(255, c[0])), max(0, min(255, c[1])), max(0, min(255, c[2])))


def bake(
    key,
    size: Tuple[int, int],
    draw_fn,
    ss: int = 3,
) -> pygame.Surface:
    """
    超采样烘焙一张表面并缓存。

    key      : 缓存键（必须能唯一标识这张图；推荐 (名称, 所有影响外观的参数)）
    size     : 目标尺寸（设计像素）
    draw_fn  : callable(surf) —— 在 ss 倍尺寸的表面上作画
    ss       : 超采样倍率，3 已足够平滑，4~5 用于特别小的图标

    返回只读 Surface（带 SRCALPHA），使用方不要原地修改。
    """
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    cacheable = (w * h) <= _BAKE_MAX_PIXELS
    ck = (key, w, h, ss)
    if cacheable:
        s = _bake_cache.get(ck)
        if s is not None:
            return s
    big = pygame.Surface((w * ss, h * ss), pygame.SRCALPHA)
    draw_fn(big)
    s = pygame.transform.smoothscale(big, (w, h))
    if cacheable:
        if len(_bake_cache) > _BAKE_MAX_ENTRIES:
            _bake_cache.clear()
        _bake_cache[ck] = s
    return s


def bake_raw(key, size: Tuple[int, int], draw_fn, ss: int = 3) -> pygame.Surface:
    """同 bake，但不缓存（绘制内容每帧变化时用，注意成本）。"""
    big = pygame.Surface((size[0] * ss, size[1] * ss), pygame.SRCALPHA)
    draw_fn(big)
    return pygame.transform.smoothscale(big, size)


def aa_circle(surf, center, radius: float, color, width: int = 0, ss: int = 3, q: int = 2) -> None:
    """
    抗锯齿圆。width=0 为实心。

    q 是尺寸量化步长：半径按 q 取整后再查缓存。这一点对性能很关键 ——
    游戏里的球/粒子半径往往连续变化，若不量化会每帧产生新缓存条目，
    缓存被反复清空，反而比不缓存更慢。
    """
    r = max(2, int(radius) // q * q)
    wd = int(width)
    pad = r + wd + 2
    size = 2 * pad

    def _d(s):
        pygame.draw.circle(s, _safe(color), (pad * ss, pad * ss), r * ss,
                           wd * ss if wd else 0)
    s = bake(("c", r, wd, _safe(color)), (size, size), _d, ss)
    surf.blit(s, (int(center[0] - pad), int(center[1] - pad)))


def aa_ellipse(surf, rect, color, width: int = 0, ss: int = 3, q: int = 2) -> None:
    """抗锯齿椭圆（rect = (x, y, w, h)）。尺寸按 q 量化后缓存。"""
    rw = max(2, int(rect[2]) // q * q)
    rh = max(2, int(rect[3]) // q * q)
    wd = int(width)
    pad = 2

    def _d(s):
        pygame.draw.ellipse(s, _safe(color),
                            pygame.Rect(pad * ss, pad * ss, rw * ss, rh * ss),
                            wd * ss if wd else 0)
    s = bake(("e", rw, rh, wd, _safe(color)), (rw + pad * 2, rh + pad * 2), _d, ss)
    surf.blit(s, (int(rect[0]) - pad, int(rect[1]) - pad))


def aa_poly(surf, points, color, width: int = 0, ss: int = 3) -> None:
    """
    抗锯齿多边形。points 为设计像素坐标序列。

    面积超过阈值时直接绘制：超采样一张 1500×1000 的图要 6ms，
    对这种大面积色块（雪道、场地）来说得不偿失，AA 也看不出差别。
    """
    if len(points) < 3:
        return
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, y0 = min(xs), min(ys)
    wd = int(width)
    pad = wd + 2
    w = int(max(xs) - x0 + pad * 2 + 2)
    h = int(max(ys) - y0 + pad * 2 + 2)
    if w * h > _BAKE_MAX_PIXELS:
        pygame.draw.polygon(surf, _safe(color),
                            [(int(p[0]), int(p[1])) for p in points], wd)
        return
    pts = tuple((int(p[0] - x0 + pad), int(p[1] - y0 + pad)) for p in points)

    def _d(s):
        pygame.draw.polygon(s, _safe(color),
                            [(px * ss, py * ss) for px, py in pts], wd * ss if wd else 0)
    s = bake(("p", pts, wd, _safe(color)), (w, h), _d, ss)
    surf.blit(s, (int(x0 - pad), int(y0 - pad)))


def aa_line(surf, p0, p1, color, width: int = 2, cap: bool = True, ss: int = 3) -> None:
    """
    抗锯齿线段（width>1 时端点做圆头，近似胶囊）。

    缓存键只取 (|dx|, |dy|, width, color)，端点顺序会被归一化，
    因此"大量等长/等角度的装饰线"能命中同一张缓存，不会每帧重建表面。
    """
    x0, y0 = float(p0[0]), float(p0[1])
    x1, y1 = float(p1[0]), float(p1[1])
    dx = int(round(x1 - x0))
    dy = int(round(y1 - y0))
    if dx == 0 and dy == 0:
        return
    wd = max(1, int(width))
    pad = wd + 2
    adx, ady = abs(dx), abs(dy)
    w = adx + pad * 2 + 2
    h = ady + pad * 2 + 2
    ax, ay = pad, pad
    bx, by = pad + adx, pad + ady

    def _d(s):
        a = (ax * ss, ay * ss)
        b = (bx * ss, by * ss)
        pygame.draw.line(s, _safe(color), a, b, wd * ss)
        if cap and wd > 1:
            r = int(wd * ss / 2)
            pygame.draw.circle(s, _safe(color), a, r)
            pygame.draw.circle(s, _safe(color), b, r)
    s = bake(("l", adx, ady, wd, _safe(color)), (w, h), _d, ss)
    surf.blit(s, (int(min(x0, x1)) - pad, int(min(y0, y1)) - pad))


def aa_arc(surf, center, radius: float, color, a0: float, a1: float,
           width: int = 6, ss: int = 3, q: int = 2) -> None:
    """抗锯齿圆弧（角度用弧度）。尺寸按 q 量化后缓存。"""
    r = max(2, int(radius) // q * q)
    wd = max(1, int(width))
    pad = r + wd + 2
    size = pad * 2
    q0, q1 = round(a0, 2), round(a1, 2)

    def _d(s):
        pygame.draw.arc(s, _safe(color),
                        pygame.Rect((pad - r) * ss, (pad - r) * ss, r * 2 * ss, r * 2 * ss),
                        q0, q1, wd * ss)
    s = bake(("a", r, wd, _safe(color), q0, q1), (size, size), _d, ss)
    surf.blit(s, (int(center[0] - pad), int(center[1] - pad)))


def panel(w: float, h: float, color: Sequence[int], radius: int = 8,
          step: int = 6, **kw) -> pygame.Surface:
    """
    量化尺寸的面板（给"尺寸连续变化"的场景用，例如随透视缩放的障碍物）。

    直接对每个尺寸调用 art.shade_panel 会让缓存条目爆炸；这里把宽高
    量化到 step 像素，几十个尺寸就能覆盖整个缩放区间。
    """
    from . import art as _A
    qw = max(step, int(w / step) * step)
    qh = max(step, int(h / step) * step)
    return _A.shade_panel(qw, qh, color, radius, **kw)


def scaled(base: pygame.Surface, key, size: Tuple[int, int], step: int = 4) -> pygame.Surface:
    """带缓存的等比缩放（尺寸量化到 step 像素）。用于动态大小的精灵。"""
    w = max(2, int(size[0]) // step * step)
    h = max(2, int(size[1]) // step * step)
    ck = (key, w, h)
    s = _bake_cache.get(ck)
    if s is None:
        s = pygame.transform.smoothscale(base, (w, h))
        if len(_bake_cache) > _BAKE_MAX_ENTRIES:
            _bake_cache.clear()
        _bake_cache[ck] = s
    return s


def blur(surf: pygame.Surface, factor: int = 4) -> pygame.Surface:
    """快速模糊（降采样再升采样）。返回新表面，不修改原图。"""
    f = max(2, int(factor))
    w, h = surf.get_size()
    sw, sh = max(1, w // f), max(1, h // f)
    return pygame.transform.smoothscale(
        pygame.transform.smoothscale(surf, (sw, sh)), (w, h))


def blur_smooth(surf: pygame.Surface, passes: int = 3, factor: int = 3) -> pygame.Surface:
    """多次轻模糊，比单次大 factor 更接近高斯，用于背景景深。"""
    s = surf
    for _ in range(max(1, passes)):
        s = blur(s, factor)
    return s


_blur_cache: Dict[Tuple, pygame.Surface] = {}


def blur_bg(key, surf: pygame.Surface, factor: int = 3, passes: int = 3) -> pygame.Surface:
    """背景模糊（带缓存：背景是静态图时才用）。"""
    ck = (key, factor, passes)
    s = _blur_cache.get(ck)
    if s is None:
        s = blur_smooth(surf, passes, factor)
        if len(_blur_cache) > 60:
            _blur_cache.clear()
        _blur_cache[ck] = s
    return s


def radial(w: int, h: int, inner: Sequence[int], outer: Sequence[int],
           cx: float = 0.5, cy: float = 0.5, power: float = 1.4) -> pygame.Surface:
    """
    径向渐变（缓存）。cx/cy 为 0~1 的相对圆心，作为光照中心使用。
    inner 为中心色，outer 为边缘色（可取 RGBA）。
    """
    key = ("rad", w, h, tuple(inner), tuple(outer), round(cx, 3), round(cy, 3), round(power, 2))
    s = _grad_cache.get(key)
    if s is None:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        dx = (xx / max(1, w - 1)) - cx
        dy = (yy / max(1, h - 1)) - cy
        d = np.sqrt(dx * dx + dy * dy)
        d = np.clip(d / max(1e-6, d.max()), 0.0, 1.0) ** power
        ic = np.array(inner, dtype=np.float32)
        oc = np.array(outer, dtype=np.float32)
        n = min(len(inner), len(outer))
        arr = np.zeros((h, w, n), dtype=np.float32)
        for i in range(n):
            arr[..., i] = ic[i] + (oc[i] - ic[i]) * d
        arr = np.clip(arr, 0, 255).astype(np.uint8)
        if n == 4:
            s = pygame.image.frombuffer(arr.tobytes(), (w, h), "RGBA").convert_alpha()
        else:
            s = pygame.surfarray.make_surface(arr.swapaxes(0, 1))
        _grad_cache[key] = s
    return s


def vignette(w: int, h: int, strength: int = 120, power: float = 1.6) -> pygame.Surface:
    """暗角（缓存），用于把注意力收到画面中心。"""
    key = ("vig", w, h, strength, round(power, 2))
    s = _grad_cache.get(key)
    if s is None:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        dx = (xx / max(1, w - 1)) - 0.5
        dy = (yy / max(1, h - 1)) - 0.5
        d = np.clip(np.sqrt(dx * dx + dy * dy) * 1.42, 0.0, 1.0) ** power
        a = (d * strength).astype(np.uint8)
        arr = np.zeros((h, w, 4), dtype=np.uint8)
        arr[..., 3] = a
        s = pygame.image.frombuffer(arr.tobytes(), (w, h), "RGBA").convert_alpha()
        _grad_cache[key] = s
    return s


def tint(surf: pygame.Surface, color: Sequence[int], strength: float = 0.25) -> pygame.Surface:
    """方向性染色（保持亮度），用于统一场景色温。"""
    out = surf.copy()
    lay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
    lay.fill((color[0], color[1], color[2], int(255 * clamp(strength, 0, 1))))
    out.blit(lay, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return out


# --------------------------------------------------------------------------- #
# 环形/线性仪表（游戏里大量用到的进度环、蓄力条）
# --------------------------------------------------------------------------- #
def ring_gauge(
    surf: pygame.Surface,
    center: Tuple[int, int],
    radius: int,
    width: int,
    pct: float,
    fg: Sequence[int],
    bg: Sequence[int] = (60, 70, 96),
    start: float = -math.pi / 2,
    glow: bool = True,
) -> None:
    """环形进度条（抗锯齿）。pct 0~1。"""
    pct = clamp(pct, 0.0, 1.0)
    if glow and pct > 0.01:
        g = glow_surface(int(radius * 1.5), fg, 70, 8)
        surf.blit(g, (center[0] - int(radius * 1.5), center[1] - int(radius * 1.5)))
    if pct < 0.999:
        aa_arc(surf, center, radius, bg, 0, math.tau, width)
    if pct > 0.001:
        aa_arc(surf, center, radius, fg, start, start + math.tau * pct, width)


def bar_gauge(
    surf: pygame.Surface,
    rect: pygame.Rect,
    pct: float,
    fg: Sequence[int],
    bg: Sequence[int] = (48, 56, 78),
    radius: int = 8,
    gloss: bool = True,
) -> None:
    """圆角进度条。"""
    rr(surf, rect, radius, tuple(bg))
    w = int(rect.w * clamp(pct, 0.0, 1.0))
    if w >= 2:
        rr(surf, pygame.Rect(rect.x, rect.y, w, rect.h), radius, tuple(fg))
        if gloss and rect.h >= 10:
            hi = pygame.Surface((max(1, w - 6), max(1, rect.h // 3)), pygame.SRCALPHA)
            hi.fill((255, 255, 255, 46))
            surf.blit(hi, (rect.x + 3, rect.y + 3))


def dashed_line(surf, p0, p1, color, width: int = 3, dash: int = 14, gap: int = 10) -> None:
    x0, y0 = p0
    x1, y1 = p1
    ln = math.hypot(x1 - x0, y1 - y0)
    if ln < 1:
        return
    ux, uy = (x1 - x0) / ln, (y1 - y0) / ln
    t = 0.0
    while t < ln:
        e = min(ln, t + dash)
        aa_line(surf, (x0 + ux * t, y0 + uy * t), (x0 + ux * e, y0 + uy * e), color, width)
        t = e + gap


def bezier(p0, p1, p2, t: float):
    u = 1.0 - t
    return (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])


def bezier_path(p0, p1, p2, n: int = 16):
    return [bezier(p0, p1, p2, i / (n - 1)) for i in range(n)]


def star_points(cx: float, cy: float, r_out: float, r_in: float, n: int = 5, rot: float = -math.pi / 2):
    pts = []
    for i in range(n * 2):
        r = r_out if i % 2 == 0 else r_in
        a = rot + i * math.pi / n
        pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    return pts


def sparkle(surf, x: float, y: float, r: float, color, alpha: int = 200) -> None:
    """四角星闪光。"""
    a = int(clamp(alpha, 0, 255))
    c = (color[0], color[1], color[2], a)
    pts = [(x, y - r), (x + r * 0.22, y - r * 0.22), (x + r, y),
           (x + r * 0.22, y + r * 0.22), (x, y + r),
           (x - r * 0.22, y + r * 0.22), (x - r, y),
           (x - r * 0.22, y - r * 0.22)]
    aa_poly(surf, pts, c, 0, ss=2)


# --------------------------------------------------------------------------- #
# 场景叠加层
# --------------------------------------------------------------------------- #
_overlay_cache: Dict[Tuple, pygame.Surface] = {}


def light_cone(w: int, h: int, color, angle_spread: float = 0.30,
               alpha: int = 40, key=None) -> pygame.Surface:
    """探照灯光锥（顶端窄、底端宽），用于球场/舞台打光。"""
    ck = ("cone", w, h, tuple(color[:3]), round(angle_spread, 3), alpha, key)
    s = _overlay_cache.get(ck)
    if s is None:
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        k = yy / max(1, h - 1)                     # 0 顶端 → 1 底端
        half = (0.06 + angle_spread * k) * w
        cx = w / 2.0
        d = np.abs(xx - cx) / np.maximum(1.0, half)
        inside = np.clip(1.0 - d, 0.0, 1.0) ** 1.5
        falloff = np.clip(1.0 - k * 0.55, 0.0, 1.0)
        a = (inside * falloff * alpha).astype(np.uint8)
        arr = np.zeros((h, w, 4), dtype=np.uint8)
        arr[..., 0] = color[0]
        arr[..., 1] = color[1]
        arr[..., 2] = color[2]
        arr[..., 3] = a
        s = pygame.image.frombuffer(arr.tobytes(), (w, h), "RGBA").convert_alpha()
        if len(_overlay_cache) > 80:
            _overlay_cache.clear()
        _overlay_cache[ck] = s
    return s


_led_font = {
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
    ":": ("000", "010", "000", "010", "000"), " ": ("000", "000", "000", "000", "000"),
    ".": ("000", "000", "000", "000", "010"), "-": ("000", "000", "111", "000", "000"),
}


def led_digit_width(px: int = 5) -> int:
    return 4 * px


def draw_led_text(surf, s: str, x: int, y: int, px: int, color, alpha: int = 255) -> int:
    """7 段点阵风格数字（用于球场计时牌/LED 板）。返回绘制宽度。"""
    col = (color[0], color[1], color[2], alpha)
    cx = x
    for ch in s:
        pat = _led_font.get(ch)
        if pat is None:
            cx += led_digit_width(px)
            continue
        for r, row in enumerate(pat):
            for c, v in enumerate(row):
                if v == "1":
                    surf.fill(col, (cx + c * px, y + r * px, px - 1, px - 1))
        cx += led_digit_width(px)
    return cx - x
