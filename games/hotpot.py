"""
games/hotpot.py
===============
火锅大作战 —— 在翻滚的红油锅里捞目标食材。

头部操作
    · 左右平移 → 移动筷子
    · 抬头     → 下筷夹取
玩法
    60 秒内夹到 12 个指定食材即获胜。夹到辣椒扣 1 条命，夹错食材扣分。
"""
from __future__ import annotations

import math
import random
from typing import List, Optional

import numpy as np
import pygame

from core import art as A
from core import theme as U
from core.base import BaseGame, register
from core.inputs import GameInput

POT_C = (960, 690)
POT_R = 396
POT_RY = 300

# 名称, 颜色, 形状, 分值, 是否目标
FOODS = [
    ("毛肚", (86, 52, 44), "ruffle", 100),
    ("鸭肠", (232, 156, 156), "strip", 100),
    ("黄喉", (238, 206, 130), "ring", 100),
    ("午餐肉", (238, 152, 158), "cube", 100),
    ("土豆片", (244, 216, 128), "disc", 100),
    ("青笋", (150, 212, 130), "disc", 100),
    ("辣椒", (216, 54, 48), "chili", -1),
    ("花椒", (150, 92, 62), "dot", -20),
]

TIME = 60.0
TARGET_GOALS = 12


@register
class HotpotGame(BaseGame):
    KEY = "hotpot"
    TITLE = "火锅大作战"
    SUB = "红油锅里捞目标"
    CATEGORY = "头部控制"
    ACCENT = (236, 92, 72)
    ICON = "hotpot"
    HOW = "按提示捞出指定食材，别夹到辣椒"
    HINT = "头部左右移动筷子 · 抬头下筷 · 辣椒 = 扣命"
    DIFFICULTY = 2
    ACHIEVEMENT = f"{int(TIME)} 秒内夹到 {TARGET_GOALS} 个目标食材"
    REQUIRES = ("head",)

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.left = TIME
        self.got = 0
        self.score = 0
        self.lives = 3
        self.streak = 0
        self.best_streak = 0
        self.chop_x = 0.5           # 筷子横向位置（归一化）
        self.chop_open = 1.0        # 1 张开 / 0 夹紧
        self.chop_anim = 0.0
        self.items: List[dict] = []
        self.steam: List[dict] = []
        self.bubbles: List[dict] = []
        self.target = random.choice([f for f in FOODS if f[3] > 0])[0]
        self.target_t = 0.0
        self.pop_t = 0.0
        self.pop_txt = ""
        self.pop_col = (255, 255, 255)
        self.hit_flash = 0.0
        self._bg = self._make_bg()
        self._spawn_all()
        self.set_msg("开涮！", f"先捞 {self.target}", 1.6, (255, 208, 140))

    def _make_bg(self) -> pygame.Surface:
        W, H = self.W, self.H
        s = pygame.Surface((W, H))
        # 木桌
        s.blit(A.noise_texture(W, H, seed=9, amount=26, scale=2).copy(), (0, 0))
        base = U.vgrad3(W, H, (72, 46, 30), (52, 32, 22), (36, 22, 16))
        s.blit(base, (0, 0))
        s.blit(A.noise_texture(W, H, seed=9, amount=22, scale=2), (0, 0))
        # 锅（金属边 + 内胆）
        U.aa_ellipse(s, (POT_C[0] - POT_R - 22, POT_C[1] - POT_RY - 22,
                         (POT_R + 22) * 2, (POT_RY + 22) * 2), (36, 40, 48), 0, ss=2)
        for i in range(14, 0, -1):
            t = i / 14.0
            col = U.mix((150, 156, 168), (86, 92, 104), t)
            U.aa_ellipse(s, (int(POT_C[0] - (POT_R + 20) * t), int(POT_C[1] - (POT_RY + 20) * t),
                             int((POT_R + 20) * 2 * t), int((POT_RY + 20) * 2 * t)), col, 0, ss=2)
        U.aa_ellipse(s, (POT_C[0] - POT_R, POT_C[1] - POT_RY, POT_R * 2, POT_RY * 2),
                     (28, 16, 12), 0, ss=2)
        return s

    def _make_soup(self) -> pygame.Surface:
        """红油汤面（带油光与明暗），只需生成一次。"""
        w, h = POT_R * 2, POT_RY * 2
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        nx = (xx - w / 2) / (w / 2)
        ny = (yy - h / 2) / (h / 2)
        d = np.sqrt(nx * nx + ny * ny)
        base = np.clip(d, 0, 1)
        arr = np.zeros((h, w, 4), dtype=np.uint8)
        r0, g0, b0 = 168, 42, 30
        r1, g1, b1 = 108, 20, 16
        arr[..., 0] = (r0 + (r1 - r0) * base).astype(np.uint8)
        arr[..., 1] = (g0 + (g1 - g0) * base).astype(np.uint8)
        arr[..., 2] = (b0 + (b1 - b0) * base).astype(np.uint8)
        arr[..., 3] = (255 * (d < 1.0)).astype(np.uint8)
        s = pygame.image.frombuffer(arr.tobytes(), (w, h), "RGBA").convert_alpha()
        # 油花
        rng = random.Random(21)
        for _ in range(150):
            a = rng.uniform(0, math.tau)
            rr = rng.uniform(0, 0.94) ** 0.7
            x = w / 2 + math.cos(a) * rr * w / 2
            y = h / 2 + math.sin(a) * rr * h / 2
            rad = rng.uniform(4, 16)
            U.aa_ellipse(s, (int(x - rad), int(y - rad * 0.6), int(rad * 2), int(rad * 1.2)),
                         (232, 132, 74, rng.randint(60, 130)), 0, ss=2)
        for _ in range(70):
            a = rng.uniform(0, math.tau)
            rr = rng.uniform(0, 0.9) ** 0.7
            x = w / 2 + math.cos(a) * rr * w / 2
            y = h / 2 + math.sin(a) * rr * h / 2
            U.aa_circle(s, (x, y), rng.uniform(2, 5), (255, 190, 120, rng.randint(70, 150)), 0, ss=2)
        return s

    def _spawn_all(self):
        self.items = []
        kinds = [f for f in FOODS if f[3] > 0]
        for i in range(16):
            spec = random.choice(kinds + [FOODS[6], FOODS[7]])
            self._push(spec)
        self.steam = [{"x": random.uniform(-1, 1), "y": random.uniform(-1, 1),
                       "r": random.uniform(30, 80), "t": random.uniform(0, 3)} for _ in range(26)]
        self.bubbles = [{"a": random.uniform(0, math.tau), "rr": random.uniform(0.1, 0.9),
                         "t": random.uniform(0, 2)} for _ in range(30)]

    def _push(self, spec):
        a = random.uniform(0, math.tau)
        rr = random.uniform(0.18, 0.88)
        self.items.append({
            "name": spec[0], "col": spec[1], "shape": spec[2], "val": spec[3],
            "a": a, "rr": rr, "spd": random.uniform(0.20, 0.52) * random.choice([-1, 1]),
            "bob": random.uniform(0, 6.28), "alive": True, "sink": 0.0,
            "rot": random.uniform(0, math.tau),
        })

    # ------------------------------------------------------------------ 位置
    @staticmethod
    def _pos(it) -> tuple:
        x = POT_C[0] + math.cos(it["a"]) * it["rr"] * POT_R
        y = POT_C[1] + math.sin(it["a"]) * it["rr"] * POT_RY
        return x, y

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        self.left -= dt
        self.target_t += dt
        self.hit_flash = max(0.0, self.hit_flash - dt * 2.4)
        if self.pop_t > 0:
            self.pop_t -= dt
        if self.left <= 0:
            self.left = 0
            self.finish(self.got >= TARGET_GOALS)
            self.set_msg("时间到", f"夹到 {self.got} 个", 2.0, (255, 214, 150))
            return

        # 筷子
        self.chop_x += inp.axis * 0.62 * dt
        self.chop_x = U.clamp(self.chop_x, 0.06, 0.94)
        self.chop_anim = max(0.0, self.chop_anim - dt * 3.4)
        if inp.jump and self.chop_anim <= 0:
            self._dip()

        # 食材绕锅漂浮
        for it in self.items:
            if not it["alive"]:
                it["sink"] = min(1.0, it["sink"] + dt * 1.4)
                continue
            it["a"] += it["spd"] * dt
            it["bob"] += dt * 2.4
            it["rot"] += dt * 0.9 * it["spd"]

        # 气泡 / 蒸汽
        for b in self.bubbles:
            b["t"] += dt
        for s in self.steam:
            s["t"] += dt
            s["y"] -= dt * 0.22
            if s["y"] < -1.1:
                s["y"] = 1.0
                s["x"] = random.uniform(-1, 1)

        if len([i for i in self.items if i["alive"]]) < 11:
            self._push(random.choice(FOODS))

    def _dip(self):
        self.chop_anim = 1.0
        tip_x = self.W * (0.06 + self.chop_x * 0.88)
        best = None
        bestd = 1e9
        for it in self.items:
            if not it["alive"]:
                continue
            x, y = self._pos(it)
            d = math.hypot(x - tip_x, (y - POT_C[1]) * 1.35)
            if d < bestd:
                bestd, best = d, it
        if best is None or bestd > 156:
            self.pop_txt, self.pop_col, self.pop_t = "空筷", (200, 214, 236), 0.7
            self.streak = 0
            return
        best["alive"] = False
        x, y = self._pos(best)
        if best["name"] == self.target:
            self.got += 1
            self.streak += 1
            self.best_streak = max(self.best_streak, self.streak)
            add = best["val"] + min(60, self.streak * 15)
            self.score += add
            self.pop_txt, self.pop_col, self.pop_t = f"+{add} {best['name']}", (255, 224, 150), 0.9
            self.particles.emit(x, y, 16, color=(255, 214, 120), spread=220,
                                vy=-200, gravity=700, life=0.55, size=5)
            self.flash((255, 236, 180), 0.18)
            self.target = random.choice([f for f in FOODS if f[3] > 0])[0]
            self.target_t = 0.0
            if self.got >= TARGET_GOALS:
                self.finish(True)
                self.set_msg("吃饱了！", f"夹到 {self.got} 个目标", 2.0, (255, 232, 160))
        elif best["name"] == "辣椒":
            self.lives -= 1
            self.streak = 0
            self.pop_txt, self.pop_col, self.pop_t = "辣！扣命", (255, 130, 110), 1.0
            self.hit_flash = 1.0
            self.shake(14, 0.4)
            self.flash((255, 90, 70), 0.42)
            self.particles.emit(x, y, 26, color=(255, 96, 72), spread=300,
                                vy=-230, gravity=900, life=0.8, size=6)
            if self.lives <= 0:
                self.finish(False)
                self.set_msg("太辣了", "喝口唯怡压压惊", 2.0, (255, 176, 150))
        else:
            self.streak = 0
            self.score = max(0, self.score + best["val"])
            self.pop_txt, self.pop_col, self.pop_t = f"夹错了 {best['name']}", (255, 190, 150), 0.9
            self.shake(6, 0.2)
            self.particles.emit(x, y, 12, color=(190, 200, 220), spread=180,
                                vy=-140, gravity=760, life=0.5, size=4)

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        soup = self._soup()
        surf.blit(soup, (POT_C[0] - POT_R, POT_C[1] - POT_RY))
        self._draw_bubbles(surf)
        for it in sorted(self.items, key=lambda d: (not d["alive"], d["sink"])):
            self._draw_item(surf, it)
        self._draw_steam(surf)
        self._draw_chopsticks(surf)
        self._draw_target(surf)
        if self.pop_t > 0:
            U.text(surf, self.pop_txt, (self.W * (0.06 + self.chop_x * 0.88), 250), 40,
                   self.pop_col, center=True, bold=True, glow=12, glow_color=self.pop_col,
                   alpha=int(255 * min(1.0, self.pop_t * 2.2)))
        self.particles.draw(surf)
        if self.hit_flash > 0:
            ov = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            ov.fill((255, 70, 50, int(70 * self.hit_flash)))
            surf.blit(ov, (0, 0))
        self.draw_vignette(surf, 120)
        self.draw_msg(surf)

    def _soup(self):
        if not hasattr(self, "_soup_cache"):
            self._soup_cache = self._make_soup()
        return self._soup_cache

    def _draw_bubbles(self, surf):
        for b in self.bubbles:
            k = (b["t"] % 2.0) / 2.0
            x = POT_C[0] + math.cos(b["a"]) * b["rr"] * POT_R * 0.94
            y = POT_C[1] + math.sin(b["a"]) * b["rr"] * POT_RY * 0.94
            r = U.lerp(3, 14, k)
            a = int(180 * (1 - k))
            U.aa_circle(surf, (x, y), r, (255, 210, 150, a), 2, ss=2)

    def _draw_steam(self, surf):
        for s in self.steam:
            x = POT_C[0] + s["x"] * POT_R * 0.9
            y = POT_C[1] + s["y"] * POT_RY * 0.9 - 60
            k = 1.0 - abs(s["y"])
            a = int(52 * max(0.0, k))
            if a < 3:
                continue
            surf.blit(U.glow_surface(int(s["r"]), (255, 240, 226), a, 6),
                      (int(x - s["r"]), int(y - s["r"])))

    def _draw_item(self, surf, it):
        x, y = self._pos(it)
        k = 1.0 - it["sink"]
        if k <= 0.05:
            return
        bob = math.sin(it["bob"]) * 5
        r = 40 * k
        col = it["col"]
        if it["sink"] > 0:
            col = U.mix(col, (108, 26, 20), it["sink"] * 0.9)
        y += bob + it["sink"] * 26
        shape = it["shape"]
        if shape == "ruffle":
            for i in range(4):
                ox = (i - 1.5) * r * 0.52
                U.aa_ellipse(surf, (int(x + ox - r * 0.30), int(y - r * 0.34),
                                    int(r * 0.60), int(r * 0.68)), col, 0, ss=2)
        elif shape == "strip":
            for i in range(3):
                U.aa_ellipse(surf, (int(x - r * 0.7 + i * r * 0.24), int(y - r * 0.22),
                                    int(r * 1.05), int(r * 0.44)), col, 0, ss=2)
        elif shape == "ring":
            U.aa_ellipse(surf, (int(x - r * 0.6), int(y - r * 0.5), int(r * 1.2), int(r)), col, 0, ss=2)
            U.aa_ellipse(surf, (int(x - r * 0.26), int(y - r * 0.22), int(r * 0.52), int(r * 0.44)),
                         (196, 148, 78), 0, ss=2)
        elif shape == "cube":
            surf.blit(A.shade_panel(r * 1.5, r * 1.1, col, int(r * 0.2)), (int(x - r * 0.75), int(y - r * 0.55)))
            surf.fill(U.shade(col, 1.2), (int(x - r * 0.55), int(y - r * 0.30), int(r * 0.36), int(r * 0.2)))
        elif shape == "disc":
            U.aa_ellipse(surf, (int(x - r * 0.7), int(y - r * 0.46), int(r * 1.4), int(r * 0.92)), col, 0, ss=2)
            U.aa_ellipse(surf, (int(x - r * 0.42), int(y - r * 0.26), int(r * 0.84), int(r * 0.5)),
                         U.shade(col, 1.18), 0, ss=2)
        elif shape == "chili":
            U.aa_ellipse(surf, (int(x - r * 0.72), int(y - r * 0.24), int(r * 1.44), int(r * 0.48)),
                         col, 0, ss=2)
            U.aa_poly(surf, [(x + r * 0.62, y - r * 0.06), (x + r * 0.95, y - r * 0.34),
                             (x + r * 0.78, y + r * 0.10)], (86, 146, 72), 0, ss=2)
            surf.blit(U.glow_surface(int(r * 1.8), (255, 96, 72), 48, 6), (int(x - r * 0.9), int(y - r * 0.9)))
        else:
            U.aa_circle(surf, (x, y), r * 0.30, col, 0, ss=2)

    def _draw_chopsticks(self, surf):
        tip_x = self.W * (0.06 + self.chop_x * 0.88)
        top_y = 300
        tip_y = 640 + self.chop_anim * 96
        gap = U.lerp(16, 54, self.chop_open) * (1.0 - self.chop_anim * 0.55)
        for sgn in (-1, 1):
            U.aa_line(surf, (tip_x + sgn * (gap + 30), top_y), (tip_x + sgn * gap, tip_y),
                      (226, 196, 148), 14, ss=3)
            U.aa_line(surf, (tip_x + sgn * (gap + 30), top_y), (tip_x + sgn * gap, tip_y),
                      (198, 162, 112), 4, ss=3)
        surf.blit(U.glow_surface(40, (255, 226, 160), 46, 6), (int(tip_x - 40), int(tip_y - 40)))
        # 落点提示
        U.aa_ellipse(surf, (int(tip_x - 54), int(POT_C[1] + POT_RY * 0.42), 108, 30),
                     (255, 246, 200, 60), 3, ss=2)

    def _draw_target(self, surf):
        spec = next((f for f in FOODS if f[0] == self.target), FOODS[0])
        box = pygame.Rect(self.W // 2 - 300, 126, 600, 108)
        U.soft_shadow(surf, box, 18, 18, 120, (0, 9))
        U.glass(surf, box, 18, (14, 18, 34, 224), (255, 190, 140, 120), 2)
        U.text(surf, "要 夹", (box.x + 74, box.y + 36), 30, (240, 214, 190), center=True, bold=True)
        # 目标图标
        U.aa_circle(surf, (box.x + 74, box.y + 60), 0, spec[1], 0, ss=2)
        img = U.render_text(spec[0], 54, (255, 240, 220), True)
        surf.blit(img, (box.x + 156, box.y + 30))
        # 剩余时间环
        U.ring_gauge(surf, (box.right - 76, box.centery), 34, 9,
                     self.left / TIME, (255, 206, 120), (58, 60, 82))
        U.text(surf, f"{int(self.left)}", (box.right - 76, box.centery), 30,
               (255, 240, 210), center=True, bold=True)

    def hud_items(self):
        return [
            ("目标", f"{self.got}/{TARGET_GOALS}", (255, 214, 150)),
            ("得分", f"{self.score}", (255, 255, 255)),
            ("连夹", f"x{max(1, self.streak)}", (170, 240, 190)),
            ("生命", f"{max(0, self.lives)}", (255, 140, 130), "heart"),
        ]

    def result_title(self) -> str:
        return "吃 饱 了 ！" if self.state == "win" else "被 辣 到 了"

    def result_sub(self) -> str:
        return (f"夹到目标 {self.got}/{TARGET_GOALS}　得分 {self.score}　"
                f"最长连夹 {self.best_streak}")
