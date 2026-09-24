"""
games/puzzle.py
===============
蜀绣拼图 —— 用手掌把打乱的绣片拖回原位。

手部操作
    · 手掌移动 → 光标
    · 握拳     → 抓住光标下的绣片
    · 张开     → 放下（若放对格子就归位）
玩法
    3×3 九宫格，把 9 片绣片全部拖回正确位置。步数越少分越高。
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

N = 3
CELL = 236
GAP = 14
BOARD_X = 300
BOARD_Y = 250
TILE = 108


@register
class PuzzleGame(BaseGame):
    KEY = "puzzle"
    TITLE = "蜀绣拼图"
    SUB = "九宫归位"
    CATEGORY = "手部控制"
    ACCENT = (226, 116, 138)
    ICON = "puzzle"
    HOW = "握拳抓起绣片，拖到正确位置松开"
    HINT = "手掌移动 · 握拳抓起 · 张开放下"
    DIFFICULTY = 2
    ACHIEVEMENT = "在 40 步内拼好整幅蜀绣"
    REQUIRES = ("hand",)
    MSG_Y = 220
    MAX_MOVES = 40

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        rng = random.Random(23)
        self.order = list(range(N * N))
        # 洗牌（保证不是已解状态）
        while True:
            rng.shuffle(self.order)
            if self.order != list(range(N * N)):
                break
        self.preview = self._full_picture()      # 必须先有整幅图，才能切出绣片
        self.tiles = [self._tile_sprite(i) for i in range(N * N)]
        self.moves = 0
        self.score = 0
        self.solved = 0
        self.holding = None          # 被抓住的格子索引
        self.hx = self.W / 2
        self.hy = self.BOT - 200
        self.h_open = 1.0
        self.h_found = True
        self.grab_cd = 0.0
        self.last_ok = 0.0
        self.pop: List[dict] = []
        self.solve_flash = 0.0
        self.best_moves = None
        self._bg = self._make_bg()
        self._recount()
        self.set_msg("拼好蜀绣", "握拳抓起绣片", 1.6, (255, 226, 232))

    # ------------------------------------------------------------------ 图案
    def _full_picture(self) -> pygame.Surface:
        """程序化生成一幅"蜀绣"风格图案（几何花纹 + 熊猫）。"""
        s = pygame.Surface((N * CELL, N * CELL))
        s.fill((34, 22, 34))
        # 底色渐变
        s.blit(U.vgrad3(N * CELL, N * CELL, (92, 34, 56), (56, 24, 42), (26, 18, 30)), (0, 0))
        import random as _r
        rng = _r.Random(31)
        # 底纹
        for _ in range(220):
            x, y = rng.uniform(0, N * CELL), rng.uniform(0, N * CELL)
            r = rng.uniform(20, 70)
            c = rng.choice([(200, 80, 110), (230, 170, 90), (120, 190, 180), (220, 120, 180)])
            U.aa_circle(s, (x, y), r, (c[0], c[1], c[2], 34), 0, ss=2)
        # 中央大花
        cx = cy = N * CELL / 2
        for k in range(8):
            a = k * math.tau / 8
            U.aa_ellipse(s, (int(cx + math.cos(a) * 170 - 62), int(cy + math.sin(a) * 170 - 40),
                             124, 80), (226, 168, 92), 0, ss=2)
            U.aa_circle(s, (cx + math.cos(a) * 170, cy + math.sin(a) * 170), 18,
                        (255, 226, 160), 0, ss=2)
        U.aa_circle(s, (cx, cy), 92, (238, 196, 116), 0, ss=2)
        U.aa_circle(s, (cx, cy), 62, (206, 96, 128), 0, ss=2)
        U.aa_circle(s, (cx, cy), 30, (255, 232, 180), 0, ss=2)
        # 熊猫
        px, py = N * CELL * 0.5, N * CELL * 0.80
        U.aa_circle(s, (px, py), 66, (250, 250, 252), 0, ss=2)
        for sgn in (-1, 1):
            U.aa_circle(s, (px + sgn * 46, py - 48), 24, (36, 34, 40), 0, ss=2)
            U.aa_ellipse(s, (int(px + sgn * 26 - 20), int(py - 22), 40, 34), (36, 34, 40), 0, ss=2)
            U.aa_circle(s, (px + sgn * 30, py - 10), 7, (250, 250, 252), 0, ss=2)
        U.aa_ellipse(s, (int(px - 12), int(py + 16), 24, 18), (36, 34, 40), 0, ss=2)
        # 边框
        U.rr(s, pygame.Rect(0, 0, N * CELL, N * CELL), 18, None, (226, 180, 116), 8)
        return s

    def _tile_sprite(self, idx: int) -> pygame.Surface:
        r, c = divmod(idx, N)
        src = self.preview.subsurface(pygame.Rect(c * CELL, r * CELL, CELL, CELL)).copy()
        small = pygame.transform.smoothscale(src, (TILE * 2, TILE * 2))
        return pygame.transform.smoothscale(small, (TILE, TILE))

    def _make_bg(self) -> pygame.Surface:
        W, H = self.W, self.H
        s = pygame.Surface((W, H))
        s.blit(U.vgrad3(W, H, (28, 20, 30), (54, 34, 48), (24, 16, 24)), (0, 0))
        rng = random.Random(7)
        for _ in range(70):
            x, y = rng.uniform(0, W), rng.uniform(0, H)
            r = rng.uniform(60, 220)
            c = rng.choice([(200, 80, 110), (90, 160, 180), (220, 160, 90)])
            U.aa_circle(s, (x, y), r, (c[0], c[1], c[2], 16), 0, ss=2)
        # 绣架
        board_w = N * CELL + GAP * 2
        board_h = N * CELL + GAP * 2
        s.blit(A.shade_panel(board_w + 48, board_h + 48, (112, 78, 52), 20),
               (BOARD_X - 24, BOARD_Y - 24))
        return s

    def _cell_rect(self, pos: int) -> pygame.Rect:
        r, c = divmod(pos, N)
        return pygame.Rect(BOARD_X + c * CELL + GAP, BOARD_Y + r * CELL + GAP,
                           CELL - GAP * 2, CELL - GAP * 2)

    def _recount(self):
        self.solved = sum(1 for i, v in enumerate(self.order) if i == v)

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        self.grab_cd = max(0.0, self.grab_cd - dt)
        self.solve_flash = max(0.0, self.solve_flash - dt * 2.0)
        if self.last_ok > 0:
            self.last_ok -= dt

        tx, ty = self.hand_screen(inp, pygame.Rect(150, self.TOP + 140,
                                                   self.W - 300, self.GAME_H - 240), 1.24)
        self.hx += (tx - self.hx) * min(1.0, dt * 16.0)
        self.hy += (ty - self.hy) * min(1.0, dt * 16.0)
        self.h_open = inp.hand_open
        self.h_found = inp.hand_found

        # 抓 / 放
        if self.holding is None and (inp.pinch or inp.grab_hold) and self.grab_cd <= 0:
            pos = self._pos_at(self.hx, self.hy)
            if pos is not None and self.order[pos] != pos:
                self.holding = pos
                self.grab_cd = 0.34
                self.particles.emit(self.hx, self.hy, 10, color=(255, 226, 170),
                                    spread=180, vy=-140, gravity=700, life=0.4, size=4)
        elif self.holding is not None and (inp.release or inp.hand_open > 0.66) and self.grab_cd <= 0:
            self._drop()

        for p in self.pop:
            p["t"] -= dt
            p["y"] -= dt * 56
        self.pop = [p for p in self.pop if p["t"] > 0]

    def _pos_at(self, x: float, y: float):
        for pos in range(N * N):
            r = self._cell_rect(pos)
            if r.collidepoint(x, y):
                return pos
        return None

    def _drop(self):
        pos = self._pos_at(self.hx, self.hy)
        held = self.holding
        self.holding = None
        self.grab_cd = 0.30
        self.moves += 1
        if pos is None or pos == held:
            if self.moves >= self.MAX_MOVES:
                self._fail()
            return
        # 交换
        self.order[held], self.order[pos] = self.order[pos], self.order[held]
        self.particles.emit(self._cell_rect(pos).centerx, self._cell_rect(pos).centery,
                            12, color=(200, 220, 255), spread=180, vy=-120,
                            gravity=700, life=0.4, size=4)
        self._recount()
        if self.order[pos] == pos:
            self.score += 60
            self.pop.append({"x": self._cell_rect(pos).centerx,
                             "y": self._cell_rect(pos).centery, "txt": "+60",
                             "col": (255, 236, 170), "t": 0.7})
            self.last_ok = 0.5
            self.particles.emit(self._cell_rect(pos).centerx, self._cell_rect(pos).centery,
                                16, color=(255, 232, 160), spread=220, vy=-150,
                                gravity=720, life=0.5, size=5)
            self.shake(4, 0.12)
        if self.solved >= N * N:
            self.state = "win"
            self.solve_flash = 1.0
            bonus = max(0, (self.MAX_MOVES - self.moves)) * 40
            self.score += 400 + bonus
            self.flash((255, 246, 220), 0.5)
            self.set_msg("绣成！", f"用了 {self.moves} 步", 2.2, (255, 240, 200))
            self.particles.emit(self.W / 2, self.H / 2, 60, color=(255, 232, 170),
                                spread=420, vy=-260, gravity=620, life=1.1, size=6)
        elif self.moves >= self.MAX_MOVES:
            self._fail()

    def _fail(self):
        self.state = "over"
        self.shake(12, 0.4)
        self.set_msg("步数用完了", f"归位 {self.solved} / {N * N}", 2.2, (255, 190, 170))

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        # 目标小图
        pv = pygame.transform.smoothscale(self.preview, (300, 300))
        surf.blit(A.shade_panel(324, 324, (92, 62, 44), 18), (96, 300))
        surf.blit(pv, (108, 312))
        U.text(surf, "目标", (258, 272), 28, (240, 216, 196), center=True, bold=True)
        # 棋盘
        for pos in range(N * N):
            r = self._cell_rect(pos)
            ok = self.order[pos] == pos
            U.rr(surf, r, 12, (18, 12, 20, 190),
                 (150, 236, 180) if ok else (96, 78, 92), 3)
        # 绣片
        for pos in range(N * N):
            idx = self.order[pos]
            if self.holding == pos:
                continue
            r = self._cell_rect(pos)
            surf.blit(self.tiles[idx], (r.centerx - TILE // 2, r.centery - TILE // 2))
            if idx == pos:
                U.aa_poly(surf, [(r.right - 26, r.top + 16), (r.right - 18, r.top + 26),
                                 (r.right - 8, r.top + 10)], (150, 236, 180), 0, ss=3)
        # 抓在手上的那片
        if self.holding is not None:
            idx = self.order[self.holding]
            surf.blit(self.tiles[idx], (int(self.hx - TILE // 2), int(self.hy - TILE // 2)))
            U.aa_circle(surf, (self.hx, self.hy), TILE * 0.66, (255, 236, 170, 150), 3, ss=3)
        # 高亮即将放下的格子
        if self.holding is not None:
            tgt = self._pos_at(self.hx, self.hy)
            if tgt is not None:
                rr = self._cell_rect(tgt)
                perfect = self.order[self.holding] == tgt
                U.rr(surf, rr, 12, None,
                     (150, 246, 190) if perfect else (255, 200, 150), 5)
                if perfect:
                    surf.blit(U.glow_surface(160, (150, 246, 190), 60, 7),
                              (rr.centerx - 160, rr.centery - 160))
        self.draw_hand(surf, (self.hx, self.hy), self.h_open, self.h_found,
                       "已抓起" if self.holding is not None else "")
        for p in self.pop:
            U.text(surf, p["txt"], (p["x"], p["y"]), 32, p["col"], center=True,
                   bold=True, glow=10, glow_color=p["col"],
                   alpha=int(255 * min(1, p["t"] * 2.8)))
        self.particles.draw(surf)
        self._draw_hud(surf)
        if self.last_ok > 0:
            ov = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            ov.fill((150, 250, 190, int(26 * min(1, self.last_ok * 2))))
            surf.blit(ov, (0, 0))
        if self.solve_flash > 0:
            ov = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            ov.fill((255, 244, 210, int(48 * self.solve_flash)))
            surf.blit(ov, (0, 0))
        self.draw_msg(surf)

    def _draw_hud(self, surf):
        U.text(surf, f"归位 {self.solved} / {N * N}", (self.W // 2, 130), 32,
               (255, 232, 236), center=True, bold=True, glow=10, glow_color=(230, 120, 150))
        bar = pygame.Rect(self.W // 2 - 260, 174, 520, 16)
        U.bar_gauge(surf, bar, self.solved / (N * N), self.ACCENT, (52, 40, 52), 8)
        U.text(surf, f"步数 {self.moves} / {self.MAX_MOVES}", (self.W // 2, 206), 26,
               (238, 220, 230), center=True)

    def hud_items(self):
        return [
            ("归位", f"{self.solved}/{N*N}", (255, 236, 240)),
            ("步数", f"{self.moves}/{self.MAX_MOVES}", (255, 255, 255)),
            ("得分", f"{self.score}", (255, 226, 150)),
        ]

    def result_title(self) -> str:
        return "绣 成 ！" if self.state == "win" else "没 拼 完"

    def result_sub(self) -> str:
        return f"用了 {self.moves} 步　归位 {self.solved}/{N*N}　得分 {self.score}"
