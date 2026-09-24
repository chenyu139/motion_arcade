"""
生成素材精灵层。

素材来自 `assets/sprites/*.png`（AI 生成 + `tools/matte.py` 抠底），
统一画风：cel-shading + 粗描边，和 `core/art.py` 的程序化矢量是同一套语言。

这一层只做三件事：加载、按需缩放并缓存、按锚点贴图。

设计原则
--------
**缺图不崩**。`get()` 返回 `None`，调用方据此回退到原来的矢量绘制。
这样仓库里不带素材也能跑，素材是"增强"而不是"依赖"；同时素材换版本、
重新生成、临时删掉都不影响可用性。

用法
----
    from core import sprites as SP

    SP.draw(surf, "panda_curl", x, cy, height=260, rot=self.roll)
    if SP.draw(...):          # 返回 False 表示没有这张图，调用方自己兜底
        ...
    else:
        ...矢量画法...
"""
from __future__ import annotations

import math
import os
from typing import Dict, Optional, Tuple

import pygame

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "assets", "sprites")

# 缓存： (名称, 宽, 高, 旋转取整) → Surface
_cache: Dict[Tuple, pygame.Surface] = {}
_loaded: Dict[str, Optional[pygame.Surface]] = {}
_missing: set = set()


# --------------------------------------------------------------------------- #
def _load_raw(name: str) -> Optional[pygame.Surface]:
    """从磁盘载入原图（带缓存）。不做缩放，保持原始分辨率备用。"""
    if name in _loaded:
        return _loaded[name]
    path = os.path.join(DIR, f"{name}.png")
    try:
        if not os.path.exists(path):
            _loaded[name] = None
            _missing.add(name)
            return None
        img = pygame.image.load(path).convert_alpha()
        _loaded[name] = img
        return img
    except Exception as e:                                       # noqa: BLE001
        print(f"[sprites] 载入 {name} 失败：{e}")
        _loaded[name] = None
        return None


def available(name: str) -> bool:
    return _load_raw(name) is not None


def missing() -> Tuple[str, ...]:
    """当前缺失的素材名（供诊断打印）。"""
    return tuple(sorted(_missing))


def native_size(name: str) -> Optional[Tuple[int, int]]:
    raw = _load_raw(name)
    return raw.get_size() if raw else None


def get(name: str, height: Optional[float] = None,
        width: Optional[float] = None) -> Optional[pygame.Surface]:
    """
    取一张缩放好的精灵（保持长宽比，只按比例缩到指定的一边）。

    pygame 的 smoothscale 在高分辨率下不便宜，所以结果按尺寸缓存 ——
    但尺寸在游戏里是连续变化的，必须**量化**，否则缓存会爆炸
    （这个坑在 art.py 的抗锯齿图元上已经踩过一次）。
    """
    raw = _load_raw(name)
    if raw is None:
        return None
    nw, nh = raw.get_size()
    if height:
        h = max(2, int(height) // 2 * 2)                 # 量化到偶数
        w = max(2, int(round(nw * h / nh)))
    elif width:
        w = max(2, int(width) // 2 * 2)
        h = max(2, int(round(nh * w / nw)))
    else:
        w, h = nw, nh

    key = (name, w, h)
    s = _cache.get(key)
    if s is None:
        s = raw if (w, h) == (nw, nh) else pygame.transform.smoothscale(raw, (w, h))
        if len(_cache) > 240:
            _cache.clear()
        _cache[key] = s
    return s


def _rotated(name: str, w: int, h: int, deg: float) -> Optional[pygame.Surface]:
    """旋转并缓存。角度取整到 2°，避免连续角度把缓存冲爆。"""
    q = int(round(deg / 2.0)) * 2 % 360
    key = (name, w, h, q)
    s = _cache.get(key)
    if s is not None:
        return s
    base = get(name, height=h)
    if base is None:
        return None
    s = pygame.transform.rotozoom(base, q, 1.0) if q else base
    if len(_cache) > 240:
        _cache.clear()
    _cache[key] = s
    return s


# --------------------------------------------------------------------------- #
# 只有这几个锚点是"点值"，可以传 (x, y)。
# 注意 pygame 里 bottom / top / left / right / centerx / centery 是**标量**，
# 传元组会直接抛 "invalid rect assignment"，所以统一用 mid* 系列。
_ANCHORS = ("midbottom", "center", "midtop", "topleft", "midleft", "midright",
            "bottomleft", "bottomright")
_ALIAS = {"bottom": "midbottom", "top": "midtop",
          "left": "midleft", "right": "midright"}


def draw(surf: pygame.Surface, name: str, x: float, y: float,
         height: Optional[float] = None, width: Optional[float] = None,
         anchor: str = "bottom", rot: float = 0.0, flip: bool = False,
         alpha: int = 255, tint: Optional[Tuple[int, int, int]] = None,
         shadow: float = 0.0) -> bool:
    """
    贴一张精灵。

    x, y    : 锚点在设计坐标系里的位置
    height  : 目标高度（推荐，人物/道具都按高度对齐）
    anchor  : 'bottom'（底部中心，默认）/ 'center' / 'midtop' / ...
    rot     : 旋转角度（度）
    flip    : 水平镜像
    alpha   : 整体不透明度 0~255
    tint    : 叠加色（用 MULT 混合做暗化/染色），如 (150, 150, 150) 压暗
    shadow  : >0 时在底部画一个椭圆投影

    返回 False 表示素材不存在或参数无效，调用方应自行兜底绘制。
    """
    anchor = _ALIAS.get(anchor, anchor)
    if anchor not in _ANCHORS:
        anchor = "midbottom"

    if rot:
        base = get(name, height=height, width=width)
        if base is None:
            return False
        sp = _rotated(name, base.get_width(), base.get_height(), rot)
    else:
        sp = get(name, height=height, width=width)
    if sp is None:
        return False

    if flip:
        key = ("__flip", name, sp.get_width(), sp.get_height())
        f = _cache.get(key)
        if f is None:
            f = pygame.transform.flip(sp, True, False)
            if len(_cache) > 300:
                _cache.clear()
            _cache[key] = f
        sp = f

    r = sp.get_rect(**{anchor: (int(x), int(y))})

    if shadow > 0:
        sw = r.width * 0.66
        sh = max(3, r.height * 0.075)
        a = int(max(0.0, min(1.0, shadow)) * 96)
        srf = pygame.Surface((int(sw), int(sh)), pygame.SRCALPHA)
        pygame.draw.ellipse(srf, (0, 0, 0, a), srf.get_rect())
        surf.blit(srf, (int(r.centerx - sw / 2), int(r.bottom - sh * 0.55)))

    if tint is not None or alpha < 255:
        tmp = sp.copy()
        if tint is not None:
            tmp.fill(tuple(tint) + (255,), special_flags=pygame.BLEND_RGB_MULT)
        if alpha < 255:
            tmp.fill((255, 255, 255, int(alpha)), special_flags=pygame.BLEND_RGBA_MULT)
        surf.blit(tmp, r)
    else:
        surf.blit(sp, r)
    return True


def tinted(name: str, height: float, color: Tuple[int, int, int]) -> Optional[pygame.Surface]:
    """取一张已染色的独立表面（用在需要反复 blit 同一染色的场合）。"""
    sp = get(name, height=height)
    if sp is None:
        return None
    key = ("__tint", name, sp.get_width(), sp.get_height(), tuple(color))
    c = _cache.get(key)
    if c is None:
        c = sp.copy()
        c.fill(tuple(color) + (255,), special_flags=pygame.BLEND_RGB_MULT)
        _cache[key] = c
    return c


def hued(name: str, height: float, deg: float, sat: float = 1.0,
         val: float = 1.0) -> Optional[pygame.Surface]:
    """
    按色相角旋转一张精灵，用来从同一素材派生多种配色。

    自贡灯会要 6 盏颜色不同的灯，但素材只有一张。用 `BLEND_RGB_MULT` 染色
    会把它压暗成一片黑（多颜色相乘必然掉亮度），所以这里做真正的色相旋转：
    用标准 RGB 色相旋转矩阵，一次算完、按 (名称, 尺寸, 角度) 缓存。

    deg : 色相旋转角度（正数顺时针）；sat / val : 饱和度与明度增益
    """
    sp = get(name, height=height)
    if sp is None:
        return None
    key = ("__hue", name, sp.get_width(), sp.get_height(),
           round(deg, 1), round(sat, 2), round(val, 2))
    c = _cache.get(key)
    if c is not None:
        return c

    import numpy as np

    a = math.radians(deg)
    cs, sn = math.cos(a), math.sin(a)
    k = 1.0 / 3.0
    s = math.sqrt(1.0 / 3.0)
    m = np.array([
        [cs + (1 - cs) * k, k * (1 - cs) - s * sn, k * (1 - cs) + s * sn],
        [k * (1 - cs) + s * sn, cs + (1 - cs) * k, k * (1 - cs) - s * sn],
        [k * (1 - cs) - s * sn, k * (1 - cs) + s * sn, cs + (1 - cs) * k],
    ], dtype=np.float32)

    rgb = pygame.surfarray.pixels3d(sp).astype(np.float32)      # (w, h, 3)
    out = rgb @ m.T
    if sat != 1.0:
        gray = out.mean(axis=2, keepdims=True)
        out = gray + (out - gray) * sat
    if val != 1.0:
        out = out * val

    # 用 pixels3d 拿到的**视图**写回，这样只改 RGB、alpha 原样保留。
    # 之前用 surface.copy() + surfarray.blit_array 写，会把透明通道一起写成
    # 不透明 —— 结果是每盏灯背后都多出一个黑色矩形。
    res = sp.copy()
    view = pygame.surfarray.pixels3d(res)
    view[...] = np.clip(out, 0, 255).astype(np.uint8)
    del view
    if len(_cache) > 300:
        _cache.clear()
    _cache[key] = res
    return res


def clear() -> None:
    _cache.clear()
