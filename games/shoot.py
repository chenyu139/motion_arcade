"""
games/shoot.py
==============
手控射箭 —— 用手掌瞄准靶心，握拳放箭。

手部操作
    · 移动手掌 → 移动准星
    · 握拳     → 放箭（保持手掌不动才能稳住准星）
玩法
    12 箭，按环数计分：红心 100、内环 80、中环 55、外环 30。
    靶心会缓慢漂移，手抖就没高分。
"""
from __future__ import annotations

import math
import random
from typing import List

import pygame

from core import art as A
from core import theme as U
from core import scene as SCN
from core import sprites as SP
from core.base import BaseGame, register
from core.inputs import GameInput

TARGET_C = (1360, 560)
N_ARROWS = 12
RINGS = [(46, 100, "红心"), (86, 80, "内环"), (132, 55, "中环"), (188, 30, "外环")]


@register
class ShootGame(BaseGame):
    KEY = "shoot"
    TITLE = "手控射箭"
    SUB = "掌中准星"
    CATEGORY = "手部控制"
    ACCENT = (150, 208, 120)
    WORLD = "meadow"
    ICON = "bow"
    HOW = "移动手掌瞄准，握拳放箭"
    HINT = "手掌移动准星 · 握拳放箭 · 瞄准要稳"
    DIFFICULTY = 2
    ACHIEVEMENT = f"{N_ARROWS} 箭拿到 800 分"
    REQUIRES = ("hand",)
    MSG_Y = 232
    GOAL = 800

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.shot_i = 0
        self.score = 0
        self.rings = {r[2]: 0 for r in RINGS}
        self.aim = (TARGET_C[0], TARGET_C[1])
        self.sx, self.sy = self.aim
        self.wobble = 0.0
        self.tcx, self.tcy = TARGET_C
        self.drift = (random.uniform(-30, 30), random.uniform(-16, 16))
        self.h_open = 1.0
        self.h_found = True
        self.arrows: List[dict] = []
        self.flying: List[dict] = []
        self.pop: List[dict] = []
        self.cool = 0.0
        self.last_ring = ""
        self.best_ring = "未上靶"
        self.streak = 0
        self.best_streak = 0
        self._bg = self._make_bg()
        self._targets = self._make_targets()
        self.set_msg("第一箭", "掌心瞄准，握拳放箭", 1.5, (216, 244, 200))

    def _make_bg(self) -> pygame.Surface:
        W, H = self.W, self.H
        s = pygame.Surface((W, H))
        SCN.sky_or(s, "sky_day", W, H, (58, 82, 106), (108, 146, 168), (60, 88, 72))
        rng = random.Random(13)
        # 远山
        for _ in range(10):
            x = rng.uniform(-120, W)
            w = rng.uniform(320, 700)
            h = rng.uniform(160, 340)
            U.aa_poly(s, [(x, 700), (x + w * 0.5, 700 - h), (x + w, 700)], (78, 108, 118, 220), 0, ss=2)
        # 草地
        s.blit(A.grass_pitch(W, H - 700, (92, 146, 84), (56, 106, 60), stripes=12), (0, 700))
        # 靶架
        s.blit(A.shade_panel(28, 260, (150, 118, 78), 8),
               (TARGET_C[0] - 14, TARGET_C[1] + 130))
        s.blit(A.shade_panel(28, 260, (150, 118, 78), 8),
               (TARGET_C[0] + 300 - 14, TARGET_C[1] + 130))
        return s

    def _make_targets(self):
        """预烘焙靶面（同心环，最内圈金色靶心）。"""
        R = 196
        size = R * 2

        def _d(s):
            cx = cy = R * 3
            for k in range(len(RINGS) - 1, -1, -1):
                c = (246, 246, 244) if k % 2 == 0 else (232, 88, 76)
                if k == 0:
                    c = (250, 214, 70)
                pygame.draw.circle(s, c, (cx, cy), RINGS[k][0] * 3)
                pygame.draw.circle(s, (60, 50, 44), (cx, cy), RINGS[k][0] * 3, 4)
            # 环线刻度
            for k in range(4):
                for a in range(4):
                    ang = a * math.pi / 2 + math.pi / 4
                    r0 = RINGS[k][0] * 3
                    pygame.draw.line(s, (60, 50, 44),
                                     (cx + math.cos(ang) * r0 * 0.72, cy + math.sin(ang) * r0 * 0.72),
                                     (cx + math.cos(ang) * r0, cy + math.sin(ang) * r0), 4)
        return U.bake(("tgt", 1), (size, size), _d, ss=3)

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        self.cool = max(0.0, self.cool - dt)
        # 靶心缓慢漂移
        self.tcx += self.drift[0] * dt
        self.tcy += self.drift[1] * dt
        if abs(self.tcx - TARGET_C[0]) > 84:
            self.drift = (-self.drift[0], self.drift[1])
        if abs(self.tcy - TARGET_C[1]) > 46:
            self.drift = (self.drift[0], -self.drift[1])

        # 准星跟随手
        tx, ty = self.hand_screen(inp, pygame.Rect(140, self.TOP + 110,
                                                   self.W - 280, self.GAME_H - 200), 1.30)
        self.wobble += dt * 7.0
        # 手掌越张开越稳，握拳前会抖
        wob = 10.0 * (1.0 - U.clamp(inp.hand_open, 0, 1)) + 3.0
        tx += math.sin(self.wobble) * wob
        ty += math.cos(self.wobble * 1.3) * wob
        k = min(1.0, dt * 13.0)
        self.sx += (tx - self.sx) * k
        self.sy += (ty - self.sy) * k
        self.aim = (self.sx, self.sy)
        self.h_open = inp.hand_open
        self.h_found = inp.hand_found

        # 放箭
        if inp.pinch and self.cool <= 0:
            self.cool = 0.6
            self._release()
        if inp.jump and self.cool <= 0:
            self.cool = 0.6
            self._release()

        for a in self.flying:
            a["t"] += dt * 2.6
        for a in self.flying:
            if a["t"] >= 1.0 and not a.get("done"):
                a["done"] = True
                self._land(a)
        self.flying = [a for a in self.flying if a["t"] < 1.6]
        for p in self.pop:
            p["t"] -= dt
            p["y"] -= dt * 52
        self.pop = [p for p in self.pop if p["t"] > 0]

    def _release(self):
        self.shot_i += 1
        self.flying.append({"x0": 260, "y0": self.BOT - 80,
                            "x1": self.aim[0], "y1": self.aim[1], "t": 0.0})
        self.particles.emit(260, self.BOT - 80, 10, color=(230, 236, 246),
                            spread=160, vy=-140, gravity=560, life=0.4, size=4)

    def _land(self, a):
        d = math.hypot(a["x1"] - self.tcx, a["y1"] - self.tcy)
        ring = None
        for radius, val, name in RINGS:
            if d <= radius:
                ring = (val, name)
                break
        if ring is None:
            self.pop.append({"x": a["x1"], "y": a["y1"], "txt": "脱靶", "col": (250, 150, 130), "t": 0.9})
            self.arrows.append(("脱靶", a["x1"], a["y1"]))
            self.streak = 0
            self.last_ring = "脱靶"
            self.shake(6, 0.2)
        else:
            val, name = ring
            self.score += val
            self.rings[name] += 1
            self.streak += 1
            self.best_streak = max(self.best_streak, self.streak)
            self.last_ring = name
            order = ["外环", "中环", "内环", "红心"]
            if self.best_ring not in order or order.index(name) > order.index(self.best_ring):
                self.best_ring = name
            self.pop.append({"x": a["x1"], "y": a["y1"], "txt": f"{name} +{val}",
                             "col": (255, 236, 160) if name != "红心" else (255, 210, 120), "t": 0.9})
            self.arrows.append((name, a["x1"], a["y1"]))
            self.particles.emit(a["x1"], a["y1"], 16, color=(255, 226, 150),
                                spread=240, vy=-180, gravity=780, life=0.6, size=5)
            if name == "红心":
                self.flash((255, 236, 170), 0.28)
                self.shake(8, 0.26)
        self.particles.emit(a["x1"], a["y1"], 8, color=(240, 228, 200),
                            spread=160, vy=-100, gravity=700, life=0.4, size=4)
        if self.shot_i >= N_ARROWS:
            self.finish(self.score >= self.GOAL)
            self.set_msg("射完啦", f"总分 {self.score}", 2.2, (240, 246, 220))

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        # 靶
        surf.blit(self._targets, (int(self.tcx - 196), int(self.tcy - 196)))
        # 已射中的箭
        for name, x, y in self.arrows:
            U.aa_line(surf, (x + 30, y + 46), (x, y), (176, 140, 92), 6)
            U.aa_poly(surf, [(x, y), (x - 14, y - 10), (x - 6, y + 6)],
                      (232, 236, 244), 0, ss=2)
        for a in self.flying:
            if a.get("done"):
                continue
            e = U.ease_out_cubic(min(1.0, a["t"] / 1.0))
            x = U.lerp(a["x0"], a["x1"], e)
            y = U.lerp(a["y0"], a["y1"], e) - math.sin(e * math.pi) * 130
            U.aa_line(surf, (x + 34, y + 12), (x, y), (186, 148, 98), 6)
            U.aa_poly(surf, [(x, y), (x - 14, y - 10), (x - 6, y + 6)], (240, 244, 250), 0, ss=2)
        # 准星
        if self.shot_i < N_ARROWS:
            self._draw_crosshair(surf)
        for p in self.pop:
            U.text(surf, p["txt"], (p["x"], p["y"]), 34, p["col"], center=True,
                   bold=True, glow=10, glow_color=p["col"],
                   alpha=int(255 * min(1, p["t"] * 2.8)))
        self.particles.draw(surf)
        self._draw_hud(surf)
        self.draw_msg(surf)

    def _draw_crosshair(self, surf):
        x, y = self.aim
        col = (255, 240, 190)
        pulse = 0.5 + 0.5 * math.sin(self.t * 6)
        U.aa_circle(surf, (x, y), 30 + pulse * 4, (col[0], col[1], col[2], 220), 4, ss=3)
        for a in range(4):
            ang = a * math.pi / 2
            U.aa_line(surf, (x + math.cos(ang) * 40, y + math.sin(ang) * 40),
                      (x + math.cos(ang) * 62, y + math.sin(ang) * 62), col, 4)
        U.aa_circle(surf, (x, y), 5, (255, 120, 100), 0, ss=3)
        surf.blit(U.glow_surface(70, (255, 236, 170), 54, 7), (int(x - 70), int(y - 70)))
        # 拉弦力度：手掌越收拢越满
        U.bar_gauge(surf, pygame.Rect(int(x - 60), int(y + 74), 120, 12),
                    1.0 - U.clamp(self.h_open, 0, 1), (255, 200, 120), (60, 56, 66), 6)

    def _draw_hud(self, surf):
        U.text(surf, f"第 {min(self.shot_i + 1, N_ARROWS)} / {N_ARROWS} 箭",
               (self.W // 2, 132), 32, (240, 248, 226), center=True, bold=True, glow=10,
               glow_color=(160, 220, 140))
        U.text(surf, f"{self.score} / {self.GOAL} 分", (self.W // 2, 176), 28,
               (255, 236, 180), center=True, bold=True)
        if self.last_ring:
            U.text(surf, f"上一箭：{self.last_ring}", (self.W // 2, 214), 24,
                   (216, 236, 208), center=True)
        # 环数统计
        y = 300
        for i, (r, val, name) in enumerate(reversed(RINGS)):
            U.text(surf, f"{name} {self.rings[name]}", (TARGET_C[0] + 260, y + i * 36),
                   24, (232, 240, 226), center=True)

    def hud_items(self):
        return [
            ("箭数", f"{min(self.shot_i, N_ARROWS)}/{N_ARROWS}", (255, 255, 255)),
            ("得分", f"{self.score}", (255, 236, 180)),
            ("红心", f"{self.rings['红心']}", (255, 200, 120)),
            ("目标", f"{self.GOAL}", (200, 240, 200)),
        ]

    def result_title(self) -> str:
        return "神 射 手 ！" if self.state == "win" else "再 练 练"

    def result_sub(self) -> str:
        return (f"总分 {self.score}（目标 {self.GOAL}）　红心 {self.rings['红心']} 次　"
                f"最长连中 {self.best_streak}")
