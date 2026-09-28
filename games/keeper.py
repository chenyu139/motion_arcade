"""
games/keeper.py
===============
双人守门 —— 头手各守半扇门。

操作
    · 头部左右平移 → 控制左边那位守门员
    · 手掌左右移动 → 控制右边那位守门员
玩法
    20 次射门，扑出 12 次获胜。球会随机打向任意一侧，
    你必须同时盯着两边 —— 这就是这个游戏的难点。
"""
from __future__ import annotations

import math
import random
from typing import List, Optional

import pygame

from core import art as A
from core import theme as U
from core.base import BaseGame, register
from core.inputs import GameInput

GOAL_L, GOAL_R = 420, 1500
CROSSBAR_Y = 372
GOAL_LINE_Y = 716
GOAL_DEPTH = 118
MID = (GOAL_L + GOAL_R) / 2
KEEPER_H = 226
SHOTS = 20
WIN = 12
SAVE_R = 132


@register
class KeeperGame(BaseGame):
    KEY = "keeper"
    TITLE = "双人守门"
    SUB = "头手各守半边"
    CATEGORY = "头部 + 手部"
    ACCENT = (120, 220, 176)
    WORLD = "stadium"
    ICON = "glove"
    HOW = "头管左门将、手管右门将，20 球扑出 12 个"
    HINT = "头部控制左门将 · 手掌控制右门将"
    DIFFICULTY = 3
    ACHIEVEMENT = f"{SHOTS} 球扑出 {WIN} 个"
    REQUIRES = ("head", "hand")
    MSG_Y = 216

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.shot_i = 0
        self.saves = 0
        self.score = 0
        self.streak = 0
        self.best_streak = 0
        self.history: List[str] = []
        self.lx = GOAL_L + 240       # 左门将（头）
        self.rx = GOAL_R - 240       # 右门将（手）
        self.hy = 0.5
        self.h_open = 1.0
        self.h_found = True
        self.ball: Optional[dict] = None
        self.phase = "aim"
        self.phase_t = 0.0
        self.aim_t = 0.0
        self.dive_l = 0.0
        self.dive_r = 0.0
        self.flash_side = 0.0
        self.wide = False
        self.wide_anim = 0.0
        self._bg = self._make_bg()
        self.set_msg("准备", "头管左边，手管右边", 1.8, (200, 246, 224))

    def _make_bg(self) -> pygame.Surface:
        W, H = self.W, self.H
        s = pygame.Surface((W, H))
        s.blit(A.stadium_bg(W, H, (8, 14, 32), (22, 36, 70), seed=6), (0, 0))
        s.blit(A.crowd_stand(W, 260, seed=14, rows=7, lit=-0.06), (0, 120))
        s.blit(A.shade_panel(W, 56, (22, 30, 52), 0, 1.0, 0.7), (0, 386))
        s.blit(A.grass_pitch(W, H - 442, (56, 134, 72), (28, 90, 50), stripes=12), (0, 442))
        A.stadium_lights(s, [220, 960, 1700], 130, 150, cone_to=650)
        # 球门
        for i in range(29):
            t = i / 28
            x0 = U.lerp(GOAL_L, GOAL_R, t)
            x1 = U.lerp(GOAL_L - 46, GOAL_R + 46, t)
            pygame.draw.line(s, (226, 234, 246, 130), (x0, CROSSBAR_Y), (x1, GOAL_LINE_Y + GOAL_DEPTH), 2)
        for i in range(11):
            t = i / 10
            y0 = U.lerp(CROSSBAR_Y, GOAL_LINE_Y + GOAL_DEPTH, t)
            pygame.draw.line(s, (226, 234, 246, 130),
                             (U.lerp(GOAL_L, GOAL_L - 46, t), y0),
                             (U.lerp(GOAL_R, GOAL_R + 46, t), y0), 2)
        s.blit(A.shade_panel(26, GOAL_LINE_Y - CROSSBAR_Y + 26, (250, 252, 255), 8),
               (GOAL_L - 13, CROSSBAR_Y - 8))
        s.blit(A.shade_panel(26, GOAL_LINE_Y - CROSSBAR_Y + 26, (250, 252, 255), 8),
               (GOAL_R - 13, CROSSBAR_Y - 8))
        s.blit(A.shade_panel(GOAL_R - GOAL_L + 26, 26, (250, 252, 255), 8),
               (GOAL_L - 13, CROSSBAR_Y - 13))
        # 中线（提示两边分界）
        pygame.draw.line(s, (255, 255, 255, 40), (MID, CROSSBAR_Y), (MID, GOAL_LINE_Y), 2)
        return s

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        self.phase_t += dt
        self.flash_side = max(0.0, self.flash_side - dt * 2.4)
        self.dive_l = max(0.0, self.dive_l - dt * 3.0)
        self.dive_r = max(0.0, self.dive_r - dt * 3.0)

        # 左门将：头部
        self.lx += inp.xc * 940.0 * dt
        self.lx = U.clamp(self.lx, GOAL_L + 120, MID - 60)
        # 右门将：手（只用横向分量，纵向留给别的手势）
        hx_norm = U.clamp(0.5 + (inp.hx - 0.5) * 1.34, 0.0, 1.0)
        want_rx = MID + 60 + hx_norm * (GOAL_R - 120 - (MID + 60))
        self.rx += (want_rx - self.rx) * min(1.0, dt * 12.0)
        self.rx = U.clamp(self.rx, MID + 60, GOAL_R - 120)
        self.hy = inp.hy
        self.h_open = inp.hand_open
        self.h_found = inp.hand_found
        # 体感：双臂展开时两名门将的覆盖范围都变大（他整个人横过来挡）
        self.wide = bool(inp.arms_wide)
        self.wide_anim += ((1.0 if self.wide else 0.0) - self.wide_anim) \
            * min(1.0, dt * 6.0)

        if self.phase == "aim":
            self.aim_t -= dt
            if self.aim_t <= 0:
                self._shoot()
        elif self.phase == "fly":
            self._update_ball(dt)
        elif self.phase == "result" and self.phase_t > 1.3:
            self._next()

    def _shoot(self):
        side = random.choice(["L", "R"])
        if side == "L":
            tx = random.uniform(GOAL_L + 90, MID - 80)
        else:
            tx = random.uniform(MID + 80, GOAL_R - 90)
        ty = random.uniform(CROSSBAR_Y + 70, GOAL_LINE_Y - 40)
        self.ball = {"x": MID, "y": self.BOT - 120, "tx": tx, "ty": ty, "t": 0.0,
                     "side": side, "rot": random.uniform(-8, 8), "r": 32}
        self.phase = "fly"
        self.phase_t = 0.0
        self.shake(6, 0.2)
        self.particles.emit(MID, self.BOT - 120, 14, color=(226, 232, 240),
                            spread=180, vy=-160, gravity=760, life=0.5, size=5)

    def _update_ball(self, dt: float):
        b = self.ball
        dur = 0.62
        b["t"] += dt / dur
        k = U.clamp(b["t"], 0.0, 1.0)
        e = k * k * (3 - 2 * k)
        b["x"] = U.lerp(MID, b["tx"], e)
        b["y"] = U.lerp(self.BOT - 120, b["ty"], e) - math.sin(e * math.pi) * 108
        b["r"] = U.lerp(32, 17, e)
        if k >= 1.0:
            self._resolve(b)

    def _resolve(self, b):
        self.phase = "result"
        self.phase_t = 0.0
        self.shot_i += 1
        guard_x = self.lx if b["side"] == "L" else self.rx
        d = abs(b["tx"] - guard_x)
        # 门将扑救：正中区域容差更大（身体挡住），边缘要靠扑
        reach = SAVE_R if d < 120 else SAVE_R * 0.72
        reach *= (1.0 + 0.42 * self.wide_anim)      # 双臂展开 → 覆盖更宽
        saved = d < reach
        if saved:
            self.saves += 1
            self.streak += 1
            self.best_streak = max(self.best_streak, self.streak)
            add = 100 + min(120, self.streak * 20)
            self.score += add
            self.history.append("扑出")
            self.flash_side = 1.0
            self.flash((180, 255, 220), 0.24)
            if b["side"] == "L":
                self.dive_l = 1.0
            else:
                self.dive_r = 1.0
            self.set_msg("扑出！", f"+{add}", 1.0, (170, 250, 200))
            self.particles.emit(b["tx"], b["ty"], 24, color=(180, 250, 220),
                                spread=280, vy=-200, gravity=760, life=0.7, size=5.5)
            self.shake(9, 0.3)
        else:
            self.streak = 0
            self.history.append("被进")
            self.set_msg("被进了", f"差 {int(d)} 像素", 1.0, (255, 180, 150))
            self.shake(11, 0.36)
            self.particles.emit(b["tx"], b["ty"], 20, color=(255, 150, 120),
                                spread=260, vy=-180, gravity=820, life=0.7, size=5.5)
        if self.shot_i >= SHOTS:
            self.finish(self.saves >= WIN)

    def _next(self):
        self.ball = None
        self.phase = "aim"
        self.aim_t = random.uniform(0.45, 0.95)
        if self.shot_i < SHOTS:
            self.set_msg(f"第 {self.shot_i + 1} 球", "", 0.7, (216, 240, 255))

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        self._draw_keeper(surf, self.lx, "L", self.dive_l,
                          A.FigureStyle(shirt=(72, 220, 160), shirt2=(24, 40, 60),
                                        pants=(26, 36, 54), skin=(240, 198, 164),
                                        hair=(38, 32, 34), shoes=(240, 240, 80),
                                        number="1"))
        self._draw_keeper(surf, self.rx, "R", self.dive_r,
                          A.FigureStyle(shirt=(96, 168, 240), shirt2=(240, 244, 252),
                                        pants=(26, 36, 54), skin=(242, 202, 168),
                                        hair=(40, 32, 32), shoes=(250, 250, 252),
                                        number="2"))
        if self.ball is not None:
            A.draw_ball(surf, self.ball["x"], self.ball["y"], self.ball["r"],
                        "football", rot=self.ball["rot"] * self.ball["t"] * 4)
        self._draw_side_labels(surf)
        self._draw_hud(surf)
        self.particles.draw(surf)
        self.draw_msg(surf)

    def _draw_keeper(self, surf, x, side, dive, style):
        foot = GOAL_LINE_Y + 6
        lean = max(dive * 0.75, self.wide_anim * 0.40)
        spread = 0.5 + self.wide_anim * 1.05      # 双臂展开时张得更开
        pose = A.pose(lean=lean * 0.9, crouch=0.30,
                      arm_l=-spread - lean * 1.7 if side == "L" else -spread,
                      arm_r=spread + lean * 1.7 if side == "R" else spread,
                      leg_l=-0.22 - lean * 0.4, leg_r=0.22 + lean * 0.4, flip=1)
        spr = A.figure_cached(KEEPER_H, style, pose, ss=3)
        U.aa_ellipse(surf, (int(x - 62), foot - 12, 124, 26), (0, 0, 0, 90), 0, ss=2)
        A.draw_figure(surf, spr, x, foot, 26)
        # 可达范围提示（体感模式下会随双臂展开变宽，玩家能直接看到收益）
        col = (150, 240, 190) if side == "L" else (150, 200, 250)
        half = SAVE_R * (1.0 + 0.42 * self.wide_anim)
        U.aa_line(surf, (x - half, foot + 6), (x + half, foot + 6),
                  (col[0], col[1], col[2], 90), 4)
        if self.wide_anim > 0.2 and side == "L":
            U.text(surf, "双臂展开 · 范围 +42%", (MID, GOAL_LINE_Y - 40), 24,
                   (170, 246, 200), center=True, bold=True,
                   alpha=int(230 * self.wide_anim))

    def _draw_side_labels(self, surf):
        U.text(surf, "头部控制", ((GOAL_L + MID) / 2, 258), 26, (170, 240, 200),
               center=True, bold=True)
        U.text(surf, "手部控制", ((MID + GOAL_R) / 2, 258), 26, (170, 210, 250),
               center=True, bold=True)
        U.aa_line(surf, (MID, CROSSBAR_Y - 40), (MID, GOAL_LINE_Y + 40),
                  (255, 255, 255, 70), 3)

    def _draw_hud(self, surf):
        U.text(surf, f"扑出 {self.saves} / {WIN}　射门 {self.shot_i} / {SHOTS}",
               (self.W // 2, 130), 30, (216, 246, 232), center=True, bold=True,
               glow=10, glow_color=(120, 220, 176))
        for i in range(SHOTS):
            x = self.W // 2 - (SHOTS - 1) * 13 + i * 26
            if i < len(self.history):
                c = (140, 240, 180) if self.history[i] == "扑出" else (250, 130, 110)
            else:
                c = (58, 70, 92)
            U.aa_circle(surf, (x, 176), 9, c, 0, ss=3)
        if self.streak >= 2:
            U.text(surf, f"{self.streak} 连扑！", (self.W // 2, 210), 28,
                   (255, 236, 150), center=True, bold=True, glow=10,
                   glow_color=(255, 210, 120))

    def hud_items(self):
        return [
            ("扑出", f"{self.saves}/{WIN}", (170, 250, 200)),
            ("射门", f"{self.shot_i}/{SHOTS}", (255, 255, 255)),
            ("得分", f"{self.score}", (255, 226, 150)),
            ("连扑", f"{self.streak}", (255, 200, 220)),
        ]

    def result_title(self) -> str:
        return "钢 门 双 保 ！" if self.state == "win" else "球 门 失 守"

    def result_sub(self) -> str:
        return (f"{SHOTS} 球扑出 {self.saves} 个　得分 {self.score}　"
                f"最长连扑 {self.best_streak}")
