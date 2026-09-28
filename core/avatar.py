"""
core/avatar.py
==============
玩家化身 —— 把「摄像头识别结果」变成游戏角色的视觉中心。

为什么要单独一层
----------------
原来的做法是在左下角放一块深色面板，里面是摄像头画面 + 一个方框 + 关节点，
角上写着 FPS。那是**调试界面**：它告诉开发者"检测在工作"，但告诉玩家
"你正在被一个摄像头监视"。

商业体感游戏的正确做法是让玩家**成为**画面里的角色。这里用一个卡通头部化身：

  · 位置来自真实头部坐标（归一化值），所以真人动作与角色是同一个来源
  · 但用弹簧跟随而不是硬绑定 —— 玩家能"看见"自己移动的惯性
  · 有呼吸浮动、轮廓光、投影，快速移动留拖尾粒子
  · 命中目标时整张脸弹一下 + 星形爆发 + 能量环闪

原始摄像头 + 骨架 + FPS 全部移到按 H 打开的诊断层（`shell._draw_debug`），
只在开发者需要时才出现。
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import pygame

from . import theme as U
from . import ui as UI

Color = Tuple[int, int, int]


# --------------------------------------------------------------------------- #
def _head_sprite(size: int, base: Color, seed: int = 0) -> pygame.Surface:
    """
    烘焙卡通头部（静态部分）：耳朵 + 轮廓 + 渐变脸 + 顶部轮廓光 + 腮红。

    眼睛和嘴是每帧动态画的（要跟着头部位移转向），所以不烘在这张里。
    """
    ss = 2
    S = max(24, int(size) // 2 * 2)
    W = S
    H = int(S * 1.12)
    BW, BH = W * ss, H * ss
    big = pygame.Surface((BW, BH), pygame.SRCALPHA)
    cx = BW / 2.0
    cy = BH * 0.56
    rx = BW * 0.40
    ry = BH * 0.36
    ink = UI.INK
    light = U.shade(base, 1.45)
    deep = U.shade(base, 0.72)

    # 耳朵（先画，被头压住一部分）
    for sgn in (-1, 1):
        ex = cx + sgn * rx * 0.78
        ey = cy - ry * 0.78
        er = rx * 0.34
        pygame.draw.circle(big, ink, (int(ex), int(ey)), int(er + 3 * ss))
        pygame.draw.circle(big, deep, (int(ex), int(ey)), int(er))
        pygame.draw.circle(big, U.shade(base, 1.1),
                           (int(ex - er * 0.2), int(ey - er * 0.2)), int(er * 0.5))

    # 头（描边 + 渐变脸）
    pygame.draw.ellipse(big, ink, pygame.Rect(int(cx - rx - 3 * ss), int(cy - ry - 3 * ss),
                                              int(rx * 2 + 6 * ss), int(ry * 2 + 6 * ss)))
    face = pygame.Surface((int(rx * 2), int(ry * 2)), pygame.SRCALPHA)
    grad = U.vgrad(int(rx * 2), int(ry * 2), light, deep)
    face.blit(grad, (0, 0))
    mask = pygame.Surface((int(rx * 2), int(ry * 2)), pygame.SRCALPHA)
    pygame.draw.ellipse(mask, (255, 255, 255, 255), mask.get_rect())
    face.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    big.blit(face, (int(cx - rx), int(cy - ry)))

    # 顶部轮廓光（rim light）—— 卡通材质的关键
    rim = pygame.Surface((BW, BH), pygame.SRCALPHA)
    pygame.draw.arc(rim, (255, 255, 255, 150),
                    pygame.Rect(int(cx - rx), int(cy - ry), int(rx * 2), int(ry * 2)),
                    math.radians(35), math.radians(150), int(5 * ss))
    big.blit(rim, (0, 0))

    return pygame.transform.smoothscale(big, (W, H))


_HEAD_CACHE: Dict[Tuple, pygame.Surface] = {}


def head_sprite(size: int, base: Color) -> pygame.Surface:
    S = max(24, int(size) // 2 * 2)
    key = (S, tuple(base))
    s = _HEAD_CACHE.get(key)
    if s is None:
        if len(_HEAD_CACHE) > 40:
            _HEAD_CACHE.clear()
        s = _head_sprite(S, base)
        _HEAD_CACHE[key] = s
    return s


# --------------------------------------------------------------------------- #
class PlayerAvatar:
    """
    玩家化身 + 它的表现层状态（弹簧位置、拖尾、命中反馈）。

    与识别结果的耦合只有两处：`update()` 收到的归一化头部坐标，
    以及 `present`（当前是否稳定识别）。**不参与任何游戏逻辑判断**，
    所以接进来不会改变任何玩法。
    """

    def __init__(self, color: Color = UI.PRIMARY, name: str = "PLAYER 1",
                 cap: int = 320) -> None:
        self.color = color
        self.name = name
        # 弹簧跟随：位置来自真实头部，但带惯性，玩家能"看见"自己移动
        self.x = 0.5          # 归一化 0~1（面板内）
        self.y = 0.5
        self.vx = 0.0
        self.vy = 0.0
        self.present = False
        self.look = (0.0, 0.0)          # 视线方向（缓动）
        self.particles = U.Particles(cap=cap)
        self.pop = UI.Pop(k=9.0, w=4.0)
        self.ring = UI.Tween(0.0, 6.0)  # 能量环强度
        self._was_present = False
        self._blink = 0.0
        self._t = 0.0

    # ------------------------------------------------------------------ 每帧
    def update(self, dt: float, hx: float, hy: float, present: bool) -> None:
        self._t += dt
        self.present = present

        if present:
            # 弹簧跟随（临界阻尼附近），比直接赋值多出"跟手感"
            k, d = 46.0, 11.0
            ax = (hx - self.x) * k - self.vx * d
            ay = (hy - self.y) * k - self.vy * d
            self.vx += ax * dt
            self.vy += ay * dt
            self.x += self.vx * dt
            self.y += self.vy * dt

            # 视线：朝向运动方向，带缓动
            tx = max(-1.0, min(1.0, self.vx * 0.35))
            ty = max(-1.0, min(1.0, self.vy * 0.35))
            self.look = (self.look[0] + (tx - self.look[0]) * min(1.0, dt * 8.0),
                         self.look[1] + (ty - self.look[1]) * min(1.0, dt * 8.0))

            # 快速移动 → 拖尾粒子（服务"我动起来了"的反馈，不是为了堆特效）
            speed = math.hypot(self.vx, self.vy)
            if speed > 0.55:
                n = min(3, int(speed * 2))
                self.particles.emit(
                    self.x * 100.0, self.y * 100.0, n,
                    color=self.color, shape="glow", gravity=-30.0,
                    spread=46.0, life=0.36, size=5.0, fade=True)
            if not self._was_present:
                self.particles.emit(self.x * 100.0, self.y * 100.0, 16,
                                    color=UI.ACCENT, shape="star", gravity=-60.0,
                                    spread=190.0, life=0.65, size=6.5)
        else:
            # 未识别：**不做任何位移**（与输入层同一原则：没有检测就不动）
            self.vx *= max(0.0, 1.0 - dt * 4.0)
            self.vy *= max(0.0, 1.0 - dt * 4.0)

        self._was_present = present
        self.pop.step(dt)
        self.ring.to(1.0 if present else 0.22)
        self.ring.step(dt)
        self.particles.update(dt)

        # 眨眼：每 3~6 秒一次
        self._blink -= dt
        if self._blink < -0.14:
            self._blink = 3.0 + (self._t * 7.13) % 3.0

    def hit(self, strength: float = 1.0) -> None:
        """命中反馈：整张脸弹一下 + 能量环闪光 + 星形爆发。"""
        self.pop.hit(strength)
        self.particles.emit(self.x * 100.0, self.y * 100.0, int(10 + 10 * strength),
                            color=UI.SECONDARY, shape="star", gravity=520.0,
                            spread=290.0, life=0.6, size=7.0)
        self.particles.emit(self.x * 100.0, self.y * 100.0, 6,
                            color=UI.PAPER, shape="glow", gravity=-40.0,
                            spread=130.0, life=0.45, size=8.0)

    # ------------------------------------------------------------------ 绘制
    def draw_head(self, surf: pygame.Surface, cx: float, cy: float, size: float,
                  alpha: int = 255) -> None:
        """画卡通头部（含眼睛与嘴），眼睛朝向随运动方向偏。"""
        pop = self.pop.v
        scale = 1.0 + 0.14 * pop
        S = max(28, int(size * scale) // 2 * 2)
        # 柔和投影（贴着头底）—— 少了它，头像是"浮"在卡片上的贴纸
        U.aa_ellipse(surf, (int(cx - S * 0.36), int(cy + S * 0.44),
                            int(S * 0.72), max(4, int(S * 0.12))),
                     (0, 0, 0, 92), 0, ss=3)
        spr = head_sprite(S, self.color)
        r = spr.get_rect(center=(int(cx), int(cy)))
        if alpha < 255:
            spr = spr.copy()
            spr.set_alpha(alpha)
        surf.blit(spr, r)

        # 眼睛
        eye_r = S * 0.085
        dx = self.look[0] * S * 0.055
        dy = self.look[1] * S * 0.045
        for sgn in (-1, 1):
            ex = cx + sgn * S * 0.145 + dx
            ey = cy - S * 0.045 + dy
            if self._blink < 0.0:
                U.aa_line(surf, (ex - eye_r, ey), (ex + eye_r, ey), UI.INK,
                          max(2, int(S * 0.028)))
            else:
                U.aa_ellipse(surf, (int(ex - eye_r * 0.82), int(ey - eye_r),
                                    int(eye_r * 1.64), int(eye_r * 2.0)),
                             UI.INK, 0, ss=3)
                U.aa_circle(surf, (ex + eye_r * 0.22, ey - eye_r * 0.4),
                            max(1.0, eye_r * 0.34), UI.PAPER, 0, ss=3)

        # 嘴：识别到就笑，没识别到就是一条平线（一眼看出状态）
        my = cy + S * 0.135
        if self.present:
            U.aa_arc(surf, (cx, my - S * 0.03), S * 0.10,
                     (60, 34, 40), math.radians(200), math.radians(340),
                     max(2, int(S * 0.026)), ss=3)
        else:
            U.aa_line(surf, (cx - S * 0.07, my), (cx + S * 0.07, my),
                      (70, 44, 50), max(2, int(S * 0.024)))

    def draw_ring(self, surf: pygame.Surface, cx: float, cy: float, size: float,
                  state: str, t: float) -> None:
        """
        能量环：颜色即识别状态，转动即"正在捕捉"。

        关键是**先画一条很淡的完整引导环**，再叠两段反向旋转的亮弧。
        只有旋转弧的话，视觉上是一堆断开的线段；有了轨道，才读得出
        "有一个环在转"，这正是体感游戏里"系统正在追踪我"的语感。
        """
        r = size * 0.62
        col = {"track": self.color, "hold": UI.WARN}.get(state, UI.DANGER)
        k = self.ring.v
        pulse = 0.5 + 0.5 * math.sin(t * 3.4)

        U.glow(surf, (int(cx), int(cy)), int(r * 1.5 * (1.0 + 0.05 * pulse)),
               col, int(56 * k) + 14, 8)

        ca = int(64 * k) + 16
        # 引导环（完整一圈，很淡）+ 外圈
        U.aa_circle(surf, (cx, cy), r, (col[0], col[1], col[2], ca),
                    max(2, int(r * 0.030)), ss=3)
        U.aa_circle(surf, (cx, cy), r * 1.12, (col[0], col[1], col[2], ca // 2),
                    max(2, int(r * 0.020)), ss=3)

        # 两段反向旋转的亮弧
        for sp, span, rr in ((0.85, 74, 1.0), (-1.45, 48, 1.12)):
            a0 = t * sp
            U.aa_arc(surf, (cx, cy), r * rr,
                     (min(255, col[0] + 40), min(255, col[1] + 40),
                      min(255, col[2] + 40), int(215 * k) + 24),
                     a0, a0 + math.radians(span),
                     max(3, int(r * 0.036 * (1 + self.pop.v))), ss=3)

        # 轨道上的能量点
        if k > 0.28:
            for j in range(3):
                a = -t * 1.7 + j * math.tau / 3
                px = cx + math.cos(a) * r * 1.06
                py = cy + math.sin(a) * r * 1.06
                U.aa_circle(surf, (px, py),
                            max(2.5, size * 0.030 * (1 + 0.45 * pulse)), UI.PAPER, 0, ss=3)

    def draw_particles(self, surf: pygame.Surface, cx: float, cy: float,
                       span: float) -> None:
        """
        把粒子铺进以 (cx, cy) 为中心、span 为边长的区域。

        粒子发射时用的是 0~100 归一化坐标，所以这里只要给出原点与缩放，
        同一套粒子既能贴在卡片里，也能直接铺到全屏（见 Particles.draw 的说明）。
        """
        self.particles.draw(surf, origin=(cx - span / 2.0, cy - span / 2.0),
                            scale=span / 100.0)

    # ------------------------------------------------------------------ 卡片
    def draw_card(self, surf: pygame.Surface, rect: pygame.Rect, t: float,
                  state: str, hud: str = "", neutral: Optional[float] = None,
                  deadzone: float = 0.06) -> None:
        """
        玩家卡片：整个"玩家存在感"的载体，替换原来的调试预览框。

        结构自上而下是：名字 + 状态 → 卡通化身 → 识别位置条。
        最下面那条不是装饰：它把**真实的检测位置**如实画出来（发光点 = 头，
        竖线 = 校准中性位，浅色带 = 死区），既是给玩家的"我在被捕捉"的确认，
        也让开发者一眼看出中性位准不准 —— 但看起来是游戏 UI，不是调试界面。
        """
        UI.card(surf, rect, UI.R_LG)
        accent = {"track": self.color, "hold": UI.WARN}.get(state, UI.DANGER)

        # ---- 顶部：名字 + 状态 ----
        UI.text(surf, self.name, (rect.x + 24, rect.y + 16), UI.T_XS, UI.PAPER,
                outline=UI.INK, outline_w=3)
        tag = {"track": "已锁定", "hold": "丢帧", "lost": "未识别"}[state]
        col = {"track": UI.ACCENT, "hold": UI.WARN, "lost": UI.DANGER}[state]
        UI.pill(surf, (rect.right - 20, rect.y + 40), tag, col, size=UI.T_XS - 4,
                align="right", height=44, pad=20, alpha=210)

        # ---- 中：化身 ----
        cx = rect.centerx
        cy = rect.y + int(rect.h * 0.43)
        size = int(rect.h * 0.49)
        self.draw_ring(surf, cx, cy, size, state, t)
        self.draw_head(surf, cx, cy, size * 0.80,
                       alpha=255 if state != "lost" else 150)
        self.draw_particles(surf, cx, cy, size * 1.9)

        # ---- 底：识别位置条 ----
        strip = pygame.Rect(rect.x + 20, rect.bottom - 76, rect.w - 40, 58)
        pygame.draw.rect(surf, (30, 25, 62), strip, border_radius=UI.R_SM)
        pygame.draw.rect(surf, (62, 54, 112), strip, 2, border_radius=UI.R_SM)
        if hud:
            UI.text(surf, hud, (strip.x + 12, strip.y + 4), UI.T_XS - 6,
                    UI.PAPER_DIM, bold=True)

        # 死区带 + 中性位竖线
        if neutral is not None:
            dz0 = strip.x + int((neutral - deadzone) * strip.w)
            dz1 = strip.x + int((neutral + deadzone) * strip.w)
            band = pygame.Surface((max(1, dz1 - dz0), strip.h - 16), pygame.SRCALPHA)
            band.fill((72, 228, 186, 46))
            surf.blit(band, (dz0, strip.y + 8))
            pygame.draw.line(surf, UI.ACCENT, (strip.x + int(neutral * strip.w),
                                               strip.y + 6),
                             (strip.x + int(neutral * strip.w), strip.bottom - 6), 3)

        # 当前头部：发光点（位置取真实归一化坐标）
        px = strip.x + int(max(0.0, min(1.0, self.x)) * strip.w)
        py = strip.y + 10 + int(max(0.0, min(1.0, self.y)) * (strip.h - 20))
        if state != "lost":
            U.glow(surf, (px, py), 22, accent, 120)
            U.aa_circle(surf, (px, py), 8, UI.PAPER, 0, ss=3)
            U.aa_circle(surf, (px, py), 12, accent, 3, ss=3)
        else:
            U.aa_circle(surf, (px, py), 11, (120, 110, 160), 3, ss=3)

    # ------------------------------------------------------------------ 摄像头
    def draw_cam_card(self, surf: pygame.Surface, rect: pygame.Rect,
                      cam: pygame.Surface, st, t: float, state: str,
                      name: str = "PLAYER 1") -> None:
        """
        玩家卡片（摄像头版）：**真实摄像头画面 + 包住真实头部的能量环**。

        设计取舍说明（这是被明确要求的形态）：
        玩家希望"看到摄像头里的自己"，而 prompt 又明确禁止
        "黄色/红色矩形框、OpenCV bounding box、坐标与 FPS 之类的工程信息"。
        两者并不矛盾 —— 解法是：

          · 画面：真实摄像头（镜像），四角柔化 + 暗角，让它读起来是"游戏里的一块屏幕"
            而不是一个视频窗口
          · 头部：**不用任何矩形**，改用一圈发光能量环精确套在头部位置上，
            两段反向旋转的亮弧 + 轨道能量点 —— 光环的位置就是真实检测位置，
            所以"真人动作"与"游戏角色"是同一处，而不是两套并排
          · 状态：只用颜色与动效表达（绿=锁定 / 黄=丢帧 / 红=未识别），不写任何数字
          · 卡通身份：左上角一枚小巧的卡通头像徽章，不占画面、也不和真人抢中心

        `cam` 必须是已经缩放好的预览表面（由 shell 限频生成，见 CAM_PREVIEW_HZ）。
        """
        UI.card(surf, rect, UI.R_LG)
        accent = {"track": self.color, "hold": UI.WARN}.get(state, UI.DANGER)

        # ---- 顶部：卡通头像徽章 + 名字 + 状态 ----
        bh = 40
        self.draw_head(surf, rect.x + 34, rect.y + 40, bh * 0.78,
                       alpha=255 if state != "lost" else 150)
        UI.text(surf, name, (rect.x + 62, rect.y + 14), UI.T_XS, UI.PAPER,
                outline=UI.INK, outline_w=3)
        tag = {"track": "已锁定", "hold": "丢帧", "lost": "未识别"}[state]
        col = {"track": UI.ACCENT, "hold": UI.WARN, "lost": UI.DANGER}[state]
        UI.pill(surf, (rect.right - 20, rect.y + 38), tag, col, size=UI.T_XS - 4,
                align="right", height=42, pad=20, alpha=210)

        # ---- 画面 ----
        img = pygame.Rect(rect.x + 12, rect.y + 66, rect.w - 24, rect.h - 66 - 12)
        if cam is not None:
            pic = pygame.transform.smoothscale(cam, img.size)
            # 四角柔化：直接贴一张方图，读起来就是"嵌进来的视频"
            pic = pic.copy()
            pic.blit(_round_mask(img.w, img.h, UI.R_MD), (0, 0),
                     special_flags=pygame.BLEND_RGBA_MULT)
            surf.blit(pic, img.topleft)
            # 画面内暗角 + 边缘渐隐，把注意力收到中间的头部
            U.aa_ellipse(surf, (img.x - 40, img.y - 30, img.w + 80, img.h + 60),
                         (0, 0, 0, 0), 0, ss=2)
            edge = _edge_fade(img.w, img.h, UI.R_MD)
            surf.blit(edge, img.topleft)
        else:
            surf.fill((16, 14, 34), img)
            UI.text(surf, "无摄像头", (img.centerx, img.centery), UI.T_S,
                    UI.PAPER_DIM, center=True)

        # ---- 头部能量环：位置即真实检测位置 ----
        if st is not None and getattr(st, "found", False):
            hx = img.x + U.clamp(st.cx, 0.0, 1.0) * img.w
            # 光环要套住**整个头**，而不是"脸框的几何中心"：
            # 人脸框只覆盖眉眼到下巴，含头发的头部中心比它高约 1/6 个框高。
            # 不补这个偏移的话，光环会正好压在下巴上 —— 一看就不准。
            hy = img.y + U.clamp(st.cy - st.h * 0.16, 0.0, 1.0) * img.h
            r = U.clamp(st.w * img.w * 0.74, 20.0, min(img.w, img.h) * 0.50)
            self._head_halo(surf, hx, hy, r, accent, t, state)
        else:
            # 没识别到时：中间一圈缓慢呼吸的虚线环，表达"在找你"，而不是留空
            r = min(img.w, img.h) * 0.30
            k = 0.5 + 0.5 * math.sin(t * 2.0)
            U.aa_circle(surf, (img.centerx, img.centery), r,
                        (UI.DANGER[0], UI.DANGER[1], UI.DANGER[2],
                         int(60 + 70 * k)), 3, ss=3)

    def _head_halo(self, surf, cx: float, cy: float, r: float, accent,
                   t: float, state: str) -> None:
        """
        头部光环保。**这是"识别框"的游戏化替代品** —— 没有任何矩形。

        结构：外发光 → 淡引导环 → 两段反向旋转的亮弧 → 轨道能量点。
        引导环很关键：只有旋转弧的话视觉上是一堆断线；有了淡环才读得出
        "有一个环在套着我的头"，也就是"系统正在捕捉我"。
        """
        k = self.ring.v
        pop = self.pop.v
        rr = r * (1.0 + 0.10 * pop)
        pulse = 0.5 + 0.5 * math.sin(t * 3.2)

        U.glow(surf, (int(cx), int(cy)), int(rr * 1.55 * (1 + 0.05 * pulse)),
               accent, int(72 * (0.6 + 0.4 * k) + 26), 8)
        ca = int(70 * k) + 26
        U.aa_circle(surf, (cx, cy), rr, (accent[0], accent[1], accent[2], ca),
                    max(2, int(rr * 0.055)), ss=3)
        for sp, span, mul in ((0.9, 96, 1.0), (-1.5, 62, 1.14)):
            a0 = t * sp
            U.aa_arc(surf, (cx, cy), rr * mul,
                     (min(255, accent[0] + 45), min(255, accent[1] + 45),
                      min(255, accent[2] + 45), int(220 * k) + 30),
                     a0, a0 + math.radians(span),
                     max(3, int(rr * 0.075 * (1 + pop))), ss=3)
        if k > 0.25:
            for j in range(3):
                a = -t * 1.6 + j * math.tau / 3
                U.aa_circle(surf, (cx + math.cos(a) * rr * 1.08,
                                   cy + math.sin(a) * rr * 1.08),
                            max(2.5, rr * 0.075 * (1 + 0.4 * pulse)),
                            UI.PAPER, 0, ss=3)

    def draw_cam_orb(self, surf: pygame.Surface, cx: float, cy: float, size: float,
                     cam: pygame.Surface, st, t: float, state: str) -> None:
        """
        圆形摄像头光球（大厅用）：圆形画面 + 头部光环。

        大厅的选择网格占满整宽，左下角放不下整张卡片，但"玩家自己在画面里"
        在第一屏同样重要 —— 圆形比方形更不像监控画面，也更像游戏里的东西。
        """
        d = max(24, int(size))
        accent = {"track": self.color, "hold": UI.WARN}.get(state, UI.DANGER)

        # 环先画（这样画面能盖住环的内侧，不会出现"环浮在脸上"的错觉）
        U.glow(surf, (int(cx), int(cy)), int(d * 0.86), accent, 76, 8)
        if cam is not None:
            tmp = pygame.Surface((d, d), pygame.SRCALPHA)
            tmp.blit(pygame.transform.smoothscale(cam, (d, d)), (0, 0))
            tmp.blit(_circle_mask(d), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            surf.blit(tmp, (int(cx - d / 2), int(cy - d / 2)))
            # 头部光环（相对圆内的位置）
            if st is not None and getattr(st, "found", False):
                hx = cx + (U.clamp(st.cx, 0, 1) - 0.5) * d
                hy = cy + (U.clamp(st.cy - st.h * 0.16, 0, 1) - 0.5) * d
                r = U.clamp(st.w * d * 0.74, 16.0, d * 0.48)
                self._head_halo(surf, hx, hy, r, accent, t, state)
        else:
            self.draw_head(surf, cx, cy, d * 0.78)
            self._head_halo(surf, cx, cy, d * 0.42, accent, t, state)

        # 外圈：与卡片同源的圆边 + 状态色描边
        U.aa_circle(surf, (cx, cy), d / 2 + 3, (12, 10, 28, 230), 4, ss=3)
        U.aa_circle(surf, (cx, cy), d / 2 + 1,
                    (accent[0], accent[1], accent[2], 200), 3, ss=3)
        U.aa_arc(surf, (cx, cy), d / 2 + 7,
                 (min(255, accent[0] + 40), min(255, accent[1] + 40),
                  min(255, accent[2] + 40), 220),
                 t * 1.1, t * 1.1 + math.radians(84), max(3, int(d * 0.055)), ss=3)


_CIRCLE_MASKS: Dict[int, pygame.Surface] = {}


def _circle_mask(d: int) -> pygame.Surface:
    """圆形遮罩（缓存）。把方形摄像头画面裁成圆，比方形少很多"监控感"。"""
    m = _CIRCLE_MASKS.get(d)
    if m is None:
        m = pygame.Surface((d, d), pygame.SRCALPHA)
        m.fill((0, 0, 0, 0))
        pygame.draw.circle(m, (255, 255, 255, 255), (d // 2, d // 2), d // 2)
        if len(_CIRCLE_MASKS) > 24:
            _CIRCLE_MASKS.clear()
        _CIRCLE_MASKS[d] = m
    return m


_ROUND_MASKS: Dict[Tuple[int, int, int], pygame.Surface] = {}


def _round_mask(w: int, h: int, r: int) -> pygame.Surface:
    """圆角遮罩（缓存），用于把摄像头画面裁成卡片圆角。"""
    key = (w, h, r)
    m = _ROUND_MASKS.get(key)
    if m is None:
        m = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(m, (255, 255, 255, 255), (0, 0, w, h), border_radius=r)
        if len(_ROUND_MASKS) > 24:
            _ROUND_MASKS.clear()
        _ROUND_MASKS[key] = m
    return m


_EDGE_FADES: Dict[Tuple[int, int, int], pygame.Surface] = {}


def _edge_fade(w: int, h: int, r: int) -> pygame.Surface:
    """
    画面内侧的渐隐边（缓存）。

    摄像头画面直接贴进卡片会显得"硬"、"像嵌了个视频窗口"；四周压一层渐隐，
    再叠一点内阴影，它就读起来像"游戏里的一块屏幕"。
    """
    key = (w, h, r)
    m = _EDGE_FADES.get(key)
    if m is None:
        m = pygame.Surface((w, h), pygame.SRCALPHA)
        band = max(6, int(min(w, h) * 0.13))
        for i in range(band):
            a = int(150 * (1 - i / band) ** 1.7)
            m.fill((6, 5, 18, a), (0, i, w, 1))
            m.fill((6, 5, 18, a), (0, h - 1 - i, w, 1))
        for i in range(band):
            a = int(130 * (1 - i / band) ** 1.7)
            m.fill((6, 5, 18, a), (i, 0, 1, h))
            m.fill((6, 5, 18, a), (w - 1 - i, 0, 1, h))
        # 只保留圆角内的部分
        m.blit(_round_mask(w, h, r), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        if len(_EDGE_FADES) > 16:
            _EDGE_FADES.clear()
        _EDGE_FADES[key] = m
    return m
