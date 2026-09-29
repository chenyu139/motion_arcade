"""
core/feedback.py
================
得分 / 连击的即时反馈。

设计上的关键决定：**由 HUD 数值变化驱动，而不是各游戏自己调用**
----------------------------------------------------------------
"每次正确操作要有强反馈"最直接的实现是去改 20 个游戏，让它们在得分处调一个
特效函数。但那有三个问题：改动面大、容易漏、而且不同游戏的手感会不一致。

这里改成在外壳层监听 HUD 的数值变化：只要某个数值变大了，就认为"玩家刚完成
了一次操作"，自动产出浮动数字 + 粒子 + 连击 + 弹跳。**20 款游戏零改动**，
并且所有游戏的反馈强度完全一致 —— 这正是"像同一个团队做的"那种整体感。

反馈强度按连击递进（这是需求里明确要的）：
    第 1 次命中   → 小的 +N 数字 + 几点星火
    连击 2~3      → 数字变大、COMBO 标签出现、粒子变多
    连击 4~6      → 屏幕边缘泛起主题色光、数字带辉光
    连击 7+       → 全屏轻微脉冲 + 彩纸，"爆发"感
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pygame

from . import theme as U
from . import sfx
from . import ui as UI

Color = Tuple[int, int, int]

# 连击窗口：两次得分间隔超过这个时长就算断了
COMBO_WINDOW = 2.2
# 单次加分到达这些阈值就给"叫好"横幅
NICE_AT = 20
PERFECT_AT = 50


class Floating:
    """一个向上飘走的数字。"""

    __slots__ = ("x", "y", "vy", "life", "max_life", "text", "color", "size", "wob")

    def __init__(self, x: float, y: float, text: str, color: Color, size: int,
                 life: float = 1.15, wob: float = 0.0) -> None:
        self.x, self.y = x, y
        self.vy = -150.0
        self.life = self.max_life = life
        self.text, self.color, self.size = text, color, size
        self.wob = wob


class Feedback:
    """外壳级的反馈汇总：浮动数字、连击、叫好横幅、庆祝、氛围粒子。"""

    def __init__(self) -> None:
        self.numbers: List[Floating] = []
        self.particles = U.Particles(cap=700)
        self.combo = 0
        self.combo_t = 0.0
        sfx.play("fail")
        self.combo_pop = UI.Pop(k=7.0)
        self.banner: Optional[Dict] = None
        self.pulse = 0.0                 # 全屏脉冲强度
        self._t = 0.0
        self.max_combo = 0          # 本局的最高连击（结算页要用）
        self._accent: Color = UI.PRIMARY

    # ------------------------------------------------------------------ 事件
    def set_accent(self, c: Color) -> None:
        self._accent = c

    def score(self, x: float, y: float, delta: int, color: Color) -> None:
        """
        报告一次得分。x/y 是浮字起点（通常就取那个变大的 HUD 卡片中心）。

        delta <= 0 时不产生正反馈（扣分不该有彩带）。
        """
        if delta <= 0:
            return
        self._bump_combo(delta)

        k = min(self.combo, 9)
        size = UI.T_M + min(34, delta) + k * 4
        self.numbers.append(Floating(x, y, f"+{delta}", color, size,
                                     wob=(hash(delta) % 100) / 100.0 * 6.28 - 3.14))
        self.particles.emit(x, y, 6 + k * 2, color=color, shape="star",
                            gravity=420.0, spread=150 + k * 22,
                            life=0.55, size=5.5 + k * 0.5)
        self.particles.emit(x, y, 4 + k, color=UI.PAPER, shape="glow",
                            gravity=-30.0, spread=90, life=0.4, size=7.0)

        if delta >= PERFECT_AT:
            self._banner("PERFECT!", UI.SECONDARY)
            self.pulse = max(self.pulse, 0.5)
        elif delta >= NICE_AT:
            self._banner("NICE!", UI.ACCENT)
        if self.combo >= 4:
            self.pulse = max(self.pulse, min(0.34, 0.06 * self.combo))

    def fail(self, x: float, y: float) -> None:
        """扣分/失误：明确但不庆祝 —— 只用向下掉的暗色粒子。"""
        self.combo = 0
        self.combo_t = 0.0
        sfx.play("fail")
        self.particles.emit(x, y, 10, color=UI.DANGER, shape="square",
                            gravity=760.0, spread=170, life=0.55, size=5.0)

    def celebrate(self) -> None:
        """通关庆祝：全屏彩纸 + 全屏脉冲。"""
        for i in range(3):
            self.particles.emit(
                U.__dict__.get("_celebrate_x", 0) or (240 + i * 720), 120, 70,
                color=(UI.SECONDARY, UI.ACCENT, UI.PRIMARY, UI.INFO,
                       (232, 122, 232))[i % 5],
                shape="confetti", gravity=620.0, spread=340,
                life=2.0, size=8.0, fade=True)
        self.pulse = max(self.pulse, 0.7)

    def _bump_combo(self, amt: int) -> None:
        if self.combo_t > 0:
            self.combo = min(99, self.combo + 1)
        else:
            self.combo = 1
        self.combo_t = COMBO_WINDOW
        self.max_combo = max(self.max_combo, self.combo)
        # 音效与连击等级联动：越连越高（prompt 第 5 项"反馈逐渐增强"）
        sfx.play("hit_big" if amt >= 40 else "hit")
        if self.combo >= 2:
            sfx.play_combo(self.combo)
        if self.combo >= 2:
            self.combo_pop.hit(min(1.0, 0.45 + 0.12 * self.combo))

    def _banner(self, text: str, color: Color) -> None:
        self.banner = {"text": text, "color": color, "life": 0.95, "max": 0.95}

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float) -> None:
        self._t += dt
        for f in self.numbers:
            f.life -= dt
            f.vy += 130.0 * dt              # 轻微重力 → 有"抛出去"的感觉
            f.y += f.vy * dt
        self.numbers = [f for f in self.numbers if f.life > 0]

        if self.combo_t > 0:
            self.combo_t -= dt
            if self.combo_t <= 0:
                self.combo = 0
        self.combo_pop.step(dt)
        self.pulse = max(0.0, self.pulse - dt * 1.6)
        self.particles.update(dt)

        if self.banner is not None:
            self.banner["life"] -= dt
            if self.banner["life"] <= 0:
                self.banner = None

    def reset(self) -> None:
        self.numbers.clear()
        self.particles.clear()
        self.combo = 0
        self.combo_t = 0.0
        sfx.play("fail")
        self.banner = None
        self.pulse = 0.0
        self.max_combo = 0

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        w, h = surf.get_size()

        # 1) 连击脉冲：屏幕四边泛起主题色光（"气势上来了"）
        if self.pulse > 0.02:
            a = int(min(1.0, self.pulse) * 96)
            for rect in ((0, 0, w, 26), (0, h - 26, w, 26),
                         (0, 0, 26, h), (w - 26, 0, 26, h)):
                s = pygame.Surface((rect[2], rect[3]), pygame.SRCALPHA)
                s.fill(tuple(self._accent) + (a,))
                surf.blit(s, (rect[0], rect[1]))

        # 2) 浮动数字（带描边 + 弹性缩放）
        for f in self.numbers:
            k = f.life / max(1e-6, f.max_life)
            grow = 1.0 + 0.5 * U.ease_out_back(min(1.0, (1.0 - k) * 6.0))
            alpha = int(255 * min(1.0, k * 2.6))
            img = U.outline_text(f.text, int(f.size * grow), f.color, UI.INK, 4, True)
            if f.life > f.max_life - 0.12:
                U.glow(surf, (int(f.x), int(f.y)), int(f.size * 1.1), f.color, 90)
            if alpha < 255:
                img = img.copy()
                img.set_alpha(alpha)
            surf.blit(img, (f.x - img.get_width() / 2, f.y - img.get_height() / 2))

        # 3) 叫好横幅
        if self.banner is not None:
            b = self.banner
            k = b["life"] / b["max"]
            pop = U.ease_out_back(min(1.0, (1.0 - k) * 4.5))
            alpha = int(255 * min(1.0, k * 2.4))
            size = int(UI.T_XL * (0.7 + 0.3 * pop))
            img = U.outline_text(b["text"], size, b["color"], UI.INK, 6, True)
            img = pygame.transform.rotozoom(img, -6 * (1 - pop), 1.0)
            if alpha < 255:
                img = img.copy()
                img.set_alpha(alpha)
            cx, cy = w // 2, int(h * 0.30)
            U.glow(surf, (cx, cy), int(size * 1.5), b["color"], int(80 * k))
            surf.blit(img, (cx - img.get_width() / 2, cy - img.get_height() / 2))

        # 4) 连击计数（右侧，随连击递进变亮变大）
        if self.combo >= 2:
            k = min(1.0, self.combo_t / COMBO_WINDOW)
            pop = self.combo_pop.v
            size = int(UI.T_L * (1.0 + 0.30 * pop))
            col = UI.SECONDARY if self.combo < 5 else (
                (255, 150, 60) if self.combo < 8 else UI.DANGER)
            x, y = w - 96, int(h * 0.30)
            U.text(surf, "COMBO", (x, y - 34), UI.T_XS, UI.PAPER_DIM,
                   center=True, bold=True, outline=UI.INK, outline_w=3)
            img = U.outline_text(f"×{self.combo}", size, col, UI.INK, 6, True)
            U.glow(surf, (x, y + 24), int(size * 1.2), col, int(60 + 90 * pop))
            surf.blit(img, (x - img.get_width() / 2, y + 24 - img.get_height() / 2))
            # 剩余时间条：让"连击要断了"变得可见
            bw = 150
            pygame.draw.rect(surf, (52, 44, 96),
                             (x - bw // 2, y + 24 + size // 2 + 10, bw, 8),
                             border_radius=4)
            pygame.draw.rect(surf, col,
                             (x - bw // 2, y + 24 + size // 2 + 10, int(bw * k), 8),
                             border_radius=4)

        # 5) 粒子
        self.particles.draw(surf)
