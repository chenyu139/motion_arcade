"""
games/hoop.py
=============
手控投篮 —— 用手掌的高度和力度控制出手。

手部操作
    · 手掌上下移动   → 出手高度（越高抛物线越平）
    · 张开 / 握拳    → 力度（握拳蓄力，张开出手）
玩法
    10 次出手，命中 6 次获胜。空心入网额外加分。
"""
from __future__ import annotations

import math
from typing import List, Optional

import pygame

from core import art as A
from core import theme as U
from core import sprites as SP
from core import scene as SCN
from core.base import BaseGame, register
from core.inputs import GameInput

FLOOR = 946
HOOP_X = 1470
HOOP_Y = 470
RIM_R = 66
BALL_X0, BALL_Y0 = 380, 700
SHOTS = 10
WIN = 6
GRAV = 1900.0


@register
class HoopGame(BaseGame):
    KEY = "hoop"
    TITLE = "手控投篮"
    SUB = "掌上准星"
    CATEGORY = "手部控制"
    ACCENT = (238, 148, 62)
    WORLD = "court"
    ICON = "hoop"
    HOW = "握拳蓄力，掌心抬高，松开出手"
    HINT = "手掌高低决定弧线 · 握拳蓄力 · 张开出手"
    DIFFICULTY = 2
    ACHIEVEMENT = f"{SHOTS} 次出手命中 {WIN} 次"
    REQUIRES = ("hand",)
    MSG_Y = 226

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.shot_i = 0
        self.goals = 0
        self.score = 0
        self.swish = 0
        self.history: List[str] = []
        self.charge = 0.0
        self.charging = False
        self.h_open = 0.8
        self.h_found = True
        self.hy = 0.6
        self.ball: Optional[dict] = None
        self.phase = "aim"          # aim | fly | result
        self.phase_t = 0.0
        self.spring = 0.0
        self.hit_flash = 0.0
        self.hoop_sway = 0.0
        self.hoop_y = HOOP_Y
        self._bg = self._make_bg()
        self.set_msg("第一次出手", "握拳蓄力，松开投出", 1.6, (255, 232, 190))

    def _make_bg(self) -> pygame.Surface:
        W, H = self.W, self.H
        s = pygame.Surface((W, H))
        SCN.sky_or(s, "bg_bev_mist", W, H, (26, 30, 52), (52, 58, 88), (34, 38, 60))
        # 观众背景
        s.blit(A.crowd_stand(W, 300, seed=21, rows=7, lit=-0.16), (0, 118))
        # 球场
        s.blit(A.hard_court(W, H - 500, (150, 132, 116), (96, 82, 72)), (0, 500))
        for i in range(14):
            x = i * (W / 13.0)
            U.aa_line(s, (x, 500), (x + 60, H), (0, 0, 0, 20), 3, ss=2)
        U.aa_line(s, (0, FLOOR), (W, FLOOR), (238, 232, 220, 90), 5)
        # 篮板与篮架
        s.blit(A.shade_panel(20, 380, (128, 132, 148), 8), (HOOP_X + 118, HOOP_Y - 180))
        s.blit(A.shade_panel(240, 160, (232, 236, 246), 10), (HOOP_X + 18, HOOP_Y - 150))
        s.blit(A.shade_panel(150, 100, (206, 212, 226), 8), (HOOP_X + 58, HOOP_Y - 120))
        return s

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        self.phase_t += dt
        self.hit_flash = max(0.0, self.hit_flash - dt * 2.4)
        self.spring = max(0.0, self.spring - dt * 3.0)

        if self.phase == "result":
            if self.phase_t > 1.4:
                self._next()
            return

        # 手部
        tx, ty = self.hand_screen(inp, pygame.Rect(160, self.TOP + 120,
                                                   self.W - 320, self.GAME_H - 220), 1.20)
        self.hy = inp.hy
        self.h_open = inp.hand_open
        self.h_found = inp.hand_found
        self.hoop_y = HOOP_Y + math.sin(self.t * 1.4) * 12

        if self.phase == "aim":
            if inp.grab_hold or inp.pinch:
                self.charging = True
            if self.charging:
                self.charge = min(1.0, self.charge + dt * 0.92)
            if self.charging and (inp.release or inp.hand_open > 0.68):
                self._shoot()
        elif self.phase == "fly":
            self._update_ball(dt)

    def _shoot(self):
        self.charging = False
        self.phase = "fly"
        self.phase_t = 0.0
        # 出手高度由手掌位置决定：手抬得越高，出手点越高、弧线越平
        h = U.clamp(self.hy, 0.12, 0.94)
        y0 = U.lerp(FLOOR - 120, self.TOP + 200, 1.0 - h)
        power = U.lerp(600.0, 1240.0, self.charge)
        b = {"x": BALL_X0, "y": y0, "rot": 0.0, "t": 0.0, "scored": None}
        tgt_x, tgt_y = HOOP_X - 26, self.hoop_y
        # 反解一个能到达篮筐的抛体
        g = GRAV
        vy0 = -math.sqrt(max(1.0, 2 * g * max(40.0, y0 - (tgt_y - 150))))
        vy0 *= U.lerp(0.92, 1.10, self.charge)
        b["vy"] = vy0
        disc = max(0.0, vy0 * vy0 + 2 * g * (tgt_y - y0))
        tt = (-vy0 + math.sqrt(disc)) / g
        tt = max(0.35, min(2.6, tt))
        b["vx"] = (tgt_x - BALL_X0) / tt
        b["vy"] = vy0
        b["power"] = power
        self.ball = b
        self.spring = 1.0
        self.particles.emit(BALL_X0, y0, 14, color=(255, 226, 170),
                            spread=180, vy=-160, gravity=700, life=0.5, size=4.5)

    def _update_ball(self, dt: float):
        b = self.ball
        if b is None:
            return
        b["vy"] += GRAV * dt
        b["x"] += b["vx"] * dt
        b["y"] += b["vy"] * dt
        b["rot"] += dt * 6.0
        # 篮板
        if b["x"] > HOOP_X + 20 and b["vy"] > 0 and b["y"] < self.hoop_y - 60:
            b["x"] = HOOP_X + 20
            b["vx"] = -abs(b["vx"]) * 0.55
            self.particles.emit(b["x"], b["y"], 10, color=(226, 232, 246),
                                spread=180, vy=-120, gravity=620, life=0.4, size=4)
            self.shake(5, 0.16)
        # 篮筐判定（在圈平面内下落）
        if b["scored"] is None and abs(b["x"] - HOOP_X) < RIM_R and b["vy"] > 0 \
                and abs(b["y"] - self.hoop_y) < 34:
            d = abs(b["x"] - HOOP_X)
            b["scored"] = "swish" if d < 24 else "in"
            self._resolve(b, b["scored"])
            return
        if b["y"] > FLOOR + 60 or b["x"] > self.W + 80:
            b["scored"] = "miss"
            self._resolve(b, "miss")

    def _resolve(self, b, kind):
        self.phase = "result"
        self.phase_t = 0.0
        self.shot_i += 1
        if kind == "miss":
            self.history.append("不中")
            self.set_msg("不中", "调整一下力度", 1.1, (255, 180, 150))
            self.shake(7, 0.24)
            self.particles.emit(b["x"], min(b["y"], FLOOR), 16, color=(180, 190, 210),
                                spread=220, vy=-160, gravity=880, life=0.6, size=5)
        else:
            self.goals += 1
            if kind == "swish":
                self.swish += 1
                add = 160
            else:
                add = 100 if abs(b["x"] - HOOP_X) < 40 else 70
            self.score += add
            self.hit_flash = 1.0
            self.flash((255, 244, 210), 0.28)
            self.shake(10, 0.34)
            tag = "空心入网！" if kind == "swish" else "命中！"
            self.history.append("空心" if kind == "swish" else "命中")
            self.set_msg(tag, f"+{add}", 1.1, (255, 236, 170))
            self.particles.emit(HOOP_X, self.hoop_y, 30, color=(255, 224, 140),
                                spread=300, vy=-160, gravity=800, life=0.8, size=6)

    def _next(self):
        self.ball = None
        self.charge = 0.0
        self.charging = False
        if self.shot_i >= SHOTS:
            self.finish(self.goals >= WIN)
            return
        self.phase = "aim"
        self.set_msg(f"第 {self.shot_i + 1} 球", "", 0.9, (220, 236, 255))

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        # 篮筐
        self._draw_hoop(surf)
        if self.phase in ("aim", "fly"):
            self._draw_shooter(surf)
        if self.ball is not None:
            if not SP.draw(surf, "basketball", self.ball["x"], self.ball["y"],
                           height=68, rot=math.degrees(self.ball["rot"]), shadow=0.6):
                A.draw_ball(surf, self.ball["x"], self.ball["y"], 34, "basketball",
                            rot=self.ball["rot"], shadow=0.6, ground_y=FLOOR)
        if self.phase == "aim":
            self._draw_aim(surf)
        for i, h in enumerate(self.history):
            x = 80 + i * 44
            col = (255, 224, 140) if h in ("空心", "命中") else (170, 180, 198)
            U.aa_circle(surf, (x, 900), 14, col, 0, ss=3)
        self.particles.draw(surf)
        self._draw_hud(surf)
        if self.hit_flash > 0:
            ov = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            ov.fill((255, 240, 190, int(44 * self.hit_flash)))
            surf.blit(ov, (0, 0))
        self.draw_msg(surf)

    def _draw_hoop(self, surf):
        hy = self.hoop_y
        # 网
        for i in range(11):
            t = i / 10.0
            x0 = HOOP_X - RIM_R + t * RIM_R * 2
            U.aa_line(surf, (x0, hy), (HOOP_X + (t - 0.5) * RIM_R * 0.9, hy + 74),
                      (236, 242, 250, 150), 2, ss=2)
        for k in range(3):
            yy = hy + 18 + k * 20
            rr = RIM_R * (1.0 - k * 0.20)
            U.aa_arc(surf, (HOOP_X, yy - 12), rr, (236, 242, 250, 130), 0, math.pi, 3)
        # 篮圈
        U.aa_ellipse(surf, (int(HOOP_X - RIM_R), int(hy - 18), RIM_R * 2, 36),
                     (238, 122, 48), 0, ss=2)
        U.aa_ellipse(surf, (int(HOOP_X - RIM_R), int(hy - 18), RIM_R * 2, 36),
                     (160, 66, 24), 6, ss=2)
        surf.blit(U.glow_surface(160, (255, 170, 90), 46, 7), (HOOP_X - 160, int(hy - 160)))

    def _draw_shooter(self, surf):
        pose = A.pose(lean=0.16, arm_l=-2.5, arm_l2=-0.3, arm_r=-2.4, arm_r2=-0.3,
                      leg_l=-0.26, leg_r=0.28, crouch=0.30 + self.charge * 0.28, flip=1)
        spr = A.figure_cached(232, A.FigureStyle(
            shirt=(238, 148, 62), shirt2=(250, 246, 236), pants=(44, 52, 74),
            skin=(242, 202, 168), hair=(40, 32, 32), shoes=(240, 244, 250),
            hair_style="short", number="23"), pose, ss=3)
        A.draw_figure(surf, spr, BALL_X0 - 60, FLOOR + 4, 26)

    def _draw_aim(self, surf):
        # 力度环
        r = 90
        U.ring_gauge(surf, (BALL_X0, 760), r, 14, self.charge,
                     (255, 200, 110) if self.charge < 0.85 else (255, 140, 100),
                     (50, 54, 72))
        U.text(surf, "松开出手" if self.charging else "握拳蓄力",
               (BALL_X0, 760), 22, (240, 240, 250), center=True)
        # 预测弧线
        if self.charging:
            y0 = BALL_Y0
            h = U.clamp(self.hy, 0.12, 0.94)
            y0 = U.lerp(FLOOR - 120, self.TOP + 200, 1.0 - h)
            g = GRAV
            vy0 = -math.sqrt(max(1.0, 2 * g * max(40.0, y0 - (self.hoop_y - 150))))
            vy0 *= U.lerp(0.92, 1.10, self.charge)
            disc = max(0.0, vy0 * vy0 + 2 * g * (self.hoop_y - y0))
            tt = (-vy0 + math.sqrt(disc)) / g
            vx = (HOOP_X - 26 - BALL_X0) / max(0.3, tt)
            for i in range(26):
                td = tt * i / 25.0
                px = BALL_X0 + vx * td
                py = y0 + vy0 * td + 0.5 * g * td * td
                if py > FLOOR:
                    break
                U.aa_circle(surf, (px, py), 4, (255, 226, 150, 90), 0, ss=2)

    def _draw_hud(self, surf):
        U.text(surf, f"命中 {self.goals} / {WIN}　出手 {min(self.shot_i, SHOTS)} / {SHOTS}",
               (self.W // 2, 130), 30, (255, 240, 214), center=True, bold=True,
               glow=10, glow_color=(255, 170, 90))
        U.text(surf, f"得分 {self.score}　空心 {self.swish}", (self.W // 2, 172), 26,
               (238, 226, 210), center=True)

    def hud_items(self):
        return [
            ("命中", f"{self.goals}/{WIN}", (255, 236, 180)),
            ("出手", f"{min(self.shot_i, SHOTS)}/{SHOTS}", (255, 255, 255)),
            ("得分", f"{self.score}", (255, 214, 150)),
            ("空心", f"{self.swish}", (180, 240, 255)),
        ]

    def result_title(self) -> str:
        return "投 中 了 ！" if self.state == "win" else "手 感 冰 凉"

    def result_sub(self) -> str:
        return (f"{SHOTS} 次出手命中 {self.goals} 次　空心 {self.swish} 次　"
                f"得分 {self.score}")
