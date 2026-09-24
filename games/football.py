"""
games/football.py
=================
川超 · 点球王 —— 2025/2026 四川省城市足球联赛主题点球大战。

头部操作
    · 左右平移 → 横向瞄准球门
    · 抬头     → 起脚射门（抬头高度决定打上角还是下角）
玩法
    10 次射门，进 6 球获胜。守门员会随难度提高移动速度与"读心"概率。
    打中死角 +60，连续命中每级 +50。
"""
from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple

import pygame

from core import art as A
from core import config as C
from core import theme as U
from core.base import BaseGame, register
from core.inputs import GameInput

# ---- 场景几何（1920×1080 设计坐标）----
GOAL_L, GOAL_R = 500, 1420
CROSSBAR_Y = 392
GOAL_LINE_Y = 700
GOAL_DEPTH = 150                     # 球门纵深（透视）
BALL_X0, BALL_Y0 = 960, 936
KEEPER_W, KEEPER_H = 112, 232

TEAMS = [
    ("成都锦城", (208, 62, 68)),
    ("达州川汉子", (44, 96, 188)),
    ("凉山好医生", (56, 168, 128)),
    ("宜宾长江首城", (238, 148, 56)),
    ("绵阳科技城", (124, 88, 208)),
    ("乐山味道", (232, 92, 152)),
    ("自贡盐帮", (76, 196, 220)),
    ("德阳重装", (156, 164, 180)),
    ("遂宁观音故里", (196, 176, 72)),
    ("内江甜城", (108, 200, 96)),
]

LED_TEXTS = ["川超", "四川观察", "雄起", "川越山海", "为四川而战", "天府之国"]


@register
class FootballGame(BaseGame):
    KEY = "football"
    TITLE = "川超 · 点球王"
    SUB = "四川省城市足球联赛"
    CATEGORY = "头部控制"
    ACCENT = (72, 196, 138)
    ICON = "football"
    HOW = "瞄准球门死角，抬头起脚，10 球进 6 球"
    HINT = "头部左右瞄准 · 抬头射门 · 死角 +60 · 连击加成"
    DIFFICULTY = 2
    ACHIEVEMENT = "10 次射门中打进 6 球"
    REQUIRES = ("head",)
    MSG_Y = 226
    SHOTS = C.FB_SHOTS

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.shot_i = 0
        self.goals = 0
        self.score = 0
        self.combo = 0
        self.best_combo = 0
        self.history: List[str] = []
        self.aim_x = (GOAL_L + GOAL_R) / 2
        self.aim_dir = 1
        self.aim_y = 0.55            # 0 上角 → 1 下角
        self.keeper_x = (GOAL_L + GOAL_R) / 2
        self.keeper_tx = self.keeper_x
        self.keeper_dive = 0.0
        self.keeper_dir = 0.0
        self.ball: Optional[dict] = None
        self.ball_t = 0.0
        self.phase = "aim"           # aim → shoot → result → done
        self.phase_t = 0.0
        self.flash_goal = 0.0
        self.team = TEAMS[0]
        self._build_scene()
        self.guide = 2.6
        self.set_msg("准备射门", "头部左右瞄准，抬头起脚", 1.6, (140, 236, 190))

    def _build_scene(self):
        W, H = self.W, self.H
        self._bg = pygame.Surface((W, H))
        self._bg.blit(A.stadium_bg(W, H, (8, 12, 34), (20, 32, 68), seed=4), (0, 0))
        # 看台（远近两层）
        stand = A.crowd_stand(W, 296, seed=7, rows=8, lit=-0.05)
        self._bg.blit(stand, (0, 108))
        # 广告牌
        self._led = self._make_led()
        self._bg.blit(self._led, (0, 412))
        # 草坪
        self._pitch_top = 488
        self._pitch = self._make_pitch()
        self._bg.blit(self._pitch, (0, self._pitch_top))
        # 灯光
        A.stadium_lights(self._bg, [230, 960, 1690], 142, 160, cone_to=690)

    def _make_led(self) -> pygame.Surface:
        W = self.W
        h = 68
        s = pygame.Surface((W, h), pygame.SRCALPHA)
        s.blit(A.shade_panel(W, h, (22, 30, 52), 0, 1.0, 0.7), (0, 0))
        rng = random.Random(3)
        x = -60
        while x < W + 60:
            quad = rng.choice([0, 1])
            for i in range(4):
                col = (28, 42, 70) if (i + quad) % 2 == 0 else (36, 54, 88)
                s.fill((col[0], col[1], col[2], 255), (int(x + i * 60), 6, 56, h - 12))
            x += 240
        return s

    def _led_strip(self, surf, y: int):
        """滚动的 LED 文字（广告牌的动态部分，每帧重画）。"""
        W = self.W
        txt = "　".join(LED_TEXTS)
        img = U.render_text(txt, 40, (255, 238, 176), bold=True)
        tw = img.get_width() + 220
        off = int((self.t * 118) % tw)
        x = -off
        while x < W:
            strip = pygame.Surface((img.get_width() + 60, img.get_height() + 8), pygame.SRCALPHA)
            strip.blit(img, (30, 4))
            surf.blit(strip, (int(x), y - 26), special_flags=pygame.BLEND_PREMULTIPLIED)
            x += tw

    def _make_pitch(self) -> pygame.Surface:
        W = self.W
        h = self.H - self._pitch_top
        s = A.grass_pitch(W, h, (58, 138, 74), (30, 92, 52), stripes=14)
        out = s.copy()
        # 纵向透视条纹（越远越密）
        for i in range(0, 13):
            x0 = int(W * i / 13)
            x1 = int(W * (i + 1) / 13)
            if i % 2 == 0:
                band = pygame.Surface((x1 - x0, h), pygame.SRCALPHA)
                band.fill((255, 255, 255, 16))
                out.blit(band, (x0, 0))
        # 球场白线
        U.aa_line(out, (0, h - 6), (W, h - 6), (232, 240, 246, 110), 4)
        # 大禁区（梯形）
        U.aa_poly(out, [(300, 0), (W - 300, 0), (W - 150, h * 0.62), (150, h * 0.62)],
                  (0, 0, 0, 0), 3, ss=2)
        return out

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.phase == "done":
            return
        self.phase_t += dt
        if self.guide > 0:
            self.guide -= dt

        if self.phase == "aim":
            # 横向：头部 axis 直接驱动（带惯性更跟手）
            self.aim_x += inp.axis * 1080.0 * dt
            # 不操作时缓慢自动扫动，避免玩家完全不参与
            if abs(inp.axis) < 0.10:
                self.aim_x += self.aim_dir * 250.0 * dt
            if self.aim_x < GOAL_L + 56:
                self.aim_x = GOAL_L + 56
                self.aim_dir = 1
            elif self.aim_x > GOAL_R - 56:
                self.aim_x = GOAL_R - 56
                self.aim_dir = -1
            # 纵向：抬头抬高 → 打上角
            self.aim_y += (U.clamp(0.62 - inp.up * 0.72, 0.16, 0.94) - self.aim_y) * min(1.0, dt * 5.0)

            # 守门员游走
            diff = self.shot_i / max(1, self.SHOTS - 1)
            spd = U.lerp(C.FB_KEEPER_MIN, C.FB_KEEPER_MAX, diff)
            if abs(self.keeper_x - self.keeper_tx) < 12:
                self.keeper_tx = random.uniform(GOAL_L + 130, GOAL_R - 130)
            self.keeper_x += math.copysign(min(spd * dt, abs(self.keeper_tx - self.keeper_x)),
                                           self.keeper_tx - self.keeper_x)

            if inp.jump:
                self._shoot()
        elif self.phase == "shoot":
            self._update_ball(dt)
        elif self.phase == "result":
            if self.keeper_dive:
                self.keeper_x += self.keeper_dir * 620 * dt * (1.0 - min(1.0, self.phase_t * 1.6))
            if self.phase_t > 1.5:
                self._next_shot()

        if self.flash_goal > 0:
            self.flash_goal = max(0.0, self.flash_goal - dt * 2.2)

    def _shoot(self):
        self.phase = "shoot"
        self.phase_t = 0.0
        tx = self.aim_x
        ty = U.lerp(CROSSBAR_Y + 46, GOAL_LINE_Y - 34, self.aim_y)
        diff = self.shot_i / max(1, self.SHOTS - 1)
        read = U.lerp(C.FB_READ_CHANCE, C.FB_READ_CHANCE + 0.34, diff)
        err = U.lerp(130, 34, diff)
        if random.random() < read:
            self.keeper_tx = tx + random.uniform(-err, err)
            self.keeper_dive = 1.0
            self.keeper_dir = 1.0 if tx > self.keeper_x else -1.0
        else:
            self.keeper_dive = 0.0
        self.ball = {"x": BALL_X0, "y": BALL_Y0, "tx": tx, "ty": ty, "k": 0.0,
                     "spin": random.uniform(-8, 8)}
        self.shake(9, 0.28)
        self.particles.emit(BALL_X0, BALL_Y0 + 10, 22, color=(226, 232, 240),
                            spread=180, vy=-160, gravity=800, life=0.55, size=5)

    def _update_ball(self, dt: float):
        b = self.ball
        if b is None:
            return
        dur = 0.62
        b["k"] += dt / dur
        k = U.clamp(b["k"], 0.0, 1.0)
        e = k * k * (3 - 2 * k)
        b["x"] = U.lerp(BALL_X0, b["tx"], e)
        b["y"] = U.lerp(BALL_Y0, b["ty"], e) - math.sin(e * math.pi) * 132
        if b["k"] >= 1.0:
            self._resolve(b)

    def _resolve(self, b):
        self.phase = "result"
        self.phase_t = 0.0
        kx0 = self.keeper_x - KEEPER_W / 2 - 16
        kx1 = self.keeper_x + KEEPER_W / 2 + 16
        near_keeper = abs(b["tx"] - self.keeper_x) < KEEPER_W * 0.62
        corner = (b["tx"] < GOAL_L + 130 or b["tx"] > GOAL_R - 130) or b["ty"] < CROSSBAR_Y + 92
        saved = near_keeper and self.keeper_dive > 0 and random.random() < 0.74
        if saved:
            self.history.append("扑出")
            self.combo = 0
            self.set_msg("被扑出！", "换个角度再试试", 1.3, (255, 176, 120))
            self.shake(8, 0.3)
            self.particles.emit(b["tx"], b["ty"], 18, color=(255, 168, 120),
                                spread=240, vy=-120, gravity=900, life=0.6, size=5)
        else:
            self.goals += 1
            self.combo += 1
            self.best_combo = max(self.best_combo, self.combo)
            add = C.FB_SCORE_GOAL
            if corner:
                add += C.FB_SCORE_CORNER
            if self.combo >= C.FB_COMBO_STEP:
                add += C.FB_SCORE_COMBO * (self.combo // C.FB_COMBO_STEP)
            self.score += add
            self.history.append("进球" + ("·死角" if corner else ""))
            self.flash_goal = 1.0
            self.flash((255, 250, 220), 0.30)
            self.shake(11, 0.4)
            tag = "死角！" if corner else "进球！"
            sub = f"+{add}"
            if self.combo >= C.FB_COMBO_STEP:
                sub += f"　{self.combo} 连击"
            self.set_msg(tag, sub, 1.3, (150, 244, 196))
            self.particles.emit(b["tx"], b["ty"], 40, color=(255, 240, 170),
                                spread=380, vy=-220, gravity=720, life=1.0, size=6)

    def _next_shot(self):
        self.shot_i += 1
        if self.shot_i >= self.SHOTS:
            self.phase = "done"
            self.finish(self.goals >= 6)
            return
        self.ball = None
        self.keeper_dive = 0.0
        self.phase = "aim"
        self.phase_t = 0.0
        self.team = TEAMS[self.shot_i % len(TEAMS)]
        self.set_msg(f"第 {self.shot_i + 1} 球", f"对手：{self.team[0]}", 1.1, (200, 226, 255))

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        self._led_strip(surf, 434)
        self._draw_goal(surf)
        self._draw_keeper(surf)
        if self.phase in ("aim", "shoot"):
            self._draw_taker(surf)
        if self.phase == "aim":
            self._draw_aim(surf)
        if self.ball is not None:
            k = U.clamp(self.ball["k"], 0.0, 1.0)
            r = U.lerp(30, 15, k)
            A.draw_ball(surf, self.ball["x"], self.ball["y"], r, "football",
                        rot=self.ball["spin"] * k * 3)
        self._draw_scoreboard(surf)
        self.particles.draw(surf)
        if self.flash_goal > 0:
            ov = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            ov.fill((255, 244, 190, int(58 * self.flash_goal)))
            surf.blit(ov, (0, 0))
        self.draw_msg(surf)
        if self.guide > 0:
            self._draw_guide(surf)

    def _draw_goal(self, surf):
        net = (226, 234, 246, 138)
        # 球网底面
        U.aa_poly(surf, [(GOAL_L, GOAL_LINE_Y), (GOAL_R, GOAL_LINE_Y),
                         (GOAL_R + 52, GOAL_LINE_Y + GOAL_DEPTH),
                         (GOAL_L - 52, GOAL_LINE_Y + GOAL_DEPTH)], (16, 22, 40, 168), 0, ss=2)
        # 网面（横竖细线）
        for i in range(0, 29):
            t = i / 28
            x0 = U.lerp(GOAL_L, GOAL_R, t)
            x1 = U.lerp(GOAL_L - 52, GOAL_R + 52, t)
            U.aa_line(surf, (x0, CROSSBAR_Y), (x1, GOAL_LINE_Y + GOAL_DEPTH), net, 2)
        for i in range(0, 13):
            t = i / 12
            y0 = U.lerp(CROSSBAR_Y, GOAL_LINE_Y + GOAL_DEPTH, t)
            xl = U.lerp(GOAL_L, GOAL_L - 52, t)
            xr = U.lerp(GOAL_R, GOAL_R + 52, t)
            U.aa_line(surf, (xl, y0), (xr, y0), net, 2)
        # 门柱与横梁（加粗，才像真的球门）
        post = A.shade_panel(26, GOAL_LINE_Y - CROSSBAR_Y + 26, (250, 252, 255), 8)
        surf.blit(post, (GOAL_L - 13, CROSSBAR_Y - 8))
        surf.blit(post, (GOAL_R - 13, CROSSBAR_Y - 8))
        surf.blit(A.shade_panel(GOAL_R - GOAL_L + 26, 26, (250, 252, 255), 8),
                  (GOAL_L - 13, CROSSBAR_Y - 13))
        # 门柱投影
        U.aa_ellipse(surf, (GOAL_L - 16, GOAL_LINE_Y - 4, 32, 52), (0, 0, 0, 70), 0, ss=2)
        U.aa_ellipse(surf, (GOAL_R - 16, GOAL_LINE_Y - 4, 32, 52), (0, 0, 0, 70), 0, ss=2)
        surf.blit(U.glow_surface(200, (190, 226, 255), 40, 8),
                  (int((GOAL_L + GOAL_R) / 2 - 200), CROSSBAR_Y - 200))

    def _draw_keeper(self, surf):
        foot = GOAL_LINE_Y + 8
        h = KEEPER_H
        lean = U.clamp(self.keeper_dive * 0.8, 0, 1)
        spr = A.figure_cached(h, A.FigureStyle(
            shirt=(72, 220, 160), shirt2=(24, 40, 60), pants=(24, 34, 52),
            skin=(240, 198, 164), hair=(38, 32, 34), shoes=(240, 240, 80),
            number="1"), A.pose(
            lean=lean * 0.9, arm_l=-0.5 - lean * 1.6, arm_r=0.5 + lean * 1.6,
            leg_l=-0.2 - lean * 0.5, leg_r=0.2 + lean * 0.5, crouch=0.28,
            flip=1 if self.keeper_dir >= 0 else -1), ss=3)
        # 门将落影
        U.aa_ellipse(surf, (int(self.keeper_x - 62), foot - 12, 124, 26), (0, 0, 0, 90), 0, ss=2)
        A.draw_figure(surf, spr, self.keeper_x, foot, 26)

    def _draw_taker(self, surf):
        """
        主罚视角：不画整人，只画一条从画面底部伸向球门的腿，
        更接近"站在点球点后面"的第一人称感觉，也避免比例失真。
        """
        thigh = A.shade_capsule(74, 210, (240, 244, 252), ss=3)
        shin = A.shade_capsule(58, 200, (242, 200, 166), ss=3)
        hip = (BALL_X0 - 340, 1120)
        knee = (BALL_X0 - 196, 968)
        # 摆动：射门时腿前摆
        sw = 0.0
        if self.phase == "shoot":
            sw = min(1.0, self.phase_t / 0.32)
        knee = (knee[0] + sw * 96, knee[1] - sw * 16)
        foot = (knee[0] + 118, knee[1] + 92 - sw * 46)

        def _leg(s, a, b, w, col):
            pygame.draw.line(s, col, a, b, int(w))
            pygame.draw.circle(s, col, a, int(w / 2))
            pygame.draw.circle(s, col, b, int(w / 2))
        # 大腿
        pygame.draw.line(surf, (238, 242, 250), hip, knee, 76)
        pygame.draw.circle(surf, (238, 242, 250), (int(knee[0]), int(knee[1])), 36)
        # 小腿
        pygame.draw.line(surf, (242, 200, 166), knee, foot, 58)
        pygame.draw.circle(surf, (242, 200, 166), (int(foot[0]), int(foot[1])), 28)
        # 球鞋
        ex, ey = foot
        U.aa_ellipse(surf, (int(ex - 52), int(ey - 24), 118, 52), (52, 226, 186), 0, ss=3)
        U.aa_ellipse(surf, (int(ex - 40), int(ey - 16), 92, 30), (16, 168, 142), 0, ss=3)
        if sw > 0.05:
            U.aa_arc(surf, (foot[0] + 30, foot[1]), 90, (255, 246, 200, 120),
                     -1.1 + sw, 0.6 + sw, 8)

    def _draw_aim(self, surf):
        tx = self.aim_x
        ty = U.lerp(CROSSBAR_Y + 46, GOAL_LINE_Y - 34, self.aim_y)
        pulse = 0.5 + 0.5 * math.sin(self.t * 7.0)
        col = (255, 246, 210)
        r = 40 + 5 * pulse
        U.aa_circle(surf, (tx, ty), r, (255, 255, 255, 200), 4, ss=3)
        U.aa_circle(surf, (tx, ty), r + 12, (255, 240, 180, 90), 2, ss=3)
        for a in range(4):
            ang = a * math.pi / 2 + self.t * 1.5
            x0 = tx + math.cos(ang) * (r + 14)
            y0 = ty + math.sin(ang) * (r + 14)
            x1 = tx + math.cos(ang) * (r + 34)
            y1 = ty + math.sin(ang) * (r + 34)
            U.aa_line(surf, (x0, y0), (x1, y1), col, 4)
        surf.blit(U.glow_surface(64, (255, 232, 150), 70, 7), (int(tx - 64), int(ty - 64)))
        # 蓄力条：抬头程度
        bar = pygame.Rect(int(tx - 62), int(ty + 60), 124, 12)
        U.bar_gauge(surf, bar, 1.0 - self.aim_y, (255, 226, 120), (40, 48, 70), 6)

    def _draw_scoreboard(self, surf):
        w, h = 320, 118
        x, y = self.W - w - 40, 132
        U.soft_shadow(surf, pygame.Rect(x, y, w, h), 16, 16, 120, (0, 8))
        U.glass(surf, pygame.Rect(x, y, w, h), 16, (10, 16, 34, 216), (120, 156, 210, 120), 2)
        U.text(surf, f"射门 {min(self.shot_i + 1, self.SHOTS)} / {self.SHOTS}",
               (x + 22, y + 14), 24, (206, 222, 246), bold=True)
        U.text(surf, f"{self.goals}", (x + w - 26, y + 44), 56, (150, 244, 196),
               bold=True)
        # 结果点阵
        for i in range(self.SHOTS):
            px = x + 22 + i * 27
            py = y + 96
            if i < len(self.history):
                c = (110, 236, 170) if self.history[i].startswith("进球") else (250, 130, 110)
            else:
                c = (58, 70, 96)
            U.aa_circle(surf, (px, py), 9, c, 0, ss=3)

    def _draw_guide(self, surf):
        a = min(1.0, self.guide)
        box = pygame.Rect(self.W // 2 - 430, 168, 860, 62)
        U.rr(surf, box, 16, (10, 16, 34, int(210 * a)), (150, 200, 236, int(150 * a)), 2)
        U.text(surf, "左右平移看球门两侧　低头打上角　抬头起脚射门",
               (box.centerx, box.centery), 26, (232, 242, 255), center=True, alpha=int(255 * a))

    def hud_items(self):
        return [
            ("射门", f"{min(self.shot_i + 1, self.SHOTS)}/{self.SHOTS}", (255, 255, 255)),
            ("进球", f"{self.goals}", (140, 240, 180)),
            ("得分", f"{self.score}", (255, 226, 130)),
            ("连击", f"x{max(1, self.combo)}", (255, 180, 220)),
        ]

    def result_title(self) -> str:
        return "晋 级 ！" if self.state == "win" else "止 步 点 球"

    def result_sub(self) -> str:
        return (f"{self.SHOTS} 球打进 {self.goals} 球　得分 {self.score}　"
                f"最高连击 {self.best_combo}")
