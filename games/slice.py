"""
games/slice.py
==============
川果切切 —— 用手掌劈开飞起的水果。

手部操作
    · 手掌快速划过水果 → 切开（速度不够只能把水果推歪）
玩法
    60 秒内切到 2200 分。切到花椒炸弹扣 1 条命，水果掉出画面也扣分。
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

TIME = 60.0
GOAL = 2200
FLOOR = 1010

FRUITS = [
    ("橙子", (240, 152, 56), 58, 120),
    ("猕猴桃", (168, 196, 92), 52, 130),
    ("蜜桃", (248, 158, 150), 56, 140),
    ("西瓜", (86, 178, 96), 76, 180),
    ("枇杷", (246, 190, 76), 44, 100),
    ("花椒", (108, 74, 52), 50, -1),
]

# 每种水果对应的 AI 生成精灵（缺图时回退到程序绘制）
_FRUIT_SPRITE = {
    "橙子": "fruit", "猕猴桃": "kiwi", "蜜桃": "peach",
    "西瓜": "watermelon", "枇杷": "loquat", "花椒": "pepper",
}


@register
class SliceGame(BaseGame):
    KEY = "slice"
    TITLE = "川果切切"
    SUB = "手掌劈果"
    CATEGORY = "手部控制"
    ACCENT = (246, 176, 76)
    WORLD = "teahouse"
    ICON = "fruit"
    HOW = "挥手劈开飞起来的水果，别切到花椒"
    HINT = "手掌快速划过水果才能切开 · 花椒扣命"
    DIFFICULTY = 2
    ACHIEVEMENT = f"{int(TIME)} 秒内切到 {GOAL} 分"
    REQUIRES = ("hand",)
    MSG_Y = 236

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.left = TIME
        self.score = 0
        self.cut = 0
        self.lives = 3
        self.combo = 0
        self.best_combo = 0
        self.hx = self.W / 2
        self.hy = self.BOT - 300
        self.phx, self.phy = self.hx, self.hy
        self.trail: List[tuple] = []
        self.h_open = 1.0
        self.h_found = True
        self.items: List[dict] = []
        self.halves: List[dict] = []
        self.spawn_t = 0.5
        self.pop: List[dict] = []
        self._bg = self._make_bg()
        self.set_msg("开始", "挥手切果", 1.3, (255, 236, 180))

    def _make_bg(self) -> pygame.Surface:
        W, H = self.W, self.H
        s = pygame.Surface((W, H))
        SCN.sky_or(s, "sky_teahouse", W, H, (34, 40, 56), (58, 68, 92), (30, 34, 48))
        # 案板
        s.blit(A.shade_panel(W, 180, (128, 92, 62), 0, 1.1, 0.7), (0, FLOOR))
        rng = random.Random(11)
        for _ in range(60):
            x, y = rng.uniform(0, W), rng.uniform(FLOOR, H)
            w, h = rng.uniform(40, 140), rng.uniform(3, 7)
            s.fill(U.shade((108, 76, 50), rng.uniform(0.8, 1.2)),
                   (int(x), int(y), int(w), int(h)))
        U.aa_line(s, (0, FLOOR), (W, FLOOR), (170, 132, 92), 5)
        return s

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        self.left -= dt
        if self.left <= 0:
            self.left = 0
            self.finish(self.score >= GOAL)
            self.set_msg("时间到", f"切到 {self.score} 分", 2.0, (255, 240, 210))
            return

        tx, ty = self.hand_screen(inp, pygame.Rect(110, self.TOP + 120,
                                                   self.W - 220, self.GAME_H - 200), 1.36)
        self.phx, self.phy = self.hx, self.hy
        self.hx += (tx - self.hx) * min(1.0, dt * 18.0)
        self.hy += (ty - self.hy) * min(1.0, dt * 18.0)
        self.h_open = inp.hand_open
        self.h_found = inp.hand_found
        vx = (self.hx - self.phx) / max(1e-4, dt)
        vy = (self.hy - self.phy) / max(1e-4, dt)
        self.trail.append((self.hx, self.hy))
        if len(self.trail) > 10:
            self.trail.pop(0)

        # 出手
        self.spawn_t -= dt
        if self.spawn_t <= 0:
            self.spawn_t = random.uniform(0.72, 1.25)
            n = 1 if random.random() < 0.72 else 2
            for _ in range(n):
                spec = random.choice(FRUITS)
                x = random.uniform(260, self.W - 260)
                self.items.append({
                    "x": x, "y": FLOOR - 40, "vx": (self.W / 2 - x) * random.uniform(0.5, 0.9),
                    "vy": random.uniform(-1420, -1160), "spec": spec,
                    "rot": random.uniform(0, 6.28), "spin": random.uniform(-4, 4),
                    "dead": False, "cut": False})

        for it in self.items:
            it["vy"] += 1500 * dt
            it["x"] += it["vx"] * dt
            it["y"] += it["vy"] * dt
            it["rot"] += it["spin"] * dt
        for h in self.halves:
            h["vy"] += 1700 * dt
            h["x"] += h["vx"] * dt
            h["y"] += h["vy"] * dt
            h["rot"] += h["spin"] * dt
            h["t"] -= dt

        # 切割判定
        speed = math.hypot(vx, vy)
        if speed > 480 and self.h_found:
            for it in self.items:
                if it["dead"]:
                    continue
                if math.hypot(it["x"] - self.hx, it["y"] - self.hy) < it["spec"][2] * 1.1 + 60:
                    self._cut_item(it, vx, vy)

        for it in self.items:
            if not it["dead"] and it["y"] > FLOOR + 40:
                it["dead"] = True
                if it["spec"][3] > 0:
                    self.combo = 0
        self.items = [it for it in self.items if not it["dead"] or it.get("fly", 0) < 0.5]
        self.halves = [h for h in self.halves if h["t"] > 0 and h["y"] < self.H + 200]

        for p in self.pop:
            p["t"] -= dt
            p["y"] -= dt * 60
        self.pop = [p for p in self.pop if p["t"] > 0]

    def _cut_item(self, it, vx, vy):
        it["dead"] = True
        it["fly"] = 1.0
        name, col, size, val = it["spec"]
        ang = math.atan2(vy, vx)
        if val < 0:
            self.lives -= 1
            self.combo = 0
            self.shake(14, 0.45)
            self.flash((255, 110, 90), 0.4)
            self.pop.append({"x": it["x"], "y": it["y"], "txt": "花椒！", "col": (255, 150, 130), "t": 1.1})
            self.particles.emit(it["x"], it["y"], 26, color=(150, 110, 80),
                                spread=320, vy=-220, gravity=900, life=0.8, size=6)
            if self.lives <= 0:
                self.finish(False)
                self.set_msg("切到花椒了", f"切到 {self.score} 分", 2.2, (255, 190, 170))
            return
        self.cut += 1
        self.combo += 1
        self.best_combo = max(self.best_combo, self.combo)
        mult = 1.0 + min(1.5, self.combo * 0.08)
        add = int(val * mult)
        self.score += add
        self.pop.append({"x": it["x"], "y": it["y"], "txt": f"+{add}" + (" 连切!" if self.combo >= 4 else ""),
                         "col": (255, 240, 170), "t": 0.7})
        self.particles.emit(it["x"], it["y"], 18, color=col, spread=280,
                            vy=-180, gravity=800, life=0.6, size=5)
        self.shake(4, 0.12)
        # 两个半块
        for sgn in (-1, 1):
            self.halves.append({"x": it["x"], "y": it["y"], "spec": it["spec"],
                                "vx": math.cos(ang + math.pi / 2) * 300 * sgn,
                                "vy": math.sin(ang + math.pi / 2) * 300 * sgn - 260,
                                "rot": 0.0, "spin": random.uniform(-6, 6),
                                "t": 0.95, "side": sgn})
        if self.score >= GOAL:
            self.finish(True)
            self.flash((255, 246, 210), 0.5)
            self.set_msg("果盘满上！", f"切到 {self.score} 分", 2.0, (255, 246, 210))

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        for h in self.halves:
            self._draw_half(surf, h)
        for it in self.items:
            if it["dead"]:
                continue
            self._draw_fruit(surf, it)
        self._draw_trail(surf)
        self.draw_hand(surf, (self.hx, self.hy), self.h_open, self.h_found)
        for p in self.pop:
            U.text(surf, p["txt"], (p["x"], p["y"]), 34, p["col"], center=True,
                   bold=True, glow=10, glow_color=p["col"],
                   alpha=int(255 * min(1, p["t"] * 2.8)))
        self.particles.draw(surf)
        self._draw_hud(surf)
        self.draw_msg(surf)

    def _draw_trail(self, surf):
        if len(self.trail) < 2:
            return
        for i in range(1, len(self.trail)):
            a = int(180 * i / len(self.trail))
            x0, y0 = self.trail[i - 1]
            x1, y1 = self.trail[i]
            U.aa_line(surf, (x0, y0), (x1, y1), (255, 250, 220, a), 4 + i // 3)

    def _draw_fruit(self, surf, it):
        name, col, size, val = it["spec"]
        x, y = it["x"], it["y"]
        spr = _FRUIT_SPRITE.get(name)
        if spr and SP.draw(surf, spr, x, y, height=size * 1.15, anchor="center"):
            if val < 0:
                U.text(surf, "✕", (x, y - size * 1.9), 30, (255, 150, 130),
                       center=True, bold=True)
            return
        # 回退：程序绘制
        r = size * 0.5
        surf.blit(A.shade_ball(r, col, ss=2), (int(x - r), int(y - r)))
        if name == "西瓜":
            U.aa_arc(surf, (x, y), r * 0.86, (36, 96, 48), 0, math.tau, 5)
        elif name == "猕猴桃":
            U.aa_circle(surf, (x, y), r * 0.42, (120, 150, 66), 0, ss=2)
        elif name == "花椒":
            for k in range(5):
                a = k * math.tau / 5
                U.aa_circle(surf, (x + math.cos(a) * r * 0.5, y + math.sin(a) * r * 0.5),
                            r * 0.34, (76, 52, 36), 0, ss=2)
            U.text(surf, "!", (x, y - r * 1.9), 30, (255, 150, 130), center=True, bold=True)
        else:
            U.aa_circle(surf, (x - r * 0.3, y - r * 0.26), r * 0.22, U.shade(col, 1.34), 0, ss=2)

    def _draw_half(self, surf, h):
        name, col, size, val = h["spec"]
        r = size * 0.5
        sp = A.shade_ball(r, col, ss=2)
        sp = pygame.transform.rotate(sp, math.degrees(h["rot"]))
        a = int(255 * min(1.0, h["t"] * 2.2))
        sp.set_alpha(a)
        surf.blit(sp, (int(h["x"] - sp.get_width() / 2), int(h["y"] - sp.get_height() / 2)))

    def _draw_hud(self, surf):
        bar = pygame.Rect(self.W // 2 - 280, 126, 560, 18)
        U.bar_gauge(surf, bar, min(1.0, self.score / GOAL), self.ACCENT, (48, 48, 62), 9)
        U.text(surf, f"{self.score} / {GOAL} 分　剩余 {int(self.left)}s", (self.W // 2, 156), 26,
               (255, 244, 214), center=True, bold=True, shadow=3)
        for i in range(3):
            cx = self.W - 72 - i * 52
            col = (255, 130, 120) if i < self.lives else (86, 84, 96)
            U.aa_circle(surf, (cx - 11, 66), 12, col, 0, ss=3)
            U.aa_circle(surf, (cx + 11, 66), 12, col, 0, ss=3)
            U.aa_poly(surf, [(cx - 23, 70), (cx + 23, 70), (cx, 96)], col, 0, ss=3)

    def hud_items(self):
        return [
            ("得分", f"{self.score}", (255, 255, 255)),
            ("目标", f"{GOAL}", (255, 226, 150)),
            ("连切", f"x{self.combo}", (180, 240, 255)),
            ("剩余", f"{int(self.left)}s", (255, 214, 180)),
        ]

    def result_title(self) -> str:
        return "大 丰 收 ！" if self.state == "win" else "切 到 花 椒 了"

    def result_sub(self) -> str:
        return f"切到 {self.score} 分（{self.cut} 个）　最长连切 {self.best_combo}"
