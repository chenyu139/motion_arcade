"""
games/mask.py
=============
川剧变脸 —— 按题目要求挑出正确的脸谱。

头部操作
    · 左右平移 → 移动选择框
    · 抬头     → 确认变脸
玩法
    屏幕上给出一张"目标脸谱"，下方 5 张候选脸谱。选中正确的那张，
    每答对一题限时会缩短。答错扣 1 条命，共 15 题。
"""
from __future__ import annotations

import math
import random
from typing import List

import pygame

from core import art as A
from core import theme as U
from core.base import BaseGame, register
from core.inputs import GameInput

# 脸谱配色与纹样：(名称, 主色, 副色, 纹样)
MASKS = [
    ("红脸", (206, 52, 46), (250, 226, 180), "flame"),
    ("黑脸", (44, 46, 58), (232, 218, 176), "crack"),
    ("白脸", (244, 242, 236), (72, 76, 96), "cloud"),
    ("蓝脸", (46, 96, 196), (238, 236, 220), "wave"),
    ("金脸", (216, 168, 52), (86, 48, 26), "sun"),
    ("绿脸", (52, 150, 96), (244, 240, 210), "leaf"),
    ("紫脸", (128, 74, 176), (248, 226, 196), "star"),
    ("银脸", (196, 202, 214), (56, 60, 78), "moon"),
]

TOTAL_Q = 15


@register
class MaskGame(BaseGame):
    KEY = "mask"
    TITLE = "川剧变脸"
    SUB = "看准了就变"
    CATEGORY = "头部控制"
    ACCENT = (232, 96, 96)
    ICON = "mask"
    HOW = "按提示挑中同一张脸谱，越答越快"
    HINT = "头部左右选脸谱 · 抬头确认 · 答错扣命"
    DIFFICULTY = 2
    ACHIEVEMENT = f"答对 {TOTAL_Q} 题中的 12 题"
    REQUIRES = ("head",)

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.q = 0
        self.correct = 0
        self.lives = 3
        self.score = 0
        self.streak = 0
        self.best_streak = 0
        self.sel = 2
        self.sel_f = 2.0
        self.cool = 0.0
        self.limit = 6.0
        self.left = 6.0
        self.cards: List[tuple] = []
        self.answer = 0
        self.feedback = ""
        self.feed_col = (255, 255, 255)
        self.feed_t = 0.0
        self.reveal = 0.0
        self._bg = self._make_bg()
        self._new_round()

    def _make_bg(self) -> pygame.Surface:
        W, H = self.W, self.H
        s = pygame.Surface((W, H))
        s.blit(U.vgrad3(W, H, (26, 12, 22), (58, 22, 34), (30, 14, 24)), (0, 0))
        # 舞台帷幕
        for i in range(16):
            x = i * (W / 15.0)
            w = W / 15.0
            col = U.shade((128, 30, 44), 0.62 + 0.30 * math.sin(i * 1.7))
            U.aa_poly(s, [(x, 200), (x + w, 220), (x + w * 0.9, 420), (x + w * 0.1, 410)],
                      col, 0, ss=2)
        # 顶部横批
        s.blit(A.shade_panel(W, 120, (72, 22, 30), 0, 1.1, 0.7), (0, 92))
        # 地面光
        s.blit(U.radial(W, H, (255, 216, 160, 70), (0, 0, 0, 0), 0.5, 0.42, 1.2), (0, 0))
        return s

    def _new_round(self):
        pool = list(range(len(MASKS)))
        random.shuffle(pool)
        self.cards = [MASKS[i] for i in pool[:5]]
        self.answer = random.randrange(5)
        self.sel = 2
        self.sel_f = 2.0
        self.limit = max(2.4, 6.0 - self.q * 0.24)
        self.left = self.limit
        self.reveal = 0.0
        self.cool = 0.3

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        self.cool = max(0.0, self.cool - dt)
        if self.feed_t > 0:
            self.feed_t -= dt
        if self.reveal > 0:
            self.reveal = max(0.0, self.reveal - dt * 1.8)

        if self.cool > 0:
            return
        self.left -= dt
        if self.left <= 0:
            self._wrong("超 时")
            return

        # 选择
        if inp.xc < -0.32 and self.sel > 0:
            self.sel -= 1
            self.cool = 0.20
        elif inp.xc > 0.32 and self.sel < 4:
            self.sel += 1
            self.cool = 0.20
        self.sel_f += (self.sel - self.sel_f) * min(1.0, dt * 13.0)

        if inp.action:
            self.cool = 0.45
            if self.sel == self.answer:
                self._right()
            else:
                self._wrong("选 错")

    def _right(self):
        self.correct += 1
        self.streak += 1
        self.best_streak = max(self.best_streak, self.streak)
        bonus = min(80, self.streak * 16)
        add = 100 + bonus
        self.score += add
        self.feedback, self.feed_col, self.feed_t = f"+{add}　漂亮！", (150, 244, 190), 0.9
        self.reveal = 1.0
        cx = self._card_x(self.sel)
        self.particles.emit(cx, 620, 24, color=(255, 226, 140), spread=280,
                            vy=-240, gravity=760, life=0.7, size=5.5)
        self.flash((255, 240, 190), 0.22)
        self._advance()

    def _wrong(self, why: str):
        self.lives -= 1
        self.streak = 0
        self.feedback, self.feed_col, self.feed_t = f"{why}　正确答案已标出", (255, 150, 130), 1.3
        self.reveal = 1.0
        self.shake(12, 0.4)
        self.flash((255, 100, 80), 0.34)
        cx = self._card_x(self.sel)
        self.particles.emit(cx, 620, 20, color=(255, 120, 100), spread=260,
                            vy=-200, gravity=860, life=0.7, size=5)
        if self.lives <= 0:
            self.state = "over"
            self.set_msg("变脸失败", f"答对 {self.correct} 题", 2.0, (255, 170, 150))
            return
        self._advance(delay=0.7)

    def _advance(self, delay: float = 0.35):
        self.q += 1
        if self.q >= TOTAL_Q:
            self.finish(self.correct >= 12)
            self.set_msg("演出结束", f"答对 {self.correct}/{TOTAL_Q}", 2.0, (255, 232, 170))
            return
        self._new_round()
        self.cool = delay

    def _card_x(self, i: int) -> float:
        return self.W / 2 + (i - 2) * 344.0

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        self._draw_stage_title(surf)
        self._draw_target(surf)
        for i, spec in enumerate(self.cards):
            self._draw_card(surf, i, spec)
        self._draw_timer(surf)
        if self.feed_t > 0:
            U.text(surf, self.feedback, (self.W // 2, 900), 42, self.feed_col,
                   center=True, bold=True, glow=14, glow_color=self.feed_col,
                   alpha=int(255 * min(1.0, self.feed_t * 2.2)))
        self.particles.draw(surf)
        self.draw_vignette(surf, 130)
        self.draw_msg(surf)

    def _draw_stage_title(self, surf):
        U.text(surf, "川 剧 变 脸", (self.W // 2, 152), 46, (255, 226, 180),
               center=True, bold=True, glow=14, glow_color=(255, 150, 90))
        U.text(surf, f"第 {min(self.q + 1, TOTAL_Q)} / {TOTAL_Q} 题", (self.W // 2, 202), 26,
               (226, 196, 176), center=True)

    def _mask_sprite(self, spec, size: int, hl: bool = False) -> pygame.Surface:
        name, c1, c2, pat = spec

        def _d(s):
            r = size / 2
            cx = cy = r
            # 脸型
            U_pts = []
            n = 40
            for i in range(n):
                a = i / n * math.tau
                rx = r * (0.80 if math.cos(a) > 0 else 0.80)
                ry = r * 0.96
                x = cx + math.cos(a) * rx
                y = cy + math.sin(a) * ry * (1.0 + 0.10 * max(0, math.sin(a)))
                U_pts.append((int(x), int(y)))
            pygame.draw.polygon(s, tuple(c1), U_pts)
            # 暗部
            pygame.draw.polygon(s, tuple(U.shade(c1, 0.74)),
                                [(int(cx), int(cy - r * 0.9)), (int(cx + r * 0.82), int(cy + r * 0.5)),
                                 (int(cx), int(cy + r * 1.02))])
            # 眼
            for sgn in (-1, 1):
                ex = cx + sgn * r * 0.36
                ey = cy - r * 0.10
                pygame.draw.ellipse(s, (28, 22, 26),
                                    pygame.Rect(int(ex - r * 0.24), int(ey - r * 0.17),
                                                int(r * 0.48), int(r * 0.34)))
                pygame.draw.ellipse(s, tuple(c2),
                                    pygame.Rect(int(ex - r * 0.17), int(ey - r * 0.10),
                                                int(r * 0.34), int(r * 0.22)))
            # 眉/纹样
            if pat == "flame":
                for sgn in (-1, 1):
                    for k in range(3):
                        x0 = cx + sgn * (r * 0.20 + k * r * 0.20)
                        pygame.draw.polygon(s, tuple(c2), [
                            (int(x0), int(cy - r * 0.52)), (int(x0 + sgn * r * 0.10), int(cy - r * 0.86)),
                            (int(x0 + sgn * r * 0.20), int(cy - r * 0.52))])
            elif pat == "crack":
                for k in range(5):
                    y0 = cy - r * 0.66 + k * r * 0.10
                    pygame.draw.line(s, tuple(c2), (int(cx - r * 0.44), int(y0)),
                                     (int(cx + r * 0.44), int(y0 + r * 0.04)), max(1, int(r * 0.045)))
            elif pat == "cloud":
                for k in range(4):
                    pygame.draw.arc(s, tuple(c2),
                                    pygame.Rect(int(cx + (k - 2) * r * 0.34), int(cy - r * 0.74),
                                                int(r * 0.34), int(r * 0.28)), 0, math.pi,
                                    max(1, int(r * 0.045)))
            elif pat == "wave":
                for k in range(3):
                    y0 = cy - r * 0.56 + k * r * 0.16
                    for j in range(6):
                        pygame.draw.arc(s, tuple(c2),
                                        pygame.Rect(int(cx - r * 0.46 + j * r * 0.16), int(y0),
                                                    int(r * 0.16), int(r * 0.16)), 0, math.pi,
                                        max(1, int(r * 0.04)))
            elif pat == "sun":
                pygame.draw.circle(s, tuple(c2), (int(cx), int(cy - r * 0.60)), int(r * 0.20))
                for k in range(8):
                    a = k * math.tau / 8
                    pygame.draw.line(s, tuple(c2),
                                     (int(cx + math.cos(a) * r * 0.26), int(cy - r * 0.60 + math.sin(a) * r * 0.26)),
                                     (int(cx + math.cos(a) * r * 0.40), int(cy - r * 0.60 + math.sin(a) * r * 0.40)),
                                     max(1, int(r * 0.04)))
            elif pat == "leaf":
                for sgn in (-1, 1):
                    pygame.draw.ellipse(s, tuple(c2),
                                        pygame.Rect(int(cx + sgn * r * 0.30 - r * 0.12),
                                                    int(cy - r * 0.80), int(r * 0.24), int(r * 0.30)))
            elif pat == "star":
                pts = U.star_points(cx, cy - r * 0.62, r * 0.24, r * 0.10, 5)
                pygame.draw.polygon(s, tuple(c2), pts)
            elif pat == "moon":
                pygame.draw.circle(s, tuple(c2), (int(cx), int(cy - r * 0.62)), int(r * 0.22))
                pygame.draw.circle(s, tuple(c1), (int(cx + r * 0.10), int(cy - r * 0.66)), int(r * 0.18))
            # 嘴
            pygame.draw.arc(s, tuple(U.shade(c1, 0.5)),
                            pygame.Rect(int(cx - r * 0.24), int(cy + r * 0.28),
                                        int(r * 0.48), int(r * 0.30)), math.pi, math.tau,
                            max(1, int(r * 0.06)))
            if hl:
                pygame.draw.polygon(s, (255, 255, 255, 40),
                                    [(int(cx - r * 0.6), int(cy - r * 0.7)),
                                     (int(cx), int(cy - r * 0.95)), (int(cx - r * 0.2), int(cy + r * 0.4))])
        return U.bake(("mask", name, size), (size, int(size * 1.10)), _d, ss=3)

    def _draw_target(self, surf):
        spec = self.cards[self.answer]
        sp = self._mask_sprite(spec, 148)
        x = self.W // 2
        y = 272
        surf.blit(U.glow_surface(150, (255, 200, 120), 60, 8), (x - 150, y - 150))
        surf.blit(sp, (x - sp.get_width() // 2, y))
        U.text(surf, "找出左边这张脸", (x, y + 176), 28, (240, 214, 194), center=True)

    def _draw_card(self, surf, i, spec):
        x = self._card_x(i)
        sel = abs(self.sel_f - i) < 0.5
        lift = U.ease_out_cubic(1.0 - min(1.0, abs(self.sel_f - i))) * 34
        y = 596 - lift
        w, h = 296, 366
        rect = pygame.Rect(int(x - w / 2), int(y), w, h)
        is_right = self.reveal > 0 and i == self.answer
        border = (150, 246, 190) if is_right else \
                 ((255, 226, 150) if sel else (120, 84, 96))
        if sel:
            U.soft_shadow(surf, rect, 22, 20, 150, (0, 10))
        U.glass(surf, rect, 22,
                (32, 16, 26, 232) if sel else (20, 12, 20, 200),
                border, 3 if sel else 2)
        sp = self._mask_sprite(spec, 190)
        surf.blit(sp, (rect.centerx - sp.get_width() // 2, rect.y + 28))
        U.text(surf, spec[0], (rect.centerx, rect.bottom - 56), 30,
               (255, 236, 216), center=True, bold=True)
        if is_right:
            U.text(surf, "✓", (rect.right - 42, rect.y + 24), 40, (150, 246, 190), center=True, bold=True)
        elif sel:
            pulse = 0.5 + 0.5 * math.sin(self.t * 8)
            U.text(surf, "▲", (rect.centerx, rect.y - 26 - pulse * 5), 30,
                   (255, 226, 150), center=True, bold=True)

    def _draw_timer(self, surf):
        k = max(0.0, self.left / self.limit)
        bar = pygame.Rect(self.W // 2 - 320, 986, 640, 18)
        col = (150, 244, 190) if k > 0.5 else ((255, 214, 120) if k > 0.24 else (255, 130, 110))
        U.bar_gauge(surf, bar, k, col, (44, 36, 52), 9)

    def hud_items(self):
        return [
            ("题号", f"{min(self.q + 1, TOTAL_Q)}/{TOTAL_Q}", (255, 255, 255)),
            ("答对", f"{self.correct}", (150, 244, 190)),
            ("得分", f"{self.score}", (255, 226, 150)),
            ("生命", f"{max(0, self.lives)}", (255, 140, 130), "heart"),
        ]

    def result_title(self) -> str:
        return "满 堂 彩 ！" if self.state == "win" else "下 台 了"

    def result_sub(self) -> str:
        return (f"答对 {self.correct}/{TOTAL_Q} 题　得分 {self.score}　"
                f"最长连对 {self.best_streak}")
