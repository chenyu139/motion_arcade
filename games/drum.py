"""
games/drum.py
=============
蜀韵鼓点 —— 跟着节奏击鼓。

头部操作
    · 左右平移 → 选择鼓面（4 面）
    · 抬头     → 击鼓
玩法
    音符落到判定线时击打对应的鼓。判定越准分越高，连击有倍率。
    漏掉 6 个音符即结束。
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

N_LANE = 4
HIT_Y = 872
PERFECT, GOOD, OK = 16, 40, 68
TOTAL_NOTES = 46
MISS_LIMIT = 6
LANE_COLORS = [(232, 84, 76), (240, 178, 66), (94, 200, 150), (96, 158, 236)]


@register
class DrumGame(BaseGame):
    KEY = "drum"
    TITLE = "蜀韵鼓点"
    SUB = "跟着节奏敲鼓"
    CATEGORY = "头部控制"
    ACCENT = (232, 96, 76)
    ICON = "drum"
    HOW = "音符落到判定线时，击打对应的鼓"
    HINT = "头部左右选鼓 · 抬头击鼓 · 越准分越高"
    DIFFICULTY = 3
    ACHIEVEMENT = f"打完 {TOTAL_NOTES} 个音符"
    REQUIRES = ("head",)
    MSG_Y = 232

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.notes: List[dict] = []
        self.next_i = 0
        self.make_t = 0.6
        self.bpm = 108.0
        self.sel = 1
        self.sel_f = 1.0
        self.cool = 0.0
        self.score = 0
        self.combo = 0
        self.best_combo = 0
        self.miss = 0
        self.perfect = self.good = self.ok = 0
        self.hit_flash = [0.0] * N_LANE
        self.pop: List[dict] = []
        self.judge_t = 0.0
        self.judge_txt = ""
        self.judge_col = (255, 255, 255)
        self.speed = 620.0
        self.pattern: List[int] = []
        self._build_pattern()
        self._bg = self._make_bg()
        self._lanes_img = self._make_lanes()
        self.set_msg("准备", "跟上鼓点", 1.4, (255, 226, 170))

    def _build_pattern(self):
        """预生成一个可行的节奏型（避免连续大量同轨）。"""
        rng = random.Random(12)
        for i in range(TOTAL_NOTES):
            if self.pattern and rng.random() < 0.45:
                choices = [k for k in range(N_LANE) if k != self.pattern[-1]]
            else:
                choices = list(range(N_LANE))
            self.pattern.append(rng.choice(choices))

    def _make_bg(self) -> pygame.Surface:
        W, H = self.W, self.H
        s = pygame.Surface((W, H))
        s.blit(U.vgrad3(W, H, (34, 16, 20), (66, 26, 30), (28, 14, 18)), (0, 0))
        # 舞台幕布
        for i in range(20):
            x = i * (W / 19.0)
            col = U.shade((138, 34, 40), 0.58 + 0.28 * math.sin(i * 1.4))
            U.aa_poly(s, [(x, self.TOP), (x + W / 19.0, self.TOP + 12),
                          (x + W / 19.0 * 0.92, 620), (x + W / 19.0 * 0.08, 610)],
                      col, 0, ss=2)
        # 顶部灯笼
        for i in range(7):
            x = W * (i + 0.5) / 7.0
            s.blit(U.glow_surface(90, (255, 190, 110), 60, 7), (int(x - 90), 78))
            U.aa_ellipse(s, (int(x - 32), 146, 64, 82), (226, 70, 62), 0, ss=2)
            U.aa_ellipse(s, (int(x - 22), 158, 44, 58), (255, 176, 120), 0, ss=2)
            pygame.draw.line(s, (216, 170, 100), (x, 128), (x, 148), 5)
        return s

    def _make_lanes(self) -> pygame.Surface:
        W = self.W
        s = pygame.Surface((W, self.H), pygame.SRCALPHA)
        for i in range(N_LANE):
            x = self._lane_x(i)
            band = pygame.Surface((228, self.H - HIT_Y + 260), pygame.SRCALPHA)
            band.fill((255, 255, 255, 12))
            s.blit(band, (int(x - 114), HIT_Y - 220))
            U.aa_line(s, (x - 114, self.TOP), (x - 114, HIT_Y + 60), (255, 255, 255, 26), 2)
            U.aa_line(s, (x + 114, self.TOP), (x + 114, HIT_Y + 60), (255, 255, 255, 26), 2)
        return s

    @staticmethod
    def _lane_x(i: int) -> float:
        return 960 + (i - (N_LANE - 1) / 2) * 268.0

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        self.cool = max(0.0, self.cool - dt)
        if self.judge_t > 0:
            self.judge_t -= dt
        for i in range(N_LANE):
            self.hit_flash[i] = max(0.0, self.hit_flash[i] - dt * 4.0)
        for p in self.pop:
            p["t"] -= dt
        self.pop = [p for p in self.pop if p["t"] > 0]

        # 出音符
        beat = 60.0 / self.bpm
        self.make_t -= dt
        if self.make_t <= 0 and self.next_i < len(self.pattern):
            self.make_t = beat * (1.0 if self.next_i % 8 else 1.5)
            self.notes.append({"lane": self.pattern[self.next_i], "y": self.TOP - 80,
                               "hit": False, "done": False})
            self.next_i += 1

        # 移动
        sp = self.speed * (1.0 + self.next_i * 0.006)
        for n in self.notes:
            n["y"] += sp * dt
        for n in self.notes:
            if not n["done"] and n["y"] > HIT_Y + OK:
                n["done"] = True
                self._miss_note(n)
        self.notes = [n for n in self.notes if n["y"] < self.H + 80 and not n.get("gone")]

        # 选轨
        if inp.xc < -0.28 and self.sel > 0 and self.cool <= 0:
            self.sel -= 1
            self.cool = 0.16
        elif inp.xc > 0.28 and self.sel < N_LANE - 1 and self.cool <= 0:
            self.sel += 1
            self.cool = 0.16
        self.sel_f += (self.sel - self.sel_f) * min(1.0, dt * 14.0)

        # 击鼓
        if inp.action and self.cool <= 0:
            self.cool = 0.18
            self._hit(self.sel)

        # 完成判定
        if self.next_i >= len(self.pattern) and not self.notes and self.state == "play":
            self.finish(self.miss <= MISS_LIMIT)
            self.set_msg("演奏结束", f"漏掉 {self.miss} 个", 2.0, (255, 236, 180))

    def _hit(self, lane: int):
        best = None
        for n in self.notes:
            if n["done"] or n["lane"] != lane:
                continue
            d = abs(n["y"] - HIT_Y)
            if best is None or d < abs(best["y"] - HIT_Y):
                best = n
        if best is None:
            self.hit_flash[lane] = 0.7
            self._judge("空击", (190, 200, 220))
            self.combo = 0
            return
        d = abs(best["y"] - HIT_Y)
        best["done"] = True
        best["gone"] = True
        self.hit_flash[lane] = 1.0
        if d <= PERFECT:
            q, base, col = "完美", 150, (255, 226, 130)
            self.perfect += 1
        elif d <= GOOD:
            q, base, col = "良好", 100, (150, 240, 190)
            self.good += 1
        elif d <= OK:
            q, base, col = "勉强", 50, (255, 190, 140)
            self.ok += 1
        else:
            self._miss_note(best)
            return
        self.combo += 1
        self.best_combo = max(self.best_combo, self.combo)
        mult = 1.0 + min(1.5, self.combo * 0.06)
        add = int(base * mult)
        self.score += add
        self._judge(q, col)
        lane_x = self._lane_x(lane)
        self.pop.append({"x": lane_x, "y": HIT_Y - 40, "txt": f"+{add}",
                         "col": col, "t": 0.6})
        self.particles.emit(lane_x, HIT_Y, 14, color=col, spread=220, vy=-200,
                            gravity=760, life=0.5, size=5)
        if self.combo and self.combo % 10 == 0:
            self.set_msg(f"{self.combo} 连击！", f"倍率 x{mult:.1f}", 0.9, (255, 236, 170))
            self.flash(col, 0.18)
        self.shake(4, 0.10)

    def _miss_note(self, n):
        n["done"] = True
        n["gone"] = True
        if n.get("missed"):
            return
        n["missed"] = True
        self.miss += 1
        self.combo = 0
        self._judge("漏掉", (255, 150, 130))
        self.shake(6, 0.2)
        if self.miss > MISS_LIMIT:
            self.state = "over"
            self.set_msg("鼓点乱了", f"漏掉 {self.miss} 个", 2.0, (255, 180, 160))

    def _judge(self, txt, col):
        self.judge_txt, self.judge_col, self.judge_t = txt, col, 0.6

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        surf.blit(self._lanes_img, (0, 0))
        self._draw_drums(surf)
        for n in self.notes:
            if n["done"]:
                continue
            self._draw_note(surf, n)
        self._draw_judgeline(surf)
        for p in self.pop:
            U.text(surf, p["txt"], (p["x"], p["y"] - (0.6 - p["t"]) * 60), 34,
                   p["col"], center=True, bold=True, alpha=int(255 * min(1, p["t"] * 3)))
        if self.judge_t > 0:
            U.text(surf, self.judge_txt, (self.W // 2, HIT_Y + 150), 40, self.judge_col,
                   center=True, bold=True, glow=12, glow_color=self.judge_col,
                   alpha=int(255 * min(1, self.judge_t * 3)))
        self.particles.draw(surf)
        self.draw_vignette(surf, 140)
        self.draw_msg(surf)

    def _draw_note(self, surf, n):
        x = self._lane_x(n["lane"])
        y = n["y"]
        col = LANE_COLORS[n["lane"]]
        U.aa_ellipse(surf, (int(x - 96), int(y - 22), 192, 44),
                     (col[0], col[1], col[2], 230), 0, ss=2)
        U.aa_ellipse(surf, (int(x - 82), int(y - 14), 164, 22),
                     (255, 255, 255, 90), 0, ss=2)
        surf.blit(U.glow_surface(110, col, 46, 6), (int(x - 110), int(y - 110)))

    def _draw_judgeline(self, surf):
        U.aa_line(surf, (self.W // 2 - 620, HIT_Y), (self.W // 2 + 620, HIT_Y),
                  (255, 240, 200, 130), 5)
        for i in range(N_LANE):
            x = self._lane_x(i)
            col = LANE_COLORS[i]
            if self.hit_flash[i] > 0:
                surf.blit(U.glow_surface(180, col, int(120 * self.hit_flash[i]), 8),
                          (int(x - 180), int(HIT_Y - 180)))

    def _draw_drums(self, surf):
        for i in range(N_LANE):
            x = self._lane_x(i)
            sel = abs(self.sel_f - i) < 0.5
            y = HIT_Y + 84
            r = 104
            col = LANE_COLORS[i]
            if sel:
                pulse = 0.5 + 0.5 * math.sin(self.t * 8)
                surf.blit(U.glow_surface(int(r * 1.7), col, int(60 + 40 * pulse), 8),
                          (int(x - r * 1.7), int(y - r * 1.7)))
            U.aa_ellipse(surf, (int(x - r), int(y - r * 0.42), r * 2, int(r * 0.84)),
                         (58, 34, 28), 0, ss=2)
            U.aa_ellipse(surf, (int(x - r), int(y - r * 0.54), r * 2, int(r * 0.84)),
                         U.shade(col, 0.62), 0, ss=2)
            U.aa_ellipse(surf, (int(x - r * 0.84), int(y - r * 0.50), int(r * 1.68), int(r * 0.66)),
                         col, 0, ss=2)
            U.aa_ellipse(surf, (int(x - r * 0.60), int(y - r * 0.42), int(r * 1.20), int(r * 0.40)),
                         U.shade(col, 1.22), 0, ss=2)
            for k in range(8):
                a = k * math.tau / 8
                U.aa_circle(surf, (x + math.cos(a) * r * 0.90, y + math.sin(a) * r * 0.36),
                            5, (216, 176, 96), 0, ss=2)

    def hud_items(self):
        return [
            ("得分", f"{self.score}", (255, 255, 255)),
            ("连击", f"x{self.combo}", (255, 226, 150)),
            ("完美", f"{self.perfect}", (255, 240, 180)),
            ("漏掉", f"{self.miss}/{MISS_LIMIT}", (255, 150, 140)),
        ]

    def result_title(self) -> str:
        return "演 奏 完 成 ！" if self.state == "win" else "鼓 点 乱 了"

    def result_sub(self) -> str:
        return (f"得分 {self.score}　完美 {self.perfect} 良好 {self.good} "
                f"勉强 {self.ok}　最长连击 {self.best_combo}")
