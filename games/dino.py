"""
games/dino.py
=============
太阳神鸟 —— 金沙遗址主题的飞行穿越。

头部操作
    · 抬头     → 扇动翅膀上升（抬头越高升得越快）
    · 低头/放松 → 自然下坠
    · 左右平移 → 微调前后位置（影响与柱子的相对宽度）
玩法
    穿过一对对金杖立柱，撞到立柱或上下边界即结束。越往后越快。
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

GRAVITY = 1180.0
LIFT = -2450.0
BIRD_X = 470
GAP0 = 400.0


@register
class DinoGame(BaseGame):
    KEY = "dino"
    TITLE = "太阳神鸟"
    SUB = "金沙遗址飞行穿越"
    CATEGORY = "头部控制"
    ACCENT = (238, 190, 88)
    ICON = "bird"
    HOW = "抬头扇翅往上飞，穿过一对对金杖立柱"
    HINT = "抬头持续上升 · 放松就下坠 · 撞柱结束"
    DIFFICULTY = 3
    ACHIEVEMENT = "穿过 20 对立柱"
    REQUIRES = ("head",)
    MSG_Y = 250
    TARGET = 20

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.by = 560.0
        self.vy = 0.0
        self.rot = 0.0
        self.passed = 0
        self.score = 0
        self.speed = 420.0
        self.pillars: List[dict] = []
        self.spawn_x = self.W + 240
        self.flap = 0.0
        self.trail: List[tuple] = []
        self.crash_cd = 0.0
        self.ready = 1.2
        self._bg = self._make_bg()
        self._bird = self._make_bird()
        self._spawn(self.W + 420)
        self._spawn(self.W + 980)
        self.set_msg("起飞", "抬头向上飞", 1.4, (255, 236, 170))

    def _make_bg(self) -> pygame.Surface:
        W, H = self.W, self.H
        s = pygame.Surface((W, H))
        s.blit(U.vgrad3(W, H, (44, 24, 14), (128, 74, 30), (206, 148, 66)), (0, 0))
        # 巨大的太阳轮（背景）
        cx, cy = W * 0.72, self.TOP + 300
        for i in range(7):
            r = 300 + i * 46
            U.aa_arc(s, (cx, cy), r, (255, 208, 110, 34), 0, math.tau, 12)
        for i in range(12):
            a = i * math.tau / 12
            U.aa_line(s, (cx + math.cos(a) * 330, cy + math.sin(a) * 330),
                      (cx + math.cos(a) * 420, cy + math.sin(a) * 420), (255, 214, 130, 60), 9)
        U.aa_circle(s, (cx, cy), 168, (255, 214, 130, 46), 0, ss=2)
        # 远山
        rng = random.Random(3)
        for _ in range(9):
            x = rng.uniform(-100, W)
            w = rng.uniform(260, 560)
            h = rng.uniform(120, 250)
            U.aa_poly(s, [(x, H), (x + w * 0.5, H - h), (x + w, H)], (86, 52, 30, 190), 0, ss=2)
        # 江面
        s.blit(U.vgrad(W, 200, (46, 66, 84), (26, 40, 56)), (0, H - 200))
        return s

    def _make_bird(self) -> pygame.Surface:
        W, H = 208, 190

        def _d(s):
            cx, cy = W * 3 // 2, H * 3 // 2
            for j in range(10, 0, -1):
                a = int(64 * (1 - j / 10) ** 1.6) + 3
                pygame.draw.circle(s, (255, 214, 120, a), (cx, cy), int((48 + j * 11) * 3))
            # 双翼（金色，带羽毛分层）
            for sgn in (-1, 1):
                for k, (dy, ln, wd) in enumerate([(0, 132, 30), (16, 108, 26), (30, 82, 22)]):
                    pts = [(cx, cy - 6 + dy * 0.3),
                           (cx + sgn * ln * 3, cy - 52 * 3 / 3 + dy * 3),
                           (cx + sgn * (ln - 26) * 3, cy + (18 + dy) * 3)]
                    pygame.draw.polygon(s, U.shade((248, 200, 96), 1.0 - k * 0.10), pts)
            # 身体
            pygame.draw.ellipse(s, (250, 208, 104),
                                pygame.Rect(int(cx - 52 * 3), int(cy - 34 * 3), int(104 * 3), int(74 * 3)))
            pygame.draw.ellipse(s, (176, 118, 42),
                                pygame.Rect(int(cx - 52 * 3), int(cy - 34 * 3), int(104 * 3), int(74 * 3)), 6)
            # 头
            pygame.draw.circle(s, (250, 208, 104), (int(cx + 56 * 3), int(cy - 34 * 3)), int(27 * 3))
            pygame.draw.circle(s, (250, 208, 104), (int(cx - 56 * 3), int(cy - 34 * 3)), int(27 * 3))
            # 眼
            for sgn in (-1, 1):
                pygame.draw.circle(s, (255, 255, 255),
                                   (int(cx + sgn * 58 * 3), int(cy - 40 * 3)), int(9 * 3))
                pygame.draw.circle(s, (44, 30, 20),
                                   (int(cx + sgn * 60 * 3), int(cy - 40 * 3)), int(5 * 3))
            # 尾羽
            pygame.draw.polygon(s, (238, 176, 72), [
                (cx - 48 * 3, cy + 26 * 3), (cx - 108 * 3, cy + 62 * 3), (cx - 40 * 3, cy + 44 * 3)])
        return U.bake_raw(("bird", 0), (W, H), _d, 3)

    def _spawn(self, x: float):
        H = self.H
        gap = max(220.0, GAP0 - self.passed * 9.0)
        top = random.uniform(self.TOP + 120, self.H - 200 - gap)
        self.pillars.append({"x": x, "top": top, "gap": gap, "passed": False})

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        if self.ready > 0:
            self.ready -= dt
            self.by += math.sin(self.t * 3) * 40 * dt
            return

        # 抬头 → 上升
        lift = 1.0 if inp.action else max(0.0, inp.up - 0.15) * 1.3
        lift = U.clamp(lift, 0.0, 1.4)
        self.vy += GRAVITY * dt + LIFT * lift * dt
        self.vy = U.clamp(self.vy, -880.0, 900.0)
        self.by += self.vy * dt
        self.flap += dt * (8.0 + lift * 12.0)
        self.rot = U.clamp(self.vy / 900.0, -0.55, 0.9)

        if lift > 0.05 and random.random() < 0.6:
            self.particles.emit(BIRD_X - 40, self.by + 20, 1, color=(255, 226, 150),
                                spread=90, vy=120, gravity=-40, life=0.6, size=4.5)

        # 边界
        if self.by < self.TOP + 40:
            self.by = self.TOP + 40
            self.vy = 40
        if self.by > self.H - 170:
            self._crash("坠入江面")
            return

        # 滚动
        self.speed = min(880.0, self.speed + dt * 15.0)
        move = self.speed * dt
        for p in self.pillars:
            p["x"] -= move
        self.spawn_x -= move
        if self.spawn_x <= 0:
            self.spawn_x = random.uniform(420, 620)
            self._spawn(self.W + 160)
        self.pillars = [p for p in self.pillars if p["x"] > -260]

        # 碰撞与计分
        for p in self.pillars:
            if not p["passed"] and p["x"] + 105 < BIRD_X:
                p["passed"] = True
                self.passed += 1
                self.score += 100
                self.particles.emit(BIRD_X + 60, self.by, 14, color=(255, 224, 140),
                                    spread=200, vy=-120, gravity=520, life=0.5, size=4.5)
                if self.passed % 5 == 0:
                    self.set_msg(f"{self.passed} 对！", "速度在加快", 0.9, (255, 240, 180))
                if self.passed >= self.TARGET:
                    self.finish(True)
                    self.flash((255, 244, 200), 0.5)
                    self.set_msg("飞越金沙！", f"穿过 {self.passed} 对", 2.0, (255, 244, 190))
                    return
            # 柱体矩形碰撞
            if abs(p["x"] - BIRD_X) < 105:
                if self.by - 44 < p["top"] or self.by + 44 > p["top"] + p["gap"]:
                    self._crash("撞上金杖立柱")
                    return

        # 拖尾
        self.trail.append((BIRD_X, self.by))
        if len(self.trail) > 14:
            self.trail.pop(0)

    def _crash(self, why: str):
        self.state = "over"
        self.shake(18, 0.6)
        self.flash((255, 150, 100), 0.45)
        self.particles.emit(BIRD_X, self.by, 34, color=(255, 208, 130),
                            spread=360, vy=-220, gravity=900, life=0.9, size=6)
        self.set_msg("坠落", f"{why}　穿过 {self.passed} 对", 2.2, (255, 210, 170))

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        for p in self.pillars:
            self._draw_pillar(surf, p)
        for i, (tx, ty) in enumerate(self.trail):
            a = int(120 * i / max(1, len(self.trail)))
            U.aa_circle(surf, (tx - (len(self.trail) - i) * 16, ty), 4 + i * 0.5,
                        (255, 226, 150, a), 0, ss=2)
        self._draw_bird(surf)
        self._draw_hud(surf)
        self.particles.draw(surf)
        self.draw_msg(surf)

    def _draw_pillar(self, surf, p):
        x = p["x"]
        top, gap = p["top"], p["gap"]
        for y0, h in ((self.TOP, top - self.TOP), (top + gap, self.H - top - gap)):
            if h <= 2:
                continue
            # 金杖：上宽下窄的柱体 + 环纹
            surf.blit(A.shade_panel(210, h, (196, 152, 66), 10), (int(x - 105), int(y0)))
            for k in range(int(y0 + 30), int(y0 + h - 20), 46):
                U.aa_line(surf, (x - 105, k), (x + 105, k), (140, 100, 38), 6)
            surf.blit(A.shade_panel(232, 26, (238, 202, 118), 8),
                      (int(x - 116), int(y0 + (h - 26 if y0 > top else 0))))
        # 顶部太阳纹
        U.aa_circle(surf, (x, top), 30, (238, 202, 118), 0, ss=2)
        U.aa_circle(surf, (x, top + gap), 30, (238, 202, 118), 0, ss=2)

    def _draw_bird(self, surf):
        sp = pygame.transform.rotate(self._bird, -math.degrees(self.rot) * 0.6)
        flap_s = 0.86 + 0.14 * abs(math.sin(self.flap))
        sp = pygame.transform.smoothscale(
            sp, (max(8, int(sp.get_width() * flap_s)), max(8, int(sp.get_height() / flap_s))))
        surf.blit(sp, (int(BIRD_X - sp.get_width() / 2), int(self.by - sp.get_height() / 2)))

    def _draw_hud(self, surf):
        bar = pygame.Rect(self.W // 2 - 280, 130, 560, 18)
        U.bar_gauge(surf, bar, self.passed / self.TARGET, self.ACCENT, (58, 40, 24), 9)
        U.text(surf, f"{self.passed} / {self.TARGET} 对", (self.W // 2, 160), 28,
               (255, 240, 200), center=True, bold=True, shadow=3)
        U.text(surf, f"速度 {int(self.speed)}", (self.W - 60, 130), 26,
               (255, 226, 180), center=True, bold=True)
        # 高度提示条
        y0, y1 = self.TOP + 40, self.H - 170
        U.aa_line(surf, (self.W - 150, y0), (self.W - 150, y1), (255, 226, 160, 60), 4)
        by = U.clamp(self.by, y0, y1)
        U.aa_circle(surf, (self.W - 150, by), 12, (255, 236, 170), 0, ss=3)

    def hud_items(self):
        return [
            ("穿过", f"{self.passed}", (255, 226, 150)),
            ("得分", f"{self.score}", (255, 255, 255)),
            ("速度", f"{int(self.speed)}", (255, 200, 150)),
        ]

    def result_title(self) -> str:
        return "飞 越 金 沙 ！" if self.state == "win" else "坠 落 了"

    def result_sub(self) -> str:
        return f"穿过 {self.passed} 对立柱　得分 {self.score}"
