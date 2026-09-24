"""
games/handcatch.py
==================
手抓青铜 —— 用手心接住从三星堆祭坛上落下的青铜器。

手部操作
    · 移动手掌 → 控制手心光标
    · 张开手掌 → 稳稳接住（手心朝上）
    · 握拳       → 手掌变成拳头，碰到器物会把它打飞
玩法
    接住 16 件青铜器即通关，漏掉 5 件出局。金面具最值钱但下落最快。
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
TARGET = 16
MISS_LIMIT = 5

KINDS = [
    ("青铜面具", (108, 152, 118), 66, 120, 300),
    ("金杖", (226, 186, 82), 54, 150, 360),
    ("太阳轮", (196, 154, 76), 60, 120, 320),
    ("玉琮", (198, 212, 196), 48, 110, 260),
    ("陶盉", (170, 128, 96), 56, 90, 220),
]


@register
class HandCatchGame(BaseGame):
    KEY = "handcatch"
    TITLE = "手抓青铜"
    SUB = "三星堆祭祀坑"
    CATEGORY = "手部控制"
    ACCENT = (176, 196, 120)
    ICON = "hand"
    HOW = "张开手掌接住落下的青铜器，握拳会打飞"
    HINT = "移动手掌接物 · 保持张开 · 握拳会撞飞"
    DIFFICULTY = 2
    ACHIEVEMENT = f"接住 {TARGET} 件青铜器"
    REQUIRES = ("hand",)
    MSG_Y = 224

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.left = TIME
        self.got = 0
        self.miss = 0
        self.score = 0
        self.combo = 0
        self.best_combo = 0
        self.items: List[dict] = []
        self.spawn_t = 0.5
        self.hx = self.W / 2
        self.hy = self.BOT - 190
        self.h_open = 1.0
        self.h_found = True
        self.pop: List[dict] = []
        self.catch_flash = 0.0
        self.difficulty = 0.0
        self._bg = self._make_bg()
        self.set_msg("准备接住", "张开手掌", 1.4, (226, 240, 200))

    def _make_bg(self) -> pygame.Surface:
        W, H = self.W, self.H
        s = pygame.Surface((W, H))
        s.blit(U.vgrad3(W, H, (26, 34, 30), (48, 60, 50), (22, 28, 26)), (0, 0))
        rng = random.Random(9)
        # 祭祀坑壁
        for _ in range(700):
            x, y = rng.uniform(0, W), rng.uniform(0, H)
            w, h = rng.uniform(20, 90), rng.uniform(14, 54)
            c = U.shade((58, 70, 58), rng.uniform(0.62, 1.3))
            pygame.draw.rect(s, c, pygame.Rect(int(x), int(y), int(w), int(h)), border_radius=4)
        # 顶部光柱
        s.blit(U.light_cone(880, 900, (255, 240, 190), 0.24, 42), (int(W / 2 - 440), self.TOP))
        # 祭坛地面
        s.blit(A.shade_panel(W, 240, (74, 62, 48), 0, 1.06, 0.68), (0, H - 240))
        for i in range(14):
            x = i * (W / 13.0)
            U.aa_line(s, (x, H - 240), (x, H), (58, 48, 36), 4)
        U.aa_line(s, (0, H - 240), (W, H - 240), (110, 96, 72), 5)
        return s

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        self.left -= dt
        self.difficulty = 1.0 - self.left / TIME
        self.catch_flash = max(0.0, self.catch_flash - dt * 2.6)
        if self.left <= 0:
            self.left = 0
            self.finish(self.got >= TARGET)
            self.set_msg("时间到", f"接住 {self.got} 件", 2.0, (232, 244, 210))
            return

        # 手部光标
        tx, ty = self.hand_screen(inp, pygame.Rect(110, self.TOP + 160,
                                                   self.W - 220, self.GAME_H - 280), 1.32)
        self.hx += (tx - self.hx) * min(1.0, dt * 15.0)
        self.hy += (ty - self.hy) * min(1.0, dt * 15.0)
        self.h_open = inp.hand_open
        self.h_found = inp.hand_found

        # 生成
        self.spawn_t -= dt
        if self.spawn_t <= 0:
            self.spawn_t = random.uniform(0.62, 1.05) * (1.0 - self.difficulty * 0.38)
            spec = random.choices(KINDS, weights=[26, 12, 16, 22, 24])[0]
            self.items.append({"x": random.uniform(200, self.W - 200), "y": self.TOP + 60,
                               "vy": spec[3] * random.uniform(0.9, 1.15) * (1 + self.difficulty * 0.5),
                               "spec": spec, "rot": random.uniform(0, 6.28),
                               "dead": False, "fly": 0.0})

        for it in self.items:
            if it["dead"]:
                it["fly"] = min(1.0, it["fly"] + dt * 2.4)
                it["x"] += it.get("fvx", 0) * dt
                it["y"] -= dt * 420
                it["rot"] += dt * 5
                continue
            it["y"] += it["vy"] * dt
            it["rot"] += dt * 0.9

        # 接触判定
        r_hand = 92
        for it in self.items:
            if it["dead"]:
                continue
            d = math.hypot(it["x"] - self.hx, it["y"] - self.hy)
            if d < r_hand + it["spec"][2] * 0.5:
                it["dead"] = True
                it["fvx"] = (it["x"] - self.hx) * 2.4
                if self.h_found and self.h_open > 0.48:
                    self.got += 1
                    self.combo += 1
                    self.best_combo = max(self.best_combo, self.combo)
                    bonus = min(120, self.combo * 20)
                    add = it["spec"][4] + bonus
                    self.score += add
                    self.catch_flash = 1.0
                    self.pop.append({"x": it["x"], "y": it["y"], "txt": f"+{add}",
                                     "col": (255, 236, 160), "t": 0.8})
                    self.particles.emit(it["x"], it["y"], 18, color=(240, 224, 150),
                                        spread=260, vy=-200, gravity=760, life=0.6, size=5)
                    self.shake(5, 0.16)
                    if self.got >= TARGET:
                        self.finish(True)
                        self.flash((255, 246, 210), 0.5)
                        self.set_msg("祭坑满仓！", f"接住 {self.got} 件", 2.0, (255, 244, 220))
                        return
                else:
                    self.combo = 0
                    self.pop.append({"x": it["x"], "y": it["y"], "txt": "打飞了",
                                     "col": (255, 176, 140), "t": 0.7})
                    self.shake(6, 0.2)
            elif it["y"] > self.BOT - 60:
                it["dead"] = True
                it["fvx"] = 0
                self.miss += 1
                self.combo = 0
                self.pop.append({"x": it["x"], "y": self.BOT - 120, "txt": "漏了",
                                 "col": (255, 150, 130), "t": 0.9})
                self.shake(9, 0.3)
                self.flash((255, 130, 110), 0.22)
                if self.miss >= MISS_LIMIT:
                    self.finish(False)
                    self.set_msg("摔碎太多", f"接住 {self.got} 件", 2.0, (255, 190, 170))
                    return
        self.items = [it for it in self.items if it["fly"] < 1.0 and it["y"] < self.H + 200]

        for p in self.pop:
            p["t"] -= dt
            p["y"] -= dt * 54
        self.pop = [p for p in self.pop if p["t"] > 0]

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        for it in self.items:
            self._draw_item(surf, it)
        self.draw_hand(surf, (self.hx, self.hy), self.h_open, self.h_found,
                       "张开 · 接住" if self.h_open > 0.48 else "握拳 · 打飞")
        for p in self.pop:
            U.text(surf, p["txt"], (p["x"], p["y"]), 34, p["col"], center=True,
                   bold=True, glow=10, glow_color=p["col"],
                   alpha=int(255 * min(1, p["t"] * 2.6)))
        self.particles.draw(surf)
        self._draw_hud(surf)
        if self.catch_flash > 0:
            ov = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            ov.fill((255, 240, 190, int(30 * self.catch_flash)))
            surf.blit(ov, (0, 0))
        self.draw_msg(surf)

    def _draw_item(self, surf, it):
        name, col, size, vy, val = it["spec"]
        x, y = it["x"], it["y"]
        if it["dead"] and it["fly"] > 0:
            col = U.mix(col, (60, 60, 60), min(1.0, it["fly"]))
        sp = self._item_sprite(it["spec"])
        if it["dead"]:
            sp = pygame.transform.rotate(sp, math.degrees(it["rot"]) % 360)
        surf.blit(sp, (int(x - sp.get_width() / 2), int(y - sp.get_height() / 2)))

    @staticmethod
    def _item_sprite(spec) -> pygame.Surface:
        name, col, size, vy, val = spec

        def _d(s):
            r = size * 2
            cx = cy = r
            if name == "青铜面具":
                pts = []
                for i in range(36):
                    a = i / 36 * math.tau
                    pts.append((cx + math.cos(a) * 62, cy + math.sin(a) * 54))
                pygame.draw.polygon(s, col, pts)
                pygame.draw.polygon(s, U.shade(col, 0.66), pts, 5)
                for sgn in (-1, 1):
                    pygame.draw.ellipse(s, (26, 34, 28),
                                        pygame.Rect(int(cx + sgn * 24 - 16), int(cy - 22), 32, 22))
                pygame.draw.rect(s, U.shade(col, 1.22), pygame.Rect(int(cx - 8), int(cy + 6), 16, 26))
            elif name == "金杖":
                pygame.draw.rect(s, col, pygame.Rect(int(cx - 12), int(cy - 74), 24, 148),
                                 border_radius=8)
                pygame.draw.rect(s, U.shade(col, 1.24), pygame.Rect(int(cx - 8), int(cy - 68), 8, 136))
                for k in range(4):
                    pygame.draw.circle(s, (160, 118, 40), (cx, int(cy - 52 + k * 34)), 7)
            elif name == "太阳轮":
                pygame.draw.circle(s, col, (cx, cy), 46)
                pygame.draw.circle(s, (54, 40, 24), (cx, cy), 16)
                for k in range(5):
                    a = k * math.tau / 5 - math.pi / 2
                    pygame.draw.line(s, col, (cx + math.cos(a) * 42, cy + math.sin(a) * 42),
                                     (cx + math.cos(a) * 74, cy + math.sin(a) * 74), 14)
                pygame.draw.circle(s, U.shade(col, 1.2), (cx, cy), 46, 5)
            elif name == "玉琮":
                pygame.draw.rect(s, col, pygame.Rect(int(cx - 42), int(cy - 42), 84, 84),
                                 border_radius=8)
                pygame.draw.rect(s, U.shade(col, 0.7), pygame.Rect(int(cx - 42), int(cy - 42),
                                                                   84, 84), 5, border_radius=8)
                pygame.draw.circle(s, (46, 60, 52), (cx, cy), 22)
            else:
                pygame.draw.ellipse(s, col, pygame.Rect(int(cx - 44), int(cy - 52), 88, 104))
                pygame.draw.ellipse(s, U.shade(col, 0.7),
                                    pygame.Rect(int(cx - 44), int(cy - 52), 88, 104), 5)
                pygame.draw.arc(s, U.shade(col, 1.2),
                                pygame.Rect(int(cx - 20), int(cy - 40), 40, 52), 0, math.pi, 7)
        return U.bake(("hc", name, size), (size * 2, size * 2), _d, ss=3)

    def _draw_hud(self, surf):
        bar = pygame.Rect(self.W // 2 - 280, 126, 560, 18)
        U.bar_gauge(surf, bar, self.got / TARGET, self.ACCENT, (48, 54, 44), 9)
        U.text(surf, f"接住 {self.got} / {TARGET}　剩余 {int(self.left)}s",
               (self.W // 2, 156), 26, (232, 244, 214), center=True, bold=True, shadow=3)
        for i in range(MISS_LIMIT):
            cx = self.W - 62 - i * 44
            col = (255, 140, 120) if i < self.miss else (86, 92, 82)
            U.aa_circle(surf, (cx, 74), 13, col, 0, ss=3)

    def hud_items(self):
        return [
            ("接住", f"{self.got}/{TARGET}", (232, 244, 200)),
            ("得分", f"{self.score}", (255, 255, 255)),
            ("连击", f"x{self.combo}", (255, 226, 150)),
            ("漏掉", f"{self.miss}/{MISS_LIMIT}", (255, 150, 140)),
        ]

    def result_title(self) -> str:
        return "圆 满 收 网 ！" if self.state == "win" else "摔 碎 太 多"

    def result_sub(self) -> str:
        return (f"接住 {self.got} 件　漏掉 {self.miss} 件　得分 {self.score}　"
                f"最长连击 {self.best_combo}")
