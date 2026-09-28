"""
core/ui.py
==========
统一视觉语言（Design System）。

为什么要有这一层
----------------
之前每个页面各写各的：顶栏一套灰底、卡片一套玻璃、结算又是一套文字排版，
颜色也是每个元素自己挑一个 —— 于是整体像"几个不同的人分别做的页面拼在一起"，
这就是廉价感的根本来源。

这个模块只做两件事：

  1. **定 token**：颜色语义、圆角阶梯、字号阶梯、阴影阶梯。
     所有 UI 代码只许引用 token，不许写裸色值。
  2. **给组件**：卡片 / 状态块 / 胶囊 / 大按钮 / 星级 / 图标。
     组件内部保证同一套圆角、同一套描光、同一套投影。

调色板取向：明亮、活泼、高饱和但不刺眼（家庭体感游戏，不是写实游戏）。
关键手法是**深紫底 + 亮色件**：底色带紫调且压暗，所有亮色才会"跳"出来；
如果底色用中性灰，再亮的颜色也会发闷 —— 这是廉价感最常见的来源。

性能
----
卡片/胶囊这类静态外观全部走 `theme.bake()` 缓存（按尺寸与配色做键），
每帧只做一次 blit。动画只改变**位置与缩放**，不重新生成表面。
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Sequence, Tuple

import pygame

from . import theme as U

# 颜色混合在 UI 里用得极多（主题色与表面色互混），直接暴露一下
mix = U.mix

Color = Tuple[int, int, int]


# =========================================================================== #
# 1) 颜色 token —— 只许用这些，不许再写裸色值
# =========================================================================== #
# 背景：深紫调（不是中性灰），亮色件才能跳出来
BG_DEEP = (34, 27, 68)
BG_MID = (52, 42, 104)
BG_SOFT = (76, 62, 140)

# Primary：亮紫蓝 —— UI 主体、按钮、焦点
PRIMARY = (118, 128, 255)
PRIMARY_D = (74, 82, 202)
PRIMARY_L = (172, 180, 255)

# Secondary：暖橙 —— 分数、金币、奖励（和 Primary 冷暖对撞，最醒目）
SECONDARY = (255, 172, 60)
SECONDARY_D = (212, 124, 24)

# Accent：薄荷青 —— 能量、确认、选中态
ACCENT = (72, 228, 186)
ACCENT_D = (26, 168, 134)

# 语义色
SUCCESS = (104, 216, 120)
DANGER = (255, 94, 110)
WARN = (255, 202, 72)
INFO = (98, 198, 255)

# 中性
PAPER = (250, 250, 255)          # 深底上的主要文字
PAPER_DIM = (178, 178, 216)      # 深底上的次要文字
INK = (32, 26, 60)               # 浅底上的主要文字
INK_DIM = (110, 106, 154)

# 表面（卡片）
SURFACE = (46, 38, 92)
SURFACE_HI = (62, 52, 118)       # 卡片顶部（渐变亮端）
SURFACE_LO = (34, 28, 72)        # 卡片底部（渐变暗端）
OUTLINE = (108, 100, 168)        # 描边

# 游戏各自的 ACCENT 可能和上面撞色，统一在这里归一到调色板色系，
# 避免"某个游戏忽然冒出一个土黄/荧绿"破坏整体感
ACCENT_POOL = (PRIMARY, SECONDARY, ACCENT, INFO, (232, 122, 232), (255, 128, 96),
               (140, 220, 96), (120, 208, 255))


def normalize_accent(c: Sequence[int]) -> Color:
    """把游戏自带的强调色映射到调色板色系（保留色相，统一明度与饱和）。"""
    r, g, b = int(c[0]), int(c[1]), int(c[2])
    h, s, v = _rgb_to_hsv(r, g, b)
    s = max(0.55, min(0.78, s))          # 饱和度收进同一区间
    v = max(0.86, min(1.0, v))           # 明度抬高，避免发暗发闷
    return _hsv_to_rgb(h, s, v)


def _rgb_to_hsv(r: int, g: int, b: int) -> Tuple[float, float, float]:
    mx, mn = max(r, g, b) / 255.0, min(r, g, b) / 255.0
    d = mx - mn
    if d < 1e-6:
        return 0.0, 0.0, mx
    if mx == r / 255.0:
        h = ((g - b) / 255.0 / d) % 6
    elif mx == g / 255.0:
        h = (b - r) / 255.0 / d + 2
    else:
        h = (r - g) / 255.0 / d + 4
    return h / 6.0, (d / mx if mx else 0.0), mx


def _hsv_to_rgb(h: float, s: float, v: float) -> Color:
    i = int(h * 6.0) % 6
    f = h * 6.0 - int(h * 6.0)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r, g, b = ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))[i]
    return (int(r * 255), int(g * 255), int(b * 255))


# =========================================================================== #
# 2) 尺寸 token
# =========================================================================== #
R_SM = 14
R_MD = 22
R_LG = 32
R_XL = 46

# 字号阶梯：远距离（2~4 米）可读。低于 T_XS 的一律不用在游戏画面上，
# 只允许出现在暂停/设置面板里。
T_HERO = 128
T_XL = 84
T_L = 58
T_M = 42
T_S = 30
T_XS = 24

GAP_XS, GAP_S, GAP_M, GAP_L = 8, 14, 24, 40

# 投影阶梯
SH_S = (10, 12, 90)
SH_M = (18, 20, 130)
SH_L = (30, 34, 170)


# =========================================================================== #
# 3) 动画 tween
# =========================================================================== #
class Tween:
    """指数逼近的插值器：给 UI 值加惯性与缓动，避免线性动画的机械感。"""

    __slots__ = ("v", "target", "k")

    def __init__(self, v: float = 0.0, k: float = 12.0) -> None:
        self.v = float(v)
        self.target = float(v)
        self.k = float(k)

    def to(self, target: float) -> None:
        self.target = float(target)

    def snap(self, v: float) -> None:
        self.v = self.target = float(v)

    def step(self, dt: float) -> float:
        if self.k <= 0:
            self.v = self.target
            return self.v
        self.v += (self.target - self.v) * (1.0 - math.exp(-dt * self.k))
        if abs(self.target - self.v) < 1e-4:
            self.v = self.target
        return self.v


class Pop:
    """
    冲击式缩放：被触发时冲到 1，再弹回 0。

    用于"命中/得分"时 UI 的弹一下 —— 这是"操作有反馈"最便宜也最有效的做法。
    用弹性衰减而不是线性回弹，才有"手感"。
    """

    __slots__ = ("v", "k", "w")

    def __init__(self, k: float = 11.0, w: float = 4.6) -> None:
        self.v = 0.0
        self.k = k
        self.w = w

    def hit(self, amount: float = 1.0) -> None:
        self.v = min(2.0, self.v + amount)

    def step(self, dt: float) -> float:
        self.v += (0.0 - self.v) * (1.0 - math.exp(-dt * self.k))
        if self.v < 1e-4:
            self.v = 0.0
        return self.v

    def scale(self, amount: float = 0.18) -> float:
        """转成缩放系数：静止时 1.0，冲击瞬间 1+amount。"""
        return 1.0 + self.v * amount


# =========================================================================== #
# 4) 材质基元 —— 所有卡片/面板共用同一套"描光 + 渐变 + 投影"
# =========================================================================== #
_MASK_CACHE: Dict[Tuple[int, int, int], pygame.Surface] = {}
_MASK_PX = 0
_CARD_PX = 0
# 表面缓存的内存预算（像素数）。按"条数"限制是不够的 ——
# 结算面板那种 1060×880 的卡片单张就 3.7MB，烘焙时按 2 倍超采样还要再 ×4，
# 十几张就能吃掉几百 MB。按**总像素**封顶才控得住。
_CACHE_MAX_PX = 26_000_000


def _evict_if_needed() -> None:
    global _MASK_PX, _CARD_PX
    if _MASK_PX + _CARD_PX > _CACHE_MAX_PX:
        _MASK_CACHE.clear()
        _CARD_CACHE.clear()
        # 同时把烘焙链上的临时表面清掉：卡片按 2 倍超采样烘焙，
        # 一张 1800×330 的卡片在烘焙瞬间要 9.5MB 临时表面，
        # 而它们同样留在 theme 的缓存里 —— 内存是分几处一起涨的。
        U.clear_transient()
        _MASK_PX = _CARD_PX = 0


def _round_mask(w: int, h: int, r: int) -> pygame.Surface:
    """圆角遮罩（缓存）。用它裁渐变，比逐像素算圆角快得多。"""
    global _MASK_PX
    key = (w, h, r)
    m = _MASK_CACHE.get(key)
    if m is None:
        _evict_if_needed()
        _MASK_PX += w * h
        m = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(m, (255, 255, 255, 255), (0, 0, w, h), border_radius=r)
        _MASK_CACHE[key] = m
    return m


def _card_surface(w: int, h: int, radius: int, top: Color, bottom: Color,
                  outline: Optional[Color], rim: float) -> pygame.Surface:
    """
    烘焙一张卡片：竖向渐变 + 顶部描光（rim light）+ 1px 描边。

    顶部那道"描光"是卡通材质的关键 —— 少了它，卡片就是一块死板的纯色矩形，
    这正是之前 HUD 看起来像后台管理系统的直接原因。
    """
    ss = 2
    W, H = max(1, int(w)), max(1, int(h))
    R = max(0, int(radius))
    BW, BH = W * ss, H * ss

    surf = pygame.transform.smoothscale(U.vgrad(W, H, top, bottom), (BW, BH))
    surf = surf.convert_alpha()
    surf.blit(_round_mask(BW, BH, R * ss), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

    if rim > 0:
        band_h = max(3, int(BH * 0.30))
        band = pygame.Surface((BW, BH), pygame.SRCALPHA)
        a = int(130 * rim)
        for i in range(band_h):
            k = 1.0 - i / max(1, band_h - 1)
            band.fill((255, 255, 255, int(a * k * k)), (0, i, BW, 1))
        band.blit(_round_mask(BW, BH, R * ss), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        surf.blit(band, (0, 0))

    if outline is not None:
        pygame.draw.rect(surf, tuple(outline) + (140,), (0, 0, BW, BH),
                         max(2, int(1.4 * ss)), border_radius=R * ss)

    return pygame.transform.smoothscale(surf, (W, H))


_CARD_CACHE: Dict[Tuple, pygame.Surface] = {}


def card_surface(w: int, h: int, radius: int = R_MD,
                 top: Optional[Color] = None, bottom: Optional[Color] = None,
                 outline: Optional[Color] = OUTLINE, rim: float = 0.6) -> pygame.Surface:
    global _CARD_PX
    top = top or SURFACE_HI
    bottom = bottom or SURFACE_LO
    key = (int(w), int(h), int(radius), tuple(top), tuple(bottom),
           None if outline is None else tuple(outline), round(rim, 2))
    s = _CARD_CACHE.get(key)
    if s is None:
        _evict_if_needed()
        _CARD_PX += int(w) * int(h)
        s = _card_surface(int(w), int(h), radius, tuple(top), tuple(bottom),
                          None if outline is None else tuple(outline), rim)
        _CARD_CACHE[key] = s
    return s


def card(surf: pygame.Surface, rect: pygame.Rect, radius: int = R_MD,
         top: Optional[Color] = None, bottom: Optional[Color] = None,
         outline: Optional[Color] = OUTLINE, rim: float = 0.6,
         shadow: Optional[Tuple[int, int, int]] = SH_M,
         glow: Optional[Color] = None, glow_a: int = 90) -> None:
    """画一张游戏卡片（圆角 + 渐变 + 顶部描光 + 投影 + 可选外发光）。"""
    if glow is not None:
        g = U.glow_surface(max(rect.w, rect.h) // 2 + 18, glow, glow_a, 7)
        surf.blit(g, (rect.centerx - g.get_width() // 2,
                      rect.centery - g.get_height() // 2))
    if shadow is not None:
        d, spread, a = shadow
        U.soft_shadow(surf, rect, radius, spread, a, (0, d))
    surf.blit(card_surface(rect.w, rect.h, radius, top, bottom, outline, rim),
              (rect.x, rect.y))


def ink_card(surf: pygame.Surface, rect: pygame.Rect, radius: int = R_MD,
             alpha: int = 232, shadow: Optional[Tuple[int, int, int]] = SH_L,
             outline: Optional[Color] = None) -> None:
    """半透明深色卡片：压在游戏画面之上时用，保证文字始终可读。"""
    if shadow is not None:
        d, spread, a = shadow
        U.soft_shadow(surf, rect, radius, spread, a, (0, d))
    s = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
    pygame.draw.rect(s, tuple(SURFACE) + (alpha,), (0, 0, rect.w, rect.h),
                     border_radius=radius)
    pygame.draw.rect(s, (255, 255, 255, 40), (0, 0, rect.w, max(2, rect.h // 12)),
                     border_radius=radius)
    if outline is not None:
        pygame.draw.rect(s, tuple(outline) + (140,), (0, 0, rect.w, rect.h),
                         2, border_radius=radius)
    surf.blit(s, (rect.x, rect.y))


# =========================================================================== #
# 5) 组件
# =========================================================================== #
def text(surf: pygame.Surface, s: str, pos: Tuple[float, float], size: int,
         color: Color = PAPER, center: bool = False, bold: bool = True,
         outline: Optional[Color] = None, outline_w: int = 3,
         shadow: int = 0, alpha: int = 255) -> pygame.Rect:
    """
    统一文字。默认**加粗 + 深色描边**：卡通游戏的字必须有描边，
    否则压在花花绿绿的背景上会糊成一片 —— 这是"专业"和"业余"最直观的差别。
    """
    return U.text(surf, s, pos, size, color, center=center, bold=bold,
                  outline=outline, outline_w=outline_w, shadow=shadow,
                  alpha=alpha)


def stat(surf: pygame.Surface, rect: pygame.Rect, label: str, value: str,
         color: Color = PAPER, icon: str = "", pop: float = 0.0,
         value_size: int = 0) -> None:
    """
    状态块：图标 + 小标签 + 大数值。这是 HUD 的基本单元。

    刻意做成"小标签 + 大数值"的强层级：远距离看不清标签没关系，
    数值必须最先被读到。
    """
    vs = value_size or min(54, rect.h - 34)
    card(surf, rect, R_MD)
    # 左侧色条（该状态的主题色）
    pygame.draw.rect(surf, color, (rect.x + 2, rect.y + 12, 7, rect.h - 24),
                     border_radius=4)

    cx = rect.x + 22
    if icon:
        draw_icon(surf, icon, cx + 15, rect.centery, 30, color)
        cx += 44
    text(surf, label, (cx, rect.y + 10), T_XS, PAPER_DIM, bold=True)
    s = U.outline_text(value, vs, color, INK, 3, True)
    if pop > 0.01:
        s = pygame.transform.rotozoom(s, 0, 1.0 + 0.22 * pop)
    surf.blit(s, (cx, rect.y + 30))


def pill(surf: pygame.Surface, center: Tuple[float, float], label: str,
         color: Color, icon: str = "", size: int = T_XS, alpha: int = 224,
         pad: int = 26, height: int = 54, align: str = "center",
         glow: bool = False) -> pygame.Rect:
    """
    胶囊标签：用于"识别状态""连击""模式"这类短信息。

    align: center / right / left —— 决定 center[0] 被当作中心、右边缘还是左边缘。
    HUD 右上角的状态条必须右对齐，用 center 摆会随文字长度抖动。
    """
    img = U.outline_text(label, size, PAPER, INK, 3, True)
    w = img.get_width() + pad * 2 + (40 if icon else 0)
    x = {"right": center[0] - w, "left": center[0]}.get(align, center[0] - w / 2)
    r = pygame.Rect(int(x), int(center[1] - height / 2), int(w), height)
    if glow:
        U.glow(surf, (r.centerx, r.centery), r.h // 2 + 22, color, 74)
    s = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
    pygame.draw.rect(s, tuple(color) + (alpha,), (0, 0, r.w, r.h),
                     border_radius=r.h // 2)
    pygame.draw.rect(s, (255, 255, 255, 54), (0, 0, r.w, max(3, r.h // 3)),
                     border_radius=r.h // 2)
    pygame.draw.rect(s, (255, 255, 255, 74), (0, 0, r.w, r.h), 2,
                     border_radius=r.h // 2)
    surf.blit(s, (r.x, r.y))
    if icon:
        draw_icon(surf, icon, r.x + pad + 4, r.centery, size + 6, PAPER)
        surf.blit(img, (r.x + pad + 34, r.centery - img.get_height() // 2))
    else:
        surf.blit(img, (r.centerx - img.get_width() // 2,
                        r.centery - img.get_height() // 2))
    return r


def big_button(surf: pygame.Surface, rect: pygame.Rect, label: str,
               color: Color = PRIMARY, t: float = 0.0, hot: bool = False,
               size: int = T_L, sub: str = "") -> None:
    """大按钮：体感游戏里按钮必须大、必须一眼看出"这是焦点"。"""
    pulse = 0.5 + 0.5 * math.sin(t * 3.0)
    grow = 1.0 + (0.02 + 0.015 * pulse) * (1.0 if hot else 0.0)
    r = rect.inflate(int(rect.w * (grow - 1)), int(rect.h * (grow - 1)))
    dark = U.shade(color, 0.62)
    s = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
    pygame.draw.rect(s, tuple(dark), (0, 5, r.w, r.h - 5), border_radius=r.h // 2)
    pygame.draw.rect(s, tuple(color), (0, 0, r.w, r.h - 6), border_radius=r.h // 2)
    pygame.draw.rect(s, (255, 255, 255, 96), (0, 3, r.w, r.h // 3),
                     border_radius=r.h // 2)
    pygame.draw.rect(s, (255, 255, 255, 120), (0, 0, r.w, r.h - 6), 3,
                     border_radius=r.h // 2)
    U.glow(surf, (r.centerx, r.centery), r.w // 2 + 30, color,
           70 + int(50 * pulse) if hot else 40)
    surf.blit(s, (r.x, r.y))
    img = U.outline_text(label, size, PAPER, INK, 3, True)
    y = r.centery - img.get_height() // 2 - (14 if sub else 0)
    surf.blit(img, (r.centerx - img.get_width() // 2, y))
    if sub:
        text(surf, sub, (r.centerx, r.centery + img.get_height() // 2 - 16),
             T_XS, PAPER_DIM, center=True)


def stars(surf: pygame.Surface, center: Tuple[float, float], filled: int,
          total: int, r: float = 30.0, t: float = 0.0, gap: float = 12.0) -> None:
    """星级：结算页用。未点亮的星星是暗描边，点亮的带发光与轻微跳动。"""
    span = total * (r * 2 + gap) - gap
    x0 = center[0] - span / 2 + r
    for i in range(total):
        on = i < filled
        pop = 1.0 + (0.16 * math.sin(t * 6.0 - i * 0.9) if on else 0.0)
        cx = x0 + i * (r * 2 + gap)
        pts = U.star_points(cx, center[1], r * pop, r * 0.46 * pop, 5)
        if on:
            U.glow(surf, (int(cx), int(center[1])),
                   int(r * pop * 1.9), SECONDARY, 110)
            pygame.draw.polygon(surf, SECONDARY, pts)
            pygame.draw.polygon(surf, (255, 244, 196), pts, 4)
        else:
            pygame.draw.polygon(surf, (72, 66, 118), pts)
            pygame.draw.polygon(surf, (110, 102, 160), pts, 3)


# =========================================================================== #
# 6) UI 图标（和游戏图标分开：这里只放界面语义图标）
# =========================================================================== #
_ICON_CACHE: Dict[Tuple, pygame.Surface] = {}


def _icon_surface(name: str, size: int, color: Color) -> pygame.Surface:
    # 尺寸量化到 2px：图标带冲击缩放动画时尺寸是连续值，不量化会冲爆缓存
    W = max(8, int(size) // 2 * 2)
    key = (name, W, tuple(color))
    s = _ICON_CACHE.get(key)
    if s is not None:
        return s
    ss = 3
    big = pygame.Surface((W * ss, W * ss), pygame.SRCALPHA)
    k = W * ss / 100.0
    c = tuple(color)
    dark = U.shade(color, 0.55)

    def P(pts, col, wd=0):
        pygame.draw.polygon(big, col, [(x * k, y * k) for x, y in pts], int(wd * k))

    def C(x, y, r, col, wd=0):
        pygame.draw.circle(big, col, (int(x * k), int(y * k)), int(r * k),
                           int(wd * k) if wd else 0)

    def L(p0, p1, col, wd):
        pygame.draw.line(big, col, (p0[0] * k, p0[1] * k), (p1[0] * k, p1[1] * k),
                         max(1, int(wd * k)))

    if name == "star":
        P(U.star_points(50 * k, 50 * k, 46 * k, 20 * k, 5), c)
    elif name == "heart":
        C(34, 38, 20, c)
        C(66, 38, 20, c)
        P([(15, 44), (85, 44), (50, 90)], c)
    elif name == "clock":
        C(50, 50, 44, c, 12)
        L((50, 50), (50, 24), c, 12)
        L((50, 50), (70, 58), c, 12)
    elif name == "bolt":
        P([(58, 4), (24, 54), (47, 54), (40, 96), (78, 44), (54, 44)], c)
    elif name == "target":
        for rr, col in ((46, c), (30, dark), (14, c)):
            C(50, 50, rr, col)
    elif name == "crown":
        P([(12, 74), (22, 30), (38, 52), (50, 22), (62, 52), (78, 30), (88, 74)], c)
    elif name == "trophy":
        P([(30, 22), (70, 22), (66, 56), (34, 56)], c)
        L((50, 56), (50, 78), c, 10)
        P([(28, 78), (72, 78), (68, 92), (32, 92)], c)
        C(26, 34, 12, c, 7)
        C(74, 34, 12, c, 7)
    elif name == "combo":
        P([(50, 6), (62, 38), (96, 38), (68, 58), (79, 92), (50, 71),
           (21, 92), (32, 58), (4, 38), (38, 38)], c)
    elif name == "check":
        L((18, 52), (40, 76), c, 16)
        L((40, 76), (84, 26), c, 16)
    elif name == "eye":
        P([(6, 50), (50, 20), (94, 50), (50, 80)], c)
        C(50, 50, 16, dark)
    elif name == "wave":
        for i, y in enumerate((30, 50, 70)):
            L((14, y), (86, y), c, 8)
    else:                                   # 兜底：一个圆点
        C(50, 50, 34, c)
    s = pygame.transform.smoothscale(big, (W, W))
    if len(_ICON_CACHE) > 160:
        _ICON_CACHE.clear()
    _ICON_CACHE[key] = s
    return s


def draw_icon(surf: pygame.Surface, name: str, cx: float, cy: float,
              size: float, color: Color) -> None:
    s = _icon_surface(name, max(8, int(size)), tuple(color))
    r = s.get_rect(center=(int(cx), int(cy)))
    surf.blit(s, r)
