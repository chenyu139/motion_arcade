"""
core/sichuan.py
===============
四川文旅元素库：把地标做成可复用的**程序化剪影**，供各游戏当背景层用。

为什么用剪影而不是照片
----------------------
· 分辨率无关：同一份代码能从 480p 画到 4K，不会糊；
· 风格统一：所有游戏的天际线是一套视觉语言，不会像贴图拼盘；
· 无版权风险：没有一张素材来自网络；
· 零体积：比塞几十张 PNG 强得多。

每个地标都提炼了最有辨识度的一两笔 —— 剪影画得准，靠的就是这个：

    都江堰   鱼嘴分水堤（前窄后宽的锐角）+ 索桥弧线 + 内外江水纹
    青城山   三层递进峰峦 + 山顶道观小亭（"青城天下幽"的层叠感）
    乐山大佛 山体里凿出的坐佛：螺髻头、宽肩、双手扶膝
    峨眉金顶 陡峭主峰 + 顶上一座金色重檐殿
    九寨沟   层叠彩林带 + 钙化滩的水面横纹
    宽窄巷子 川西民居：硬山坡屋顶 + 穿斗结构 + 天井院墙
    锦里     牌坊（三间四柱）+ 檐下成串灯笼
    蜀南竹海 密集竹秆 + 竹叶簇
    三星堆   青铜面具轮廓 + 通天神树
    稻城亚丁 三座品字形雪山（仙乃日、央迈勇、夏诺多吉）
"""
from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Sequence, Tuple

import pygame

from . import theme as U

Color = Sequence[int]
Point = Tuple[float, float]


# =========================================================================== #
# 各地标（都在 (0,0)-(w,h) 的局部坐标系里作画，基线在 y=h）
# =========================================================================== #
def _dujiangyan(s, w, h, c):
    """都江堰：鱼嘴分水堤 + 安澜索桥 + 内外江。"""
    base = h
    # 两侧远山
    U.aa_poly(s, [(-w * 0.35, base), (w * 0.16, base - h * 0.55),
                  (w * 0.52, base)], U.shade(c, 0.86), 0, ss=2)
    # 鱼嘴：前窄后宽的锐角堤
    U.aa_poly(s, [(w * 0.46, base - h * 0.10), (w * 0.60, base - h * 0.62),
                  (w * 0.74, base - h * 0.44), (w * 0.86, base - h * 0.02),
                  (w * 0.52, base + h * 0.06)], c, 0, ss=2)
    # 索桥：两道悬链弧
    for k, dy in ((0, 0.0), (1, 0.10)):
        pts = []
        for i in range(17):
            t = i / 16.0
            x = w * (0.02 + t * 0.42)
            sag = math.sin(t * math.pi) * h * (0.20 - dy)
            pts.append((x, base - h * (0.50 - dy) + sag))
        pygame.draw.lines(s, U.shade(c, 1.18), False, pts, max(1, int(h * 0.022)))
        # 桥塔
    for tx in (0.03, 0.43):
        U.aa_poly(s, [(w * tx - w * 0.012, base), (w * tx + w * 0.012, base),
                      (w * (tx + 0.004), base - h * 0.78), (w * (tx - 0.004), base - h * 0.78)],
                  U.shade(c, 1.10), 0, ss=2)
    # 内外江水纹
    for i in range(5):
        y = base - h * (0.06 + i * 0.055)
        U.aa_line(s, (w * 0.02, y), (w * 0.40, y), U.shade(c, 1.24, ), max(1, int(h * 0.016)))


def _qingcheng(s, w, h, c):
    """青城山：三层递进的峰峦 + 山顶道观。"""
    base = h
    layers = [(0.98, 0.62, 0.30), (0.80, 0.86, 0.52), (0.62, 1.00, 0.74)]
    for shade_k, peak_k, xk in layers:
        for j, (dx, peak) in enumerate(((-0.22, 0.72), (0.0, 1.0), (0.24, 0.80))):
            px = w * (xk + dx)
            pk = h * peak_k * peak
            U.aa_poly(s, [(px - w * 0.30, base), (px, base - pk), (px + w * 0.30, base)],
                      U.shade(c, shade_k), 0, ss=2)
    # 山顶小亭（重檐）
    tx, ty = w * 0.62, base - h * 0.74
    U.aa_poly(s, [(tx - w * 0.055, ty), (tx + w * 0.055, ty),
                  (tx + w * 0.032, ty - h * 0.10), (tx - w * 0.032, ty - h * 0.10)],
              U.shade(c, 1.30), 0, ss=2)
    U.aa_poly(s, [(tx - w * 0.075, ty - h * 0.09), (tx + w * 0.075, ty - h * 0.09),
                  (tx + w * 0.050, ty - h * 0.19), (tx - w * 0.050, ty - h * 0.19)],
              U.shade(c, 1.42), 0, ss=2)


def _leshan(s, w, h, c):
    """乐山大佛：山体里凿出的坐佛轮廓。"""
    base = h
    # 山体
    U.aa_poly(s, [(-w * 0.25, base), (w * 0.10, base - h * 0.60),
                  (w * 0.42, base - h * 0.92), (w * 0.90, base - h * 0.66),
                  (w * 1.22, base)], c, 0, ss=2)
    # 佛身（比山体亮，形成"凿出来"的感觉）
    fx, fy = w * 0.50, base - h * 0.10
    top = fy - h * 0.66
    # 肩
    U.aa_poly(s, [(fx - w * 0.20, fy - h * 0.26), (fx - w * 0.15, top + h * 0.20),
                  (fx + w * 0.15, top + h * 0.20), (fx + w * 0.20, fy - h * 0.26),
                  (fx + w * 0.13, fy), (fx - w * 0.13, fy)],
              U.shade(c, 1.24), 0, ss=2)
    # 头 + 螺髻
    hr = h * 0.13
    U.aa_circle(s, (fx, top + hr * 0.9), hr, U.shade(c, 1.32), 0, ss=2)
    for i in range(5):
        ang = math.pi * (0.15 + i * 0.175)
        U.aa_circle(s, (fx + math.cos(ang) * hr * 0.86, top + hr * 0.9 - math.sin(ang) * hr * 0.86),
                    hr * 0.17, U.shade(c, 1.44), 0, ss=2)
    # 双手扶膝
    for sgn in (-1, 1):
        U.aa_ellipse(s, (int(fx + sgn * w * 0.12 - w * 0.045), int(fy - h * 0.14),
                         int(w * 0.09), int(h * 0.09)), U.shade(c, 1.18), 0, ss=2)


def _emei(s, w, h, c):
    """峨眉金顶：陡峰 + 金色重檐殿。"""
    base = h
    U.aa_poly(s, [(-w * 0.20, base), (w * 0.36, base - h * 0.86),
                  (w * 0.62, base - h * 0.62), (w * 0.86, base - h * 0.78),
                  (w * 1.20, base)], c, 0, ss=2)
    # 金顶
    tx, ty = w * 0.42, base - h * 0.86
    gold = (236, 196, 96)
    for k, (dw, dy) in enumerate(((0.11, 0.0), (0.085, -0.09), (0.055, -0.175))):
        U.aa_poly(s, [(tx - w * dw, ty + h * dy), (tx + w * dw, ty + h * dy),
                      (tx + w * (dw - 0.02), ty + h * (dy - 0.07)),
                      (tx - w * (dw - 0.02), ty + h * (dy - 0.07))], gold, 0, ss=2)
    U.aa_line(s, (tx, ty - h * 0.30), (tx, ty - h * 0.42), gold, max(1, int(h * 0.018)))
    # 云海
    for i in range(7):
        x = w * (0.05 + i * 0.13)
        U.aa_ellipse(s, (int(x - w * 0.11), int(base - h * 0.20), int(w * 0.22), int(h * 0.07)),
                     U.shade(c, 1.30), 0, ss=2)


def _jiuzhai(s, w, h, c):
    """九寨沟：层叠彩林（扇形树冠）+ 钙化滩水面。"""
    base = h
    layers = ((0.84, 0.84), (0.60, 0.98), (0.40, 1.12))
    for k, (yk, sk) in enumerate(layers):
        rng = random.Random(100 + k)
        x = -0.05
        while x < 1.05:
            tw = rng.uniform(0.045, 0.090)
            th = h * yk * rng.uniform(0.60, 1.0)
            col = U.shade(c, sk * rng.uniform(0.9, 1.12))
            cx = w * (x + tw / 2)
            top = base - h * 0.10 - th
            # 树冠：三层扇形而不是尖三角，才像阔叶彩林
            for j, (frac, spread) in enumerate(((1.0, 1.0), (0.72, 0.80), (0.44, 0.58))):
                cy = top + th * (1 - frac) * 0.55
                U.aa_ellipse(s, (int(cx - w * tw * spread * 0.62),
                                 int(cy - th * 0.30 * frac),
                                 int(w * tw * spread * 1.24),
                                 int(th * 0.62 * frac)),
                             U.shade(col, 1.0 + j * 0.06), 0, ss=2)
            # 树干
            U.aa_line(s, (cx, base - h * 0.10), (cx, top + th * 0.30),
                      U.shade(col, 0.78), max(1, int(w * tw * 0.12)))
            x += tw * rng.uniform(1.00, 1.35)
    # 水面 + 钙化滩横纹
    U.aa_poly(s, [(0, base - h * 0.10), (w, base - h * 0.10), (w, base), (0, base)],
              U.shade(c, 0.72), 0, ss=2)
    for i in range(6):
        y = base - h * (0.02 + i * 0.016)
        U.aa_line(s, (0, y), (w, y), U.shade(c, 1.22), max(1, int(h * 0.010)))


def _xiangzi(s, w, h, c):
    """宽窄巷子：川西民居 —— 硬山坡屋顶 + 穿斗结构 + 院墙。"""
    base = h
    rng = random.Random(7)
    x = -0.03
    while x < 1.06:
        bw = rng.uniform(0.16, 0.26)
        bh = h * rng.uniform(0.44, 0.66)
        # 墙体
        U.aa_poly(s, [(w * x, base), (w * (x + bw), base),
                      (w * (x + bw), base - bh), (w * x, base - bh)], c, 0, ss=2)
        # 穿斗木构线条
        for i in range(1, 4):
            yy = base - bh * i / 4.0
            U.aa_line(s, (w * x, yy), (w * (x + bw), yy), U.shade(c, 1.22),
                      max(1, int(h * 0.012)))
        # 硬山坡屋顶（两坡 + 出檐）
        U.aa_poly(s, [(w * (x - 0.035), base - bh), (w * (x + bw / 2), base - bh - h * 0.20),
                      (w * (x + bw + 0.035), base - bh)], U.shade(c, 1.34), 0, ss=2)
        # 天井院墙（矮一截）
        if rng.random() < 0.6:
            U.aa_poly(s, [(w * (x + bw), base), (w * (x + bw + 0.05), base),
                          (w * (x + bw + 0.05), base - h * 0.22), (w * (x + bw), base - h * 0.22)],
                      U.shade(c, 0.9), 0, ss=2)
        # 窗
        if rng.random() < 0.7:
            wx = w * (x + bw * rng.uniform(0.25, 0.6))
            U.aa_poly(s, [(wx, base - bh * 0.62), (wx + w * 0.045, base - bh * 0.62),
                          (wx + w * 0.045, base - bh * 0.40), (wx, base - bh * 0.40)],
                      U.shade(c, 1.45), 0, ss=2)
        x += bw + rng.uniform(0.005, 0.035)


def _jinli(s, w, h, c):
    """锦里：三间四柱牌坊 + 檐下成串灯笼。"""
    base = h
    # 立柱
    for k, xk in enumerate((0.18, 0.42, 0.66, 0.90)):
        U.aa_poly(s, [(w * xk - w * 0.014, base), (w * xk + w * 0.014, base),
                      (w * xk + w * 0.010, base - h * 0.66), (w * xk - w * 0.010, base - h * 0.66)],
                  c, 0, ss=2)
    # 三重檐（中间最高）
    for cx, cw, cy in ((0.54, 0.46, 0.66), (0.30, 0.20, 0.54), (0.78, 0.20, 0.54)):
        U.aa_poly(s, [(w * (cx - cw / 2), base - h * cy),
                      (w * cx, base - h * (cy + 0.20)),
                      (w * (cx + cw / 2), base - h * cy),
                      (w * (cx + cw / 2 - 0.02), base - h * (cy - 0.05)),
                      (w * (cx - cw / 2 + 0.02), base - h * (cy - 0.05))],
                  U.shade(c, 1.30), 0, ss=2)
    # 匾额
    U.aa_poly(s, [(w * 0.44, base - h * 0.50), (w * 0.64, base - h * 0.50),
                  (w * 0.64, base - h * 0.42), (w * 0.44, base - h * 0.42)],
              U.shade(c, 1.48), 0, ss=2)
    # 成串灯笼（小一点、稀一点，别把牌坊盖住）
    rng = random.Random(11)
    for i in range(5):
        x = w * (0.12 + i * 0.19)
        for k in range(2):
            y = base - h * (0.64 - k * 0.13)
            r = h * 0.030
            U.aa_ellipse(s, (int(x - r), int(y - r * 1.15), int(r * 2), int(r * 2.3)),
                         (208, 74, 66), 0, ss=2)
            U.aa_line(s, (x, y - h * 0.075), (x, y - h * 0.095), U.shade(c, 1.3),
                      max(1, int(h * 0.008)))
            U.aa_line(s, (x, y + r * 2.3), (x, y + h * 0.035), (216, 176, 96),
                      max(1, int(h * 0.008)))


def _bamboo(s, w, h, c):
    """蜀南竹海：密集竹秆 + 竹叶簇。"""
    base = h
    rng = random.Random(23)
    for i in range(46):
        x = w * rng.uniform(-0.02, 1.02)
        bh = h * rng.uniform(0.62, 1.02)
        bw = max(1, int(w * rng.uniform(0.005, 0.010)))
        col = U.shade(c, rng.uniform(0.86, 1.16))
        U.aa_poly(s, [(x - bw, base), (x + bw, base), (x + bw * 0.6, base - bh),
                      (x - bw * 0.6, base - bh)], col, 0, ss=2)
        # 竹节
        for k in range(1, int(bh / (h * 0.10)) + 1):
            yy = base - k * h * 0.10
            U.aa_line(s, (x - bw * 1.4, yy), (x + bw * 1.4, yy), U.shade(col, 1.2),
                      max(1, int(h * 0.008)))
        # 叶簇
        for k in range(rng.randint(2, 4)):
            ly = base - bh * rng.uniform(0.55, 1.0)
            for j in range(4):
                ang = rng.uniform(-2.6, -0.5)
                ln = w * rng.uniform(0.02, 0.045)
                U.aa_line(s, (x, ly), (x + math.cos(ang) * ln, ly + math.sin(ang) * ln),
                          U.shade(col, 1.10), max(1, int(h * 0.012)))


def _sanxingdui(s, w, h, c):
    """三星堆：青铜面具 + 通天神树。"""
    base = h
    # 通天神树
    tx = w * 0.26
    U.aa_line(s, (tx, base), (tx, base - h * 0.78), U.shade(c, 1.16), max(2, int(w * 0.010)))
    for k in range(4):
        yy = base - h * (0.24 + k * 0.16)
        for sgn in (-1, 1):
            pts = []
            for i in range(9):
                t = i / 8.0
                pts.append((tx + sgn * w * 0.14 * t,
                            yy - h * 0.10 * math.sin(t * math.pi) + h * 0.05 * t))
            pygame.draw.lines(s, U.shade(c, 1.24), False, pts, max(1, int(w * 0.008)))
        U.aa_circle(s, (tx + w * 0.11, yy - h * 0.06), w * 0.012,
                    U.shade(c, 1.44), 0, ss=2)
        U.aa_circle(s, (tx - w * 0.11, yy - h * 0.06), w * 0.012,
                    U.shade(c, 1.44), 0, ss=2)
    # 面具：三星堆面具是**宽大于高**的扁方形，不是椭圆
    mx, my = w * 0.68, base - h * 0.34
    mw, mh = w * 0.24, h * 0.19
    U.aa_poly(s, [(mx - mw, my - mh * 0.7), (mx - mw * 0.72, my - mh),
                  (mx + mw * 0.72, my - mh), (mx + mw, my - mh * 0.7),
                  (mx + mw * 0.86, my + mh * 0.5), (mx + mw * 0.40, my + mh),
                  (mx - mw * 0.40, my + mh), (mx - mw * 0.86, my + mh * 0.5)],
              c, 0, ss=2)
    # 纵目：向前凸出的柱状眼，三星堆最具标志性的一笔
    for sgn in (-1, 1):
        U.aa_poly(s, [(mx + sgn * mw * 0.30, my - mh * 0.34),
                      (mx + sgn * mw * 0.34, my - mh * 0.06),
                      (mx + sgn * mw * 1.12, my - mh * 0.02),
                      (mx + sgn * mw * 1.14, my - mh * 0.30)],
                  U.shade(c, 1.26), 0, ss=2)
        U.aa_circle(s, (mx + sgn * mw * 1.16, my - mh * 0.16), w * 0.026,
                    U.shade(c, 1.50), 0, ss=2)
    # 云雷纹额饰
    U.aa_poly(s, [(mx - mw * 0.62, my - mh * 0.86), (mx, my - mh * 1.44),
                  (mx + mw * 0.62, my - mh * 0.86)], U.shade(c, 1.36), 0, ss=2)
    # 大耳
    for sgn in (-1, 1):
        U.aa_poly(s, [(mx + sgn * mw * 0.94, my - mh * 0.56),
                      (mx + sgn * mw * 1.34, my - mh * 0.44),
                      (mx + sgn * mw * 1.30, my + mh * 0.62),
                      (mx + sgn * mw * 0.92, my + mh * 0.50)],
                  U.shade(c, 1.14), 0, ss=2)
    # 阔嘴
    U.aa_line(s, (mx - mw * 0.44, my + mh * 0.82), (mx + mw * 0.44, my + mh * 0.82),
              U.shade(c, 0.7), max(1, int(h * 0.012)))


def _yading(s, w, h, c):
    """稻城亚丁：三座品字形雪山。"""
    base = h
    for (xk, pk) in ((0.24, 0.62), (0.50, 0.86), (0.76, 0.68)):
        px = w * xk
        top = base - h * pk
        U.aa_poly(s, [(px - w * 0.24, base), (px, top), (px + w * 0.24, base)], c, 0, ss=2)
        # 雪线
        U.aa_poly(s, [(px - w * 0.10, base - h * pk * 0.58), (px, top),
                      (px + w * 0.10, base - h * pk * 0.58),
                      (px + w * 0.045, base - h * pk * 0.66),
                      (px - w * 0.045, base - h * pk * 0.66)],
                  U.shade(c, 1.46), 0, ss=2)


LANDMARKS: Dict[str, callable] = {
    "dujiangyan": _dujiangyan,
    "qingcheng": _qingcheng,
    "leshan": _leshan,
    "emei": _emei,
    "jiuzhai": _jiuzhai,
    "xiangzi": _xiangzi,
    "jinli": _jinli,
    "bamboo": _bamboo,
    "sanxingdui": _sanxingdui,
    "yading": _yading,
}

LANDMARK_NAMES = {
    "dujiangyan": "都江堰", "qingcheng": "青城山", "leshan": "乐山大佛",
    "emei": "峨眉金顶", "jiuzhai": "九寨沟", "xiangzi": "宽窄巷子",
    "jinli": "锦里", "bamboo": "蜀南竹海", "sanxingdui": "三星堆",
    "yading": "稻城亚丁",
}

# 预设组合：不同主题的游戏用不同的地标群
PRESETS = {
    "city": ("xiangzi", "jinli", "emei", "qingcheng"),
    "nature": ("jiuzhai", "yading", "emei", "bamboo"),
    "culture": ("sanxingdui", "dujiangyan", "leshan", "jinli"),
    "mountain": ("emei", "qingcheng", "yading", "leshan"),
    "panda": ("bamboo", "jiuzhai", "qingcheng", "sanxingdui"),
}


# =========================================================================== #
def skyline(w: int, h: int, preset: str = "city", seed: int = 5,
            base: Color = (26, 30, 52), haze: float = 0.0,
            count: int = 4, top: float = 1.0) -> pygame.Surface:
    """
    生成一条地标天际线剪影（透明底）。

    preset  用哪组地标（见 PRESETS）
    base    剪影颜色；越远越淡由 haze 控制
    haze    0=全黑剪影，1=完全融进背景
    top     剪影高度上限（占 h 的比例）
    """
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    picks = PRESETS.get(preset, PRESETS["city"])
    rng = random.Random(seed)
    n = max(1, min(count, len(picks)))
    order = list(picks)
    rng.shuffle(order)
    slot = w / n
    for i in range(n):
        name = order[i % len(order)]
        fn = LANDMARKS.get(name)
        if fn is None:
            continue
        # 远处的地标更淡、更小
        depth = i / max(1, n - 1) if n > 1 else 0.5
        k = 0.72 + 0.28 * depth
        col = U.shade(base, 1.0 + 0.55 * (1 - depth) * 0.0)
        col = U.mix(base, (255, 255, 255), haze * (0.22 + 0.30 * (1 - depth)))
        lw = int(slot * rng.uniform(1.05, 1.34))
        lh = int(h * top * k * rng.uniform(0.92, 1.08))
        x0 = int(i * slot - (lw - slot) * 0.5 + rng.uniform(-slot * 0.08, slot * 0.08))
        sub = pygame.Surface((max(8, lw), max(8, lh)), pygame.SRCALPHA)
        try:
            fn(sub, sub.get_width(), sub.get_height(), col)
        except Exception:                                            # noqa: BLE001
            continue
        s.blit(sub, (x0, h - lh))
    return s


def blend_haze(w: int, h: int, color: Color, strength: float = 0.55,
               top: float = 0.0) -> pygame.Surface:
    """给天际线加一层从下往上的雾，让它"退"进背景而不是贴上去。"""
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    for y in range(h):
        t = y / max(1, h - 1)
        a = int(255 * strength * (1.0 - t) ** 1.5)
        if a > 0:
            s.fill((color[0], color[1], color[2], a), (0, y, w, 1))
    return s


def named(preset: str) -> str:
    """把组合里的地标名连成一句，方便标注在画面上。"""
    return " · ".join(LANDMARK_NAMES.get(k, k) for k in PRESETS.get(preset, ()))
