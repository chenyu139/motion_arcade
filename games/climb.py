"""
games/climb.py
==============
蜀道攀岩 —— 剑门关栈道式岩壁攀爬。

头部操作
    · 左右平移 → 横向挪动身体，够到相邻的抓点
    · 抬头     → 向上抓握（必须抓点在你的横向范围内，否则脱手）
玩法
    爬到崖顶（20 段）即通关。体力随时间下降，踩中"落脚点"可以恢复；
    上方会掉落碎石，被砸中直接脱手。
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

HOLDS = 22                # 抓点层数
HOLD_DY = 132
WALL_L, WALL_R = 320, 1600
PLAYER_Y = 806
GRAB_TOL = 178            # 抬头抓握的横向容差


@register
class ClimbGame(BaseGame):
    KEY = "climb"
    TITLE = "蜀道攀岩"
    SUB = "剑门关崖壁"
    CATEGORY = "头部控制"
    ACCENT = (196, 168, 120)
    ICON = "climb"
    HOW = "左右挪到抓点下方，抬头向上抓，别被碎石砸中"
    HINT = "头部左右挪动 · 抬头抓握 · 站稳落脚点回体力"
    DIFFICULTY = 3
    ACHIEVEMENT = f"爬到崖顶（{HOLDS} 段）"
    REQUIRES = ("head",)
    MSG_Y = 232

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.holds: List[dict] = []
        rng = random.Random(17)
        for i in range(HOLDS + 6):
            if i == 0:
                x = (WALL_L + WALL_R) / 2
                kind = "rest"
            else:
                x = rng.uniform(WALL_L + 40, WALL_R - 40)
                kind = "rest" if i % 5 == 0 else ("slope" if rng.random() < 0.3 else "hold")
            self.holds.append({"x": x, "y": -i * HOLD_DY + PLAYER_Y, "kind": kind,
                               "shake": 0.0})
        self.idx = 0
        self.px = self.holds[0]["x"]
        self.py = self.holds[0]["y"]
        self.cam = 0.0
        self.stamina = 1.0
        self.height = 0
        self.score = 0
        self.hit_cd = 0.0
        self.rocks: List[dict] = []
        self.hand_cd = 0.0
        self.best = 0
        self.climb_anim = 0.0
        self.reach = None
        self._bg = self._make_wall()
        self.set_msg("向上爬", "抬头抓握，别掉下去", 1.6, (240, 226, 190))

    def _make_wall(self) -> pygame.Surface:
        """把整面岩壁烘焙成一张长图（静态，只生成一次）。"""
        H = HOLDS * HOLD_DY + 900
        W = self.W
        s = pygame.Surface((W, H))
        base = U.vgrad3(W, H, (58, 48, 42), (74, 62, 52), (44, 36, 32))
        s.blit(base, (0, 0))
        rng = random.Random(4)
        # 岩壁质感：块状色斑
        for _ in range(1400):
            x = rng.uniform(0, W)
            y = rng.uniform(0, H)
            w = rng.uniform(24, 120)
            h = rng.uniform(16, 70)
            c = U.shade((82, 70, 58), rng.uniform(0.62, 1.34))
            pygame.draw.rect(s, c, pygame.Rect(int(x), int(y), int(w), int(h)),
                             border_radius=6)
        # 裂缝
        for _ in range(70):
            x = rng.uniform(0, W)
            y = rng.uniform(0, H)
            pts = [(x, y)]
            for k in range(6):
                x += rng.uniform(-46, 46)
                y += rng.uniform(20, 66)
                pts.append((x, y))
            pygame.draw.lines(s, (34, 28, 24), False, pts, rng.randint(2, 5))
        # 两侧暗部
        U.aa_poly(s, [(0, 0), (WALL_L - 90, 0), (WALL_L - 190, H), (0, H)], (22, 18, 16), 0, ss=1)
        U.aa_poly(s, [(W, 0), (WALL_R + 90, 0), (WALL_R + 190, H), (W, H)], (22, 18, 16), 0, ss=1)
        # 抓点
        for i, h in enumerate(self.holds):
            self._paint_hold(s, h)
        # 顶部旗帜
        top = self.holds[HOLDS - 1]
        return s

    @staticmethod
    def _paint_hold(s, h):
        x, y, kind = h["x"], h["y"], h["kind"]
        if kind == "rest":
            U.aa_ellipse(s, (int(x - 76), int(y - 24), 152, 48), (108, 168, 108), 0, ss=2)
            U.aa_ellipse(s, (int(x - 62), int(y - 16), 124, 30), (140, 204, 132), 0, ss=2)
        elif kind == "slope":
            U.aa_poly(s, [(x - 82, y + 30), (x + 82, y + 30), (x + 44, y - 26), (x - 44, y - 26)],
                      (150, 132, 104), 0, ss=2)
            U.aa_poly(s, [(x - 60, y + 20), (x + 60, y + 20), (x + 30, y - 14), (x - 30, y - 14)],
                      (184, 166, 132), 0, ss=2)
        else:
            U.aa_circle(s, (x, y), 30, (128, 116, 92), 0, ss=2)
            U.aa_circle(s, (x - 5, y - 6), 22, (176, 162, 128), 0, ss=2)
            U.aa_arc(s, (x, y), 30, (72, 62, 48), 0, math.tau, 4)

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        self.hit_cd = max(0.0, self.hit_cd - dt)
        self.hand_cd = max(0.0, self.hand_cd - dt)
        self.climb_anim = max(0.0, self.climb_anim - dt * 2.6)

        # 体力
        hanging = True
        drain = 0.070
        on_rest = self.holds[self.idx]["kind"] == "rest" and abs(self.px - self.holds[self.idx]["x"]) < 70
        if on_rest:
            drain = -0.16
        self.stamina = U.clamp(self.stamina - drain * dt, 0.0, 1.0)
        if self.stamina <= 0:
            self._fall("体力耗尽")
            return

        # 横向挪动
        self.px += inp.xc * 330.0 * dt
        self.px = U.clamp(self.px, WALL_L - 60, WALL_R + 60)

        # 抬头抓握
        if inp.action and self.hand_cd <= 0:
            self.hand_cd = 0.32
            self._grab()

        # 碎石
        if random.random() < 0.020 + self.height * 0.0032:
            hx = random.uniform(WALL_L - 40, WALL_R + 40)
            self.rocks.append({"x": hx, "y": self.py - 720, "vy": random.uniform(210, 380),
                               "r": random.uniform(12, 30), "rot": 0.0})
        for r in self.rocks:
            r["y"] += r["vy"] * dt
            r["vy"] += 260 * dt
            r["rot"] += dt * 2.4
        for r in self.rocks:
            if abs(r["x"] - self.px) < 44 + r["r"] and abs(r["y"] - self.py) < 70 and self.hit_cd <= 0:
                self._fall("被碎石砸中")
                return
        self.rocks = [r for r in self.rocks if r["y"] < self.py + 900]

        # 摄像机与得分
        want = self.py - (self.TOP + 560)
        self.cam += (want - self.cam) * min(1.0, dt * 4.2)
        self.height = max(self.height, self.idx)
        self.best = max(self.best, self.idx)

        if self.idx >= HOLDS - 1:
            self.finish(True)
            self.flash((255, 244, 200), 0.5)
            self.set_msg("登顶！", f"爬了 {self.idx} 段", 2.0, (250, 240, 200))

    def _grab(self):
        """抬头：找上方最近的抓点，横向够得到就抓上，够不到就脱手。"""
        nxt = self.idx + 1
        if nxt >= len(self.holds):
            return
        tgt = self.holds[nxt]
        dx = abs(tgt["x"] - self.px)
        self.reach = {"x": tgt["x"], "y": tgt["y"], "t": 0.4}
        if dx <= GRAB_TOL:
            self.idx = nxt
            self.py = tgt["y"]
            self.px += (tgt["x"] - self.px) * 0.72
            self.climb_anim = 1.0
            add = 60 + (40 if tgt["kind"] == "rest" else 0)
            self.score += add
            self.stamina = U.clamp(self.stamina + 0.10, 0, 1)
            tgt["shake"] = 0.35
            self.particles.emit(tgt["x"], tgt["y"], 10, color=(226, 208, 160),
                                spread=170, vy=-90, gravity=620, life=0.45, size=4)
            self.shake(3, 0.10)
        else:
            self._fall("手够不到那个点")

    def _fall(self, why: str):
        self.state = "over"
        self.shake(18, 0.6)
        self.flash((255, 180, 140), 0.42)
        self.particles.emit(self.px, self.py, 30, color=(216, 200, 168),
                            spread=340, vy=-180, gravity=900, life=0.9, size=6)
        self.set_msg("脱手了！", f"{why}　爬到 {self.idx} 段", 2.2, (255, 200, 170))

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        cam = int(self.cam)
        surf.blit(self._bg, (0, -cam))
        # 碎石
        for r in self.rocks:
            y = r["y"] - cam
            if y < self.TOP - 60 or y > self.H:
                continue
            surf.blit(A.shade_ball(r["r"], (108, 100, 88), ss=2),
                      (int(r["x"] - r["r"]), int(y - r["r"])))
        # 抓点发光提示
        nxt = self.idx + 1
        if nxt < len(self.holds):
            t = self.holds[nxt]
            y = t["y"] - cam
            if self.TOP < y < self.H:
                pulse = 0.5 + 0.5 * math.sin(self.t * 5.4)
                reachable = abs(t["x"] - self.px) <= GRAB_TOL
                col = (150, 240, 180) if reachable else (250, 140, 120)
                U.aa_circle(surf, (t["x"], y), 48 + pulse * 5, (col[0], col[1], col[2], 130), 4, ss=3)
                if reachable:
                    surf.blit(U.glow_surface(80, col, int(46 + 40 * pulse), 7),
                              (int(t["x"] - 80), int(y - 80)))
        self._draw_climber(surf, cam)
        if self.reach is not None:
            self.reach["t"] -= 1 / 60
            if self.reach["t"] <= 0:
                self.reach = None
            else:
                y = self.reach["y"] - cam
                a = max(0, min(255, int(200 * min(1.0, self.reach["t"] * 3))))
                U.aa_circle(surf, (self.reach["x"], y), 56, (255, 236, 180, a), 3, ss=2)
        self._draw_gauges(surf)
        self.particles.draw(surf)
        self.draw_vignette(surf, 130)
        self.draw_msg(surf)

    def _draw_climber(self, surf, cam):
        y = self.py - cam
        reach = 1.0 - self.climb_anim
        pose = A.pose(lean=0.14, arm_l=-2.7 + reach * 0.7, arm_l2=-0.2,
                      arm_r=-2.5 + reach * 0.6, arm_r2=-0.3,
                      leg_l=-0.30 + reach * 0.2, leg_l2=0.62,
                      leg_r=0.34 - reach * 0.2, leg_r2=0.55, crouch=0.16, flip=1)
        spr = A.figure_cached(206, A.FigureStyle(
            shirt=(228, 132, 62), shirt2=(250, 240, 210), pants=(52, 58, 78),
            skin=(242, 200, 166), hair=(40, 32, 30), shoes=(72, 62, 50),
            hair_style="helm", number=""), pose, ss=3)
        A.draw_figure(surf, spr, self.px, y + 120, 26)

    def _draw_gauges(self, surf):
        # 体力
        bar = pygame.Rect(70, 132, 340, 20)
        U.text(surf, "体力", (70, 100), 24, (240, 226, 200), bold=True)
        col = (150, 236, 180) if self.stamina > 0.35 else (255, 150, 120)
        U.bar_gauge(surf, bar, self.stamina, col, (46, 40, 36), 10)
        # 高度
        hb = pygame.Rect(70, 216, 340, 20)
        U.text(surf, f"高度 {self.idx} / {HOLDS - 1} 段", (70, 184), 24, (240, 226, 200), bold=True)
        U.bar_gauge(surf, hb, self.idx / max(1, HOLDS - 1), (250, 214, 130), (46, 40, 36), 10)
        # 可达提示
        nxt = self.idx + 1
        if nxt < len(self.holds):
            d = abs(self.holds[nxt]["x"] - self.px)
            ok = d <= GRAB_TOL
            U.text(surf, "抓点已在范围内，抬头！" if ok else "先挪到抓点下方",
                   (self.W // 2, self.BOT - 66), 28,
                   (150, 240, 180) if ok else (250, 180, 140), center=True, bold=True,
                   shadow=3)

    def hud_items(self):
        return [
            ("高度", f"{self.idx} 段", (255, 255, 255)),
            ("得分", f"{self.score}", (255, 226, 130)),
            ("体力", f"{int(self.stamina * 100)}%", (150, 236, 180)),
        ]

    def result_title(self) -> str:
        return "登 顶 成 功 ！" if self.state == "win" else "脱 手 坠 落"

    def result_sub(self) -> str:
        return f"爬到第 {self.idx} 段　得分 {self.score}"
