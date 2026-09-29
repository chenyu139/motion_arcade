"""
core/scene.py
=============
分层场景与氛围。

要解决的问题
------------
之前的背景是"纯色分块"：一大片纯蓝天空、一块深蓝灰梯形当中景、几座纯绿三角山，
云是一串白圆圈。它一眼就能看出是代码拼的，这是"廉价感"最直观的来源。

商业卡通场景的做法是把画面拆成**明确的前中后景**，并用三件事把它们粘起来：

  1. **大气透视**（fog）：越远的东西越淡、越偏天空色。没有它，远近元素一样实，
     画面就是平的。
  2. **顶光 + 环境光遮蔽**：所有物体有统一的受光方向（左上），底部压暗。
     一致的打光方向是"同一个世界"的核心，比任何单独的画得好看都重要。
  3. **氛围层**：空气里的浮尘、从上方洒下的柔光、边缘压暗。它们本身几乎看不见，
     但去掉之后画面立刻变成"贴图 PPT"。

模块分两部分：
  · `Atmosphere`：**全屏氛围层**。由外壳对全部 20 款游戏无差别叠加，
    所以不需要改动任何游戏就能整体抬一个档次。
  · 一组场景构件（sky / cloud / hill_range / ground_band / fog_band / sun），
    供各游戏重建自己的背景。
"""
from __future__ import annotations

import math
import os
import random
from typing import Dict, List, Optional, Tuple

import numpy as np
import pygame

from . import theme as U
from . import ui as UI

Color = Tuple[int, int, int]


# =========================================================================== #
# 绘制好的天空背景（assets/bg/sky_*.png，AI 生成原创）
# =========================================================================== #
# 纯渐变天空是"代码感"最重的一层。这里提供一张真正画出来的天空作为可选底图：
# 有云、有大气层次、有光照方向 —— 各游戏的远景/地面照旧画在它上面，
# 深度合成（depth_pass）再统一叠加，风格就能保持一致。
_BG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "assets", "bg")
_SKY_CACHE: Dict[str, Optional[pygame.Surface]] = {}


def sky_img(w: int, h: int, name: str, tile_x: bool = False) -> Optional[pygame.Surface]:
    """
    取一张绘制好的天空背景图，缩放到 (w, h)。

    tile_x=True 时水平平铺（超长关卡背景用，比如横版跑酷的 6000px 长图）。
    素材缺失时返回 None —— 调用方据此回退到原来的渐变天空，
    与 `core/sprites.py` 的"缺图不崩"是同一条设计原则。
    """
    key = (name, w, h, tile_x)
    got = _SKY_CACHE.get(key)
    if got is not None or (key in _SKY_CACHE and got is None):
        return got
    path = os.path.join(_BG_DIR, f"{name}.png")
    if not os.path.exists(path):
        _SKY_CACHE[key] = None
        return None
    try:
        raw = pygame.image.load(path).convert()
    except Exception as e:                                       # noqa: BLE001
        print(f"[scene] 载入天空 {name} 失败：{e}")
        _SKY_CACHE[key] = None
        return None
    # cover：等比缩放填满 (w, h) 并居中裁剪，避免宽幅背景被横向拉变形
    sw, sh = raw.get_size()
    scale = max(w / sw, h / sh)
    nw, nh = int(round(sw * scale)), int(round(sh * scale))
    scaled = pygame.transform.smoothscale(raw, (nw, nh))
    if tile_x:
        s = pygame.Surface((w, h))
        step = scaled.get_width()
        for x in range(0, w, step):
            s.blit(scaled, (x, 0))
    else:
        if nw == w and nh == h:
            s = scaled
        else:
            s = scaled.subsurface(((nw - w) // 2, (nh - h) // 2, w, h)).copy()
    if len(_SKY_CACHE) > 24:
        _SKY_CACHE.clear()
    _SKY_CACHE[key] = s
    return s


def sky(w: int, h: int, top: Color, mid: Color, bottom: Color) -> pygame.Surface:
    """三段渐变天空。比两段渐变多一层中间色，天顶到地平线的过渡才不生硬。"""
    return U.vgrad3(w, h, top, mid, bottom)


def sky_or(surf: pygame.Surface, name: str, w: int, h: int,
           top: Color, mid: Color, bottom: Color, tile_x: bool = False) -> None:
    """优先贴绘制好的天空图，缺图回退到三段渐变。大多数游戏一行搞定。"""
    img = sky_img(w, h, name, tile_x=tile_x)
    surf.blit(img, (0, 0)) if img is not None else surf.blit(sky(w, h, top, mid, bottom), (0, 0))


def sun(surf: pygame.Surface, cx: float, cy: float, r: float,
        color: Color = (255, 246, 214), core: bool = True) -> None:
    """太阳：大范围柔光 + 实心亮核。柔光是"光源存在"的证据，缺了就像贴了张亮片。"""
    U.glow(surf, (int(cx), int(cy)), int(r * 2.6), color, 62, 9)
    U.glow(surf, (int(cx), int(cy)), int(r * 1.35), color, 96, 8)
    if core:
        U.aa_circle(surf, (cx, cy), r, color, 0, ss=2)


_CLOUD_CACHE: Dict[Tuple, pygame.Surface] = {}


def cloud_sprite(width: int, color: Color, shade_k: float = 0.78,
                 seed: int = 0) -> pygame.Surface:
    """
    一团卡通云。

    之前是"一条平整的底 + 几个白圆"，看起来就是一串白气泡。两个原因：
      · 圆的排布全在一条水平线上 → 轮廓是长条而不是云；
      · 想用 `shade(color, 1.0)` 做顶部高光 —— **对纯白是无效操作**
        （已经很亮，没有提亮空间），所以上下一样亮，完全没有体积。

    纯白云只能靠**暗底外露**来造体积：把暗色轮廓整体下移，让下沿露出暗边，
    上沿留白。这个方向与"光从左上来"一致，所以看起来是被光打亮的。
    """
    W = max(24, int(width) // 4 * 4)
    key = (W, tuple(color), round(shade_k, 2), seed)
    s = _CLOUD_CACHE.get(key)
    if s is not None:
        return s

    H = int(W * 0.60)
    ss = 2
    BW, BH = W * ss, H * ss
    big = pygame.Surface((BW, BH), pygame.SRCALPHA)
    base_y = BH * 0.76

    n = max(3, int(W / 58))
    puffs = []
    for i in range(n):
        t = (i + 0.5) / n
        hump = math.sin(t * math.pi) ** 0.65          # 中间高、两侧低
        r = BH * (0.235 + 0.155 * hump)
        puffs.append((BW * (0.11 + 0.78 * t),
                      base_y - r * (0.32 + 0.85 * hump), r))

    dark = U.shade(color, shade_k)
    off = BH * 0.070
    # 暗底：整体下移，露出下沿 —— 这是体积感的唯一来源
    for px, py, r in puffs:
        pygame.draw.circle(big, dark, (int(px - r * 0.05), int(py + off)), int(r + 1.5 * ss))
    # 主体
    for px, py, r in puffs:
        pygame.draw.circle(big, color, (int(px), int(py)), int(r))
    # 底部阴影（渐变），把"平底"压下去
    sh = pygame.Surface((BW, int(BH * 0.34)), pygame.SRCALPHA)
    for i in range(sh.get_height()):
        sh.fill(tuple(dark) + (int(66 * (1 - i / max(1, sh.get_height() - 1))),),
                (0, i, BW, 1))
    big.blit(sh, (0, int(base_y - BH * 0.05)))

    s = pygame.transform.smoothscale(big, (W, H))
    if len(_CLOUD_CACHE) > 60:
        _CLOUD_CACHE.clear()
    _CLOUD_CACHE[key] = s
    return s


def hill_range(surf: pygame.Surface, rect: pygame.Rect, count: int, color: Color,
               seed: int = 1, h_min: float = 0.25, h_max: float = 0.85,
               haze: float = 0.0) -> None:
    """
    一排圆润的山丘剪影（用正弦叠加而不是三角，边缘才不会有折线感）。

    haze > 0 时把颜色往天空色混合 —— 这就是**大气透视**：
    远处的东西必须"褪"进背景，而不是同样实心地贴上去。
    """
    rng = random.Random(seed)
    col = U.mix(color, (176, 208, 236), haze) if haze > 0 else color
    w = rect.w
    # 每个谐波只生成**一个**峰：频率低 + 相位固定，得到的是圆润的丘，
    # 而不是折线。旧版对和取 abs() —— 零点处一阶导不连续，于是到处是尖角，
    # 一排丘陵看起来像一排锯齿。
    waves = []
    for k in range(count):
        amp = 1.0 / (k + 1.6)
        freq = rng.uniform(0.6, 1.5) * (k + 1) * 0.5
        ph = rng.uniform(0, math.tau)
        waves.append((amp, freq, ph))
    norm = sum(a for a, _, _ in waves) or 1.0
    step = 10
    pts = [(rect.x, rect.bottom)]
    for i in range(0, int(w) + step, step):
        t = i / max(1.0, w)
        v = sum(a * math.sin(t * f * math.tau + ph) for a, f, ph in waves) / norm
        hh = (h_min + (h_max - h_min) * (0.5 + 0.5 * v)) * rect.h
        pts.append((rect.x + i, rect.bottom - hh))
    pts.append((rect.right, rect.bottom))
    U.aa_poly(surf, pts, col, 0, ss=2)


def ground_band(surf: pygame.Surface, rect: pygame.Rect, top: Color, bottom: Color,
                ao: int = 90, edge: Optional[Color] = None) -> None:
    """
    地面：竖向渐变 + 顶部一条环境光遮蔽（AO）暗带 + 一条受光亮边。

    顶部那条暗带（AO）是"物体坐在地面上"的关键：没有它，地面和景物之间
    会有一条生硬的直线接缝。
    """
    band = U.vgrad(rect.w, rect.h, top, bottom)
    surf.blit(band, (rect.x, rect.y))
    if ao > 0:
        a = pygame.Surface((rect.w, max(1, int(rect.h * 0.16))), pygame.SRCALPHA)
        h = a.get_height()
        for i in range(h):
            a.fill((0, 0, 0, int(ao * (1 - i / max(1, h - 1)) ** 1.4)),
                   (0, i, rect.w, 1))
        surf.blit(a, (rect.x, rect.y))
    if edge is not None:
        pygame.draw.line(surf, edge, (rect.x, rect.y), (rect.right, rect.y), 3)


def fog_band(surf: pygame.Surface, rect: pygame.Rect, color: Color,
             peak: int = 165, top: float = 0.35, bottom: float = 0.85) -> None:
    """
    雾带：把远景区和近景区在视觉上分开，制造纵深。

    强度必须是**中间浓、上下都归零**的驼峰，两端不能留边 ——
    旧版从 alpha 0 线性升到 168，于是雾带的下边缘（正好落在近景山的山脊上）
    会形成一条贯穿全屏的硬接缝，看起来就像画面被横切了一刀。
    """
    a = pygame.Surface((rect.w, max(2, rect.h)), pygame.SRCALPHA)
    h = a.get_height()
    for i in range(h):
        k = i / (h - 1)
        if k < top:
            v = k / max(1e-6, top)
        elif k > bottom:
            v = max(0.0, (1.0 - k) / max(1e-6, 1.0 - bottom))
        else:
            v = 1.0
        al = int(peak * (v ** 1.15))
        if al > 0:
            a.fill(tuple(color) + (al,), (0, i, rect.w, 1))
    surf.blit(a, (rect.x, rect.y))


# 可复用图层：全屏 SRCALPHA 一次 8MB，每帧新建两张会直接拖垮帧率
_LAYERS: Dict[Tuple[int, int, str], pygame.Surface] = {}


def reuse_layer(w: int, h: int, tag: str = "default") -> pygame.Surface:
    """取一张清空过的可复用图层（按尺寸与用途分池）。"""
    key = (w, h, tag)
    s = _LAYERS.get(key)
    if s is None or s.get_size() != (w, h):
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        _LAYERS[key] = s
    s.fill((0, 0, 0, 0))
    return s


def light_rays(surf: pygame.Surface, w: int, h: int, color: Color = (255, 244, 210),
               n: int = 5, alpha: int = 16, t: float = 0.0, seed: int = 3) -> None:
    """从画面上方斜洒下来的柔光柱。alpha 必须很低（10~20），否则立刻变脏。"""
    rng = random.Random(seed)
    layer = reuse_layer(w, h, "rays")
    for i in range(n):
        x0 = rng.uniform(-w * 0.1, w * 1.1)
        wdt = rng.uniform(w * 0.045, w * 0.13)
        lean = rng.uniform(0.12, 0.34)
        sway = math.sin(t * 0.28 + i) * w * 0.012
        pts = [(x0 + sway, 0), (x0 + wdt + sway, 0),
               (x0 + wdt + lean * h + sway, h), (x0 + lean * h + sway, h)]
        U.aa_poly(layer, pts, tuple(color) + (alpha,), 0, ss=2)
    surf.blit(layer, (0, 0))


# =========================================================================== #
# 全屏氛围层
# =========================================================================== #
class Atmosphere:
    """
    对全部游戏统一叠加的氛围层。

    这是"让 20 款游戏看起来像同一个游戏"最省力也最有效的一刀：
    不需要改任何游戏，只需要在合成时垫一层统一的空气、柔光与暗角。

    三部分（全部预烘焙，每帧只做固定次数的 blit）：
      · 底图：暗角 + 轻微色调分级（同时压掉四角的杂色，让视线集中在中央）
      · 光柱：从上方斜洒的柔光，缓慢摆动（让画面"在呼吸"）
      · 浮尘：空气里的微粒，缓慢移动（让空间有尺度感）
    """

    def __init__(self, w: int, h: int, accent: Color = UI.PRIMARY,
                 seed: int = 11, dust: int = 46) -> None:
        self.w, self.h = w, h
        self.accent = accent
        self._t = 0.0
        self._base = self._bake_base(w, h)
        # 光柱预烘焙成一张"加宽"的图，之后只靠水平平移摆动 ——
        # 每帧现画 5 个多边形 + 一次全屏合成太贵（实测整层 3.4ms）。
        self._rays = self._bake_rays(w, h)
        rng = random.Random(seed)
        self.dust = [
            {"x": rng.uniform(0, w), "y": rng.uniform(0, h * 0.92),
             "vx": rng.uniform(-9, 9), "vy": rng.uniform(-16, -4),
             "r": rng.uniform(1.2, 3.4), "ph": rng.uniform(0, math.tau),
             "a": rng.randint(22, 60)}
            for _ in range(dust)
        ]

    # ------------------------------------------------------------------ 烘焙
    @staticmethod
    @staticmethod
    def _bake_rays(w: int, h: int) -> pygame.Surface:
        """预烘焙光柱（比画面宽 160px，留给摆动余量）。"""
        pw = w + 160
        s = pygame.Surface((pw, h), pygame.SRCALPHA)
        rng = random.Random(3)
        for i in range(5):
            x0 = rng.uniform(0, pw)
            wdt = rng.uniform(w * 0.045, w * 0.13)
            lean = rng.uniform(0.12, 0.34)
            pts = [(x0, 0), (x0 + wdt, 0),
                   (x0 + wdt + lean * h, h), (x0 + lean * h, h)]
            U.aa_poly(s, pts, (255, 246, 214, 11), 0, ss=2)
        return s

    @staticmethod
    def _bake_base(w: int, h: int) -> pygame.Surface:
        """暗角 + 色调分级，合成一张，每帧一次 blit。"""
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        cx, cy = w / 2.0, h * 0.46
        maxd = math.hypot(w / 2.0, h / 2.0)
        # 用低分辨率径向渐变再放大 —— 全分辨率逐像素算暗角太慢
        step = 6
        sw, sh = max(2, w // step), max(2, h // step)
        small = pygame.Surface((sw, sh), pygame.SRCALPHA)
        for yy in range(sh):
            for xx in range(sw):
                px = xx * step + step / 2.0
                py = yy * step + step / 2.0
                d = math.hypot(px - cx, py - cy) / maxd
                a = int(120 * max(0.0, (d - 0.45) / 0.55) ** 1.7)
                # 顶部微暖、底部微冷：极轻的色调分级，压掉"死平"的观感
                k = py / h
                tr = int(58 * (1 - k) * 0.35)
                tb = int(70 * k * 0.35)
                small.set_at((xx, yy), (10 + tr, 8 + tr // 2, 26 + tb, a))
        s.blit(pygame.transform.smoothscale(small, (w, h)), (0, 0))
        return s

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float) -> None:
        self._t += dt
        for p in self.dust:
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            if p["y"] < -10:
                p["y"] = self.h * 0.95
                p["x"] = (p["x"] * 1.37) % self.w
            if p["x"] < -10:
                p["x"] = self.w + 8
            elif p["x"] > self.w + 10:
                p["x"] = -8

    def draw(self, surf: pygame.Surface, rays: bool = True) -> None:
        """
        三件事，全部是"每帧固定次数"的开销：

          1. 光柱：预烘焙图 + 水平平移摆动（一次 blit，不重画多边形）
          2. 浮尘：直接用带 alpha 的小圆点画 —— 走缓存 blit，
             不用整张全屏图层（那要多一次 8MB 合成，实测贵 1ms 以上）
          3. 暗角 + 色调分级：预烘焙，一次 blit

        合计约 2ms，对 16.7ms 的预算是可以接受的代价 ——
        它换来的是 20 款游戏统一的"空气感"，不叠加的话每款都得单独调。
        """
        if rays:
            off = int(math.sin(self._t * 0.28) * 60)
            surf.blit(self._rays, (-80 + off, 0))
        for p in self.dust:
            a = int(p["a"] * (0.55 + 0.45 * math.sin(self._t * 1.3 + p["ph"])))
            if a > 6:
                U.aa_circle(surf, (p["x"], p["y"]), p["r"],
                            (255, 255, 255, a), 0, ss=2, q=2)
        surf.blit(self._base, (0, 0))

# =========================================================================== #
# 世界预设 + 深度合成
# =========================================================================== #
# 这一步解决的是"廉价感"最根本的一条：**画面没有纵深与光照**。
#
# 20 款游戏各自的背景内容其实是有主题的（看台、球场、坑壁、幕布、竹林…），
# 但都是"平铺在一个平面上"：没有前后层次、没有雾、没有统一光源、
# 物体与地面之间没有接触阴影。结果就是"贴纸拼盘"，一眼像 AI Demo。
#
# 与其重写 19 套背景（工作量大、风格还会各自跑偏），这里做一次**统一的
# 深度合成**：给任何一张已画好的主题背景叠上
#
#     统一调色 → 方向光 + 边缘光 → 雾带 → 接触阴影(AO)
#              → 前景失焦剪影 → 暗角
#
# 六层都是烘焙好的图，运行时只有 6 次 blit。它同时满足了 prompt 里的
# 第 1 项（前中后三层 / 景深 / 阴影 / 氛围）、第 8 项（soft lighting /
# ambient occlusion / subtle bloom / rim light）和第 9 项（统一调色）。
_WORLD_PRESETS: Dict[str, Dict] = {
    # 白天草地：暖阳在左上，绿调
    "meadow": dict(light=(0.26, 0.13), light_col=(255, 246, 206), light_a=22,
                   rim=(255, 250, 224), fog=(202, 226, 246), fog_a=32,
                   fog_span=(0.60, 0.24), fg=(24, 46, 32), fg_a=88, vig=57,
                   rim_a=14, grade=(1.00, 1.02, 0.94)),
    # 雪线/高山：冷调高光，蓝雾
    "alpine": dict(light=(0.22, 0.12), light_col=(228, 242, 255), light_a=20,
                   rim=(240, 250, 255), fog=(224, 238, 252), fog_a=38,
                   fog_span=(0.58, 0.26), fg=(28, 44, 68), fg_a=93, vig=64,
                   rim_a=14, grade=(0.97, 1.00, 1.06)),
    # 黄昏球场：顶灯为主光，暖雾压在看台之上
    "stadium": dict(light=(0.50, 0.08), light_col=(255, 240, 208), light_a=18,
                    rim=(255, 236, 198), fog=(138, 156, 196), fog_a=27,
                    fog_span=(0.50, 0.20), fg=(16, 20, 40), fg_a=101, vig=69,
                    rim_a=14, grade=(1.02, 1.00, 1.00)),
    # 室内馆：冷顶光，蓝紫
    "court": dict(light=(0.34, 0.10), light_col=(250, 246, 255), light_a=17,
                  rim=(236, 240, 255), fog=(126, 138, 176), fog_a=24,
                  fog_span=(0.48, 0.22), fg=(18, 20, 42), fg_a=99, vig=68,
                  rim_a=14, grade=(1.00, 1.00, 1.05)),
    # 星夜：月光右上，极暗前景
    "night": dict(light=(0.74, 0.18), light_col=(206, 224, 255), light_a=15,
                  rim=(196, 214, 255), fog=(84, 92, 146), fog_a=29,
                  fog_span=(0.56, 0.26), fg=(8, 8, 24), fg_a=110, vig=81,
                  rim_a=14, grade=(0.96, 0.98, 1.08)),
    # 戏台：暖红顶光（川剧/舞台）
    "stage": dict(light=(0.50, 0.07), light_col=(255, 210, 164), light_a=21,
                  rim=(255, 196, 150), fog=(104, 62, 60), fog_a=26,
                  fog_span=(0.52, 0.24), fg=(28, 10, 16), fg_a=106, vig=75,
                  rim_a=14, grade=(1.06, 0.99, 0.98)),
    # 茶室 / 室内暖木
    "teahouse": dict(light=(0.28, 0.15), light_col=(255, 228, 184), light_a=20,
                     rim=(255, 218, 170), fog=(158, 118, 86), fog_a=23,
                     fog_span=(0.54, 0.24), fg=(30, 18, 12), fg_a=97, vig=71,
                     rim_a=14, grade=(1.05, 1.00, 0.96)),
    # 江河：暖阳 + 水面亮雾
    "river": dict(light=(0.30, 0.18), light_col=(255, 246, 214), light_a=21,
                  rim=(255, 244, 208), fog=(190, 216, 234), fog_a=36,
                  fog_span=(0.46, 0.26), fg=(22, 38, 42), fg_a=90, vig=62,
                  rim_a=14, grade=(1.00, 1.01, 1.00)),
    # 祭祀坑 / 神庙：顶部单点光，暗调
    "temple": dict(light=(0.50, 0.06), light_col=(255, 232, 176), light_a=22,
                   rim=(255, 224, 160), fog=(122, 96, 78), fog_a=28,
                   fog_span=(0.50, 0.26), fg=(22, 16, 12), fg_a=109, vig=78,
                   rim_a=14, grade=(1.03, 1.00, 0.96)),
    # 竹林 / 林间：绿色散射光
    "forest": dict(light=(0.36, 0.10), light_col=(232, 255, 214), light_a=18,
                   rim=(226, 252, 200), fog=(150, 190, 150), fog_a=30,
                   fog_span=(0.58, 0.24), fg=(18, 34, 24), fg_a=96, vig=66,
                   rim_a=14, grade=(0.98, 1.04, 0.98)),
}

_OVERLAY_CACHE: Dict[Tuple, Dict[str, pygame.Surface]] = {}
_OVERLAY_PX = 0
_OVERLAY_MAX_PX = 6_000_000     # 约 24MB（每个预设一套是 6 张全屏图）


# 饱和度提升：prompt 要求"高饱和但不刺眼"。1.12 是实测边界 ——
# 再高卡通色块会开始溢色，再低画面会发灰（第一版就是这样，像蒙了一层灰）。
_SAT_BOOST = 1.12


def _grade(surf: pygame.Surface, preset: str) -> None:
    """
    色彩分级：按预设做通道配平 + 轻度饱和度提升（prompt 第 9 项）。

    用 numpy 直接改像素，只在切游戏时跑一次（约 8~15ms），不影响帧率。
    """
    P = _WORLD_PRESETS.get(preset)
    if P is None:
        return
    gr, gg, gb = P.get("grade", (1.0, 1.0, 1.0))
    if abs(gr - 1) < 1e-3 and abs(gg - 1) < 1e-3 and abs(gb - 1) < 1e-3 \
            and abs(_SAT_BOOST - 1) < 1e-3:
        return
    try:
        px = pygame.surfarray.pixels3d(surf)
    except (pygame.error, ValueError):
        return
    a = px.astype("float32")
    a[..., 0] *= gr
    a[..., 1] *= gg
    a[..., 2] *= gb
    gray = a.mean(axis=2, keepdims=True)
    a = gray + (a - gray) * _SAT_BOOST
    px[:] = np.clip(a, 0, 255).astype("uint8")
    del px


def _world_overlays(w: int, h: int, preset: str, ground_y: int,
                    accent: Color) -> Dict[str, pygame.Surface]:
    """烘焙某套世界预设的六层叠加图（按 尺寸+预设+地平线+主题色 缓存）。"""
    global _OVERLAY_PX
    key = (w // 8 * 8, h // 8 * 8, preset, ground_y, tuple(accent))
    got = _OVERLAY_CACHE.get(key)
    if got is not None:
        return got

    P = _WORLD_PRESETS.get(preset, _WORLD_PRESETS["meadow"])
    lx, ly = int(w * P["light"][0]), int(h * P["light"][1])
    span, thick = P["fog_span"]

    # ---- 1) 统一调色：把整幅画面往主题色相上拉一点（第 9 项）----
    tint = pygame.Surface((w, h), pygame.SRCALPHA)
    tint.fill(tuple(accent) + (12,))

    # ---- 2) 方向光 + 边缘光 + 轻度 bloom（第 8 项）----
    # ⚠ 这里必须先做成"预乘亮度"再加法叠加。
    #   踩过的坑：直接 `blit(rim, BLEND_RGBA_ADD)` —— 加法混合**忽略源 alpha**，
    #   于是边缘光那条带被按 RGB 满值（255,250,224）整体加上去，
    #   整片天空直接过曝成白色（"洗白"）。
    #   正确做法：把光画到一张**不透明黑底**上（普通 alpha 混合 → RGB 自然
    #   等于 颜色 × 强度），再把这张图按 BLEND_RGB_ADD 叠上去。
    light = pygame.Surface((w, h))
    light.fill((0, 0, 0))
    gr = int(max(w, h) * 0.80)
    glow = U.glow_surface(gr, P["light_col"], P["light_a"], 12)
    light.blit(glow, (lx - gr, ly - gr))
    # 边缘光：从画面顶部往下衰减的一条宽带，给远处物体勾出高光轮廓
    rim = pygame.Surface((w, h), pygame.SRCALPHA)
    rim_h = int(h * 0.46)
    for i in range(rim_h):
        k = 1.0 - i / max(1, rim_h - 1)
        rim.fill(tuple(P["rim"]) + (int(P["rim_a"] * k * k),), (0, i, w, 1))
    light.blit(rim, (0, 0))

    # ---- 3) 雾带：把远景与近景在视觉上分开（第 1 项"景深"）----
    fog = pygame.Surface((w, h), pygame.SRCALPHA)
    fy = int(h * span)
    fog_band(fog, pygame.Rect(0, fy - int(h * thick * 0.35), w, int(h * thick)),
             P["fog"], P["fog_a"])

    # ---- 4) 接触阴影 AO：物体与地面之间那一条暗带（第 8 项）----
    ao = pygame.Surface((w, h), pygame.SRCALPHA)
    ah = max(24, int(h * 0.055))
    for i in range(ah):
        k = 1.0 - i / (ah - 1)
        ao.fill((0, 0, 0, int(96 * k ** 1.5)), (0, ground_y - ah // 2 + i, w, 1))
    # 地面下方再压暗一点，让"地平线"读得出来
    gh = max(20, int(h * 0.09))
    for i in range(gh):
        k = i / (gh - 1)
        ao.fill((0, 0, 0, int(64 * k ** 1.2)),
                (0, ground_y + i, w, 1))

    # ---- 5) 前景失焦剪影：制造"三层空间"最有效的一刀（第 1 项）----
    fg = pygame.Surface((w, h), pygame.SRCALPHA)
    col = tuple(P["fg"]) + (P["fg_a"],)
    # 前景必须**锚在画面边缘**、且只在底部与两角。
    # 踩过的坑：第一版在两侧画了悬空的窄竖椭圆，模糊之后看起来就是两块
    # "脏抹布"抹在山和草地上 —— 没有形状、也不贴边，读不出"近景物体"，
    # 只读得出"画面脏了"。近景的要义是**大、暗、失焦、且被裁切在画外**。
    for cx_f, rad_f, top_f in ((-0.02, 0.20, 0.86), (1.02, 0.22, 0.84),
                               (0.34, 0.19, 0.95), (0.68, 0.17, 0.97)):
        rad = rad_f * w
        cy = h + rad * 0.55 - (1.0 - top_f) * h * 0.0
        pygame.draw.ellipse(fg, col, pygame.Rect(int(cx_f * w - rad), int(cy - rad * 0.85),
                                                 int(rad * 2), int(rad * 2)))
    fg = U.blur_smooth(fg, passes=2, factor=8)

    # ---- 6) 暗角：把注意力收回画面中心 ----
    vig = U.vignette(w, h, P["vig"], 1.5)

    out = {"tint": tint, "light": light, "fog": fog, "ao": ao, "fg": fg, "vig": vig}
    total = sum(v.get_width() * v.get_height() for v in out.values())
    if _OVERLAY_PX + total > _OVERLAY_MAX_PX:
        _OVERLAY_CACHE.clear()
        _OVERLAY_PX = 0
    _OVERLAY_CACHE[key] = out
    _OVERLAY_PX += total
    return out


def depth_pass(surf: pygame.Surface, accent: Color, preset: str = "meadow",
               ground_y: Optional[int] = None) -> pygame.Surface:
    """
    给一张已画好的主题背景叠上六层深度合成（原地修改并返回）。

    运行时代价：6 次全屏 blit（叠加图全部烘焙缓存），实测 < 2ms。
    游戏切换时调用一次即可。
    """
    w, h = surf.get_size()
    g = int(ground_y) if ground_y else int(h * 0.72)
    _grade(surf, preset)
    ov = _world_overlays(w, h, preset, g, accent)
    surf.blit(ov["tint"], (0, 0))
    surf.blit(ov["light"], (0, 0), special_flags=pygame.BLEND_RGB_ADD)
    surf.blit(ov["fog"], (0, 0))
    surf.blit(ov["ao"], (0, 0))
    surf.blit(ov["fg"], (0, 0))
    surf.blit(ov["vig"], (0, 0))
    return surf


def world_names() -> List[str]:
    return sorted(_WORLD_PRESETS)
