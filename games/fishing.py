"""
games/fishing.py
================
岷江捕鱼 —— 江面上撒网捕鱼。

头部操作
    · 左右平移 → 移动渔船与渔网
    · 抬头     → 撒网
玩法
    60 秒内捕到 1600 分。大鱼值钱、小鱼便宜，捞到漂浮垃圾扣 1 条命。
    抬头越高，网撒得越远（落点更靠江心）。
"""
from __future__ import annotations

import math
import random
from typing import List

import pygame

from core import art as A
from core import sichuan as SC
from core import theme as U
from core.base import BaseGame, register
from core.inputs import GameInput

WATER_Y = 430
TIME = 60.0
GOAL = 1600

FISH_KINDS = [
    ("江团", (108, 132, 156), 58, 220),
    ("鲤鱼", (226, 132, 62), 46, 150),
    ("草鱼", (150, 178, 116), 52, 180),
    ("白条", (218, 226, 236), 30, 80),
    ("垃圾", (96, 106, 96), 34, -1),
]


@register
class FishingGame(BaseGame):
    KEY = "fishing"
    TITLE = "岷江捕鱼"
    SUB = "撒网捞江鲜"
    CATEGORY = "头部控制"
    ACCENT = (92, 176, 210)
    ICON = "fish"
    HOW = "把网撒到鱼群上，垃圾别捞"
    HINT = "头部左右移动渔船 · 抬头撒网（越高越远）"
    DIFFICULTY = 2
    ACHIEVEMENT = f"{int(TIME)} 秒内捕到 {GOAL} 分"
    REQUIRES = ("head",)
    MSG_Y = 220

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.left = TIME
        self.score = 0
        self.caught = 0
        self.lives = 3
        self.boat_x = self.W / 2
        self.net_t = 0.0
        self.net_x = self.W / 2
        self.net_splash = 0.0
        self.cool = 0.0
        self.pop: List[dict] = []
        self.fish: List[dict] = []
        self.ripples: List[dict] = []
        self.spawn_t = 0.4
        self.best = 0
        self._bg = self._make_bg()
        self.set_msg("开网", "把网撒到鱼群上", 1.4, (200, 232, 250))

    def _make_bg(self) -> pygame.Surface:
        W, H = self.W, self.H
        s = pygame.Surface((W, H))
        s.blit(U.vgrad3(W, H, (96, 148, 186), (160, 200, 224), (206, 226, 238)), (0, 0))
        rng = random.Random(5)
        # 都江堰 / 乐山大佛 / 三星堆 —— 岷江两岸的四川地标
        # 注意这里必须画到局部变量 s 上：_make_bg 还没返回，self._bg 尚不存在
        s.blit(SC.skyline(W, 230, preset="culture", base=(86, 108, 122),
                          haze=0.48, seed=4, count=5), (0, WATER_Y - 230))
        # 远山
        for _ in range(6):
            x = rng.uniform(-120, W)
            w = rng.uniform(280, 620)
            h = rng.uniform(90, 210)
            U.aa_poly(s, [(x, WATER_Y), (x + w * 0.5, WATER_Y - h), (x + w, WATER_Y)],
                      (128, 150, 158, 210), 0, ss=2)
        # 江水
        water = U.vgrad(W, H - WATER_Y, (52, 104, 132), (28, 66, 92)).copy()
        s.blit(water, (0, WATER_Y))
        # 波纹
        for i in range(70):
            y = WATER_Y + rng.uniform(10, H - WATER_Y - 20)
            x = rng.uniform(0, W)
            w = rng.uniform(60, 260)
            U.aa_line(s, (x, y), (x + w, y), (190, 224, 240, rng.randint(24, 64)),
                      2, ss=2)
        return s

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        self.left -= dt
        self.cool = max(0.0, self.cool - dt)
        self.net_splash = max(0.0, self.net_splash - dt * 1.6)
        if self.left <= 0:
            self.left = 0
            self.finish(self.score >= GOAL)
            self.set_msg("收工", f"捕到 {self.score} 分", 2.0, (210, 236, 252))
            return

        # 船
        self.boat_x += inp.xc * 760.0 * dt
        self.boat_x = U.clamp(self.boat_x, 150, self.W - 150)

        # 撒网
        if inp.action and self.cool <= 0:
            self.cool = 0.55
            self.net_t = 0.55
            self.net_x = self.boat_x
            self._cast()

        # 鱼群
        self.spawn_t -= dt
        if self.spawn_t <= 0:
            self.spawn_t = random.uniform(0.34, 0.72)
            kind = FISH_KINDS[min(len(FISH_KINDS) - 1, random.choices(
                range(len(FISH_KINDS)), weights=[14, 24, 20, 26, 16])[0])]
            d = random.choice([-1, 1])
            self.fish.append({"x": -80 if d > 0 else self.W + 80, "y": WATER_Y + random.uniform(40, 560),
                              "vx": d * random.uniform(70, 210), "spec": kind,
                              "ph": random.uniform(0, 6.28), "alive": True, "sunk": 0.0})
        for f in self.fish:
            if f["alive"]:
                f["x"] += f["vx"] * dt
                f["ph"] += dt * 6
            else:
                f["sunk"] = min(1.0, f["sunk"] + dt * 1.6)
                f["y"] += dt * 90
                f["x"] += f["vx"] * 0.2 * dt
        self.fish = [f for f in self.fish
                     if -200 < f["x"] < self.W + 200 and f["y"] < self.H + 120]

        for p in self.pop:
            p["t"] -= dt
            p["y"] -= dt * 68
        self.pop = [p for p in self.pop if p["t"] > 0]
        for r in self.ripples:
            r["t"] -= dt
            r["r"] += dt * 300
        self.ripples = [r for r in self.ripples if r["t"] > 0]

        if self.net_t > 0:
            self.net_t -= dt

    def _cast(self):
        self.ripples.append({"x": self.net_x, "y": WATER_Y + 300, "r": 30, "t": 0.8})
        self.net_splash = 1.0
        r_net = 210.0
        got = 0
        for f in self.fish:
            if not f["alive"]:
                continue
            if math.hypot(f["x"] - self.net_x, (f["y"] - (WATER_Y + 300)) * 1.6) < r_net:
                f["alive"] = False
                got += 1
                name, col, size, val = f["spec"]
                if val < 0:
                    self.lives -= 1
                    self.pop.append({"x": f["x"], "y": f["y"], "txt": "垃圾！",
                                     "col": (255, 140, 120), "t": 1.1})
                    self.shake(12, 0.4)
                    self.flash((180, 190, 130), 0.3)
                    self.particles.emit(f["x"], f["y"], 20, color=(140, 150, 120),
                                        spread=260, vy=-180, gravity=800, life=0.7, size=5)
                    if self.lives <= 0:
                        self.finish(False)
                        self.set_msg("捞到垃圾", f"捕到 {self.score} 分", 2.2, (255, 190, 170))
                        return
                else:
                    self.score += val
                    self.caught += 1
                    self.best = max(self.best, val)
                    crit = val >= 200
                    self.pop.append({"x": f["x"], "y": f["y"], "txt": f"+{val}" + (" 大货!" if crit else ""),
                                     "col": (255, 232, 160) if crit else (180, 240, 255),
                                     "t": 0.9 if crit else 0.7})
                    self.particles.emit(f["x"], f["y"], 16, color=col, spread=240,
                                        vy=-200, gravity=760, life=0.55, size=5)
                    if crit:
                        self.flash((255, 230, 160), 0.2)
                        self.shake(7, 0.24)
        if got == 0:
            self.pop.append({"x": self.net_x, "y": WATER_Y + 260, "txt": "空网",
                             "col": (200, 216, 232), "t": 0.6})
        if self.score >= GOAL:
            self.finish(True)
            self.flash((255, 244, 210), 0.5)
            self.set_msg("满仓！", f"捕到 {self.score} 分", 2.0, (255, 244, 200))

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        for f in sorted(self.fish, key=lambda d: d["y"]):
            self._draw_fish(surf, f)
        for r in self.ripples:
            a = int(150 * (r["t"] / 0.8))
            U.aa_ellipse(surf, (int(r["x"] - r["r"]), int(r["y"] - r["r"] * 0.36),
                                int(r["r"] * 2), int(r["r"] * 0.72)),
                         (226, 244, 252, a), 4, ss=2)
        self._draw_net(surf)
        self._draw_boat(surf)
        for p in self.pop:
            U.text(surf, p["txt"], (p["x"], p["y"]), 36, p["col"], center=True,
                   bold=True, glow=10, glow_color=p["col"],
                   alpha=int(255 * min(1, p["t"] * 2.6)))
        self.particles.draw(surf)
        self._draw_hud(surf)
        self.draw_msg(surf)

    def _draw_fish(self, surf, f):
        name, col, size, val = f["spec"]
        if f["sunk"] > 0:
            col = U.mix(col, (30, 60, 80), f["sunk"])
        x, y = f["x"], f["y"]
        d = 1 if f["vx"] >= 0 else -1
        s = size / 40.0
        k = 1.0 - f["sunk"] * 0.7
        # 身体
        U.aa_ellipse(surf, (int(x - size * 1.25), int(y - size * 0.56 * k),
                            int(size * 2.5), int(size * 1.12 * k)), col, 0, ss=2)
        # 尾
        U.aa_poly(surf, [(x - d * size * 1.1, y), (x - d * size * 2.0, y - size * 0.72 * k),
                         (x - d * size * 2.0, y + size * 0.72 * k)],
                  U.shade(col, 0.82), 0, ss=2)
        # 背鳍
        U.aa_poly(surf, [(x - d * size * 0.2, y - size * 0.5 * k),
                         (x + d * size * 0.35, y - size * 1.05 * k),
                         (x + d * size * 0.6, y - size * 0.5 * k)], U.shade(col, 0.7), 0, ss=2)
        if k > 0.5:
            U.aa_circle(surf, (x + d * size * 0.62, y - size * 0.16), size * 0.15,
                        (252, 252, 255), 0, ss=2)
            U.aa_circle(surf, (x + d * size * 0.66, y - size * 0.16), size * 0.08,
                        (30, 30, 40), 0, ss=2)
        if val < 0:
            U.text(surf, "✕", (x, y - size * 1.6), 28, (255, 140, 120), center=True, bold=True)

    def _draw_net(self, surf):
        x = self.net_x
        cx, cy = x, WATER_Y + 300
        r = 210 * (0.55 + 0.45 * (1 - self.net_t / 0.55))
        a = int(200 * min(1.0, self.net_t * 3))
        if a <= 4:
            return
        U.aa_ellipse(surf, (int(cx - r), int(cy - r * 0.4), int(r * 2), int(r * 0.8)),
                     (240, 248, 252, a), 5, ss=2)
        for i in range(-3, 4):
            U.aa_line(surf, (cx + i * r / 3.4, cy - r * 0.4 * 0.9),
                      (cx + i * r / 3.4, cy + r * 0.4 * 0.9), (230, 240, 250, a // 2), 2)
        for j in range(-2, 3):
            U.aa_line(surf, (cx - r * 0.94, cy + j * r * 0.16),
                      (cx + r * 0.94, cy + j * r * 0.16), (230, 240, 250, a // 2), 2)

    def _draw_boat(self, surf):
        x = self.boat_x
        y = WATER_Y + 40
        # 船体
        U.aa_poly(surf, [(x - 190, y), (x + 190, y), (x + 148, y + 66), (x - 148, y + 66)],
                  (128, 84, 52), 0, ss=2)
        U.aa_poly(surf, [(x - 170, y + 8), (x + 170, y + 8), (x + 136, y + 56), (x - 136, y + 56)],
                  (162, 110, 68), 0, ss=2)
        # 船篷
        U.aa_poly(surf, [(x - 112, y - 6), (x + 112, y - 6), (x + 84, y - 84), (x - 84, y - 84)],
                  (196, 168, 118), 0, ss=2)
        U.aa_poly(surf, [(x - 84, y - 84), (x + 84, y - 84), (x + 52, y - 118), (x - 52, y - 118)],
                  (156, 130, 88), 0, ss=2)
        # 渔夫
        pose = A.pose(lean=0.2, arm_l=-1.5, arm_r=-1.3, leg_l=-0.3, leg_r=0.3, crouch=0.35)
        spr = A.figure_cached(148, A.FigureStyle(
            shirt=(84, 132, 186), shirt2=(240, 244, 250), pants=(48, 56, 72),
            skin=(238, 196, 162), hair=(44, 36, 32), shoes=(72, 58, 44),
            hair_style="short"), pose, ss=3)
        A.draw_figure(surf, spr, x + 60, y + 4, 26)
        # 撑杆
        U.aa_line(surf, (x - 176, y - 40), (x - 236, y + 96), (176, 138, 92), 9)
        self.particles.emit(x - 160, y + 62, 1, color=(226, 240, 250), spread=200,
                            vy=-120, gravity=520, life=0.7, size=4)

    def _draw_hud(self, surf):
        bar = pygame.Rect(self.W // 2 - 280, 128, 560, 18)
        U.bar_gauge(surf, bar, min(1.0, self.score / GOAL), self.ACCENT, (40, 66, 86), 9)
        U.text(surf, f"{self.score} / {GOAL} 分　剩余 {int(self.left)}s", (self.W // 2, 158), 26,
               (232, 244, 252), center=True, bold=True, shadow=3, shadow_color=(30, 60, 80))
        for i in range(3):
            cx = self.W - 72 - i * 52
            col = (255, 130, 120) if i < self.lives else (130, 150, 168)
            U.aa_circle(surf, (cx - 11, 66), 12, col, 0, ss=3)
            U.aa_circle(surf, (cx + 11, 66), 12, col, 0, ss=3)
            U.aa_poly(surf, [(cx - 23, 70), (cx + 23, 70), (cx, 96)], col, 0, ss=3)

    def hud_items(self):
        return [
            ("得分", f"{self.score}", (255, 255, 255)),
            ("目标", f"{GOAL}", (255, 226, 150)),
            ("渔获", f"{self.caught}", (180, 240, 255)),
            ("剩余", f"{int(self.left)}s", (210, 236, 252)),
        ]

    def result_title(self) -> str:
        return "满 载 而 归 ！" if self.state == "win" else "空 手 而 返"

    def result_sub(self) -> str:
        return f"捕到 {self.score} 分（{self.caught} 条）　目标 {GOAL}"
