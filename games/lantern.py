"""
games/lantern.py
================
自贡灯会 —— 记住亮灯顺序并复现（彩灯版 Simon says）。

头部操作
    · 左右平移 → 在灯笼之间移动焦点
    · 抬头     → 点亮选中的灯笼
玩法
    灯笼会依次亮起，然后你来复现。每答对一轮序列加长一格，
    错 3 次结束。看你能记住多长的序列。
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

N_LAMP = 6
LAMPS = [
    ("红", (232, 68, 62), (255, 190, 150)),
    ("金", (240, 190, 62), (255, 240, 180)),
    ("翠", (72, 202, 122), (180, 250, 200)),
    ("青", (66, 168, 232), (176, 224, 255)),
    ("紫", (168, 96, 226), (228, 196, 255)),
    ("橙", (240, 130, 58), (255, 214, 170)),
]
MAX_LIVES = 3


@register
class LanternGame(BaseGame):
    KEY = "lantern"
    TITLE = "自贡灯会"
    SUB = "记住点灯顺序"
    CATEGORY = "头部控制"
    ACCENT = (244, 168, 72)
    ICON = "lantern"
    HOW = "记住灯笼亮起的顺序，然后依次点亮"
    HINT = "头部左右选灯 · 抬头点亮 · 顺序错就重来"
    DIFFICULTY = 3
    ACHIEVEMENT = "复现 10 格以上的序列"
    REQUIRES = ("head",)
    MSG_Y = 244
    TARGET = 10

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.seq: List[int] = []
        self.pos = 0                # 玩家输入到第几格
        self.sel = 2
        self.sel_f = 2.0
        self.cool = 0.0
        self.lives = MAX_LIVES
        self.score = 0
        self.best = 0
        self.phase = "show"         # show | input | over
        self.show_i = 0
        self.show_t = 0.0
        self.lit = [0.0] * N_LAMP   # 每盏灯的亮度
        self.flash_lamp = -1
        self.ok_flash = 0.0
        self.err_flash = 0.0
        self._bg = self._make_bg()
        self._lamp_sprites()
        self._next_round(first=True)

    def _make_bg(self) -> pygame.Surface:
        W, H = self.W, self.H
        s = pygame.Surface((W, H))
        s.blit(U.vgrad3(W, H, (18, 10, 26), (44, 20, 42), (22, 12, 28)), (0, 0))
        rng = random.Random(6)
        # 夜空中的点点花灯（背景装饰）
        for _ in range(90):
            x, y = rng.uniform(0, W), rng.uniform(0, H)
            r = rng.uniform(4, 14)
            c = rng.choice([(255, 200, 120), (255, 150, 150), (180, 220, 255), (255, 240, 180)])
            s.blit(U.glow_surface(int(r * 3), c, 46, 6), (int(x - r * 3), int(y - r * 3)))
        # 地面彩灯带
        s.blit(A.shade_panel(W, 90, (56, 26, 44), 0, 1.1, 0.7), (0, H - 90))
        for i in range(28):
            x = i * (W / 27.0)
            c = rng.choice([(255, 200, 120), (255, 130, 150), (150, 220, 255)])
            s.blit(U.glow_surface(30, c, 80, 6), (int(x - 30), H - 66))
            U.aa_circle(s, (x, H - 48), 10, (255, 248, 226), 0, ss=2)
        return s

    def _lamp_sprites(self):
        """预烘焙两套灯笼：暗态与亮态。"""
        self._dark = [self._lamp(i, False) for i in range(N_LAMP)]
        self._bright = [self._lamp(i, True) for i in range(N_LAMP)]

    def _lamp(self, i: int, bright: bool) -> pygame.Surface:
        name, c1, c2 = LAMPS[i]
        W, H = 250, 306

        def _d(s):
            k = 1.0 if bright else 0.42
            col = U.shade(c1, k)
            col2 = U.shade(c2, k)
            if bright:
                for j in range(12, 0, -1):
                    a = int(78 * (1 - j / 12) ** 1.5) + 3
                    pygame.draw.circle(s, (col[0], col[1], col[2], a),
                                       (W * 3 // 2, H * 3 // 2), int((60 + j * 12) * 3))
            # 提绳
            pygame.draw.line(s, (196, 156, 96), (W * 3 // 2, 0), (W * 3 // 2, 42), 6)
            # 灯身（椭圆灯笼）
            body = pygame.Rect(int(W * 3 * 0.16), int(60), int(W * 3 * 0.68), int(H * 3 * 0.66))
            pygame.draw.ellipse(s, col, body)
            pygame.draw.ellipse(s, (40, 20, 26), body, 8)
            # 竖棱
            for t in range(1, 5):
                xx = body.x + body.w * t / 5.0
                pygame.draw.line(s, U.shade(col, 0.82), (xx, body.y + 14),
                                 (xx, body.y + body.h - 14), 5)
            # 上下箍
            pygame.draw.rect(s, (196, 156, 96),
                             pygame.Rect(int(W * 3 * 0.30), int(52), int(W * 3 * 0.40), 22))
            pygame.draw.rect(s, (196, 156, 96),
                             pygame.Rect(int(W * 3 * 0.34), int(H * 3 * 0.70),
                                         int(W * 3 * 0.32), 22))
            # 内芯亮斑
            hl = pygame.Surface((body.w, body.h), pygame.SRCALPHA)
            pygame.draw.ellipse(hl, (col2[0], col2[1], col2[2], 210 if bright else 90),
                                pygame.Rect(int(body.w * 0.24), int(body.h * 0.22),
                                            int(body.w * 0.52), int(body.h * 0.56)))
            s.blit(hl, (body.x, body.y))
            # 流苏
            pygame.draw.line(s, (216, 66, 66), (W * 3 // 2, H * 3 - 60),
                             (W * 3 // 2, H * 3), 7)
        return U.bake(("lamp", i, bright), (W, H), _d, ss=3)

    # ------------------------------------------------------------------ 回合
    def _next_round(self, first: bool = False):
        self.seq.append(random.randrange(N_LAMP))
        self.pos = 0
        self.phase = "show"
        self.show_i = 0
        self.show_t = 0.55
        self.best = max(self.best, len(self.seq) - 1)
        self.set_msg(f"第 {len(self.seq)} 轮", "看好了…" if not first else "记住顺序", 1.2,
                     (255, 226, 180))

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        for i in range(N_LAMP):
            self.lit[i] = max(0.0, self.lit[i] - dt * 2.6)
        self.cool = max(0.0, self.cool - dt)
        self.ok_flash = max(0.0, self.ok_flash - dt * 2.4)
        self.err_flash = max(0.0, self.err_flash - dt * 2.4)

        if self.phase == "show":
            self.show_t -= dt
            if self.show_t <= 0:
                if self.show_i < len(self.seq):
                    lamp = self.seq[self.show_i]
                    self.lit[lamp] = 1.0
                    self.flash_lamp = lamp
                    self.show_i += 1
                    self.show_t = 0.44
                else:
                    self.phase = "input"
                    self.set_msg("轮到你了", "按顺序点亮", 0.9, (180, 240, 210))
            return

        # 选灯
        if inp.xc < -0.30 and self.sel > 0 and self.cool <= 0:
            self.sel -= 1
            self.cool = 0.18
        elif inp.xc > 0.30 and self.sel < N_LAMP - 1 and self.cool <= 0:
            self.sel += 1
            self.cool = 0.18
        self.sel_f += (self.sel - self.sel_f) * min(1.0, dt * 12.0)

        if inp.action and self.cool <= 0:
            self.cool = 0.28
            self.lit[self.sel] = 1.0
            if self.sel == self.seq[self.pos]:
                self.pos += 1
                self.score += 30 + len(self.seq) * 12
                self.ok_flash = 1.0
                self.particles.emit(self._lamp_x(self.sel), 640, 14,
                                    color=LAMPS[self.sel][1], spread=200,
                                    vy=-180, gravity=640, life=0.5, size=4.5)
                if self.pos >= len(self.seq):
                    self.set_msg("正确！", f"序列加长到 {len(self.seq) + 1}", 0.9,
                                 (180, 250, 200))
                    if len(self.seq) >= self.TARGET:
                        self.finish(True)
                        self.flash((255, 244, 200), 0.5)
                        self.set_msg("灯会通关！", f"记住了 {len(self.seq)} 格", 2.0,
                                     (255, 240, 180))
                        return
                    self._next_round()
            else:
                self._wrong()

    def _wrong(self):
        self.lives -= 1
        self.err_flash = 1.0
        self.shake(13, 0.42)
        self.flash((255, 90, 80), 0.34)
        self.particles.emit(self._lamp_x(self.sel), 640, 22, color=(255, 120, 100),
                            spread=280, vy=-200, gravity=860, life=0.7, size=5)
        if self.lives <= 0:
            self.state = "over"
            self.set_msg("记错了", f"最长记住 {self.best} 格", 2.2, (255, 180, 160))
            return
        self.show_i = 0
        self.show_t = 0.5
        self.pos = 0
        self.phase = "show"
        self.set_msg("顺序不对", f"还剩 {self.lives} 次机会，再看一遍", 1.2, (255, 196, 150))

    def _lamp_x(self, i: int) -> float:
        return self.W / 2 + (i - (N_LAMP - 1) / 2) * 268.0

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        self._draw_sequence(surf)
        for i in range(N_LAMP):
            self._draw_lamp(surf, i)
        self._draw_lives(surf)
        self.particles.draw(surf)
        if self.ok_flash > 0:
            ov = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            ov.fill((120, 255, 190, int(26 * self.ok_flash)))
            surf.blit(ov, (0, 0))
        if self.err_flash > 0:
            ov = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            ov.fill((255, 70, 60, int(56 * self.err_flash)))
            surf.blit(ov, (0, 0))
        self.draw_vignette(surf, 150)
        self.draw_msg(surf)

    def _draw_lamp(self, surf, i):
        x = self._lamp_x(i)
        sel = abs(self.sel_f - i) < 0.5
        lift = U.ease_out_cubic(1 - min(1.0, abs(self.sel_f - i))) * 30
        y = 430 - lift
        k = self.lit[i]
        base = self._bright[i] if k > 0.55 else self._dark[i]
        if k > 0.05 and k <= 0.55:
            base = self._dark[i]
            surf.blit(U.glow_surface(int(150 * k) + 30, LAMPS[i][1], int(140 * k), 7),
                      (int(x - 150 * k - 30), int(y + 150 - 150 * k - 30)))
        if sel:
            pulse = 0.5 + 0.5 * math.sin(self.t * 7)
            U.aa_circle(surf, (x, y + 150), 138 + pulse * 5,
                        (255, 236, 170, 150), 4, ss=3)
        surf.blit(base, (int(x - 125), int(y)))
        if k > 0.55:
            surf.blit(U.glow_surface(180, LAMPS[i][1], 74, 8), (int(x - 180), int(y + 40)))
        U.text(surf, LAMPS[i][0], (x, y + 300), 30, (255, 236, 206), center=True, bold=True)

    def _draw_sequence(self, surf):
        """顶部显示序列长度与已输入进度。"""
        n = len(self.seq)
        U.text(surf, f"序列长度 {n}", (self.W // 2, 136), 34, (255, 232, 190),
               center=True, bold=True, glow=12, glow_color=(255, 170, 90))
        for i in range(n):
            x = self.W // 2 + (i - (n - 1) / 2) * 46
            col = LAMPS[self.seq[i]][1] if self.phase == "show" or i < self.pos else (60, 50, 62)
            U.aa_circle(surf, (x, 196), 15, col, 0, ss=3)

    def _draw_lives(self, surf):
        for i in range(MAX_LIVES):
            cx = self.W - 72 - i * 52
            col = (255, 130, 120) if i < self.lives else (86, 70, 88)
            U.aa_circle(surf, (cx - 11, 66), 12, col, 0, ss=3)
            U.aa_circle(surf, (cx + 11, 66), 12, col, 0, ss=3)
            U.aa_poly(surf, [(cx - 23, 70), (cx + 23, 70), (cx, 96)], col, 0, ss=3)

    def hud_items(self):
        return [
            ("序列", f"{len(self.seq)}", (255, 226, 150)),
            ("得分", f"{self.score}", (255, 255, 255)),
            ("最长", f"{self.best}", (180, 236, 255)),
            ("机会", f"{max(0, self.lives)}", (255, 150, 140), "heart"),
        ]

    def result_title(self) -> str:
        return "灯 会 通 关 ！" if self.state == "win" else "灯 灭 了"

    def result_sub(self) -> str:
        return f"最长记住 {self.best} 格　得分 {self.score}"
