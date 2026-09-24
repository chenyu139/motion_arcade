"""
core/icons.py
=============
大厅卡片用的矢量图标（20 款，与游戏一一对应）。

全部程序化绘制 + 超采样烘焙，不依赖任何图片素材。
调用 draw_icon(surf, name, cx, cy, size, color) 即可；同名同尺寸同颜色只会烘焙一次。
"""
from __future__ import annotations

import math
from typing import Sequence, Tuple

import pygame

from . import theme as U

Color = Sequence[int]


# --------------------------------------------------------------------------- #
def draw_icon(surf: pygame.Surface, name: str, cx: float, cy: float,
              size: float, color: Color, accent: Color = (255, 255, 255)) -> None:
    s = _icon(name, int(size), tuple(color[:3]), tuple(accent[:3]))
    surf.blit(s, (int(cx - s.get_width() / 2), int(cy - s.get_height() / 2)))


_ICON_CACHE = {}


def _icon(name: str, size: int, c: Tuple[int, ...], a: Tuple[int, ...]) -> pygame.Surface:
    ck = (name, size, c, a)
    s = _ICON_CACHE.get(ck)
    if s is not None:
        return s
    s = U.bake(("icon", name, size, c, a), (size, size), _make(name, c, a), ss=4)
    if len(_ICON_CACHE) > 260:
        _ICON_CACHE.clear()
    _ICON_CACHE[ck] = s
    return s


def _make(name, c, a):
    """返回绘制函数（在 ss 倍尺寸的画布上作画）。"""
    def draw(s):
        S = s.get_width()
        u = S / 100.0          # 归一化单位：100 = 图标边长
        m = S / 2.0
        W = a                  # 高光色

        def L(p0, p1, col, w):
            pygame.draw.line(s, col, (p0[0] * u, p0[1] * u), (p1[0] * u, p1[1] * u),
                             max(1, int(w * u)))
        def C(x, y, r, col, wd=0):
            pygame.draw.circle(s, col, (int(x * u), int(y * u)), int(r * u),
                               int(wd * u) if wd else 0)
        def E(x, y, rx, ry, col, wd=0):
            pygame.draw.ellipse(s, col, pygame.Rect(int((x - rx) * u), int((y - ry) * u),
                                                    int(rx * 2 * u), int(ry * 2 * u)),
                                int(wd * u) if wd else 0)
        def P(pts, col, wd=0):
            pygame.draw.polygon(s, col, [(int(x * u), int(y * u)) for x, y in pts],
                                int(wd * u) if wd else 0)
        def rect(x, y, w, h, col, wd=0, r=0):
            pygame.draw.rect(s, col, pygame.Rect(int(x * u), int(y * u),
                                                 int(w * u), int(h * u)),
                             int(wd * u) if wd else 0, border_radius=int(r * u))

        if name == "mushroom":
            E(50, 66, 40, 26, c)
            E(36, 56, 13, 9, W)
            rect(40, 58, 20, 34, W, 0, 6)
            C(34, 44, 8, W)
            C(58, 40, 9, W)
            P([(50, 26), (78, 24), (92, 40), (18, 40)], c)
            E(50, 30, 34, 18, c)
        elif name == "football":
            C(50, 50, 40, c)
            P([(50, 32), (66, 44), (60, 62), (40, 62), (34, 44)], W)
            for ang, r0, r1 in ((0, 62, 76), (72, 62, 76), (144, 62, 76),
                                (216, 62, 76), (288, 62, 76)):
                rad = math.radians(ang)
                L((50 + math.cos(rad) * 40, 50 + math.sin(rad) * 40),
                  (50 + math.cos(rad) * 52, 50 + math.sin(rad) * 52), W, 5)
        elif name == "racket":
            # 拍框
            E(42, 34, 27, 33, c)
            E(42, 34, 18, 24, (232, 244, 252))
            for k in range(5):
                L((26 + k * 8, 6), (26 + k * 8, 60), (140, 205, 238), 2)
            for k in range(7):
                L((18, 10 + k * 8), (66, 10 + k * 8), (140, 205, 238), 2)
            E(42, 34, 27, 33, c, 6)
            # 手柄
            L((50, 60), (74, 94), c, 12)
            C(74, 94, 7, U.shade(c, 0.72))
            # 球
            C(82, 72, 14, (216, 236, 78))
            pygame.draw.arc(s, (250, 252, 236),
                            pygame.Rect(int(68 * u), int(60 * u), int(28 * u), int(24 * u)),
                            math.pi * 0.15, math.pi * 0.85, max(1, int(3 * u)))
            pygame.draw.arc(s, (250, 252, 236),
                            pygame.Rect(int(68 * u), int(60 * u), int(28 * u), int(24 * u)),
                            math.pi * 1.15, math.pi * 1.85, max(1, int(3 * u)))
        elif name == "panda":
            C(50, 54, 32, c)
            C(26, 28, 14, (28, 30, 38))
            C(74, 28, 14, (28, 30, 38))
            E(34, 50, 11, 13, (28, 30, 38))
            E(66, 50, 11, 13, (28, 30, 38))
            C(36, 50, 5, W)
            C(64, 50, 5, W)
            C(50, 70, 6, (28, 30, 38))
            C(50, 54, 32, (28, 30, 38), 3)
        elif name == "hotpot":
            # 锅体（上宽下窄的梯形）
            P([(14, 44), (86, 44), (74, 86), (26, 86)], c)
            # 锅沿
            E(50, 44, 37, 11, U.shade(c, 1.16))
            # 红油汤面
            E(50, 44, 30, 8, (206, 62, 40))
            for k in range(4):
                C(34 + k * 11, 44, 3.4, (255, 190, 120))
            # 蒸汽
            for k in range(3):
                pygame.draw.arc(s, W,
                                pygame.Rect(int((34 + k * 13) * u), int(12 * u),
                                            int(12 * u), int(26 * u)),
                                math.pi * 1.1, math.pi * 1.9, max(2, int(3.4 * u)))
            # 筷子
            L((58, 36), (94, 8), (196, 150, 96), 5)
            L((66, 38), (98, 16), (196, 150, 96), 5)
            # 锅耳
            L((12, 46), (2, 46), c, 7)
            L((88, 46), (98, 46), c, 7)
        elif name == "mask":
            P([(50, 12), (86, 34), (78, 80), (50, 92), (22, 80), (14, 34)], c)
            P([(38, 44), (54, 40), (46, 56)], (255, 255, 255))
            P([(62, 44), (46, 40), (54, 56)], (255, 255, 255))
            L((34, 70), (66, 70), W, 4)
            L((28, 24), (50, 14), W, 3)
            L((72, 24), (50, 14), W, 3)
        elif name == "ski":
            # 雪板
            P([(6, 78), (84, 58), (90, 68), (12, 88)], c)
            P([(8, 77), (83, 58), (85, 62), (10, 82)], (240, 246, 252))
            # 身体前倾
            C(44, 28, 12, c)
            L((44, 40), (54, 64), c, 12)
            L((46, 46), (24, 34), c, 7)
            L((48, 52), (76, 42), c, 7)
            L((48, 62), (32, 78), (38, 32, 42), 7)
            L((54, 64), (72, 76), (38, 32, 42), 7)
            # 雪杖
            L((78, 36), (92, 84), (206, 212, 224), 4)
            L((78, 36), (66, 30), (206, 212, 224), 4)
        elif name == "climb":
            P([(10, 88), (52, 16), (92, 88)], c)
            P([(50, 22), (74, 60), (36, 60)], (240, 248, 252))
            C(34, 44, 7, W)
            C(62, 62, 7, W)
            C(48, 74, 7, W)
            C(70, 34, 5, W)
        elif name == "lantern":
            L((50, 8), (50, 24), c, 4)
            rect(36, 16, 28, 8, c, 0, 3)
            E(50, 50, 30, 28, c)
            E(50, 50, 18, 18, W)
            for k in range(1, 4):
                L((20 + k * 15, 24), (20 + k * 15, 76), (0, 0, 0, 70), 2)
            rect(40, 74, 20, 7, c, 0, 3)
            L((50, 81), (50, 94), (220, 70, 70), 4)
        elif name == "bird":
            E(50, 54, 16, 26, c)
            C(50, 24, 13, c)
            P([(24, 40), (2, 20), (10, 52)], c)
            P([(76, 40), (98, 20), (90, 52)], c)
            C(45, 22, 3, (30, 26, 22))
            C(55, 22, 3, (30, 26, 22))
            P([(44, 32), (50, 40), (56, 32)], (240, 190, 80))
            L((26, 78), (20, 94), c, 5)
            L((74, 78), (80, 94), c, 5)
        elif name == "drum":
            E(50, 34, 34, 13, W)
            rect(16, 34, 68, 34, c)
            E(50, 68, 34, 13, U.shade(c, 0.7))
            E(50, 34, 34, 13, c, 5)
            for k in range(4):
                L((24 + k * 18, 42), (24 + k * 18, 62), U.shade(c, 0.6), 3)
            L((68, 14), (40, 36), (196, 150, 96), 4)
            C(72, 12, 7, (196, 150, 96))
        elif name == "fish":
            E(46, 50, 34, 22, c)
            P([(12, 50), (-10 + 24, 24), (2, 50), (-10 + 24, 76)], c)
            P([(50, 30), (58, 8), (68, 32)], U.shade(c, 0.8))
            C(66, 44, 5, W)
            C(68, 44, 2.6, (20, 20, 26))
            L((40, 42), (60, 42), U.shade(c, 0.7), 3)
            L((40, 58), (60, 58), U.shade(c, 0.7), 3)
        elif name == "hand":
            E(50, 62, 24, 28, c)
            for k in range(4):
                rect(30 + k * 11, 16 + abs(k - 1.5) * 6, 9, 40, c, 0, 4)
            rect(16, 46, 10, 26, c, 0, 4)
            E(50, 64, 14, 16, U.shade(c, 1.2))
        elif name == "balloon":
            E(50, 40, 28, 32, c)
            P([(46, 70), (54, 70), (50, 80)], U.shade(c, 0.7))
            for k in range(5):
                L((48 + (2 if k % 2 else -2), 80 + k * 4),
                  (50 + (-2 if k % 2 else 2), 84 + k * 4), U.shade(c, 0.8), 2)
            E(38, 28, 8, 11, W)
        elif name == "fruit":
            C(50, 58, 30, c)
            E(50, 28, 14, 9, (110, 178, 96))
            L((50, 34), (50, 46), (110, 90, 60), 5)
            C(36, 46, 8, U.shade(c, 1.3))
        elif name == "bow":
            pygame.draw.arc(s, c, pygame.Rect(int(20 * u), int(8 * u), int(64 * u), int(84 * u)),
                            -math.pi / 2, math.pi / 2, max(2, int(9 * u)))
            L((20, 50), (92, 50), W, 3)
            L((92, 50), (78, 44), W, 4)
            L((92, 50), (78, 56), W, 4)
            L((22, 20), (22, 80), (196, 150, 96), 2)
        elif name == "hoop":
            E(50, 24, 30, 12, (238, 122, 48))
            E(50, 24, 30, 12, (160, 66, 24), 5)
            for k in range(7):
                L((24 + k * 9, 30), (34 + k * 5, 62), (240, 246, 252), 2)
            for k in range(3):
                pygame.draw.arc(s, (240, 246, 252),
                                pygame.Rect(int((28 - k * 5) * u), int((42 + k * 9) * u),
                                            int((44 + k * 10) * u), int(14 * u)),
                                0, math.pi, max(1, int(2.4 * u)))
            C(50, 82, 17, c)
            pygame.draw.arc(s, (30, 24, 20), pygame.Rect(int(33 * u), int(65 * u),
                                                          int(34 * u), int(34 * u)),
                            0, math.pi, max(1, int(2.6 * u)))
        elif name == "puzzle":
            P([(14, 14), (44, 14), (44, 26), (56, 26), (56, 44), (44, 44), (44, 56),
               (14, 56)], c)
            P([(60, 56), (90, 56), (90, 86), (78, 86), (78, 98), (60, 98), (60, 86),
               (48, 86), (48, 68), (60, 68)], U.shade(c, 0.76))
        elif name == "taichi":
            C(50, 50, 40, (248, 248, 252))
            pygame.draw.arc(s, c, pygame.Rect(int(10 * u), int(10 * u), int(80 * u), int(80 * u)),
                            math.pi / 2, math.pi * 1.5, int(40 * u))
            C(50, 30, 20, c)
            C(50, 70, 20, (248, 248, 252))
            C(50, 30, 7, (248, 248, 252))
            C(50, 70, 7, c)
            C(50, 50, 40, U.shade(c, 0.7), 4)
        elif name == "glove":
            E(46, 58, 24, 26, c)
            for k in range(4):
                rect(26 + k * 11, 14 + abs(k - 1.5) * 7, 10, 42, c, 0, 5)
            rect(62, 44, 22, 13, c, 0, 6)
            E(46, 76, 20, 14, U.shade(c, 0.82))
            E(50, 80, 13, 9, U.shade(c, 1.14))
        else:
            C(50, 50, 34, c)
    return draw
