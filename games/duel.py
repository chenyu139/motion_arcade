"""
games/duel.py
=============
双线太极 —— 同时用头部和手各控制一条线。

操作
    · 上轨道：头部左右平移 → 控制上面的阴阳球
    · 下轨道：手掌左右移动 → 控制下面的阴阳球
玩法
    60 秒内两条轨道都要躲开从右向左过来的障碍。
    任意一条撞到 3 次就结束。考验的是"分心两用"。
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

TIME = 60.0
LANE_H = 330
UPPER_Y = 300        # 上轨道中心 y
LOWER_Y = 760        # 下轨道中心 y
BALL_R = 44
LIVES = 3


@register
class DuelGame(BaseGame):
    KEY = "duel"
    TITLE = "双线太极"
    SUB = "头手并用"
    CATEGORY = "头部 + 手部"
    ACCENT = (168, 176, 236)
    WORLD = "night"
    ICON = "taichi"
    HOW = "上面用头、下面用手，两条线都要躲开障碍"
    HINT = "头部控制上球 · 手掌控制下球 · 撞 3 次结束"
    DIFFICULTY = 3
    ACHIEVEMENT = f"坚持 {int(TIME)} 秒不撞三次"
    REQUIRES = ("head", "hand")
    MSG_Y = 214

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.left = TIME
        self.lives = LIVES
        self.score = 0
        self.dodged = 0
        self.ax = self.W / 2          # 上球（头部）
        self.hx = self.W / 2          # 下球（手）
        self.hy = LOWER_Y
        self.h_open = 1.0
        self.h_found = True
        self.obs: List[dict] = []
        self.spawn_t = 1.0
        self.speed = 460.0
        self.flash_a = 0.0
        self.flash_b = 0.0
        self.hit_cd = 0.0
        self.invuln = 0.0
        self.trail_a: List[float] = []
        self.trail_b: List[float] = []
        self._bg = self._make_bg()
        self.set_msg("同时开动", "头管上面，手管下面", 1.8, (226, 230, 255))

    def _make_bg(self) -> pygame.Surface:
        W, H = self.W, self.H
        s = pygame.Surface((W, H))
        s.blit(U.vgrad3(W, H, (16, 18, 38), (30, 32, 62), (14, 16, 34)), (0, 0))
        # 太极背景纹
        cx, cy = W / 2, (UPPER_Y + LOWER_Y) / 2
        U.aa_circle(s, (cx, cy), 320, (255, 255, 255, 12), 0, ss=2)
        U.aa_arc(s, (cx, cy), 320, (200, 210, 255, 30), math.pi / 2, math.pi * 1.5, 6)
        U.aa_arc(s, (cx, cy), 320, (255, 190, 190, 30), -math.pi / 2, math.pi / 2, 6)
        # 两条轨道
        for y, col in ((UPPER_Y, (150, 190, 255)), (LOWER_Y, (255, 190, 150))):
            band = pygame.Surface((W, LANE_H - 40), pygame.SRCALPHA)
            band.fill((col[0], col[1], col[2], 14))
            s.blit(band, (0, int(y - (LANE_H - 40) / 2)))
            pygame.draw.line(s, (col[0], col[1], col[2], 90), (0, y), (W, y), 2)
        # 中线分隔
        pygame.draw.line(s, (120, 130, 180, 80), (0, (UPPER_Y + LOWER_Y) / 2),
                         (W, (UPPER_Y + LOWER_Y) / 2), 3)
        # 星点
        rng = random.Random(15)
        for _ in range(150):
            x, y = rng.uniform(0, W), rng.uniform(self.TOP, H)
            s.fill((255, 255, 255), (int(x), int(y), rng.randint(1, 2), rng.randint(1, 2)))
        return s

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        self.left -= dt
        self.hit_cd = max(0.0, self.hit_cd - dt)
        self.invuln = max(0.0, self.invuln - dt)
        self.flash_a = max(0.0, self.flash_a - dt * 2.6)
        self.flash_b = max(0.0, self.flash_b - dt * 2.6)
        if self.left <= 0:
            self.left = 0
            self.finish(True)
            self.flash((255, 250, 220), 0.5)
            self.set_msg("两条线都守住了！", f"躲开 {self.dodged} 个障碍", 2.2, (255, 244, 220))
            return

        # 上球：头部
        self.ax += inp.xc * 900.0 * dt
        self.ax = U.clamp(self.ax, BALL_R + 40, self.W - BALL_R - 40)
        if abs(inp.xc) < 0.08:
            self.ax += math.sin(self.t * 0.8) * 40 * dt
        # 下球：手
        tx, ty = self.hand_screen(inp, pygame.Rect(BALL_R + 40, LOWER_Y - 130,
                                                   self.W - 2 * (BALL_R + 40), 260), 1.30)
        self.hx += (tx - self.hx) * min(1.0, dt * 15.0)
        self.hy += (LOWER_Y - self.hy) * min(1.0, dt * 6.0)
        self.h_open = inp.hand_open
        self.h_found = inp.hand_found

        # 障碍
        self.speed = min(1100.0, self.speed + dt * 8.0)
        self.spawn_t -= dt
        if self.spawn_t <= 0:
            self.spawn_t = random.uniform(0.55, 0.95) * (620.0 / self.speed)
            lane = random.choice(["up", "down", "both"])
            spec = random.choice(["bar", "ball", "star"])
            self.obs.append({"x": self.W + 120, "lane": lane, "kind": spec,
                             "y": random.uniform(-1, 1), "h": random.uniform(120, 190)})

        for o in self.obs:
            o["x"] -= self.speed * dt
        for o in self.obs:
            if not o.get("passed") and o["x"] < -140:
                o["passed"] = True
                self.dodged += 1
                self.score += 40
        self.obs = [o for o in self.obs if o["x"] > -180]

        # 碰撞
        for o in self.obs:
            if o.get("hit"):
                continue
            if abs(o["x"] - self.ax) < 56 + o["h"] * 0.3 and o["lane"] in ("up", "both"):
                o["hit"] = True
                self.ax = U.clamp(self.ax - 120, BALL_R + 40, self.W - BALL_R - 40)
                self._damage("up", self.ax, UPPER_Y)
            if abs(o["x"] - self.hx) < 56 + o["h"] * 0.3 and o["lane"] in ("down", "both"):
                o["hit"] = True
                self.hx = U.clamp(self.hx - 120, BALL_R + 40, self.W - BALL_R - 40)
                self._damage("down", self.hx, LOWER_Y)
            if self.state != "play":
                return

        self.trail_a.append(self.ax)
        self.trail_b.append(self.hx)
        for arr in (self.trail_a, self.trail_b):
            while len(arr) > 16:
                arr.pop(0)

    def _damage(self, which: str, x: float, y: float):
        if self.invuln > 0:
            return
        self.lives -= 1
        self.invuln = 1.1
        self.hit_cd = 0.5
        self.shake(15, 0.48)
        self.flash((255, 120, 110), 0.34)
        if which == "up":
            self.flash_a = 1.0
        else:
            self.flash_b = 1.0
        self.particles.emit(x, y, 26, color=(255, 150, 130), spread=320,
                            vy=-220, gravity=900, life=0.8, size=6)
        if self.lives <= 0:
            self.finish(False)
            self.set_msg("撞了三次", f"躲开 {self.dodged} 个障碍", 2.2, (255, 190, 170))

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        for o in self.obs:
            self._draw_obstacle(surf, o)
        for i, x in enumerate(self.trail_a):
            a = int(110 * i / max(1, len(self.trail_a)))
            U.aa_circle(surf, (x, UPPER_Y), 8 + i * 0.7, (150, 190, 255, a), 0, ss=2)
        for i, x in enumerate(self.trail_b):
            a = int(110 * i / max(1, len(self.trail_b)))
            U.aa_circle(surf, (x, LOWER_Y), 8 + i * 0.7, (255, 190, 150, a), 0, ss=2)
        self._draw_balls(surf)
        self._draw_labels(surf)
        self.particles.draw(surf)
        self._draw_hud(surf)
        self.draw_msg(surf)

    def _draw_balls(self, surf):
        for x, y, flash, col in ((self.ax, UPPER_Y, self.flash_a, (140, 180, 255)),
                                 (self.hx, LOWER_Y, self.flash_b, (255, 180, 140))):
            if self.invuln > 0 and int(self.invuln * 14) % 2 == 0:
                continue
            surf.blit(U.glow_surface(120, col, int(70 + 70 * flash), 8),
                      (int(x - 120), int(y - 120)))
            # 阴阳球
            U.aa_circle(surf, (x, y), BALL_R, (250, 250, 252), 0, ss=3)
            U.aa_arc(surf, (x, y), BALL_R, (36, 38, 52), -math.pi / 2, math.pi / 2, BALL_R, ss=3)
            U.aa_circle(surf, (x, y - BALL_R / 2), BALL_R / 2, (36, 38, 52), 0, ss=3)
            U.aa_circle(surf, (x, y + BALL_R / 2), BALL_R / 2, (250, 250, 252), 0, ss=3)
            U.aa_circle(surf, (x, y - BALL_R / 2), BALL_R / 6, (250, 250, 252), 0, ss=3)
            U.aa_circle(surf, (x, y + BALL_R / 2), BALL_R / 6, (36, 38, 52), 0, ss=3)
            U.aa_circle(surf, (x, y), BALL_R, (200, 210, 235) if col[2] > 200 else (235, 205, 190),
                        4, ss=3)

    def _draw_obstacle(self, surf, o):
        x = o["x"]
        h = o["h"]
        for lane, y in (("up", UPPER_Y), ("down", LOWER_Y)):
            if o["lane"] not in (lane, "both"):
                continue
            col = (196, 88, 120) if lane == "up" else (88, 140, 196)
            if o["kind"] == "ball":
                surf.blit(A.shade_ball(h * 0.42, col, ss=2),
                          (int(x - h * 0.42), int(y - h * 0.42)))
            elif o["kind"] == "star":
                pts = U.star_points(x, y, h * 0.52, h * 0.24, 5)
                U.aa_poly(surf, pts, col, 0, ss=3)
            else:
                surf.blit(A.shade_panel(h * 0.5, h, col, 12),
                          (int(x - h * 0.25), int(y - h / 2)))
                for k in range(3):
                    surf.fill(U.shade(col, 1.2),
                              (int(x - h * 0.20), int(y - h / 2 + 18 + k * (h / 3.6)),
                               max(2, int(h * 0.40)), max(2, int(h * 0.06))))
            surf.blit(U.glow_surface(int(h * 1.1), col, 40, 6), (int(x - h * 0.55), int(y - h * 0.55)))

    def _draw_labels(self, surf):
        U.text(surf, "头部", (68, UPPER_Y), 26, (170, 200, 255), center=True, bold=True)
        U.text(surf, "手部", (68, LOWER_Y), 26, (255, 200, 170), center=True, bold=True)
        if self.flash_a > 0:
            U.text(surf, "撞了！", (self.ax, UPPER_Y - 86), 30, (255, 160, 140),
                   center=True, bold=True, alpha=int(255 * min(1, self.flash_a * 2)))
        if self.flash_b > 0:
            U.text(surf, "撞了！", (self.hx, LOWER_Y - 86), 30, (255, 160, 140),
                   center=True, bold=True, alpha=int(255 * min(1, self.flash_b * 2)))

    def _draw_hud(self, surf):
        U.text(surf, f"剩余 {int(self.left)}s", (self.W // 2, 132), 32, (232, 236, 255),
               center=True, bold=True, glow=10, glow_color=(150, 180, 255))
        U.text(surf, f"躲开 {self.dodged} 个", (self.W // 2, 174), 26, (214, 222, 250),
               center=True)
        bar = pygame.Rect(self.W // 2 - 260, 208, 520, 14)
        U.bar_gauge(surf, bar, self.left / TIME, self.ACCENT, (40, 44, 70), 7)
        for i in range(LIVES):
            cx = self.W - 72 - i * 52
            col = (255, 130, 120) if i < self.lives else (86, 88, 110)
            U.aa_circle(surf, (cx - 11, 66), 12, col, 0, ss=3)
            U.aa_circle(surf, (cx + 11, 66), 12, col, 0, ss=3)
            U.aa_poly(surf, [(cx - 23, 70), (cx + 23, 70), (cx, 96)], col, 0, ss=3)

    def hud_items(self):
        return [
            ("剩余", f"{int(self.left)}s", (232, 236, 255)),
            ("躲开", f"{self.dodged}", (180, 220, 255)),
            ("得分", f"{self.score}", (255, 226, 150)),
            ("机会", f"{max(0, self.lives)}", (255, 150, 140), "heart"),
        ]

    def result_title(self) -> str:
        return "两 线 全 守 ！" if self.state == "win" else "撞 了 三 次"

    def result_sub(self) -> str:
        return f"躲开 {self.dodged} 个障碍　得分 {self.score}　坚持 {int(TIME - self.left)} 秒"
