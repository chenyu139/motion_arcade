"""
core/base.py
============
所有游戏共用的基类与注册表。

统一约定
--------
每个游戏只实现三件事：reset() / update(dt, inp) / draw(surf)，
其余（HUD、摄像头预览、暂停、丢失提示、结算界面、震动、粒子、计时）
全部由外壳（core/shell.py）与基类提供。

坐标系
------
游戏在 **1920×1080 设计坐标系** 中绘制，但只有 y ∈ [GAME_TOP, GAME_BOT]
这一段会被玩家看到（上方是 HUD，下方是提示条）。x 方向全宽可用，
但左下角有一块摄像头预览面板（config.PREVIEW_RECT），
基类把它暴露为 self.preview_rect 供游戏避让。
"""
from __future__ import annotations

import math
import sys
import random
from typing import Dict, List, Optional, Sequence, Tuple

import pygame

from . import config as C
from . import theme as U
from . import scene as SCN
from .inputs import GameInput

Color = Tuple[int, ...]


class BaseGame:
    """所有小游戏的基类。"""

    # ---- 元信息（子类覆盖）----
    KEY = "base"
    TITLE = "未命名"
    SUB = ""
    CATEGORY = "头部控制"          # 头部控制 / 手部控制 / 头部 + 手部
    ACCENT: Color = (108, 148, 236)
    ICON = "dot"
    HINT = ""                      # 底部一行的操作提示
    HOW = ""                       # 菜单里的玩法一句话
    DIFFICULTY = 2                 # 1 轻松 / 2 适中 / 3 硬核
    ACHIEVEMENT = ""               # 通关条件说明
    REQUIRES = ("head",)           # 需要的输入通道
    MSG_Y = None                   # 中央提示的 y（默认 TOP+168，子类可避开关键区域）
    # ---- 世界观感（第 1、8 项：三层空间 / 光照 / 景深 / 氛围）----
    # WORLD 选 core/scene.py 里的世界预设，决定方向光、雾色、前景剪影与暗角。
    # 背景本体的主题内容仍由各游戏的 _make_bg 画，这里只是给它叠上"深度"。
    WORLD = "meadow"
    WORLD_Y = None                 # 地平线 y；None = 自动从模块常量推断

    # ---- 共享常量 ----
    W = C.DESIGN_W
    H = C.DESIGN_H
    TOP = C.GAME_TOP
    BOT = C.GAME_BOT
    GAME_H = C.GAME_H
    PW, PH = C.PREVIEW_W, C.PREVIEW_H
    PX, PY = C.PREVIEW_X, C.PREVIEW_Y
    preview_rect = pygame.Rect(C.PREVIEW_X, C.PREVIEW_Y, C.PREVIEW_W, C.PREVIEW_H)
    area = pygame.Rect(0, C.GAME_TOP, C.DESIGN_W, C.GAME_H)
    center = (C.DESIGN_W // 2, C.GAME_TOP + C.GAME_H // 2)

    def __init__(self) -> None:
        self.state = "play"        # play | win | over
        self.t = 0.0               # 本局累计时间
        self.time_scale = 1.0      # 顿帧用
        self.particles = U.Particles(cap=700)
        self._shake = 0.0
        self._shake_t = 0.0
        self._flash_a = 0.0
        self._flash_col: Color = (255, 255, 255)
        self.msg = ""
        self.msg_sub = ""
        self.msg_t = 0.0
        self.msg_max = 1.0
        self.msg_col: Color = (255, 255, 255)
        self.acc = 0.0             # 用于整秒计时
        self.reset()

    # ------------------------------------------------------------------ 生命周期
    def reset(self) -> None:
        """子类实现：把本局状态清空。"""

    def update(self, dt: float, inp: GameInput) -> None:
        """子类实现：推进一帧。dt 已按 time_scale 缩放。"""
        raise NotImplementedError

    def draw(self, surf: pygame.Surface) -> None:
        """子类实现：把画面画到 surf（全屏尺寸）。"""
        raise NotImplementedError

    # ------------------------------------------------------------------ 共用推进
    # ------------------------------------------------------------------ 世界合成
    def _ground_line(self) -> int:
        """
        推断"地平线"位置，用于雾带与接触阴影。

        优先用类属性 WORLD_Y；否则从游戏模块里找常见的地面常量
        （GROUND / FLOOR / WATER_Y / HORIZON…）。这样 20 款游戏都不用单独声明，
        而推断失败时退回画面下方 72% —— 对任何构图都还算合理的位置。
        """
        if self.WORLD_Y is not None:
            return int(self.WORLD_Y)
        mod = sys.modules.get(type(self).__module__)
        for nm in ("GROUND", "GROUND_Y", "FLOOR", "WATER_Y", "HORIZON",
                   "PITCH_TOP", "FLOOR_Y", "BASE_Y"):
            v = getattr(mod, nm, None)
            if isinstance(v, (int, float)) and 0 < v < self.H:
                return int(v)
        return int(self.H * 0.72)

    def _wear_world(self) -> None:
        """
        给背景叠上深度合成（见 core/scene.py 的 depth_pass）。

        放在 tick 里按需触发而不是构造时调用：`reset()` 会重建 `_bg`
        （"再来一局"），构造时只做一次的话第二局就退回扁平背景了。
        用对象同一性判断，换过就重新合成一次。
        """
        bg = getattr(self, "_bg", None)
        if bg is None or bg is getattr(self, "_bg_worn", None):
            return
        SCN.depth_pass(bg, self.ACCENT, self.WORLD, self._ground_line())
        self._bg_worn = bg

    def tick(self, dt: float, inp: GameInput) -> None:
        """外壳每帧调用：先跑公共计时/特效，再跑子类 update。"""
        self._wear_world()
        self.t += dt
        if self._flash_a > 0:
            self._flash_a = max(0.0, self._flash_a - dt * 3.4)
        if self._shake_t > 0:
            self._shake_t = max(0.0, self._shake_t - dt)
            if self._shake_t <= 0:
                self._shake = 0.0
        if self.msg_t > 0:
            self.msg_t = max(0.0, self.msg_t - dt)
        d = dt * self.time_scale
        self.update(d, inp)
        self.particles.update(dt)

    # ------------------------------------------------------------------ 特效工具
    def shake(self, amount: float = 10.0, dur: float = 0.30) -> None:
        self._shake = max(self._shake, amount)
        self._shake_t = max(self._shake_t, dur)

    def shake_offset(self) -> Tuple[int, int]:
        if self._shake_t <= 0 or self._shake <= 0:
            return (0, 0)
        k = self._shake
        return (int(random.uniform(-k, k)), int(random.uniform(-k, k)))

    def flash(self, color: Color = (255, 255, 255), a: float = 0.5) -> None:
        self._flash_a = max(self._flash_a, a)
        self._flash_col = color

    def draw_flash(self, surf: pygame.Surface) -> None:
        if self._flash_a > 0.01:
            ov = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            ov.fill((self._flash_col[0], self._flash_col[1], self._flash_col[2],
                     int(200 * self._flash_a)))
            surf.blit(ov, (0, 0))

    def set_msg(self, text: str, sub: str = "", dur: float = 1.0,
                col: Color = (255, 255, 255)) -> None:
        self.msg, self.msg_sub, self.msg_max = text, sub, max(0.2, dur)
        self.msg_t = self.msg_max
        self.msg_col = col

    def draw_msg(self, surf: pygame.Surface) -> None:
        """屏幕中上部的大字提示（进球/得分/失误等）。"""
        if self.msg_t <= 0 or not self.msg:
            return
        k = self.msg_t / self.msg_max
        pop = U.ease_out_back(min(1.0, (1 - k) * 5.0)) if k > 0.78 else 1.0
        alpha = int(255 * min(1.0, k * 3.2))
        cy = self.MSG_Y if self.MSG_Y is not None else self.TOP + 168
        size = int(U.lerp(46, 84, min(1.0, pop)))
        U.text(surf, self.msg, (self.W // 2, int(cy)), size, self.msg_col,
               center=True, glow=16, glow_color=self.msg_col, bold=True, alpha=alpha)
        if self.msg_sub:
            U.text(surf, self.msg_sub, (self.W // 2, int(cy) + 58), 28,
                   (226, 236, 252), center=True, shadow=2, alpha=alpha)

    # ------------------------------------------------------------------ 结算
    def result_title(self) -> str:
        return "通 关 ！" if self.state == "win" else "结 束"

    def result_sub(self) -> str:
        return ""

    def is_over(self) -> bool:
        return self.state in ("win", "over")

    def finish(self, win: bool) -> None:
        self.state = "win" if win else "over"

    # ------------------------------------------------------------------ HUD
    def hud_items(self) -> List[Tuple]:
        """返回 [(标签, 值, 颜色, 可选图标)]，由外壳统一排版。"""
        return []

    # ------------------------------------------------------------------ 摆件
    def draw_vignette(self, surf: pygame.Surface, strength: int = 96) -> None:
        surf.blit(U.vignette(self.W, self.H, strength), (0, 0))

    def draw_hint_badge(self, surf: pygame.Surface, text: str,
                        pos: Tuple[int, int] = (0, 0)) -> None:
        img = U.render_text(text, 22, (232, 240, 255))
        r = pygame.Rect(pos[0], pos[1], img.get_width() + 34, 42)
        U.rr(surf, r, 12, (10, 14, 30, 190), (110, 138, 196, 150), 2)
        surf.blit(img, (r.x + 17, r.y + 9))

    # ------------------------------------------------------------------ 手部辅助
    def hand_screen(self, inp: GameInput, rect: Optional[pygame.Rect] = None,
                    gain: float = 1.30) -> Tuple[float, float]:
        """
        把归一化手部坐标映射到设计坐标系。

        增益（gain）的作用：摄像头视野比屏幕窄，若 1:1 映射，手要挥到很大幅度
        才能碰到屏幕边缘，手感会很"够不着"。默认放大 1.30 倍。
        """
        r = rect if rect is not None else pygame.Rect(
            90, self.TOP + 40, self.W - 180, self.GAME_H - 120)
        nx = U.clamp(0.5 + (inp.hx - 0.5) * gain, 0.0, 1.0)
        ny = U.clamp(0.5 + (inp.hy - 0.5) * gain, 0.0, 1.0)
        return (r.x + nx * r.w, r.y + ny * r.h)

    def draw_hand(self, surf: pygame.Surface, pos: Tuple[float, float],
                  open_v: float, found: bool = True, label: str = "") -> None:
        """
        画一只"手心光标"：张开度直接体现在手指的开合上，
        玩家一眼就能看出系统有没有正确读到手势。
        """
        x, y = pos
        r = 46
        if not found:
            U.aa_circle(surf, (x, y), r, (170, 186, 210, 150), 3, ss=3)
            U.text(surf, "未检测到手", (x, y + r + 30), 22, (200, 214, 236), center=True)
            return
        col = (250, 236, 200) if open_v > 0.5 else (250, 200, 150)
        surf.blit(U.glow_surface(int(r * 2.2), col, 60, 7), (int(x - r * 2.2), int(y - r * 2.2)))
        # 手掌
        U.aa_circle(surf, (x, y), r * 0.66, (242, 206, 172), 0, ss=3)
        U.aa_circle(surf, (x, y), r * 0.66, (196, 150, 116), 3, ss=3)
        # 手指：张开度控制长度与角度
        spread = U.lerp(0.10, 0.62, U.clamp(open_v, 0, 1))
        length = U.lerp(r * 0.34, r * 0.86, U.clamp(open_v, 0, 1))
        for i in range(4):
            ang = -math.pi / 2 + (i - 1.5) * spread
            bx = x + math.sin(ang) * (r * 0.56)
            by = y - math.cos(ang) * (r * 0.56)
            ex = x + math.sin(ang) * (r * 0.56 + length)
            ey = y - math.cos(ang) * (r * 0.56 + length)
            U.aa_line(surf, (bx, by), (ex, ey), (242, 206, 172), 16, ss=3)
            U.aa_line(surf, (bx, by), (ex, ey), (198, 150, 116), 2, ss=3)
        # 拇指
        th = -math.pi / 2 - spread * 1.75
        U.aa_line(surf, (x - r * 0.42, y + r * 0.16),
                  (x - r * 0.42 + math.sin(th) * length * 0.86,
                   y + r * 0.16 - math.cos(th) * length * 0.86), (242, 206, 172), 17, ss=3)
        if label:
            U.text(surf, label, (x, y + r * 1.5), 22, (240, 246, 255), center=True, bold=True)


# =========================================================================== #
# 注册表
# =========================================================================== #
REGISTRY: List[type] = []


def register(cls: type) -> type:
    """把游戏类登记进大厅（顺序即菜单顺序）。"""
    REGISTRY.append(cls)
    return cls


def all_games() -> List[type]:
    return list(REGISTRY)


def meta_list() -> List[Dict]:
    return [{
        "key": c.KEY, "title": c.TITLE, "sub": c.SUB, "category": c.CATEGORY,
        "accent": c.ACCENT, "icon": c.ICON, "how": c.HOW, "hint": c.HINT,
        "difficulty": c.DIFFICULTY, "achievement": c.ACHIEVEMENT,
        "requires": c.REQUIRES, "cls": c,
    } for c in REGISTRY]
