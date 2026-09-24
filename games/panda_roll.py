"""
games/panda_roll.py
===================
熊猫滚滚 —— 三星堆主题伪 3D 管道跑酷。

头部操作
    · 左右平移 → 在三条道之间切换
    · 抬头     → 跳过矮障碍（陶俑残块）
玩法
    管道不断向前滚，躲开青铜面具与陶俑，捡竹笋。速度随距离递增，撞两次出局。
"""
from __future__ import annotations

import math
import random
from typing import List, Optional

import pygame

from core import art as A
from core import sprites as SP
from core import theme as U
from core.base import BaseGame, register
from core.inputs import GameInput

HORIZON = 436
GROUND = 986
LANES = (0.30, 0.50, 0.70)          # 三条道的横向比例
TUNNEL_R = 0.44                     # 管道半径（占画面宽比例）


def project(z: float):
    """z: 0 = 最近，1 = 地平线。返回 (屏幕 y, 缩放)。"""
    z = max(0.0, min(1.0, z))
    p = z * z * 0.84 + z * 0.16
    y = GROUND - (GROUND - HORIZON) * p
    return y, 1.0 - 0.87 * p


@register
class PandaRollGame(BaseGame):
    KEY = "panda_roll"
    TITLE = "熊猫滚滚"
    SUB = "三星堆管道疾走"
    CATEGORY = "头部控制"
    ACCENT = (120, 226, 198)
    ICON = "panda"
    HOW = "在管道里换道躲障碍，越跑越快"
    HINT = "头部左右换道 · 抬头跳过陶俑 · 竹笋 +10"
    DIFFICULTY = 3
    ACHIEVEMENT = "跑满 1200 米"
    REQUIRES = ("head",)
    TARGET_M = 1200

    # ------------------------------------------------------------------ 初始化
    def reset(self) -> None:
        self.state = "play"
        self.z_ball = 0.055
        self.lane = 1
        self.lane_f = 1.0
        self.jump_t = 0.0
        self.jump_cd = 0.0
        self.speed = 0.34               # 单位：z/秒
        self.dist = 0.0
        self.lives = 2
        self.bamboo = 0
        self.score = 0
        self.items: List[dict] = []
        self.spawn_cd = 0.9
        self.roll = 0.0
        self.crouch_anim = 0.0
        self.invuln = 0.0
        self.best = 0
        self._build_bg()
        self.set_msg("三星堆管道", "换道躲开障碍物", 1.5, (150, 240, 214))

    def _build_bg(self):
        W, H = self.W, self.H
        bg = U.vgrad3(W, H, (10, 16, 40), (22, 42, 78), (44, 84, 116))
        self._bg = bg.copy()
        # 远处遗址剪影
        rng = random.Random(5)
        s = pygame.Surface((W, H), pygame.SRCALPHA)
        for i in range(9):
            x = rng.uniform(-40, W)
            w = rng.uniform(90, 220)
            h = rng.uniform(70, 190)
            pts = [(x, HORIZON + 22), (x + w * 0.5, HORIZON + 22 - h), (x + w, HORIZON + 22)]
            U.aa_poly(s, pts, (16, 26, 48, 235), 0, ss=2)
        self._bg.blit(s, (0, 0))
        # 星点
        for _ in range(160):
            x, y = rng.uniform(0, W), rng.uniform(0, HORIZON)
            a = rng.randint(60, 190)
            self._bg.fill((255, 255, 255), (int(x), int(y), 2, 2))
        self._bg.blit(U.vignette(W, H, 150), (0, 0))

    # ------------------------------------------------------------------ 几何
    def _lane_x(self, lane: float, scale: float) -> float:
        c = self.W / 2.0
        half = self.W * TUNNEL_R * scale
        return c + (lane - 1.0) * half * 0.62

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, inp: GameInput) -> None:
        if self.state != "play":
            return
        self.invuln = max(0.0, self.invuln - dt)
        self.jump_cd = max(0.0, self.jump_cd - dt)
        self.dist += self.speed * 132.0 * dt
        self.speed = min(0.98, 0.34 + self.dist / 1500.0)
        self.roll += self.speed * dt * 26.0

        # 换道
        want = 1
        if inp.xc < -0.30:
            want = 0
        elif inp.xc > 0.30:
            want = 2
        if want != self.lane:
            self.lane = want
            self.shake(3, 0.10)
        self.lane_f += (self.lane - self.lane_f) * min(1.0, dt * 11.0)

        # 跳跃
        if inp.action and self.jump_cd <= 0 and self.jump_t <= 0.0:
            self.jump_t = 0.62
            self.jump_cd = 0.30
            self.particles.emit(self.W / 2, GROUND - 20, 10, color=(160, 236, 214),
                                spread=200, vy=-160, gravity=900, life=0.4, size=4)
        if self.jump_t > 0:
            self.jump_t = max(0.0, self.jump_t - dt)

        # 下蹲：身体姿态模式下的独有动作，可以钻过"高陶俑"（原本必须换道）
        self.crouch_anim += ((1.0 if inp.crouching else 0.0) - self.crouch_anim) \
            * min(1.0, dt * 9.0)
        self.z_ball = 0.055 + max(0.0, math.sin(
            (1.0 - self.jump_t / 0.62) * math.pi)) * 0.0  # 跳跃用高度表示，不改 z

        # 生成
        self.spawn_cd -= dt
        if self.spawn_cd <= 0:
            self.spawn_cd = max(0.42, 1.05 - self.dist / 900.0) * random.uniform(0.8, 1.25)
            self._spawn()

        # 推进
        for it in self.items:
            it["z"] -= self.speed * dt
        self.items = [it for it in self.items if it["z"] > -0.06]

        # 判定
        pz = self.z_ball
        for it in self.items:
            if it.get("dead"):
                continue
            if abs(it["z"] - pz) < 0.055:
                same_lane = abs(it["lane"] - self.lane_f) < 0.62
                if it["kind"] == "bamboo":
                    if same_lane:
                        it["dead"] = True
                        self.bamboo += 1
                        self.score += 10
                        y, sc = project(it["z"])
                        self.particles.emit(self._lane_x(it["lane"], sc), y, 14,
                                            color=(160, 240, 180), spread=220,
                                            vy=-180, gravity=720, life=0.5, size=4.5)
                        if self.bamboo % 12 == 0:
                            self.set_msg(f"竹笋 x{self.bamboo}", "+120 分", 0.9, (170, 246, 190))
                else:
                    jumping = self.jump_t > 0.10
                    # 下蹲可以钻过"高陶俑"的下沿 —— 这是体感模式独有的解法，
                    # 头部模式下只能换道绕开。
                    ducking = self.crouch_anim > 0.55 and it["kind"] == "tall"
                    if same_lane and not jumping and not ducking and self.invuln <= 0:
                        it["dead"] = True
                        self._hit()
                    elif same_lane and jumping and it["kind"] == "tall":
                        it["dead"] = True
                        self._hit()
                    elif same_lane and ducking and not it.get("ducked"):
                        it["ducked"] = True
                        self.score += 40
                        self.set_msg("钻过去了", "+40", 0.6, (200, 246, 220))

        # 结算
        if self.dist >= self.TARGET_M:
            self.finish(True)
            self.flash((255, 248, 210), 0.5)
            self.set_msg("抵达终点！", f"{int(self.dist)} 米", 2.0, (170, 250, 200))
        self.particles.update(dt)

    def _spawn(self):
        lane = random.randint(0, 2)
        r = random.random()
        if r < 0.42:
            kind = "bamboo"
        elif r < 0.78:
            kind = "low"            # 可跳过
        else:
            kind = "tall"           # 必须换道
        self.items.append({"z": 1.0, "lane": lane, "kind": kind, "dead": False,
                           "spin": random.uniform(-3, 3)})

    def _hit(self):
        self.lives -= 1
        self.invuln = 1.3
        self.shake(15, 0.45)
        self.flash((255, 120, 96), 0.42)
        self.speed = max(0.30, self.speed - 0.14)
        self.particles.emit(self.W / 2, GROUND - 60, 30, color=(255, 150, 110),
                            spread=340, vy=-240, gravity=1100, life=0.8, size=6)
        if self.lives <= 0:
            self.best = max(self.best, int(self.dist))
            self.finish(False)
            self.set_msg("撞毁！", f"跑了 {int(self.dist)} 米", 2.0, (255, 176, 140))
        else:
            self.set_msg("撞到了！", f"还剩 {self.lives} 次机会", 1.0, (255, 200, 140))

    # ------------------------------------------------------------------ 绘制
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._bg, (0, 0))
        self._draw_tunnel(surf)
        self._draw_landmark(surf)
        # 由远及近绘制
        for it in sorted(self.items, key=lambda d: -d["z"]):
            self._draw_item(surf, it)
        self._draw_ball(surf)
        self._draw_streaks(surf)
        U.aa_line(surf, (0, HORIZON), (self.W, HORIZON), (90, 130, 180, 90), 2)
        self.particles.draw(surf)
        self._draw_gauges(surf)
        self.draw_msg(surf)

    def _draw_landmark(self, surf):
        """
        隧道尽头的三星堆青铜神树 —— 让"一直往前跑"有个视觉目标。

        只用一张静态精灵：位置固定在消失点，靠 items 由远及近的绘制顺序自然
        产生遮挡关系，不需要额外的 z 排序。素材缺失时什么都不画。
        """
        y_far, _ = project(1.0)
        cx = self.W / 2.0
        if SP.draw(surf, "bronze_tree", cx, int(y_far) + 14, height=200,
                   anchor="bottom", alpha=238):
            surf.blit(U.glow_surface(200, (130, 226, 198), 50, 8),
                      (int(cx - 200), int(y_far - 70)))

    def _draw_tunnel(self, surf):
        """实心路面 + 移动的横向速度条带 + 两侧管壁，比同心环更像"跑道"。"""
        W, H = self.W, self.H
        cx = W / 2.0
        y_far, s_far = project(1.0)
        hx_far = W * TUNNEL_R * s_far
        hx_near = W * TUNNEL_R * project(0.0)[1] * 1.05
        # 管壁底色
        wall = U.vgrad(W, H - int(y_far) + 2, (18, 30, 52), (30, 52, 78))
        surf.blit(wall, (0, int(y_far)))
        # 管壁纵向棱线（perspective 汇聚）—— 每帧位置都在变，用无 AA 线
        for k in range(-7, 8):
            kk = k / 7.0
            pygame.draw.line(surf, (78, 116, 164),
                             (cx + kk * hx_far * 1.02, y_far), (cx + kk * W * 0.92, H), 2)
        # 路面
        U.aa_poly(surf, [(cx - hx_far, y_far), (cx + hx_far, y_far),
                         (cx + hx_near, H), (cx - hx_near, H)], (44, 66, 96), 0, ss=2)
        U.aa_poly(surf, [(cx - hx_far * 1.03, y_far), (cx + hx_far * 1.03, y_far),
                         (cx + hx_near * 1.03, H), (cx - hx_near * 1.03, H)],
                  (150, 200, 240, 90), 3, ss=2)
        # 移动的横向条带（速度感来源）。这里用无 AA 的 draw.line：
        # 30 条线每帧尺寸都在变，走 aa_line 会每帧产生 30 个新缓存条目。
        off = (self.dist * 0.0016) % 1.0
        for i in range(30):
            z = ((i / 30.0) + off) % 1.0
            y, s = project(z)
            hx = W * TUNNEL_R * s
            a = int(96 * (1 - z) ** 1.2) + 12
            col = (200, 236, 255, a)
            pygame.draw.line(surf, col, (cx - hx, y), (cx + hx, y), max(1, int(4 * s + 1)))
        # 车道分隔（折线一次性画，避免逐段建面）
        for lane in (0.5, 1.5):
            pts = [self._lane_x(lane, project(i / 18.0)[1]) for i in range(19)]
            ys = [project(i / 18.0)[0] for i in range(19)]
            pygame.draw.lines(surf, (120, 190, 172), False,
                              [(pts[i], ys[i]) for i in range(19)], 3)

    def _draw_item(self, surf, it):
        y, sc = project(it["z"])
        x = self._lane_x(it["lane"], sc)
        if sc < 0.05 or y > self.H:
            return
        if it.get("dead"):
            return
        if it["kind"] == "bamboo":
            h = 128 * sc
            w = 30 * sc
            if h >= 3:
                # 笋身（下宽上尖）
                U.aa_poly(surf, [(x - w * 0.5, y), (x + w * 0.5, y),
                                 (x + w * 0.30, y - h * 0.72), (x, y - h),
                                 (x - w * 0.30, y - h * 0.72)], (136, 216, 118), 0, ss=2)
                # 笋壳纹
                for k in range(3):
                    yy = y - h * (0.20 + k * 0.24)
                    U.aa_poly(surf, [(x - w * 0.44 + w * 0.10 * k, yy),
                                     (x + w * 0.44 - w * 0.10 * k, yy),
                                     (x, yy - h * 0.16)], (104, 190, 100), 0, ss=2)
                U.aa_line(surf, (x - w * 0.10, y - h * 0.86), (x - w * 0.10, y - h * 1.12),
                          (150, 224, 140), max(2, int(4 * sc + 1)))
            surf.blit(U.glow_surface(int(64 * sc) + 8, (150, 240, 170),
                                     80, 7), (int(x - 40 * sc), int(y - h * 0.5 - 40 * sc)))
        else:
            h = (130 if it["kind"] == "low" else 232) * sc
            w = 158 * sc
            tall = it["kind"] == "tall"
            if w >= 4:
                surf.blit(U.panel(w, h, (152, 128, 90), 10),
                          (int(x - w / 2), int(y - h)))
                # 陶俑纹样：竖向刻线 +（矮柱才有）圆孔眼
                if sc > 0.22:
                    for k in range(4):
                        surf.fill((114, 92, 62),
                                  (int(x - w * 0.36), int(y - h * (0.80 - k * 0.17)),
                                   int(w * 0.72), max(1, int(5 * sc))))
                    if not tall:
                        U.aa_circle(surf, (x, y - h * 0.66), 13 * sc, (56, 44, 34), 0, ss=2)
                        U.aa_circle(surf, (x, y - h * 0.66), 6 * sc, (198, 176, 140), 0, ss=2)
                # 顶部高光
                surf.fill((196, 172, 132), (int(x - w * 0.46), int(y - h), int(w * 0.92),
                                            max(1, int(6 * sc))))
                # 高柱镶三星堆纵目面具 —— 本作就是三星堆主题，用素材点题
                if tall:
                    SP.draw(surf, "sanxingdui", x, y - h * 0.68,
                            width=w * 1.08, anchor="center", alpha=248)
            surf.blit(U.glow_surface(int(70 * sc) + 8, (255, 160, 120), 56, 6),
                      (int(x - 46 * sc), int(y - h * 0.5 - 40 * sc)))

    def _draw_ball(self, surf):
        y, sc = project(self.z_ball)
        x = self._lane_x(self.lane_f, sc)
        r = max(8, int(86 * sc) // 4 * 4)     # 量化半径，避免 shade_ball 缓存爆炸
        r = max(8, int(r * (0.74 + 0.26 * (1.0 - self.crouch_anim))) // 4 * 4)  # 下蹲时压扁
        hop = math.sin(max(0.0, (1.0 - self.jump_t / 0.62)) * math.pi) if self.jump_t > 0 else 0.0
        cy = y - r * 0.86 - hop * 190
        if self.invuln > 0 and int(self.invuln * 14) % 2 == 0:
            return
        # 阴影
        U.aa_ellipse(surf, (int(x - r * 0.9), int(y - r * 0.22), int(r * 1.8), int(r * 0.44)),
                     (0, 0, 0, 110), 0, ss=2)
        # 主体：优先用生成素材（蜷成球的熊猫），旋转角跟着滚动量走
        if SP.draw(surf, "panda_curl", x, cy, height=r * 2.2, anchor="center",
                   rot=-math.degrees(self.roll)):
            surf.blit(U.glow_surface(int(r * 2.2), (150, 240, 210), 42, 7),
                      (int(x - r * 1.1), int(cy - r * 1.1)))
            return
        # 回退：原来的矢量画法（白球 + 耳朵 + 眼罩）
        # 球体
        spun = self.roll
        surf.blit(A.shade_ball(r, (246, 248, 252), ss=3), (int(x - r), int(cy - r)))
        # 滚动的花纹（用旋转的深色斑点表示球在滚）
        for i in range(5):
            a = spun + i * math.tau / 5
            sx = x + math.cos(a) * r * 0.52
            sy = cy + math.sin(a) * r * 0.52
            if math.sin(a) > -0.2:
                U.aa_ellipse(surf, (int(sx - r * 0.20), int(sy - r * 0.20),
                                    int(r * 0.40), int(r * 0.40)), (34, 38, 52), 0, ss=2)
        # 耳朵 + 眼罩（熊猫）
        for sgn in (-1, 1):
            U.aa_circle(surf, (x + sgn * r * 0.66, cy - r * 0.72), r * 0.28, (32, 34, 44), 0, ss=2)
        for sgn in (-1, 1):
            U.aa_ellipse(surf, (int(x + sgn * r * 0.34 - r * 0.22),
                                int(cy - r * 0.26 - r * 0.20),
                                int(r * 0.44), int(r * 0.40)), (30, 32, 42), 0, ss=2)
            U.aa_circle(surf, (x + sgn * r * 0.36, cy - r * 0.10), r * 0.11, (250, 250, 255), 0, ss=2)
        U.aa_ellipse(surf, (int(x - r * 0.16), int(cy + r * 0.16),
                            int(r * 0.32), int(r * 0.26)), (36, 38, 48), 0, ss=2)
        surf.blit(U.glow_surface(int(r * 2.2), (150, 240, 210), 42, 7),
                  (int(x - r * 1.1), int(cy - r * 1.1)))

    def _draw_streaks(self, surf):
        """速度线：固定垂直方向 + 量化长度，保证 aa_line 能命中缓存。"""
        rng = random.Random(int(self.t * 40) % 9973)
        for _ in range(18):
            z = rng.uniform(0.0, 0.85)
            y, sc = project(z)
            side = -1 if rng.random() < 0.5 else 1
            x = self.W / 2 + side * self.W * TUNNEL_R * sc * rng.uniform(0.5, 1.1)
            ln = max(10, int(90 * sc * (0.7 + self.speed)) // 10 * 10)
            a = int(80 * (1 - z)) + 14
            pygame.draw.line(surf, (190, 230, 255, a), (x, y), (x, y + ln),
                             max(1, int(2 * sc + 1)))

    def _draw_gauges(self, surf):
        # 距离进度
        bar = pygame.Rect(self.W // 2 - 260, 128, 520, 16)
        U.bar_gauge(surf, bar, self.dist / self.TARGET_M, self.ACCENT, (36, 46, 70), 8)
        U.text(surf, f"{int(self.dist)} / {self.TARGET_M} 米", (self.W // 2, 156), 26,
               (226, 240, 255), center=True, bold=True)
        # 生命
        for i in range(2):
            cx = self.W - 70 - i * 52
            col = (255, 130, 120) if i < self.lives else (72, 80, 104)
            U.aa_circle(surf, (cx - 11, 66), 12, col, 0, ss=3)
            U.aa_circle(surf, (cx + 11, 66), 12, col, 0, ss=3)
            U.aa_poly(surf, [(cx - 23, 70), (cx + 23, 70), (cx, 96)], col, 0, ss=3)

    def hud_items(self):
        return [
            ("距离", f"{int(self.dist)} m", (255, 255, 255)),
            ("竹笋", f"{self.bamboo}", (150, 240, 180)),
            ("得分", f"{self.score}", (255, 226, 130)),
            ("机会", f"{max(0, self.lives)}", (255, 150, 140), "heart"),
        ]

    def result_title(self) -> str:
        return "抵 达 终 点 ！" if self.state == "win" else "撞 毁 了"

    def result_sub(self) -> str:
        return f"跑了 {int(self.dist)} 米　竹笋 {self.bamboo}　得分 {self.score}"
