"""
core/menu.py
============
游戏大厅 —— **开始界面（Start Screen）**。

布局取向的变化
--------------
旧版是"标题 + 一堵 4×2 的卡片墙 + 一条快捷键状态栏"。问题不在好不好看，而在于
它是一张**信息平铺表**：每张卡都重复一遍图标/名称/分类/难度，选中项和未选中项
几乎没有视觉差别，整屏没有任何"我要开始了"的引导。这是"AI Demo"最典型的气质。

现在改成商业游戏常见的 **英雄区 + 选择网格**：

    ┌──────────────────────────────────────────────┐
    │  体感游戏厅                        ● 已锁定   │  标题栏
    ├──────────────────────────────────────────────┤
    │  ┌────┐  超级马里奥          ┌────────────┐  │
    │  │大图标│ 横版平台跳跃 · 踩敌人 +100 │  抬头开始  │  │  英雄区
    │  └────┘  [头部控制] ★★☆☆☆    └────────────┘  │
    ├──────────────────────────────────────────────┤
    │  [卡][卡][卡][卡][卡]                         │  选择网格
    │  [卡][卡][卡][卡][卡]                         │  （只留图标与名称）
    └──────────────────────────────────────────────┘

**交互**：左右平移选卡片、抬头确认进入（已去掉「停留自动进入」）、
键盘 ←→/回车/数字键。改的只是信息怎么摆 —— 详细说明只出现在英雄区一次，卡片回归"选项"。

背景也不再是纯色 + 网格：换成黄昏天空 + 星点 + 四川地标剪影 + 雾 + 地面，
让大厅本身就是一个"游戏世界"。
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

import pygame

from . import base as B
from . import config as C
from . import icons
from . import scene as SCN
from . import sichuan as SC
from . import sprites as SP
from . import theme as U
from . import ui as UI
from .inputs import GameInput

COLS = C.MENU_COLS
ROWS = C.MENU_ROWS
PER_PAGE = COLS * ROWS

CARD_W = 340
CARD_H = 226
GAP_X = 24
GAP_Y = 22
GRID_X = (C.DESIGN_W - (COLS * CARD_W + (COLS - 1) * GAP_X)) // 2
GRID_Y = 462
HERO = pygame.Rect(60, 96, C.DESIGN_W - 120, 330)

_CAT_COL = {"头部控制": UI.INFO, "手部控制": UI.SECONDARY, "头部 + 手部": (200, 150, 255)}


class Menu:
    def __init__(self, info: Optional[Dict] = None) -> None:
        self.games = B.meta_list()
        self.n = len(self.games)
        self.sel = 0
        self.sel_f = 0.0
        self.cool = 0.0
        self.enter_t = 0.0
        self.page = 0
        self.chosen: Optional[str] = None
        self.t = 0.0
        self.info = info or {}
        self.orbs = U.OrbField(C.DESIGN_W, C.DESIGN_H, n=7, seed=11)
        self.stars = U.StarField(C.DESIGN_W, C.DESIGN_H, n=170, seed=5)
        self._bg = self._make_bg()
        self._page_anim = 1.0
        self._hero_pop = UI.Pop(k=8.0)
        self._sel_prev = -1
        # 方向保持计时（见 update 里的切换逻辑）。这里必须和 reset() 一样
        # 初始化 —— __init__ 不会自动调用 reset()，漏了就是"第一帧崩"。
        self._dir = 0
        self._dir_t = 0.0

    # ------------------------------------------------------------------ 背景
    def _make_bg(self) -> pygame.Surface:
        """
        黄昏世界：天空 → 星 → 远山 → 雾 → 四川地标剪影 → 地面。

        大厅也需要"这是个游戏世界"的第一印象，所以它不是纯色底，
        而是和游戏里同一套分层做法（见 core/scene.py 的说明）。
        整体压暗、并留出中间大片低对比区域，保证卡片与文字始终清晰。
        """
        W, H = C.DESIGN_W, C.DESIGN_H
        s = pygame.Surface((W, H))
        SCN.sky_or(s, "sky_dusk", W, H, (22, 20, 54), (62, 48, 108), (188, 122, 106))
        # 地平线余晖：暖色低垂的太阳，"夕照"最省事的说法
        SCN.sun(s, W * 0.74, H * 0.66, 84, (255, 190, 134))
        self.stars.draw(s, 0.0)
        # 远山两层
        SCN.hill_range(s, pygame.Rect(0, 520, W, H - 520), 3, (54, 40, 92),
                       seed=5, h_min=0.20, h_max=0.70, haze=0.20)
        SCN.hill_range(s, pygame.Rect(0, 600, W, H - 600), 4, (38, 28, 70),
                       seed=11, h_min=0.18, h_max=0.62)
        # 四川地标剪影：宽窄巷子 / 锦里 / 峨眉 / 青城 / 三星堆
        s.blit(SC.skyline(W, 280, preset="city", base=(28, 20, 56),
                          haze=0.14, seed=7, count=7), (0, 660))
        # 雾：把剪影和地面分开
        SCN.fog_band(s, pygame.Rect(0, 600, W, 300), (150, 128, 186), 76)
        # 地面
        SCN.ground_band(s, pygame.Rect(0, 900, W, H - 900), (46, 34, 80),
                        (22, 16, 44), 130)
        return s

    # ------------------------------------------------------------------ 状态
    @property
    def total_pages(self) -> int:
        return max(1, (self.n + PER_PAGE - 1) // PER_PAGE)

    def reset(self) -> None:
        self.chosen = None
        self._dir = 0
        self._dir_t = 0.0
        self.enter_t = 0.0
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
        # 方向必须**持续**够久才切。上游已经有起振门限与迟滞，这里再加一道：
        # 大厅是最不能抖的地方 —— 抖一格就是"我刚才明明没动"。
        d = 0
        if inp.axis < -C.MENU_SWITCH_TH:
            d = -1
        elif inp.axis > C.MENU_SWITCH_TH:
            d = 1
        if d != self._dir:
            self._dir = d
            self._dir_t = 0.0
        else:
            self._dir_t += dt
        if self.cool <= 0 and d != 0 and self._dir_t >= C.MENU_SWITCH_HOLD:
            moved = d
            if moved:
                self.cool = C.MENU_SWITCH_COOLDOWN
                self.sel = (self.sel + moved) % self.n
                self._page_anim = 0.0
            self._on_move()

        # 确认进入：**只认「抬头」这一个明确动作**，不再有「停留 N 秒自动进入」。
        #
        # 原来有一条 dwell 自动确认（停住不动 2.4 秒就进游戏）。本意是照顾不想
        # 做动作的玩家，但实际后果是：玩家只是站着看看有哪些游戏，就自己进去了 ——
        # 这和「头没动却自己在选」是同一类体验伤害，都是「我没下指令它却动了」。
        # 大厅的自动行为必须全部去掉。
        #
        # 三道门槛一起保证「抬头」是真的抬头：
        #   inp.found —— 必须正在稳定识别到头（假阳性不认）
        #   cool      —— 刚切过格子时不认（防切换动作带的尾巴）
        #   enter_t   —— 刚进大厅的一小段时间不认（防还没看清就进去了）
        # 上游的起振门限（AXIS_ARM）与动作键迟滞还会再挡掉单帧尖峰。
        if (inp.found and inp.jump and self.cool <= 0
                and self.enter_t > C.MENU_CONFIRM_LOCK):
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
        self._page_anim = 0.0
        self._on_move()

    def pick(self, i: int) -> None:
        if 0 <= i < self.n:
            self.sel = i
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
        self._draw_topbar(surf)
        self._draw_hero(surf)
        for i in range(self.n):
            if i // PER_PAGE != self.page:
                continue
            self._draw_card(surf, i)
        self._draw_pager(surf)
        self._draw_footer(surf)

    # ------------------------------------------------------------------ 标题栏
    def _draw_topbar(self, surf) -> None:
        UI.text(surf, "体 感 游 戏 厅", (62, 20), UI.T_L, UI.PAPER,
                outline=UI.INK, outline_w=5)
        U.text(surf, "MOTION ARCADE", (66, 84), UI.T_XS, (196, 186, 236),
               bold=True)
        # 右侧：识别状态 + 玩法统计
        cam = self.info.get("cam_ok", False)
        tr = self.info.get("track", "track") if cam else "none"
        if not cam:
            tag, col, ic = "键盘 / 鼠标模式", UI.WARN, "wave"
        elif tr == "track":
            tag, col, ic = "头部已锁定", UI.ACCENT, "check"
        elif tr == "hold":
            tag, col, ic = "短暂丢帧 · 输入冻结", UI.WARN, "clock"
        else:
            tag, col, ic = "未识别到头 · 不会自动进入", UI.DANGER, "eye"
        UI.pill(surf, (C.DESIGN_W - 62, 46), tag, col, ic, size=UI.T_XS,
                align="right", height=58)
        cats: Dict[str, int] = {}
        for g in self.games:
            cats[g["category"]] = cats.get(g["category"], 0) + 1
        info = "　·　".join(f"{k} {v}" for k, v in cats.items())
        UI.text(surf, f"共 {self.n} 款　|　{info}", (C.DESIGN_W - 64, 92),
                UI.T_XS - 4, UI.PAPER_DIM, align := None or None) if False else None
        img = U.outline_text(f"共 {self.n} 款　|　{info}", UI.T_XS - 4,
                             (206, 196, 240), UI.INK, 3, True)
        surf.blit(img, (C.DESIGN_W - 64 - img.get_width(), 92))

    # ------------------------------------------------------------------ 英雄区
    def _draw_hero(self, surf) -> None:
        """
        选中游戏的详细信息 + 开始按钮。

        这是整个门面的核心：把"当前选中什么、玩法是什么、怎么开始"三件事
        集中在一处讲清楚，而不像旧版那样在十张卡片上各重复一遍。
        """
        g = self.games[self.sel]
        accent = UI.normalize_accent(g["accent"])
        appear = U.clamp((self.t - 0.05) / 0.5, 0.0, 1.0)
        ease = U.ease_out_back(appear)
        if ease <= 0.01:
            return
        # 切换选中时，英雄区弹一下 —— 让"选项变了"这件事被看见
        if self.sel != self._sel_prev:
            self._sel_prev = self.sel
            self._hero_pop.hit(1.0)
        pop = 1.0 + 0.045 * self._hero_pop.v

        h = HERO.inflate(int(HERO.w * (pop - 1)), int(HERO.h * (pop - 1)))
        h = h.move(0, int((1.0 - ease) * 26))

        UI.card(surf, h, UI.R_XL, glow=accent, glow_a=78,
                top=U.mix(UI.SURFACE_HI, accent, 0.16),
                bottom=U.mix(UI.SURFACE_LO, accent, 0.06))

        # 大图标
        box = pygame.Rect(h.x + 30, h.y + 30, 270, 270)
        pygame.draw.rect(surf, (26, 21, 52), box, border_radius=UI.R_LG)
        pygame.draw.rect(surf, tuple(accent) + (150,), box, 3, border_radius=UI.R_LG)
        U.glow(surf, box.center, 150, accent, 72)
        pulse = 1.0 + 0.035 * math.sin(self.t * 2.6)
        icons.draw_icon(surf, g["icon"], box.centerx, box.centery,
                        int(186 * pulse), accent, (255, 255, 255))

        # 文字区
        tx = box.right + 40
        UI.text(surf, g["title"], (tx, h.y + 42), UI.T_XL, UI.PAPER,
                outline=UI.INK, outline_w=6)
        U.text(surf, g["sub"], (tx + 4, h.y + 148), UI.T_S, (222, 214, 250),
               bold=True)
        U.text(surf, g["how"], (tx + 4, h.y + 200), UI.T_XS, UI.PAPER_DIM)

        # 分类 + 难度
        cat = g["category"]
        UI.pill(surf, (tx, h.y + 254), cat, _CAT_COL.get(cat, UI.INFO),
                size=UI.T_XS - 4, align="left", height=50, pad=22)
        cx = tx + 300
        for k in range(3):
            pts = U.star_points(cx + k * 40, h.y + 254, 15, 6.4, 5)
            U.aa_poly(surf, pts, UI.SECONDARY if k < g["difficulty"] else (74, 66, 120),
                      0, ss=3)

        # ---- 吉祥物：让英雄区的空档也有内容，同时保留四川元素 ----
        # 重构大厅时这三个精灵一度失去用处（信息都收进英雄区了），
        # 但"四川文旅"是产品的一部分，不能因为改版就丢掉。
        base = h.bottom - 14
        SP.draw(surf, "panda_hero", h.x + 1080, base, height=232, anchor="bottom",
                shadow=0.45)
        SP.draw(surf, "gaiwan", h.x + 1290, base, height=104, anchor="bottom",
                shadow=0.40)

        # 开始按钮
        btn = pygame.Rect(h.right - 372, h.y + 56, 340, 148)
        UI.big_button(surf, btn, "抬 头 开 始", accent, t=self.t, hot=True,
                      size=UI.T_L, sub="或按回车")
        # 序号。这里原本是一条「停留进度条」—— 它服务的自动进入已经去掉，
        # 进度条也就没有意义（留着反而暗示「再等一会儿会自己进去」）。
        UI.text(surf, f"{self.sel + 1} / {self.n}", (btn.centerx, btn.bottom + 40),
                UI.T_XS, UI.PAPER_DIM, center=True)

    # ------------------------------------------------------------------ 卡片
    def _draw_card(self, surf, i: int) -> None:
        """
        选择网格里的卡片：**只留图标与名称**。

        详细说明已经在英雄区讲过一遍了。旧版每张卡都重复图标 + 名称 + 副标题 +
        分类徽章 + 难度星，十张铺开就成了一片噪点 —— 信息的价值来自"只出现一次"。
        """
        g = self.games[i]
        accent = UI.normalize_accent(g["accent"])
        sel = (i == self.sel)
        r = self._card_rect(i)
        appear = U.clamp((self.t - 0.04 * (i % PER_PAGE)) / 0.5, 0.0, 1.0)
        ease = U.ease_out_back(appear)
        if ease <= 0.01:
            return
        lift = int((1.0 - ease) * 40)
        k = abs(self.sel_f - i)
        hot = max(0.0, 1.0 - k)
        r = r.inflate(int(14 * hot), int(14 * hot)).move(0, -int(10 * hot) + lift)

        UI.card(surf, r, UI.R_LG,
                top=U.mix(UI.SURFACE_HI, accent, 0.20 * hot + 0.06),
                bottom=U.mix(UI.SURFACE_LO, accent, 0.08 * hot),
                outline=accent if hot > 0.5 else UI.OUTLINE,
                glow=accent if sel else None, glow_a=int(70 * hot))
        if sel:
            pygame.draw.rect(surf, (255, 255, 255, 70), r, 3,
                             border_radius=UI.R_LG)

        icons.draw_icon(surf, g["icon"], r.centerx, r.y + int(r.h * 0.42),
                        int(r.h * 0.40), accent, (255, 255, 255))
        U.text(surf, g["title"], (r.centerx, r.y + int(r.h * 0.70)), UI.T_S,
               UI.PAPER, center=True, bold=True,
               outline=UI.INK, outline_w=3)
        # 难度：用小点而不是星星，小尺寸下更好认
        for d in range(3):
            col = UI.SECONDARY if d < g["difficulty"] else (70, 62, 112)
            U.aa_circle(surf, (r.centerx + (d - 1) * 16, r.bottom - 20), 5, col,
                        0, ss=3)

    # ------------------------------------------------------------------ 翻页
    def _draw_pager(self, surf) -> None:
        n = self.total_pages
        cx = C.DESIGN_W // 2
        y = C.DESIGN_H - 96
        total_w = n * 44
        for i in range(n):
            x = cx - total_w // 2 + 22 + i * 44
            on = (i == self.page)
            if on:
                U.glow(surf, (x, y), 26, UI.PRIMARY, 90)
            U.aa_circle(surf, (x, y), 12 if on else 7,
                        UI.PAPER if on else (78, 70, 122), 0, ss=3)

    # ------------------------------------------------------------------ 页脚
    def _draw_footer(self, surf) -> None:
        """
        页脚只手势提示，**不列键盘快捷键**。

        旧版把 ESC / 回车 / TAB / F11 全列在底部，那是开发工具的状态栏。
        玩家站在电视前不会看，也不需要看 —— 键盘提示移到暂停面板即可。
        """
        UI.pill(surf, (C.DESIGN_W // 2, C.DESIGN_H - 42),
                "左右平移选游戏　·　抬头确认进入",
                UI.SURFACE, size=UI.T_XS, alpha=192, height=52, pad=44)
