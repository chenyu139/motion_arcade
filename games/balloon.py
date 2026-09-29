"""
games/balloon.py
================
熊猫气球 —— 用手把气球推回空中。

手部操作
    · 移动手掌 → 手掌就是一个"挡板"，碰到气球会把它弹开
玩法
    45 秒内不让任何一个气球落到地面。气球会随重力下落，也会相互碰撞。
    触碰越快，弹力越强。
"""
from __future__ import annotations

import math
import colorsys
import random
from typing import List

import pygame

from core import art as A
from core import theme as U
from core import scene as SCN
from core import sprites as SP
from core.base import BaseGame, register
from core.inputs import GameInput

TIME = 45.0
FLOOR = 990
N_BALLOON = 3
COLORS = [(232, 88, 88), (240, 176, 66), (94, 190, 236), (150, 200, 120),
          (206, 130, 226), (246, 226, 120)]


@register
class BalloonGame(BaseGame):
    KEY = "balloon"
    TITLE = "熊猫气球"
    SUB = "别让气球落地"
    CATEGORY = "手部控制"
    ACCENT = (244, 158, 168)
    WORLD = "forest"
    ICON = "balloon"
    HOW = "用手掌把气球拍回空中，落地就丢命"
    HINT = "移动手掌轻拍气球 · 手越快弹力越强"
    DIFFICULTY = 2
    ACHIEVEMENT = f"{int(TIME)} 秒内不让气球落地"
    REQUIRES = ("hand",)
    MSG_Y = 232

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.left = TIME
        self.lives = 3
        self.score = 0
        self.hits = 0
        self.hx = self.W / 2
        self.hy = self.BOT - 260
        self.phx = self.hx
        self.phy = self.hy
        self.h_open = 1.0
        self.h_found = True
        self.balloons: List[dict] = []
        rng = random.Random(5)
        for i in range(N_BALLOON):
            self.balloons.append({
                "x": self.W * (i + 1) / (N_BALLOON + 1), "y": self.TOP + 280 + i * 90,
                "vx": rng.uniform(-120, 120), "vy": rng.uniform(-40, 40),
                "c": COLORS[i % len(COLORS)], "ph": rng.uniform(0, 6.28),
                "hit": 0.0, "r": rng.uniform(52, 72)})
        self._bg = self._make_bg()
        self.set_msg("看住气球", "用手掌把它们拍起来", 1.5, (255, 232, 236))

    def _make_bg(self) -> pygame.Surface:
        W, H = self.W, self.H
        s = pygame.Surface((W, H))
        SCN.sky_or(s, "bg_bev_mist", W, H, (52, 40, 74), (96, 76, 118), (54, 44, 72))
        # 竹影
        rng = random.Random(6)
        for _ in range(26):
            x = rng.uniform(0, W)
            w = rng.uniform(18, 46)
            U.aa_poly(s, [(x, self.TOP), (x + w, self.TOP), (x + w * 0.7, H), (x - w * 0.7, H)],
                      (34, 56, 44, 120), 0, ss=2)
        # 地面
        s.blit(A.shade_panel(W, 140, (58, 74, 58), 0, 1.08, 0.7), (0, FLOOR))
        U.aa_line(s, (0, FLOOR), (W, FLOOR), (140, 180, 140), 5)
        # 警示线（气球碰到这里就丢命）
        for i in range(0, W, 44):
            U.aa_line(s, (i, FLOOR - 14), (i + 22, FLOOR - 14), (250, 150, 120, 150), 4, ss=2)
        return s

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        self.left -= dt
        if self.left <= 0:
            self.left = 0
            self.finish(True)
            self.flash((255, 240, 210), 0.5)
            self.set_msg("撑住了！", f"拍了 {self.hits} 下", 2.0, (255, 240, 220))
            return

        # 手（挡板）
        tx, ty = self.hand_screen(inp, pygame.Rect(120, self.TOP + 140,
                                                   self.W - 240, self.GAME_H - 220), 1.34)
        self.phx, self.phy = self.hx, self.hy
        self.hx += (tx - self.hx) * min(1.0, dt * 16.0)
        self.hy += (ty - self.hy) * min(1.0, dt * 16.0)
        self.h_open = inp.hand_open
        self.h_found = inp.hand_found
        hvx = (self.hx - self.phx) / max(1e-4, dt)
        hvy = (self.hy - self.phy) / max(1e-4, dt)
        hspeed = math.hypot(hvx, hvy)

        for b in self.balloons:
            b["vy"] += 620 * dt
            # 空气阻力 + 轻微浮力，避免越掉越快
            b["vy"] = min(b["vy"], 900)
            b["vx"] *= (1 - 0.42 * dt)
            b["vy"] *= (1 - 0.30 * dt)
            b["x"] += b["vx"] * dt
            b["y"] += b["vy"] * dt
            b["ph"] += dt * 2.6
            b["hit"] = max(0.0, b["hit"] - dt * 3.0)
            # 左右墙
            if b["x"] < 90:
                b["x"] = 90
                b["vx"] = abs(b["vx"]) * 0.82
            elif b["x"] > self.W - 90:
                b["x"] = self.W - 90
                b["vx"] = -abs(b["vx"]) * 0.82
            # 顶部
            if b["y"] < self.TOP + 60:
                b["y"] = self.TOP + 60
                b["vy"] = abs(b["vy"]) * 0.5
            # 手掌弹开
            d = math.hypot(b["x"] - self.hx, b["y"] - self.hy)
            if d < b["r"] + 86 and self.h_found:
                nx = (b["x"] - self.hx) / max(1.0, d)
                ny = (b["y"] - self.hy) / max(1.0, d)
                power = 360.0 + min(720.0, hspeed * 0.85)
                b["vx"] = nx * power * 0.62 + hvx * 0.34
                b["vy"] = ny * power * 0.62 + hvy * 0.34 - 240.0
                if b["hit"] <= 0.1:
                    b["hit"] = 1.0
                    self.hits += 1
                    self.score += 30
                    self.particles.emit(b["x"], b["y"], 12, color=b["c"],
                                        spread=220, vy=-140, gravity=620, life=0.5, size=4.5)
                    self.shake(4, 0.12)
            # 落地
            if b["y"] + b["r"] >= FLOOR:
                self._drop(b)
                if self.state != "play":
                    return
        # 气球互撞
        for i in range(len(self.balloons)):
            for j in range(i + 1, len(self.balloons)):
                a, c = self.balloons[i], self.balloons[j]
                dx, dy = c["x"] - a["x"], c["y"] - a["y"]
                d = math.hypot(dx, dy) or 1.0
                if d < a["r"] + c["r"]:
                    push = (a["r"] + c["r"] - d) * 3.0
                    nx, ny = dx / d, dy / d
                    a["vx"] -= nx * push
                    a["vy"] -= ny * push
                    c["vx"] += nx * push
                    c["vy"] += ny * push

        # 分数随存活时间增长
        self.score += int(dt * 24)

    def _drop(self, b):
        self.lives -= 1
        self.shake(15, 0.5)
        self.flash((255, 120, 110), 0.4)
        self.particles.emit(b["x"], FLOOR, 26, color=b["c"], spread=320,
                            vy=-240, gravity=980, life=0.8, size=6)
        if self.lives <= 0:
            self.finish(False)
            self.set_msg("气球落地了", f"拍了 {self.hits} 下", 2.2, (255, 190, 180))
            return
        self.set_msg("掉了一个！", f"还剩 {self.lives} 个机会", 1.2, (255, 210, 180))
        b["y"] = self.TOP + 220
        b["x"] = random.uniform(200, self.W - 200)
        b["vy"] = -240
        b["vx"] = random.uniform(-140, 140)

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        for b in self.balloons:
            self._draw_balloon(surf, b)
        self.draw_hand(surf, (self.hx, self.hy), self.h_open, self.h_found)
        self.particles.draw(surf)
        self._draw_hud(surf)
        self.draw_vignette(surf, 120)
        self.draw_msg(surf)

    def _draw_balloon(self, surf, b):
        x, y = b["x"], b["y"]
        r = b["r"] * (1.0 + 0.08 * b["hit"])
        sway = math.sin(b["ph"]) * 10
        # 绳
        pygame.draw.lines(surf, (222, 226, 236), False,
                          [(x, y + r), (x + sway * 0.4, y + r + 34),
                           (x - sway * 0.4, y + r + 68), (x + sway * 0.3, y + r + 100)], 3)
        # 气球主体：优先用 AI 生成的红气球精灵，按配色做色相旋转派生
        rr, gg, bb = b["c"]
        h = colorsys.rgb_to_hsv(rr / 255.0, gg / 255.0, bb / 255.0)[0] * 360.0
        sp = SP.hued("balloon", height=r * 2.2, deg=h)
        if sp is not None:
            surf.blit(sp, (int(x - sp.get_width() / 2), int(y - sp.get_height() / 2)))
        else:
            # 回退：程序绘制
            U.aa_ellipse(surf, (int(x - r * 0.86), int(y - r), int(r * 1.72), int(r * 2.0)),
                         b["c"], 0, ss=2)
            U.aa_ellipse(surf, (int(x - r * 0.60), int(y - r * 0.84), int(r * 0.62), int(r * 0.9)),
                         U.shade(b["c"], 1.30), 0, ss=2)
            U.aa_ellipse(surf, (int(x - r * 0.30), int(y + r * 0.52), int(r * 0.7), int(r * 0.46)),
                         (0, 0, 0, 40), 0, ss=2)
            for sgn in (-1, 1):
                U.aa_circle(surf, (x + sgn * r * 0.52, y - r * 0.52), r * 0.26,
                            U.shade(b["c"], 0.42), 0, ss=2)
                U.aa_circle(surf, (x + sgn * r * 0.26, y - r * 0.06), r * 0.20, (250, 250, 252), 0, ss=2)
                U.aa_circle(surf, (x + sgn * r * 0.30, y - r * 0.06), r * 0.10, (36, 34, 40), 0, ss=2)
            U.aa_circle(surf, (x, y + r * 0.24), r * 0.13, (40, 38, 44), 0, ss=2)
        if b["hit"] > 0.2:
            surf.blit(U.glow_surface(int(r * 2.4), (255, 250, 220), int(70 * b["hit"]), 7),
                      (int(x - r * 2.4), int(y - r * 2.4)))

    def _draw_hud(self, surf):
        U.text(surf, f"剩余 {int(self.left)}s", (self.W // 2, 132), 34, (255, 236, 240),
               center=True, bold=True, glow=12, glow_color=(255, 150, 160))
        U.text(surf, f"拍击 {self.hits} 次", (self.W // 2, 178), 26, (238, 216, 236),
               center=True)
        for i in range(3):
            cx = self.W - 72 - i * 52
            col = (255, 130, 120) if i < self.lives else (96, 82, 100)
            U.aa_circle(surf, (cx - 11, 66), 12, col, 0, ss=3)
            U.aa_circle(surf, (cx + 11, 66), 12, col, 0, ss=3)
            U.aa_poly(surf, [(cx - 23, 70), (cx + 23, 70), (cx, 96)], col, 0, ss=3)

    def hud_items(self):
        return [
            ("剩余", f"{int(self.left)}s", (255, 236, 240)),
            ("拍击", f"{self.hits}", (255, 214, 150)),
            ("得分", f"{self.score}", (255, 255, 255)),
            ("机会", f"{max(0, self.lives)}", (255, 150, 140), "heart"),
        ]

    def result_title(self) -> str:
        return "全 部 接 住 ！" if self.state == "win" else "气 球 落 地"

    def result_sub(self) -> str:
        return f"拍击 {self.hits} 次　得分 {self.score}　坚持 {int(TIME - self.left)} 秒"
