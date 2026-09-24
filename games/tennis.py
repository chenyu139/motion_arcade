"""
games/tennis.py
===============
川网 · 底线对拉 —— 2026 四川城市网球联赛主题底线对拉。

头部操作
    · 左右平移 → 沿底线跑位
    · 抬头     → 挥拍（拍面与球的距离决定 完美 / 良好 / 勉强）
玩法
    先到 5 分获胜。对手 AI 会主动往你站位的另一侧调动，回合越长体力越低。
"""
from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple

import pygame

from core import art as A
from core import sichuan as SC
from core import config as C
from core import theme as U
from core.base import BaseGame, register
from core.inputs import GameInput

GROUND = 892
NET_X = 960
NET_TOP = GROUND - 214
COURT_L, COURT_R = 60, 1860
P_MIN, P_MAX = 380, 726
OPP_MIN, OPP_MAX = 1206, 1560
SKY_TOP, SKY_BOT = (18, 40, 84), (96, 156, 208)


@register
class TennisGame(BaseGame):
    KEY = "tennis"
    TITLE = "川网 · 底线对拉"
    SUB = "2026 四川城市网球联赛"
    CATEGORY = "头部控制"
    ACCENT = (96, 196, 244)
    ICON = "racket"
    HOW = "跑到位、抬头挥拍，先到 5 分"
    HINT = "头部左右跑位 · 抬头挥拍 · 看准拍面与球的距离"
    DIFFICULTY = 2
    ACHIEVEMENT = "先得 5 分赢得比赛"
    REQUIRES = ("head",)
    WIN_SCORE = C.TN_WIN_SCORE

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.my_score = 0
        self.op_score = 0
        self.rally = 0
        self.longest = 0
        self.px = (P_MIN + P_MAX) / 2
        self.opx = (OPP_MIN + OPP_MAX) / 2
        self.op_tx = self.opx
        self.swing = 0.0
        self.swing_cool = 0.0
        self.last_quality = ""
        self.hit_marks: List[dict] = []
        self.ball: Optional[dict] = None
        self.op_fatigue = 1.0
        self.serve_t = 1.1
        self.point_msg = ""
        self.point_t = 0.0
        self.rally_flash = 0.0
        self.best_rally = 0
        self._build_scene()
        self._serve()

    # ------------------------------------------------------------------ 场景
    def _build_scene(self):
        W, H = self.W, self.H
        self._bg = pygame.Surface((W, H))
        self._bg.blit(U.vgrad3(W, H, SKY_TOP, (48, 92, 148), SKY_BOT), (0, 0))
        # 川西自然天际线：九寨沟 / 稻城 / 峨眉 / 蜀南竹海
        self._bg.blit(SC.skyline(W, 186, preset="nature", base=(44, 62, 92),
                                 haze=0.34, seed=6, count=6), (0, 272))
        # 远景看台
        self._bg.blit(A.crowd_stand(W, 226, seed=12, rows=7, lit=-0.12), (0, 432))
        self._bg.blit(A.shade_panel(W, 34, (26, 34, 56), 0, 1.0, 0.72), (0, 512))
        # 球场
        self._court_top = 546
        court_h = H - self._court_top
        court = A.hard_court(W, court_h, (52, 112, 176), (26, 66, 118))
        self._bg.blit(court, (0, self._court_top))
        self._paint_lines()
        A.stadium_lights(self._bg, [200, 960, 1720], 120, 150, cone_to=620)

    def _paint_lines(self):
        """画球场白线（含透视的边线、发球区、底线）。"""
        s = self._bg
        ct = self._court_top
        h = self.H - ct
        # 地面白线
        U.aa_line(s, (COURT_L, GROUND), (COURT_R, GROUND), (238, 244, 250, 190), 6)
        # 边线（上方收缩，制造透视）
        U.aa_line(s, (COURT_L + 130, ct + 4), (COURT_L, GROUND), (238, 244, 250, 150), 4)
        U.aa_line(s, (COURT_R - 130, ct + 4), (COURT_R, GROUND), (238, 244, 250, 150), 4)
        # 发球区横线
        y_srv = ct + int((GROUND - ct) * 0.62)
        U.aa_line(s, (COURT_L + 74, y_srv), (COURT_R - 74, y_srv), (238, 244, 250, 130), 4)
        # 中线
        U.aa_line(s, (NET_X, y_srv), (NET_X, GROUND), (238, 244, 250, 110), 3)

    # ------------------------------------------------------------------ 回合
    def _serve(self):
        self.ball = None
        self.serve_t = 1.0
        self.rally = 0
        self.op_tx = random.uniform(OPP_MIN, OPP_MAX)

    def _launch(self, from_player: bool):
        """把球从某一侧打向另一侧（解析解求飞行时间，保证过网）。"""
        if from_player:
            x0, y0 = self.px + 96, GROUND - 116
            tgt = random.uniform(OPP_MIN - 40, OPP_MAX + 60)
            vy0 = -700.0
        else:
            x0, y0 = self.opx - 96, GROUND - 124
            tgt = random.uniform(P_MIN - 60, P_MAX + 60)
            vy0 = -660.0
        b = {"x": x0, "y": y0, "vx": 0.0, "vy": vy0, "t": 0.0,
             "who": "me" if from_player else "op", "bounces": 0, "rot": 0.0}
        self._set_vx_vy(b, tgt - x0, vy0)
        self.ball = b

    @staticmethod
    def _set_vx_vy(b: dict, dx: float, vy0: float):
        """
        斜抛飞行时间取解析解 t = (−vy0 + √(vy0² + 2g(y1−y0))) / g，
        而不是 2|vy0|/g（那只算"回到出发高度"的时间，会让球早于落点落地）。
        """
        g = C.TN_BALL_GRAVITY
        y0 = b["y"]
        y1 = GROUND - 10
        disc = max(0.0, vy0 * vy0 + 2.0 * g * (y1 - y0))
        t = (-vy0 + math.sqrt(disc)) / g
        t = max(0.42, min(3.2, t))
        b["vx"] = dx / t
        b["vy"] = vy0

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            self.point_t += dt
            return
        self.swing = max(0.0, self.swing - dt * 4.2)
        self.swing_cool = max(0.0, self.swing_cool - dt)
        if self.rally_flash > 0:
            self.rally_flash = max(0.0, self.rally_flash - dt * 2.4)
        for m in self.hit_marks:
            m["t"] -= dt
        self.hit_marks = [m for m in self.hit_marks if m["t"] > 0]

        # ---- 我方跑位 ----
        self.px += inp.xc * 620.0 * dt
        self.px = U.clamp(self.px, P_MIN, P_MAX)

        # ---- 对手跑位（回合越长越快，但会疲劳）----
        sp = U.lerp(300.0, 520.0, min(1.0, self.rally / 7.0)) * self.op_fatigue
        if abs(self.opx - self.op_tx) > 8:
            self.opx += math.copysign(min(sp * dt, abs(self.op_tx - self.opx)),
                                      self.op_tx - self.opx)

        # ---- 发球 ----
        if self.ball is None:
            self.serve_t -= dt
            if self.serve_t <= 0:
                self._launch(from_player=True)
                self.set_msg("发球", "", 0.6, (200, 232, 255))
            return

        # ---- 挥拍 ----
        if inp.action and self.swing_cool <= 0:
            self._do_swing()

        # ---- 球 ----
        b = self.ball
        b["t"] += dt
        b["vy"] += C.TN_BALL_GRAVITY * dt
        b["x"] += b["vx"] * dt
        b["y"] += b["vy"] * dt
        b["rot"] += b["vx"] * dt * 0.012

        # 触地
        if b["y"] >= GROUND - 10 and b["vy"] > 0:
            b["y"] = GROUND - 10
            b["vy"] = -abs(b["vy"]) * 0.56
            b["vx"] *= 0.86
            b["bounces"] += 1
            self.particles.emit(b["x"], GROUND - 6, 8, color=(220, 232, 246),
                                spread=140, vy=-110, gravity=700, life=0.4, size=3)
            if b["bounces"] >= 2:
                self._point("me" if b["who"] == "op" else "op",
                            "对手回球出界" if b["who"] == "op" else "两次落地")
                return

        # 撞网
        if abs(b["x"] - NET_X) < 12 and b["y"] > NET_TOP:
            self._point("me" if b["who"] == "op" else "op",
                        "下网" if b["who"] == "me" else "对手下网")
            return
        # 出界
        if b["x"] < COURT_L + 6 or b["x"] > COURT_R - 6:
            self._point("me" if b["who"] == "op" else "op", "出界")
            return

        # 对手击球判定
        if b["who"] == "me" and b["x"] > self.opx - 46 and b["y"] > GROUND - 300 and b["vy"] > 0:
            self._opponent_hit(b)
        # 我方未击中而球已到身后
        if b["who"] == "me" and b["x"] > P_MAX + 130 and b["vy"] > 0:
            self._point("op", "未能回球")
            return

    def _do_swing(self):
        self.swing = 1.0
        self.swing_cool = 0.34
        b = self.ball
        if b is None or b["who"] != "op":
            return
        d = abs((self.px + 72) - b["x"])
        if d <= C.TN_HIT_PERFECT:
            q, col = "完美", (255, 226, 120)
        elif d <= C.TN_HIT_GOOD:
            q, col = "良好", (150, 236, 190)
        elif d <= C.TN_HIT_RANGE:
            q, col = "勉强", (255, 186, 130)
        else:
            self.last_quality = ""
            self.hit_marks.append({"x": self.px + 72, "y": GROUND - 150, "t": 0.4,
                                   "col": (255, 130, 110), "txt": "挥空"})
            return
        self.last_quality = q
        self.rally += 1
        self.longest = max(self.longest, self.rally)
        self.op_fatigue = max(0.80, 1.0 - self.rally * 0.010)
        self.hit_marks.append({"x": b["x"], "y": b["y"], "t": 0.5, "col": col, "txt": q})
        self.particles.emit(b["x"], b["y"], 16, color=col, spread=240,
                            vy=-120, gravity=520, life=0.5, size=4)
        self.shake(5 if q == "完美" else 3, 0.14)
        if self.rally > 0 and self.rally % 5 == 0:
            self.rally_flash = 1.0
            self.set_msg(f"{self.rally} 拍！", "耐力在下降", 1.0, (255, 226, 150))
        # 回球：完美球更刁钻，勉强球更软
        self._launch(from_player=True)
        if q == "完美":
            b2 = self.ball
            b2["vx"] *= 1.16

    def _opponent_hit(self, b):
        dx = abs(b["x"] - self.opx)
        base = {"完美": 0.95, "良好": 0.985, "勉强": 0.996}.get(self.last_quality, 0.97)
        pos = 0.995 if dx < 70 else (0.96 if dx < 120 else 0.83)
        if random.random() < base * pos:
            # 明确瞄准我方半场的落点，保证球是"打进界内"的
            tgt = self.px + random.choice([-1, 1]) * random.uniform(150, 420)
            tgt = U.clamp(tgt, P_MIN - 40, P_MAX + 40)
            b["who"] = "op"
            self._set_vx_vy(b, tgt - b["x"], -640.0)
            self.rally += 1
            self.longest = max(self.longest, self.rally)
            self.op_tx = random.uniform(OPP_MIN, OPP_MAX)
            self.particles.emit(b["x"], b["y"], 12, color=(140, 220, 255),
                                spread=200, vy=-100, gravity=520, life=0.45, size=4)
        else:
            self._point("me", "对手回球失误")

    def _point(self, who: str, why: str):
        self.hit_marks.clear()
        gain_rally = self.rally
        self.point_t = 0.0
        self.point_msg = why
        if who == "me":
            self.my_score += 1
            self.set_msg("得分！", why, 1.2, (150, 244, 196))
            self.flash((180, 255, 220), 0.22)
        else:
            self.op_score += 1
            self.set_msg("丢分", why, 1.2, (255, 176, 140))
            self.shake(9, 0.3)
        self.best_rally = max(self.best_rally, gain_rally)
        # 重新发球
        self.ball = None
        self.serve_t = 1.3
        self.rally = 0
        self.last_quality = ""
        if self.my_score >= self.WIN_SCORE:
            self.finish(True)
            self.flash((255, 250, 210), 0.5)
        elif self.op_score >= self.WIN_SCORE:
            self.finish(False)

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        self._draw_net(surf)
        self._draw_player(surf)
        self._draw_opponent(surf)
        if self.ball is not None:
            b = self.ball
            A.draw_ball(surf, b["x"], b["y"], 20, "tennis", rot=b["rot"],
                        shadow=0.7, ground_y=GROUND - 4)
        for m in self.hit_marks:
            k = m["t"] / 0.5
            U.text(surf, m["txt"], (m["x"], m["y"] - 30 - (1 - k) * 40), int(26 + 8 * k),
                   m["col"], center=True, bold=True, glow=10, glow_color=m["col"],
                   alpha=int(255 * min(1.0, k * 2.4)))
        self._draw_score(surf)
        self.particles.draw(surf)
        if self.rally_flash > 0:
            ov = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            ov.fill((255, 240, 180, int(34 * self.rally_flash)))
            surf.blit(ov, (0, 0))
        self.draw_msg(surf)
        if self.ball is None and self.serve_t > 0 and self.state == "play":
            U.text(surf, "准备接发球…", (self.W // 2, GROUND - 300), 32,
                   (216, 232, 252), center=True, alpha=180)

    def _draw_net(self, surf):
        x = NET_X
        # 网面
        mesh = pygame.Surface((64, GROUND - NET_TOP + 10), pygame.SRCALPHA)
        w, h = mesh.get_size()
        for i in range(0, w + 1, 7):
            pygame.draw.line(mesh, (232, 240, 250, 96), (i, 0), (i, h), 1)
        for j in range(0, h + 1, 8):
            pygame.draw.line(mesh, (232, 240, 250, 96), (0, j), (w, j), 1)
        surf.blit(mesh, (x - w // 2, NET_TOP))
        # 网带
        surf.blit(A.shade_panel(70, 18, (246, 250, 254), 6), (x - 35, NET_TOP - 4))
        # 网柱
        surf.blit(A.shade_panel(10, GROUND - NET_TOP + 14, (176, 186, 202), 4),
                  (x - 5, NET_TOP - 8))
        surf.blit(U.glow_surface(70, self.ACCENT, 40, 7), (x - 70, NET_TOP - 70))

    def _me_style(self):
        return A.FigureStyle(shirt=(246, 248, 252), shirt2=(228, 76, 96),
                             pants=(30, 38, 58), skin=(242, 202, 168),
                             hair=(40, 30, 32), shoes=(240, 244, 250),
                             hair_style="pony", number="7")

    def _op_style(self):
        return A.FigureStyle(shirt=(58, 108, 206), shirt2=(240, 244, 252),
                             pants=(238, 242, 250), skin=(236, 192, 156),
                             hair=(28, 24, 28), shoes=(50, 96, 190),
                             hair_style="short", number="2")

    def _draw_player(self, surf):
        h = 248
        sw = self.swing
        if sw > 0.05:
            pose = A.pose(lean=0.30, arm_l=-0.5, arm_r=-2.35 + sw * 0.5, arm_r2=0.3,
                          leg_l=-0.32, leg_r=0.36, crouch=0.22, flip=1)
        else:
            b = math.sin(self.t * 3.0) * 0.06
            pose = A.pose(lean=0.16, arm_l=-0.55 - b, arm_r=0.35 + b, arm_r2=0.55,
                          leg_l=-0.20, leg_r=0.22, crouch=0.30, flip=1)
        spr = A.figure_cached(h, self._me_style(), pose, ss=3)
        U.aa_ellipse(surf, (int(self.px - 56), GROUND - 14, 112, 26), (0, 0, 0, 84), 0, ss=2)
        A.draw_figure(surf, spr, self.px, GROUND + 4, 26)
        # 拍面
        rx = self.px + 72 + sw * 46
        ry = GROUND - 150 - sw * 66
        ang = -0.5 + sw * 2.3
        U.aa_ellipse(surf, (int(rx - 30), int(ry - 40), 60, 80), (24, 30, 46), 0, ss=3)
        U.aa_ellipse(surf, (int(rx - 24), int(ry - 34), 48, 68), (60, 200, 236), 0, ss=3)
        for j in range(4):
            U.aa_line(surf, (rx - 16, ry - 26 + j * 16), (rx + 16, ry - 26 + j * 16),
                      (232, 246, 252, 120), 2)
        U.aa_line(surf, (rx, ry + 40), (rx, ry + 74), (36, 44, 62), 8)
        if sw > 0.4:
            U.aa_arc(surf, (rx, ry), 62, (150, 240, 255, 150), -1.2, 1.0, 6)

    def _draw_opponent(self, surf):
        h = 240
        pose = A.pose(lean=-0.20, arm_l=0.6, arm_r=-0.4, leg_l=0.24, leg_r=-0.22,
                      crouch=0.26, flip=-1)
        spr = A.figure_cached(h, self._op_style(), pose, ss=3)
        U.aa_ellipse(surf, (int(self.opx - 54), GROUND - 14, 108, 26), (0, 0, 0, 84), 0, ss=2)
        A.draw_figure(surf, spr, self.opx, GROUND + 4, 26)
        rx = self.opx - 66
        ry = GROUND - 146
        U.aa_ellipse(surf, (int(rx - 28), int(ry - 38), 56, 76), (24, 30, 46), 0, ss=3)
        U.aa_ellipse(surf, (int(rx - 22), int(ry - 32), 44, 64), (86, 140, 226), 0, ss=3)

    def _draw_score(self, surf):
        w, h = 460, 110
        x, y = self.W // 2 - w // 2, 118
        U.soft_shadow(surf, pygame.Rect(x, y, w, h), 18, 18, 130, (0, 9))
        U.glass(surf, pygame.Rect(x, y, w, h), 18, (10, 16, 34, 220), (140, 180, 226, 130), 2)
        U.text(surf, "我", (x + 74, y + 20), 26, (200, 224, 250), center=True)
        U.text(surf, f"{self.my_score}", (x + 74, y + 54), 62, (150, 244, 196), center=True, bold=True)
        U.text(surf, ":", (x + w // 2, y + 54), 52, (160, 180, 210), center=True, bold=True)
        U.text(surf, "对手", (x + w - 74, y + 20), 26, (200, 224, 250), center=True)
        U.text(surf, f"{self.op_score}", (x + w - 74, y + 54), 62, (255, 178, 150),
               center=True, bold=True)
        U.text(surf, f"本回合 {self.rally} 拍", (self.W // 2, y + h + 18), 24,
               (206, 224, 248), center=True)

    def hud_items(self):
        return [
            ("比分", f"{self.my_score} : {self.op_score}", (255, 255, 255)),
            ("本回合", f"{self.rally} 拍", (150, 232, 255)),
            ("最长回合", f"{self.best_rally} 拍", (255, 214, 130)),
        ]

    def result_title(self) -> str:
        return "赢 下 比 赛 ！" if self.state == "win" else "惜 败"

    def result_sub(self) -> str:
        return (f"比分 {self.my_score} : {self.op_score}　"
                f"最长回合 {self.best_rally} 拍")
