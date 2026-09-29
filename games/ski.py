"""
games/ski.py
============
川西滑雪 —— 沿 S 形雪道下坡。

头部操作
    · 左右平移 → 在雪道上横移
    · 抬头     → 跳过雪包
玩法
    60 秒内滑完 5000 米。冲出雪道会撞树减速，穿过旗门得分。
"""
from __future__ import annotations

import math
import random
from typing import List

import pygame

from core import art as A
from core import theme as U
from core import scene as SCN
from core.base import BaseGame, register
from core.inputs import GameInput

PLAYER_Y = 742
TRACK_W = 660
GOAL_M = 5000
TIME = 60.0


@register
class SkiGame(BaseGame):
    KEY = "ski"
    TITLE = "川西滑雪"
    SUB = "S 形雪道速降"
    CATEGORY = "头部控制"
    ACCENT = (108, 190, 246)
    WORLD = "alpine"
    ICON = "ski"
    HOW = "跟着雪道走，别撞树，穿旗门加分"
    HINT = "头部左右转向 · 抬头跳过雪包"
    DIFFICULTY = 2
    ACHIEVEMENT = f"{int(TIME)} 秒内滑完 {GOAL_M} 米"
    REQUIRES = ("head",)
    MSG_Y = 250

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.left = TIME
        self.phase = 0.0                # 雪道相位（滚动）
        self.dist = 0.0
        self.px = self.W / 2
        self.vx = 0.0
        self.score = 0
        self.gates_passed = 0
        self.lives = 3
        self.crash_cd = 0.0
        self.jump_t = 0.0
        self.jump_cd = 0.0
        self.speed = 430.0
        self.gates: List[dict] = []
        self.props: List[dict] = []
        self.bumps: List[dict] = []
        self.snow: List[dict] = []
        self.next_gate = 300.0
        self.next_prop = 200.0
        self.next_bump = 620.0
        self._build_bg()
        self.set_msg("出发", "顺着雪道往下冲", 1.4, (200, 234, 255))

    def _build_bg(self):
        W, H = self.W, self.H
        # 注意 .copy()：grad 返回的是缓存表面，直接改写会污染全局缓存
        self._bg = (SCN.sky_img(W, H, "bg_bev_mountain")
                    or U.vgrad3(W, H, (86, 140, 198), (176, 208, 236),
                                (238, 244, 252))).copy()
        # 远山
        s = pygame.Surface((W, H), pygame.SRCALPHA)
        rng = random.Random(8)
        for i in range(7):
            x = rng.uniform(-100, W)
            w = rng.uniform(300, 620)
            h = rng.uniform(160, 300)
            pts = [(x, 300), (x + w * 0.5, 300 - h), (x + w, 300)]
            U.aa_poly(s, pts, (206, 224, 242, 235), 0, ss=2)
            pts2 = [(x + w * 0.28, 300 - h * 0.42), (x + w * 0.5, 300 - h),
                    (x + w * 0.72, 300 - h * 0.42)]
            U.aa_poly(s, pts2, (250, 252, 255, 240), 0, ss=2)
        self._bg.blit(s, (0, 0))
        for _ in range(140):
            x, y = rng.uniform(0, W), rng.uniform(0, 900)
            self._bg.fill((255, 255, 255), (int(x), int(y), rng.randint(1, 3), rng.randint(1, 3)))

    # ------------------------------------------------------------------ 雪道
    def _track_cx(self, y: float) -> float:
        """给定屏幕 y，返回雪道中心 x（随滚动相位变化，形成 S 形）。"""
        k = (y + self.phase) * 0.0021
        return self.W / 2 + math.sin(k) * 372 + math.sin(k * 2.3 + 1.1) * 96

    def _track_half(self, y: float) -> float:
        return TRACK_W / 2 * U.lerp(0.72, 1.12, y / self.H)

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        self.left -= dt
        self.jump_cd = max(0.0, self.jump_cd - dt)
        self.crash_cd = max(0.0, self.crash_cd - dt)
        if self.left <= 0:
            self.left = 0
            self.finish(self.dist >= GOAL_M)
            self.set_msg("时间到", f"滑了 {int(self.dist)} 米", 2.0, (200, 224, 250))
            return

        # 加速下坡
        self.speed = min(880.0, self.speed + dt * 34.0)
        move = self.speed * dt
        self.phase += move
        self.dist += move * 0.0106

        # 横向控制
        self.px += inp.xc * 690.0 * dt
        self.px = U.clamp(self.px, 90, self.W - 90)

        # 跳跃
        if inp.action and self.jump_cd <= 0 and self.jump_t <= 0:
            self.jump_t = 0.52
            self.jump_cd = 0.28
            self.particles.emit(self.px, PLAYER_Y + 40, 14, color=(255, 255, 255),
                                spread=200, vy=-120, gravity=600, life=0.45, size=4)
        if self.jump_t > 0:
            self.jump_t = max(0.0, self.jump_t - dt)

        # 生成
        self.next_gate -= move
        if self.next_gate <= 0:
            self.next_gate = random.uniform(400, 720)
            y = self.H + 60
            self.gates.append({"y": y, "cx": self._track_cx(y), "passed": False})
        self.next_prop -= move
        if self.next_prop <= 0:
            self.next_prop = random.uniform(170, 340)
            y = self.H + 80
            side = -1 if random.random() < 0.5 else 1
            cx = self._track_cx(y)
            off = self._track_half(y) + random.uniform(120, 460)
            self.props.append({"y": y, "x": cx + side * off,
                               "kind": random.choice(["tree", "tree", "rock", "lodge"]),
                               "s": random.uniform(0.82, 1.25)})
        self.next_bump -= move
        if self.next_bump <= 0:
            self.next_bump = random.uniform(700, 1300)
            y = self.H + 60
            self.bumps.append({"y": y, "cx": self._track_cx(y)})

        # 物件上移（相对玩家向下滚动）
        for arr in (self.gates, self.props, self.bumps):
            for o in arr:
                o["y"] -= move * 0.86
        self.gates = [g for g in self.gates if g["y"] > self.TOP - 120]
        self.props = [p for p in self.props if p["y"] > self.H + 200]
        self.bumps = [b for b in self.bumps if b["y"] > self.H + 200]

        # 出界判定
        cx = self._track_cx(PLAYER_Y)
        half = self._track_half(PLAYER_Y)
        out = abs(self.px - cx) > half
        if out and self.crash_cd <= 0:
            self._crash("冲出雪道")

        # 旗门
        for g in self.gates:
            if g["passed"]:
                continue
            if abs(g["y"] - PLAYER_Y) < 40:
                if abs(self.px - g["cx"]) < 230:
                    g["passed"] = True
                    self.gates_passed += 1
                    add = 80 + (20 if abs(self.px - g["cx"]) < 90 else 0)
                    self.score += add
                    self.particles.emit(g["cx"], PLAYER_Y, 16, color=(140, 220, 255),
                                        spread=220, vy=-180, gravity=620, life=0.5, size=4.5)
                else:
                    g["passed"] = True

        # 雪包
        for b in self.bumps:
            if abs(b["y"] - PLAYER_Y) < 34 and abs(self.px - b["cx"]) < 120:
                if self.jump_t > 0.06:
                    if not b.get("scored"):
                        b["scored"] = True
                        self.score += 150
                        self.set_msg("飞跃雪包", "+150", 0.8, (200, 240, 255))
                        self.particles.emit(b["cx"], PLAYER_Y + 20, 22,
                                            color=(255, 255, 255), spread=280,
                                            vy=-200, gravity=560, life=0.7, size=5)
                elif not b.get("hit"):
                    b["hit"] = True

        # 飘雪
        if random.random() < 0.9:
            self.snow.append({"x": random.uniform(0, self.W), "y": self.TOP,
                              "vy": random.uniform(180, 460), "vx": random.uniform(-60, 60),
                              "r": random.uniform(1.5, 4.0)})
        for s in self.snow:
            s["y"] += (s["vy"] + self.speed * 0.4) * dt
            s["x"] += s["vx"] * dt
        self.snow = [s for s in self.snow if s["y"] < self.BOT + 10]

        if self.dist >= GOAL_M:
            self.finish(True)
            self.flash((255, 255, 255), 0.5)
            self.set_msg("冲过终点！", f"{int(self.dist)} 米", 2.0, (180, 240, 255))

    def _crash(self, why: str):
        self.lives -= 1
        self.crash_cd = 1.6
        self.speed = max(320.0, self.speed - 260.0)
        self.shake(16, 0.5)
        self.flash((255, 255, 255), 0.4)
        self.particles.emit(self.px, PLAYER_Y + 30, 30, color=(240, 248, 255),
                            spread=340, vy=-220, gravity=800, life=0.8, size=6)
        if self.lives <= 0:
            self.finish(False)
            self.set_msg("摔倒了", f"滑了 {int(self.dist)} 米", 2.0, (255, 190, 170))
        else:
            self.set_msg(why, f"还剩 {self.lives} 次", 1.1, (255, 214, 160))

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        self._draw_track(surf)
        for p in sorted(self.props, key=lambda d: d["y"]):
            self._draw_prop(surf, p)
        for g in self.gates:
            self._draw_gate(surf, g)
        for b in self.bumps:
            self._draw_bump(surf, b)
        self._draw_skier(surf)
        for s in self.snow:
            U.aa_circle(surf, (s["x"], s["y"]), s["r"], (255, 255, 255, 210), 0, ss=2)
        self._draw_gauges(surf)
        self.particles.draw(surf)
        self.draw_msg(surf)

    def _draw_track(self, surf):
        """
        雪道。注意所有"每帧位置都在变"的装饰线都用 pygame.draw 直出，
        不走 aa_line —— 否则每帧会产生几十个新的缓存条目，反而拖慢帧率。
        """
        pts_l, pts_r = [], []
        for i in range(0, 30):
            y = self.H * i / 29.0
            cx = self._track_cx(y)
            half = self._track_half(y)
            pts_l.append((cx - half, y))
            pts_r.append((cx + half, y))
        U.aa_poly(surf, pts_l + list(reversed(pts_r)), (236, 244, 252), 0, ss=2)
        # 压痕（两道雪槽）
        for off in (-140, 140):
            pts = [(self._track_cx(self.H * i / 24.0) + off, self.H * i / 24.0)
                   for i in range(25)]
            pygame.draw.lines(surf, (200, 218, 238), False, pts, 8)
        # 边界
        pygame.draw.lines(surf, (108, 156, 214), False, pts_l, 3)
        pygame.draw.lines(surf, (108, 156, 214), False, pts_r, 3)
        # 横向坡纹（滚动，给出速度感）
        step = self.H / 26.0
        for i in range(27):
            y = (i * step + (self.phase * 0.42) % step)
            cx = self._track_cx(y)
            half = self._track_half(y)
            pygame.draw.line(surf, (208, 224, 242), (cx - half, y), (cx + half, y), 2)

    def _draw_prop(self, surf, p):
        y = p["y"]
        s = p["s"]
        if p["kind"] == "rock":
            r = 34 * s
            surf.blit(A.shade_ball(r, (128, 134, 148), ss=2), (int(p["x"] - r), int(y - r * 1.4)))
        elif p["kind"] == "lodge":
            w, h = 150 * s, 96 * s
            surf.blit(A.shade_panel(w, h, (150, 106, 74), int(8 * s)), (int(p["x"] - w / 2), int(y - h)))
            U.aa_poly(surf, [(p["x"] - w * 0.62, y - h), (p["x"], y - h * 1.62),
                             (p["x"] + w * 0.62, y - h)], (236, 240, 246), 0, ss=2)
        else:
            h = 150 * s
            U.aa_poly(surf, [(p["x"], y - h), (p["x"] - h * 0.34, y - h * 0.34),
                             (p["x"] - h * 0.20, y - h * 0.30), (p["x"] - h * 0.44, y),
                             (p["x"] + h * 0.44, y), (p["x"] + h * 0.20, y - h * 0.30),
                             (p["x"] + h * 0.34, y - h * 0.34)], (44, 96, 68), 0, ss=2)
            U.aa_poly(surf, [(p["x"], y - h * 0.86), (p["x"] - h * 0.24, y - h * 0.42),
                             (p["x"] + h * 0.24, y - h * 0.42)], (58, 124, 84), 0, ss=2)
            surf.fill((86, 62, 44), (int(p["x"] - h * 0.05), int(y - h * 0.16),
                                     max(2, int(h * 0.10)), int(h * 0.16)))

    def _draw_gate(self, surf, g):
        y = g["y"]
        cx = g["cx"]
        col = (100, 210, 255) if not g["passed"] else (150, 236, 190)
        for sgn in (-1, 1):
            x = cx + sgn * 230
            U.aa_line(surf, (x, y), (x, y - 118), (58, 66, 84), 8)
            U.aa_poly(surf, [(x, y - 118), (x + sgn * 66, y - 96), (x, y - 74)], col, 0, ss=2)
            U.aa_circle(surf, (x, y), 12, (250, 252, 255), 0, ss=2)
        U.aa_line(surf, (cx - 230, y), (cx + 230, y), (col[0], col[1], col[2], 70), 4)
        if not g["passed"]:
            surf.blit(U.glow_surface(120, col, 40, 6), (int(cx - 120), int(y - 180)))

    def _draw_bump(self, surf, b):
        y = b["y"]
        cx = b["cx"]
        U.aa_ellipse(surf, (int(cx - 130), int(y - 34), 260, 68), (250, 252, 255), 0, ss=2)
        U.aa_ellipse(surf, (int(cx - 110), int(y - 26), 220, 44), (228, 238, 250), 0, ss=2)
        if not b.get("scored"):
            U.text(surf, "▲", (cx, y - 74), 30, (140, 200, 250), center=True, bold=True)

    def _draw_skier(self, surf):
        x = self.px
        hop = math.sin(max(0.0, (1.0 - self.jump_t / 0.52)) * math.pi) if self.jump_t > 0 else 0.0
        y = PLAYER_Y - hop * 150
        # 雪板
        U.aa_line(surf, (x - 68, y + 34), (x + 68, y + 34), (232, 76, 88), 13, ss=3)
        U.aa_line(surf, (x - 60, y + 44), (x + 60, y + 44), (250, 250, 252), 9, ss=3)
        # 身体
        craw = U.clamp(-0.30 - 0.30 * (self.px - self._track_cx(PLAYER_Y)) / 400.0, -0.9, 0.9)
        pose = A.pose(lean=0.55, crouch=0.52, arm_l=-2.0, arm_r=-1.9,
                      leg_l=-0.34, leg_l2=0.66, leg_r=0.30, leg_r2=0.60, flip=1)
        spr = A.figure_cached(196, A.FigureStyle(
            shirt=(226, 74, 88), shirt2=(250, 250, 252), pants=(30, 40, 66),
            skin=(242, 200, 166), hair=(40, 32, 34), shoes=(40, 46, 62),
            hair_style="helm", number="8"), pose, ss=3)
        surf.blit(pygame.transform.rotate(spr, math.degrees(craw) * 0.5),
                  (int(x - spr.get_width() / 2), int(y + 40 - spr.get_height())))
        # 雪雾
        if self.jump_t <= 0:
            for i in range(4):
                self.particles.emit(x + random.uniform(-30, 30), y + 48, 1,
                                    color=(255, 255, 255), spread=170, vy=-90,
                                    gravity=440, life=0.45, size=5)
        surf.blit(U.glow_surface(90, (180, 226, 255), 34, 6), (int(x - 90), int(y - 60)))

    def _draw_gauges(self, surf):
        bar = pygame.Rect(self.W // 2 - 300, 128, 600, 18)
        U.bar_gauge(surf, bar, self.dist / GOAL_M, self.ACCENT, (40, 54, 78), 9)
        U.text(surf, f"{int(self.dist)} / {GOAL_M} 米　剩余 {int(self.left)}s",
               (self.W // 2, 158), 26, (240, 250, 255), center=True, bold=True,
               shadow=3, shadow_color=(40, 60, 90))
        for i in range(3):
            cx = self.W - 72 - i * 52
            col = (255, 130, 120) if i < self.lives else (150, 170, 196)
            U.aa_circle(surf, (cx - 11, 66), 12, col, 0, ss=3)
            U.aa_circle(surf, (cx + 11, 66), 12, col, 0, ss=3)
            U.aa_poly(surf, [(cx - 23, 70), (cx + 23, 70), (cx, 96)], col, 0, ss=3)

    def hud_items(self):
        return [
            ("距离", f"{int(self.dist)} m", (255, 255, 255)),
            ("旗门", f"{self.gates_passed}", (140, 220, 255)),
            ("得分", f"{self.score}", (255, 226, 130)),
            ("剩余", f"{int(self.left)}s", (200, 232, 255)),
        ]

    def result_title(self) -> str:
        return "顺 利 到 山 脚 ！" if self.state == "win" else "摔 在 半 山"

    def result_sub(self) -> str:
        return f"滑行 {int(self.dist)} 米　旗门 {self.gates_passed} 个　得分 {self.score}"
