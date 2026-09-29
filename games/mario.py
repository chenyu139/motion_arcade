"""
games/mario.py
==============
超级马里奥（横版平台跳跃）。

头部操作
    · 左右平移 → 跑动（速度与头部偏移量成正比）
    · 抬头     → 跳跃（连续抬头不会连跳，有冷却）
键盘兜底：← → / A D 移动，空格 / ↑ / W 跳跃
"""
from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple

import pygame

from core import art as A
from core import scene as SCN
from core import sprites as SP
from core import sichuan as SC
from core import config as C
from core import theme as U
from core.base import BaseGame, register
from core.inputs import GameInput

GROUND = 900
LEVEL_W = C.LEVEL_W
DEATH_Y = 1260

# 关卡数据：(x, y, w, kind)
#   ground 地面段 / brick 砖块 / q 问号砖 / solid 硬块 / cloud 云平台
PLATFORMS = [
    # 起始地面
    (0, GROUND, 1180, "ground"),
    (1300, GROUND, 700, "ground"),
    (2160, GROUND, 520, "ground"),
    (2860, GROUND, 900, "ground"),
    (3960, GROUND, 620, "ground"),
    (4740, GROUND, 1460, "ground"),
    # 空中平台
    (620, 720, 190, "brick"),
    (880, 596, 150, "q"),
    (1330, 700, 240, "brick"),
    (1640, 560, 150, "q"),
    (1820, 700, 180, "brick"),
    (2200, 660, 200, "cloud"),
    (2520, 520, 200, "cloud"),
    (2900, 700, 190, "brick"),
    (3120, 560, 150, "q"),
    (3320, 690, 220, "brick"),
    (3560, 500, 200, "cloud"),
    (4020, 660, 210, "brick"),
    (4300, 520, 170, "q"),
    (4560, 700, 160, "brick"),
    (4980, 690, 220, "cloud"),
    (5300, 540, 220, "cloud"),
    (5620, 690, 200, "brick"),
]

# 金币：(x, y)
COINS = [
    (660, 660), (700, 660), (740, 660), (910, 530), (950, 530),
    (1370, 640), (1420, 640), (1470, 640), (1670, 490), (1710, 490),
    (1890, 640), (2250, 600), (2300, 600), (2350, 600), (2570, 460),
    (2610, 460), (2960, 640), (3160, 490), (3200, 490), (3380, 630),
    (3600, 440), (3640, 440), (4070, 600), (4120, 600), (4340, 460),
    (4610, 640), (5030, 620), (5080, 620), (5350, 480), (5390, 480),
    (5670, 630), (5720, 630), (5770, 630),
]

# 敌人：(x, 巡逻左界, 巡逻右界)
FOES = [
    (700, 600, 1150), (1000, 900, 1150),
    (1420, 1310, 1950), (1750, 1310, 1950),
    (2260, 2170, 2650), (2450, 2170, 2650),
    (2990, 2870, 3700), (3200, 2870, 3700), (3450, 2870, 3700),
    (4120, 3970, 4540), (4350, 3970, 4540),
    (4900, 4750, 5500), (5150, 4750, 5500), (5380, 4750, 5500),
    (5700, 5560, 6150),
]

GOAL_X = 6020

SKY_TOP = (58, 122, 206)
SKY_BOT = (150, 202, 244)
HILL = (86, 168, 96)


def _mk_platform_surfaces():
    return {}


class _Cloud:
    """
    云。

    旧版是"一条平整的底 + 四个白圆 + 一条灰底"，看起来就是一串白气泡 ——
    因为**上沿和下沿一样亮**，没有体积。现在改用 scene.cloud_sprite：
    底部压暗、顶部受光、轮廓封闭，才像一团云而不是几个圆。
    """

    def __init__(self, x, y, s):
        self.x, self.y, self.s = x, y, s
        self.seed = int(x) % 97

    def draw(self, surf, cam):
        spr = SCN.cloud_sprite(int(270 * self.s), (252, 252, 255), 0.78, self.seed)
        surf.blit(spr, (int(self.x - cam - spr.get_width() / 2),
                        int(self.y - spr.get_height() * 0.60)))


@register
class MarioGame(BaseGame):
    KEY = "mario"
    TITLE = "超级马里奥"
    SUB = "横版平台跳跃"
    CATEGORY = "头部控制"
    ACCENT = (228, 76, 64)
    WORLD = "meadow"
    ICON = "mushroom"
    HOW = "踩着敌人往右冲到旗杆，别掉进坑里"
    HINT = "头部左右跑动 · 抬头起跳 · 踩敌人 +100 · 到旗杆通关"
    DIFFICULTY = 2
    ACHIEVEMENT = "抵达关卡终点旗杆"
    REQUIRES = ("head",)

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.px = 140.0
        self.py = GROUND - C.PLAYER_H
        self.vx = 0.0
        self.vy = 0.0
        self.on_ground = True
        self.face = 1
        self.coyote = 0.0
        self.jump_cd = 0.0
        self.jump_held = False
        self.run_phase = 0.0
        self.cam = 0.0
        self.coins_got = 0
        self.score = 0
        self.lives = C.START_LIVES
        self.time_left = float(C.LEVEL_TIME)
        self.invuln = 0.0
        self.death_t = 0.0
        self.foes = [[x, x, lo, hi, 1, 0.0, True] for x, lo, hi in FOES]  # x,vx,lo,hi,dir,phase,alive
        self.coins = [[x, y, random.uniform(0, 6.28), True] for x, y in COINS]
        self.used_q = set()
        self.bricks_broken = set()
        self.flag = 0.0
        self.win_t = 0.0
        self._sky = (SCN.sky_img(LEVEL_W + 240, C.DESIGN_H, "sky_day", tile_x=True)
                     or SCN.sky(C.DESIGN_W, C.DESIGN_H, SKY_TOP,
                                (120, 184, 236), SKY_BOT))
        # 云的数量与尺寸都要克制：26 朵 × 最大 1.35 倍会在天上连成一片"云墙"，
        # 反而把天空糊死。14 朵、0.45~0.95 倍才是有留白的云。
        self._clouds = [_Cloud(random.uniform(200, LEVEL_W), random.uniform(110, 430),
                               random.uniform(0.45, 0.95)) for _ in range(14)]
        # 少量**动态**背景云：整片背景都烘焙成静态图会变成"PPT"，
        # 留几朵缓慢横向漂移，画面立刻活起来（4 次 blit，开销可忽略）
        self._drift = [_Cloud(random.uniform(0, C.DESIGN_W * 2), random.uniform(140, 340),
                              random.uniform(0.40, 0.72)) for _ in range(3)]
        self._hills = [(random.uniform(0, LEVEL_W), random.uniform(150, 260),
                        random.uniform(0.8, 1.5)) for _ in range(18)]
        self._bushes = [(random.uniform(0, LEVEL_W), random.uniform(0.8, 1.4)) for _ in range(22)]
        self._coin_frames = [self._coin_frame(abs(math.cos(i / 12 * math.tau))) for i in range(12)]
        self._fit_bg()
        self.state = "play"

    def _fit_bg(self):
        """把背景烘焙成一张长图，避免每帧重画云和山。"""
        W = LEVEL_W + 240
        self._bg = pygame.Surface((W, C.DESIGN_H))
        # ---- 背景分层（远 → 近），层与层之间靠"大气透视"拉开纵深 ----
        # 旧版只有"天空 + 三角山 + 白云"三层，而且远近一样实，所以是平的。
        self._bg.blit(self._sky, (0, 0))
        # 1) 太阳：给整幅画面一个明确光源，之后所有受光都朝它对齐
        SCN.sun(self._bg, W * 0.42, 210, 62)
        # 2) 远景山脊：用圆润的正弦山形而不是地标剪影。
        #    旧版直接铺 `skyline(preset="mountain")`，但青城山那三层峰峦每座
        #    宽 500px、高 400px，三座一叠就并成了一块深色梯形，把画面从中间
        #    切成两半 —— 地标剪影适合"中景可辨认"，不适合当远景。
        # 山脊颜色必须明显深于该高度的天空，否则"大气透视"会变成"看不见"。
        # 第一版取 (120,168,206) 再混 42% 天空色，结果与天空几乎同色，
        # 远山完全隐形，只剩一条被雾洗白的横带。
        # ⚠ 每层的 rect 底边都必须压到地面高度（GROUND+16）：
        #   hill_range 只在 rect 内填充，rect 下方是透明的。
        #   之前给的是"刚好包住山高"的矩形，于是山层底部被整齐截断、
        #   下面漏出天空渐变 —— 在画面上就是一条贯穿全屏的横带。
        _BOT = GROUND + 16
        SCN.hill_range(self._bg, pygame.Rect(0, 296, W, _BOT - 296), 3,
                       (92, 138, 184), seed=21, h_min=0.34, h_max=1.0, haze=0.30)
        SCN.hill_range(self._bg, pygame.Rect(0, 352, W, _BOT - 352), 4,
                       (68, 118, 164), seed=33, h_min=0.28, h_max=0.96, haze=0.16)
        # 3) 雾带：只让第一排远山"退"一点，收窄到两排山之间，上下都归零。
        SCN.fog_band(self._bg, pygame.Rect(0, 292, W, 190), (202, 226, 246), 62)
        # 4) 中景丘陵：用正弦叠加的圆润山丘，而不是三角折线
        # 同理：中景丘陵的 rect 底边也要压到地面，否则又是一条横带
        SCN.hill_range(self._bg, pygame.Rect(0, GROUND - 300, W, _BOT - (GROUND - 300)), 5,
                       U.shade(HILL, 0.80), seed=7, h_min=0.12, h_max=0.52, haze=0.30)
        SCN.hill_range(self._bg, pygame.Rect(0, GROUND - 200, W, _BOT - (GROUND - 200)), 4,
                       HILL, seed=13, h_min=0.10, h_max=0.46, haze=0.10)
        for bx, bs in self._bushes:
            if bx > W:
                continue
            for dx, r in ((-46, 40), (0, 56), (48, 38)):
                U.aa_circle(self._bg, (bx + dx * bs, GROUND + 6), r * bs, (72, 158, 88), 0, ss=2)
        for c in self._clouds:
            c.draw(self._bg, 0)
        # 地面直接烘焙进背景：它是纯静态的，逐帧重画 1180×180 的地块既没必要也很贵
        for x, y, w, kind in PLATFORMS:
            if kind == "ground":
                self._draw_ground(self._bg, x, y, w)

    # ------------------------------------------------------------------ 平台
    def _platform_rects(self):
        for i, (x, y, w, kind) in enumerate(PLATFORMS):
            yield i, pygame.Rect(x, y, w, 60 if kind == "ground" else 34), kind

    def _solids_near(self, rect: pygame.Rect):
        out = []
        for i, r, kind in self._platform_rects():
            if kind == "brick" and i in self.bricks_broken:
                continue
            if r.right < rect.left - 120 or r.left > rect.right + 120:
                continue
            out.append((i, r, kind))
        return out

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            if self.state == "win":
                self.win_t += dt
                self.particles.update(dt)
                if self.win_t > 2.4:
                    self.finish(True)
            else:
                self.death_t += dt
                self.particles.update(dt)
                if self.death_t > 1.4:
                    self._respawn()
            return

        self.time_left -= dt
        if self.time_left <= 0:
            self.time_left = 0
            self._die()
            return

        # ---- 输入 ----
        axis = max(-1.0, min(1.0, inp.xc * 1.15))
        jump = inp.action
        if abs(axis) > 0.08:
            self.face = 1 if axis > 0 else -1

        target = axis * C.MAX_RUN
        accel = C.MOVE_ACCEL if self.on_ground else C.AIR_DECEL * 1.6
        if abs(target) > abs(self.vx):
            self.vx += math.copysign(accel * dt, target - self.vx)
        else:
            dec = C.GROUND_DECEL if self.on_ground else C.AIR_DECEL
            if self.vx > 0:
                self.vx = max(target, self.vx - dec * dt)
            else:
                self.vx = min(target, self.vx + dec * dt)

        # ---- 跳跃 ----
        self.jump_cd = max(0.0, self.jump_cd - dt)
        self.coyote = max(0.0, self.coyote - dt) if not self.on_ground else C.COYOTE_TIME
        if jump and not self.jump_held and self.jump_cd <= 0 and (self.on_ground or self.coyote > 0):
            self.vy = C.JUMP_VELOCITY
            self.on_ground = False
            self.coyote = 0.0
            self.jump_cd = C.JUMP_COOLDOWN
            self.jump_held = True
            self.shake(4, 0.10)
            self.particles.emit(self.px, self.py + C.PLAYER_H, 8, color=(236, 240, 250),
                                spread=90, vy=-60, gravity=520, life=0.35, size=3.4)
        if not jump:
            self.jump_held = False

        # ---- 重力 + 碰撞 ----
        self.vy = min(C.MAX_FALL, self.vy + C.GRAVITY * dt)
        rect = pygame.Rect(int(self.px), int(self.py), C.PLAYER_W, C.PLAYER_H)

        self.px += self.vx * dt
        rect.x = int(self.px)
        for i, r, kind in self._solids_near(rect):
            if kind == "cloud":
                continue
            if rect.colliderect(r):
                if self.vx > 0:
                    rect.right = r.left
                else:
                    rect.left = r.right
                self.px = float(rect.x)
                self.vx = 0.0

        self.py += self.vy * dt
        rect.y = int(self.py)
        was_air = not self.on_ground
        self.on_ground = False
        for i, r, kind in self._solids_near(rect):
            skip = (kind == "cloud" and self.vy <= 0)
            if skip:
                continue
            if rect.colliderect(r):
                if self.vy > 0:
                    rect.bottom = r.top
                    self.py = float(rect.y)
                    self.vy = 0.0
                    self.on_ground = True
                    if was_air:
                        self._land_dust()
                else:
                    rect.top = r.bottom
                    self.py = float(rect.y)
                    self.vy = 120.0
                    if kind in ("brick", "q"):
                        if kind == "q" and i not in self.used_q:
                            self.used_q.add(i)
                            self._pop_coin(r.centerx, r.top - 40)
                        elif kind == "brick":
                            self.bricks_broken.add(i)
                            self.shake(7, 0.18)
                            self.particles.emit(r.centerx, r.centery, 16,
                                                color=(196, 108, 64), spread=260,
                                                vy=-200, gravity=1500, life=0.7, size=6)
                    else:
                        self.shake(5, 0.12)

        if self.py > DEATH_Y:
            self._die()
            return

        # ---- 跑步动画 / 粒子 ----
        self.run_phase += abs(self.vx) * dt * 0.030
        if self.on_ground and abs(self.vx) > 160 and random.random() < 0.28:
            self.particles.emit(self.px - self.face * 16, self.py + C.PLAYER_H - 4, 1,
                                color=(226, 220, 206), spread=70, vy=-70,
                                gravity=420, life=0.30, size=3.0)

        # ---- 金币 ----
        for c in self.coins:
            if not c[3]:
                continue
            if abs(c[0] - self.px) < 44 and abs(c[1] - (self.py + C.PLAYER_H / 2)) < 52:
                c[3] = False
                self.coins_got += 1
                self.score += C.COIN_SCORE
                self.particles.emit(c[0], c[1], 10, color=(255, 216, 92),
                                    spread=180, vy=-140, gravity=520, life=0.5, size=4)
                if self.coins_got % 10 == 0:
                    self.lives += 1
                    self.set_msg("+1 生命", f"已收集 {self.coins_got} 金币", 1.2, (255, 214, 120))

        # ---- 敌人 ----
        if self.invuln > 0:
            self.invuln -= dt
        for f in self.foes:
            if not f[6]:
                continue
            f[0] += f[4] * 92.0 * dt
            if f[0] < f[2]:
                f[0] = float(f[2])
                f[4] = 1
            elif f[0] > f[3]:
                f[0] = float(f[3])
                f[4] = -1
            f[5] += dt * 9
            fx, fy = f[0], GROUND - 58
            if self.invuln <= 0 and abs(fx - self.px) < 46 and \
                    abs(fy - self.py) < C.PLAYER_H * 0.95:
                if self.vy > 60 and self.py + C.PLAYER_H < fy + 46:
                    f[6] = False
                    self.score += C.STOMP_SCORE
                    self.vy = C.STOMP_BOUNCE
                    self.shake(6, 0.16)
                    self.particles.emit(fx, fy, 18, color=(180, 132, 84),
                                        spread=240, vy=-160, gravity=1500, life=0.6, size=5)
                elif self.invuln <= 0:
                    self._die()
                    return

        # ---- 终点 ----
        if self.px > GOAL_X:
            self.flag = min(1.0, self.flag + dt * 1.4)
            if self.flag >= 1.0:
                self.state = "win"
                self.win_t = 0.0
                self.score += C.GOAL_SCORE + int(self.time_left) * C.TIME_BONUS_PER_SEC
                self.shake(12, 0.5)
                self.flash((255, 250, 210), 0.55)
                self.particles.emit(GOAL_X, 640, 90, color=(255, 224, 120),
                                    spread=420, vy=-260, gravity=760, life=1.6, size=6)

        # ---- 摄像机 ----
        want = self.px - C.DESIGN_W * 0.34
        self.cam = max(0.0, min(LEVEL_W - C.DESIGN_W, want))

    def _land_dust(self):
        self.particles.emit(self.px, self.py + C.PLAYER_H, 9, color=(232, 226, 210),
                            spread=140, vy=-90, gravity=680, life=0.34, size=3.6)

    def _pop_coin(self, x, y):
        self.coins_got += 1
        self.score += C.COIN_SCORE
        self.particles.emit(x, y, 14, color=(255, 216, 92), spread=190,
                            vy=-320, gravity=1100, life=0.7, size=4.6)
        self.shake(4, 0.12)

    def _die(self):
        if self.state != "play":
            return
        self.lives -= 1
        self.state = "over"
        self.death_t = 0.0
        self.shake(14, 0.5)
        self.particles.emit(self.px, self.py + C.PLAYER_H / 2, 26, color=(255, 120, 96),
                            spread=280, vy=-220, gravity=900, life=0.9, size=5.5)

    def _respawn(self):
        if self.lives <= 0:
            self.state = "over"
            self.death_t = 999.0
            self.finish(False)
            return
        self.px, self.py = 140.0, GROUND - C.PLAYER_H
        self.vx = self.vy = 0.0
        self.cam = 0.0
        self.invuln = 1.6
        self.time_left = float(C.LEVEL_TIME)
        self.foes = [[x, x, lo, hi, 1, 0.0, True] for x, lo, hi in FOES]
        self.state = "play"

    # ------------------------------------------------------------------ 绘制
    def _style(self):
        return A.FigureStyle(shirt=(214, 60, 52), shirt2=(58, 92, 192),
                             pants=(58, 92, 192), skin=(248, 208, 172),
                             hair=(180, 46, 40), shoes=(96, 62, 40),
                             hair_style="helm", outline=(26, 20, 22))

    def draw(self, surf: pygame.Surface) -> None:
        cam = int(self.cam)
        surf.blit(self._bg, (-cam, 0))
        # 动态背景云：按 0.45 视差缓慢漂移。
        # 需求里明确要求"少量动态背景元素" —— 背景全烘焙会变成静态 PPT，
        # 这几朵云只花 4 次 blit，却让整个天空"活着"。
        for c in self._drift:
            c.x += 9.0 / 60.0
            if c.x - cam * 0.45 > C.DESIGN_W + 300:
                c.x -= C.DESIGN_W + 640
            spr = SCN.cloud_sprite(int(300 * c.s), (255, 255, 255), 0.76, c.seed)
            dy = 34
            surf.blit(spr, (int(c.x - cam * 0.45 - spr.get_width() / 2), int(c.y - dy)),
                      special_flags=0)

        # ---- 平台（地面已在背景里烘焙好）----
        for i, (x, y, w, kind) in enumerate(PLATFORMS):
            sx = x - cam
            if sx > C.DESIGN_W + 80 or sx + w < -80:
                continue
            if kind == "ground":
                continue
            if kind in ("brick", "q"):
                if i in self.bricks_broken:
                    continue
                self._draw_block(surf, sx, y, w, kind, i in self.used_q)
            else:
                self._draw_cloud_plat(surf, sx, y, w)

        # ---- 金币 ----
        for x, y, ph, alive in self.coins:
            if not alive:
                continue
            sx = x - cam
            if sx < -60 or sx > C.DESIGN_W + 60:
                continue
            self._draw_coin(surf, sx, y, self.t * 3.2 + ph)

        # ---- 敌人 ----
        for f in self.foes:
            if not f[6]:
                continue
            sx = f[0] - cam
            if sx < -90 or sx > C.DESIGN_W + 90:
                continue
            self._draw_goomba(surf, sx, GROUND, f[5], f[4])

        # ---- 旗杆 ----
        self._draw_goal(surf, GOAL_X - cam)

        # ---- 玩家 ----
        self._draw_player(surf, cam)

        self.particles.draw(surf)
        self.draw_msg(surf)

    def _draw_ground(self, surf, x, y, w):
        h = C.DESIGN_H - y
        top = U.vgrad(w, 26, (112, 190, 100), (70, 146, 74))
        surf.blit(top, (x, y))
        # 草皮顶缘：受光亮边（光源在左上）+ 一层环境光遮蔽暗带。
        # 这两条线是"物体坐在地面上"的关键，缺了地面就是一块贴上去的色板。
        pygame.draw.line(surf, (168, 226, 148), (x, y + 2), (x + w, y + 2), 4)
        ao = pygame.Surface((w, 10), pygame.SRCALPHA)
        for i in range(10):
            ao.fill((0, 0, 0, int(70 * (1 - i / 9.0) ** 1.3)), (0, i, w, 1))
        surf.blit(ao, (x, y + 24))
        body = A.shade_panel(w, h, (140, 98, 62), 0, 1.0, 0.70)
        surf.blit(body, (x, y + 26))
        # 泥土颗粒感（左右交替，避免形成规则网格）
        for gi, gx in enumerate(range(0, w, 46)):
            off = 12 if gi % 2 else 0
            surf.fill((116, 80, 50), (int(x + gx + 6 + off), y + 40, 16, 10))
            surf.fill((156, 112, 72), (int(x + gx + 28 - off), y + 62, 20, 12))
        pygame.draw.line(surf, (74, 48, 30), (x, y + 26), (x + w, y + 26), 3)

    def _draw_block(self, surf, x, y, w, kind, used):
        for bx in range(0, w, 46):
            r = pygame.Rect(int(x + bx), int(y), 46, 34)
            if r.right < 0 or r.left > C.DESIGN_W:
                continue
            if kind == "q":
                base = (196, 148, 62) if not used else (132, 96, 62)
                surf.blit(A.shade_panel(46, 34, base, 4), (r.x, r.y))
                if not used:
                    pulse = 0.5 + 0.5 * math.sin(self.t * 5)
                    U.text(surf, "?", (r.centerx, r.centery), int(22 + 3 * pulse),
                           (255, 248, 214), center=True, bold=True)
                    surf.blit(U.glow_surface(34, (255, 224, 120), int(38 + 34 * pulse), 6),
                              (r.centerx - 34, r.centery - 34))
            else:
                surf.blit(A.shade_panel(46, 34, (172, 88, 58), 4), (r.x, r.y))
                for k in range(2):
                    surf.fill((132, 64, 42), (r.x + 3, r.y + 5 + k * 16, 40, 3))
                surf.fill((206, 122, 82), (r.x + 2, r.y + 2, 42, 3))

    def _draw_cloud_plat(self, surf, x, y, w):
        for cx in range(0, w + 60, 70):
            U.aa_circle(surf, (x + cx, y + 16), 38, (250, 250, 255), 0, ss=2)
        U.aa_ellipse(surf, (int(x - 24), int(y + 8), int(w + 48), 42), (246, 248, 255), 0, ss=2)
        U.aa_ellipse(surf, (int(x - 20), int(y + 26), int(w + 40), 16), (206, 218, 240), 0, ss=2)

    def _draw_coin(self, surf, x, y, ph):
        """金币优先用 AI 生成的熊猫金币精灵，带回退的程序动画。"""
        h = 46 * (1.0 + 0.14 * abs(math.cos(ph)))
        if SP.draw(surf, "coin", x, y, height=h, anchor="center"):
            return
        idx = int(ph / math.tau * 12) % 12
        f = self._coin_frames[idx]
        surf.blit(f, (int(x - f.get_width() / 2), int(y - f.get_height() / 2)))

    @staticmethod
    def _coin_frame(k: float) -> pygame.Surface:
        w = max(3.0, 20.0 * k)
        W = int(w * 2) + 64
        H = 46 + 60

        def _d(s):
            # 光晕（直接烘进帧里，省掉一次独立 blit）
            for i in range(9, 0, -1):
                a = int(62 * (1 - i / 9) ** 1.6) + 2
                pygame.draw.circle(s, (255, 208, 90, a), (W * 3 // 2, H * 3 // 2),
                                   int((30 + i * 3) * 3))
            cx, cy = W * 3 // 2, H * 3 // 2
            pygame.draw.ellipse(s, (246, 176, 40),
                                pygame.Rect(int(cx - w * 3), int(cy - 66), int(w * 6), 132))
            pygame.draw.ellipse(s, (255, 216, 96),
                                pygame.Rect(int(cx - w * 0.62 * 3), int(cy - 48),
                                            int(w * 1.24 * 3), 96))
            if w > 10:
                pygame.draw.ellipse(s, (255, 244, 190),
                                    pygame.Rect(int(cx - w * 0.22 * 3), int(cy - 27),
                                                int(w * 0.44 * 3), 54))
        return U.bake_raw(("cf", round(k, 3)), (W, H), _d, 3)

    def _draw_goomba(self, surf, x, ground, phase, dirn):
        y = ground - 58
        bob = math.sin(phase) * 3
        if SP.draw(surf, "enemy", x, y + bob + 58, height=96, anchor="bottom",
                   flip=(dirn < 0)):
            return
        # 回退：程序绘制的板栗仔
        body = A.shade_ball(29, (168, 116, 74), ss=3)
        surf.blit(body, (int(x - 29), int(y + bob)))
        surf.blit(A.shade_ball(20, (206, 158, 108), ss=3), (int(x - 46), int(y + 4 + bob * 2)))
        surf.blit(A.shade_ball(20, (206, 158, 108), ss=3), (int(x + 6), int(y + 4 + bob * 2)))
        for ex in (-11, 6):
            U.aa_ellipse(surf, (int(x + ex), int(y + 18 + bob), 11, 15), (250, 250, 252), 0, ss=2)
            U.aa_circle(surf, (x + ex + 5.5 + dirn * 1.6, y + 26 + bob), 3.4, (32, 26, 30), 0, ss=2)
        U.aa_ellipse(surf, (int(x - 16), int(y + 42 + bob), 32, 10), (92, 62, 40), 0, ss=2)
        # 脚
        U.aa_ellipse(surf, (int(x - 26), int(y + 48), 22, 12), (78, 52, 34), 0, ss=2)
        U.aa_ellipse(surf, (int(x + 4), int(y + 48), 22, 12), (78, 52, 34), 0, ss=2)

    def _draw_goal(self, surf, x):
        if x < -160 or x > C.DESIGN_W + 160:
            return
        top, bot = 300, GROUND
        surf.blit(A.shade_panel(16, bot - top, (198, 204, 216), 6), (int(x - 8), top))
        U.aa_circle(surf, (x, top - 12), 20, (255, 214, 92), 0, ss=3)
        surf.blit(U.glow_surface(46, (255, 224, 130), 90, 7), (int(x - 46), top - 58))
        fy = top + 20 + (bot - top - 60) * self.flag
        pts = [(x - 4, fy), (x - 4, fy + 70), (x - 108, fy + 44)]
        U.aa_poly(surf, pts, (232, 66, 62), 0, ss=3)
        U.aa_poly(surf, [(x - 14, fy + 12), (x - 14, fy + 58), (x - 92, fy + 40)],
                  (250, 250, 250), 0, ss=3)
        surf.blit(A.shade_panel(64, 44, (152, 156, 168), 6), (int(x - 40), GROUND - 44))

    def _draw_player(self, surf, cam):
        x = self.px - cam
        foot = self.py + C.PLAYER_H
        if self.invuln > 0 and int(self.invuln * 14) % 2 == 0:
            return
        spd = abs(self.vx)
        if not self.on_ground:
            pose = A.pose(lean=0.18, arm_l=-2.2, arm_r=-2.0,
                          leg_l=-0.55, leg_l2=0.95, leg_r=0.5, leg_r2=0.35,
                          flip=self.face, squash=0.94)
        elif spd > 60:
            s = math.sin(self.run_phase)
            pose = A.pose(lean=0.26, arm_l=-s * 1.5, arm_l2=0.7 + s * 0.3,
                          arm_r=s * 1.5, arm_r2=0.7 - s * 0.3,
                          leg_l=-s * 1.05, leg_l2=0.55 + max(0, s) * 0.7,
                          leg_r=s * 1.05, leg_r2=0.55 + max(0, -s) * 0.7,
                          flip=self.face)
        else:
            breathe = math.sin(self.t * 2.4) * 0.05
            pose = A.pose(lean=0.05, arm_l=-0.18 - breathe, arm_r=0.18 + breathe,
                          leg_l=-0.06, leg_r=0.06, flip=self.face)
        spr = A.figure_cached(98, self._style(), pose, ss=3)
        A.draw_figure(surf, spr, x, foot, 26)
        if self.invuln > 0:
            surf.blit(U.glow_surface(84, (150, 210, 255), 60, 7), (int(x - 84), int(foot - 100 - 84)))

    def hud_items(self):
        return [
            ("分数", f"{self.score}", (255, 255, 255)),
            ("金币", f"{self.coins_got}", (250, 210, 80)),
            ("生命", f"{self.lives}", (238, 96, 88), "heart"),
            ("时间", f"{int(self.time_left)}", (255, 255, 255)),
        ]

    def result_title(self) -> str:
        return "通 关 ！" if self.state == "win" else "游 戏 结 束"

    def result_sub(self) -> str:
        return f"得分 {self.score}　金币 {self.coins_got}　剩余生命 {max(0, self.lives)}"
