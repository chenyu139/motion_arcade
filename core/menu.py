"""
core/menu.py
============
游戏大厅：20 款小游戏的分页卡片墙。

操作
    头部左右 → 切换卡片（到页边自动翻页）
    抬头     → 进入选中的游戏
    键盘     → ←→↑↓ 移动，回车进入，数字键 1-9 快速选
    停留 2.4 秒自动进入（方便演示时不用刻意做动作）
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

import pygame

from . import base as B
from . import config as C
from . import icons
from . import sprites as SP
from . import theme as U
from .inputs import GameInput

COLS = C.MENU_COLS
ROWS = C.MENU_ROWS
PER_PAGE = COLS * ROWS

CARD_W = 420
CARD_H = 310
GAP_X = 40
GAP_Y = 34
GRID_X = (C.DESIGN_W - (COLS * CARD_W + (COLS - 1) * GAP_X)) // 2
GRID_Y = 258


class Menu:
    def __init__(self, info: Optional[Dict] = None) -> None:
        self.games = B.meta_list()
        self.n = len(self.games)
        self.sel = 0
        self.sel_f = 0.0
        self.cool = 0.0
        self.dwell = 0.0
        self.enter_t = 0.0
        self.page = 0
        self.chosen: Optional[str] = None
        self.t = 0.0
        self.info = info or {}
        self.orbs = U.OrbField(C.DESIGN_W, C.DESIGN_H, n=8, seed=11)
        self.stars = U.StarField(C.DESIGN_W, C.DESIGN_H, n=130, seed=5)
        self._bg = self._make_bg()
        self._page_anim = 1.0

    # ------------------------------------------------------------------ 背景
    def _make_bg(self) -> pygame.Surface:
        W, H = C.DESIGN_W, C.DESIGN_H
        s = pygame.Surface((W, H))
        s.blit(U.vgrad3(W, H, (14, 18, 40), (22, 26, 56), (10, 12, 28)), (0, 0))
        # 细网格
        grid = pygame.Surface((W, H), pygame.SRCALPHA)
        for x in range(0, W, 60):
            grid.fill((120, 150, 220, 12), (x, 0, 1, H))
        for y in range(0, H, 60):
            grid.fill((120, 150, 220, 12), (0, y, W, 1))
        s.blit(grid, (0, 0))
        s.blit(U.vignette(W, H, 190), (0, 0))
        return s

    # ------------------------------------------------------------------ 状态
    @property
    def total_pages(self) -> int:
        return max(1, (self.n + PER_PAGE - 1) // PER_PAGE)

    def reset(self) -> None:
        self.chosen = None
        self.enter_t = 0.0
        self.dwell = 0.0
        self.cool = 0.4

    def _card_rect(self, i: int) -> pygame.Rect:
        """卡片在**当前页**中的位置。"""
        p = i // PER_PAGE
        k = i % PER_PAGE
        r, c = divmod(k, COLS)
        return pygame.Rect(GRID_X + c * (CARD_W + GAP_X),
                           GRID_Y + r * (CARD_H + GAP_Y), CARD_W, CARD_H)

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        self.t += dt
        self.orbs.update(dt)
        self.enter_t += dt
        if self.cool > 0:
            self.cool -= dt
        self._page_anim = min(1.0, self._page_anim + dt * 4.0)

        if self.chosen:
            return

        # 头部 / 键盘切换
        moved = 0
        if self.cool <= 0:
            if inp.axis < -0.52:
                moved = -1
            elif inp.axis > 0.52:
                moved = 1
            if moved:
                self.cool = C.MENU_SWITCH_COOLDOWN
                self.sel = (self.sel + moved) % self.n
                self.dwell = 0.0
                self._page_anim = 0.0
                self._on_move()

        # 停留自动确认：**必须正在稳定识别到头才计时**。
        # 之前是无条件累加，结果人走开了、或者转头看不见了，大厅会自己
        # 一路翻页、自己进游戏 —— 这就是最典型的"没识别到头却还在乱动"。
        if inp.found and not inp.jump:
            self.dwell += dt
        else:
            self.dwell = 0.0
        if self.dwell >= C.MENU_DWELL and self.enter_t > C.MENU_ENTRY_TIME:
            self.confirm()

        # 抬头确认（切换后短暂锁定，防误触）
        # 同样要求识别中：假阳性的 jump 会把人直接送进游戏
        if inp.found and inp.jump and self.cool <= 0 and self.enter_t > C.MENU_CONFIRM_LOCK:
            self.confirm()

        self.sel_f += (self.sel - self.sel_f) * min(1.0, dt * 9.0)

    def _on_move(self) -> None:
        newpage = self.sel // PER_PAGE
        if newpage != self.page:
            self.page = newpage

    def move(self, d: int) -> None:
        if self.chosen:
            return
        self.sel = (self.sel + d) % self.n
        self.dwell = 0.0
        self._page_anim = 0.0
        self._on_move()

    def pick(self, i: int) -> None:
        if 0 <= i < self.n:
            self.sel = i
            self.dwell = 0.0
            self._on_move()
            self.confirm()

    def confirm(self) -> None:
        if self.chosen:
            return
        self.chosen = self.games[self.sel]["key"]

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        self.orbs.draw(surf)
        self.stars.draw(surf, self.t)
        self._draw_header(surf)
        self._draw_mascots(surf)

        # 当前页的卡片（带翻页位移）
        slide = (1.0 - U.ease_out_cubic(self._page_anim)) * 120.0 * (1 if self.page else -1)
        for i in range(self.n):
            if i // PER_PAGE != self.page:
                continue
            self._draw_card(surf, i, slide)
        self._draw_pager(surf)
        self._draw_footer(surf)

    def _draw_mascots(self, surf):
        """
        标题两侧的吉祥物：左边熊猫组合、右边盖碗茶。

        这是最省版面又能立刻提升辨识度的位置 —— 卡片墙占满 y 258~912，
        页脚还有文字，只有标题带两侧是空的。基线统一在 246，
        加上投影让它们"站在"同一条线上。

        素材缺失时直接整体不画（保持原来的纯文字版式），不做半吊子混搭。
        """
        base = 246
        pair = (("panda_hero", 200, 116), ("panda_cub", 146, 296))
        if not all(SP.draw(surf, nm, x, base, height=h, anchor="bottom", shadow=0.55)
                   for nm, h, x in pair):
            return
        SP.draw(surf, "gaiwan", 1798, base - 2, height=100, anchor="bottom",
                shadow=0.5)

    def _draw_header(self, surf):
        # 标题
        U.text(surf, "体 感 游 戏 厅", (C.DESIGN_W // 2, 98), 62, (255, 255, 255),
               center=True, bold=True, glow=18, glow_color=(110, 158, 255))
        U.text(surf, "MOTION ARCADE", (C.DESIGN_W // 2, 150), 24, (130, 160, 220),
               center=True, bold=True)
        # 统计
        cats: Dict[str, int] = {}
        for g in self.games:
            cats[g["category"]] = cats.get(g["category"], 0) + 1
        info = "　·　".join(f"{k} {v}" for k, v in cats.items())
        U.text(surf, f"共 {self.n} 款游戏　|　{info}", (C.DESIGN_W // 2, 188), 24,
               (168, 190, 232), center=True)
        # 摄像头状态（右对齐）
        cam_ok = self.info.get("cam_ok", False)
        hand_ok = self.info.get("hand_ok", False)
        if cam_ok:
            # 直接显示识别三态：人离开时大厅必须表现出"我不认识你了"，
            # 而不是继续当作有人在操作（否则会自己翻页、自己进游戏）
            tr = self.info.get("track", "track")
            if tr == "track":
                tag = f"● 已锁定 · {self.info.get('backend', '-')}"
                col = (110, 230, 170)
            elif tr == "hold":
                tag, col = "◐ 短暂丢帧 · 输入冻结", (250, 200, 90)
            else:
                tag, col = "○ 未识别到头 · 已停止自动进入", (245, 140, 130)
        else:
            tag, col = "● 键盘 / 鼠标模式（未启用摄像头）", (250, 190, 110)
        img = U.render_text(tag, 22, col, True)
        surf.blit(img, (C.DESIGN_W - 48 - img.get_width(), 52))
        fim = U.render_text(f"{self.info.get('fps', 0):.0f} FPS", 20, (140, 165, 200))
        surf.blit(fim, (C.DESIGN_W - 48 - fim.get_width(), 84))

    def _draw_card(self, surf, i, slide):
        g = self.games[i]
        r = self._card_rect(i)
        r = r.move(int(slide * (1 + (i % 3) * 0.2)), 0)
        sel = (i == self.sel)
        accent = g["accent"]

        # 入场动画
        appear = U.clamp((self.t - 0.10 * (i % PER_PAGE)) / 0.55, 0.0, 1.0)
        ease = U.ease_out_back(appear)
        if ease <= 0.01:
            return
        lift = (1.0 - ease) * 60
        scale = 0.90 + 0.10 * ease

        base_rect = pygame.Rect(r.x, int(r.y + lift), r.w, r.h)
        if sel:
            base_rect = base_rect.inflate(18, 18).move(0, -8)
        elif g["key"] != self.games[self.sel]["key"]:
            pass

        surf_set = base_rect
        if sel:
            U.soft_shadow(surf, surf_set, 26, 26, 170, (0, 14))
            gl = U.glow_surface(int(surf_set.w * 0.9), accent, 60, 8)
            surf.blit(gl, (surf_set.centerx - gl.get_width() // 2,
                           surf_set.centery - gl.get_height() // 2))
        else:
            U.soft_shadow(surf, surf_set, 20, 18, 110, (0, 10))

        tint = (accent[0], accent[1], accent[2], 46 if sel else 22)
        glass_bg = (20, 24, 48, 238) if sel else (16, 19, 38, 210)
        U.glass(surf, surf_set, 24, glass_bg,
                (accent[0], accent[1], accent[2], 200 if sel else 90), 3 if sel else 2)
        # 顶部色带
        band = pygame.Rect(surf_set.x + 3, surf_set.y + 3, surf_set.w - 6, 7)
        U.rr(surf, band, 4, tint)

        # 图标
        isize = 118 if sel else 104
        icon_cy = surf_set.y + (104 if sel else 96)
        icons.draw_icon(surf, g["icon"], surf_set.centerx, icon_cy, isize,
                        accent, (255, 255, 255))

        # 名称
        U.text(surf, g["title"], (surf_set.centerx, surf_set.y + (196 if sel else 186)),
               34 if sel else 31, (255, 255, 255), center=True, bold=True)
        # 副标题
        U.text(surf, g["sub"], (surf_set.centerx, surf_set.y + (232 if sel else 222)),
               20, (170, 192, 228), center=True)

        # 分类徽章（右上角）
        cat = g["category"]
        badge_col = {"头部控制": (110, 170, 255),
                     "手部控制": (255, 170, 110),
                     "头部 + 手部": (190, 150, 255)}.get(cat, (170, 180, 200))
        img = U.render_text(cat, 19, badge_col)
        br = pygame.Rect(surf_set.right - img.get_width() - 34, surf_set.y + 18,
                         img.get_width() + 22, 32)
        U.rr(surf, br, 9, (badge_col[0], badge_col[1], badge_col[2], 40), badge_col, 2)
        surf.blit(img, (br.x + 11, br.y + 6))

        # 难度
        for k in range(3):
            cx = surf_set.x + 30 + k * 20
            cy = surf_set.y + 34
            on = k < g["difficulty"]
            col = (255, 206, 110) if on else (70, 78, 104)
            pts = U.star_points(cx, cy, 8, 3.4, 5)
            U.aa_poly(surf, pts, col, 0, ss=3)

        # 选中：停留进度环
        if sel:
            pct = U.clamp(self.dwell / C.MENU_DWELL, 0, 1)
            U.ring_gauge(surf, (surf_set.right - 44, surf_set.bottom - 38), 24, 7,
                         pct, accent, (60, 70, 100))
            U.text(surf, "停", (surf_set.right - 44, surf_set.bottom - 38), 20,
                   (240, 246, 255), center=True, bold=True)
            # 进入提示
            U.text(surf, "抬头进入 / 回车", (surf_set.centerx, surf_set.bottom - 36), 21,
                   (226, 240, 255), center=True, alpha=200)

    def _draw_pager(self, surf):
        n = self.total_pages
        cx = C.DESIGN_W // 2
        y = C.DESIGN_H - 108
        total_w = n * 40
        for i in range(n):
            x = cx - total_w // 2 + 20 + i * 40
            on = (i == self.page)
            U.aa_circle(surf, (x, y), 11 if on else 7,
                        (180, 210, 255) if on else (74, 86, 118), 0, ss=3)
        U.text(surf, f"第 {self.page + 1} / {n} 页", (cx, y + 34), 22, (150, 176, 216),
               center=True)

    def _draw_footer(self, surf):
        bar = pygame.Surface((C.DESIGN_W, 68), pygame.SRCALPHA)
        bar.fill((8, 10, 24, 208))
        surf.blit(bar, (0, C.DESIGN_H - 68))
        pygame.draw.line(surf, (52, 66, 104), (0, C.DESIGN_H - 68),
                         (C.DESIGN_W, C.DESIGN_H - 68), 1)
        cur = self.games[self.sel]
        U.text(surf, cur["how"], (44, C.DESIGN_H - 50), 26, (226, 236, 255), bold=True)
        right = "← → 切卡片　↑↓ 跨行　回车进入　ESC 退出　F11 全屏"
        img = U.render_text(right, 22, (150, 172, 210))
        surf.blit(img, (C.DESIGN_W - 44 - img.get_width(), C.DESIGN_H - 46))
