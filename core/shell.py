"""
core/shell.py
=============
应用外壳：显示模式、场景路由、HUD、摄像头预览、覆盖层。

显示方案
--------
设计分辨率固定 1920×1080，通过 SDL2 的 `SCALED` 模式交给 GPU 缩放，
因此：

  · 游戏代码只认 1920×1080，不需要关心真实分辨率；
  · 真机全屏时由渲染器硬件拉伸（几乎零成本），而不是 CPU 逐帧 smoothscale；
  · 窗口/全屏切换不改变任何布局。

启动时按优先级尝试一系列显示模式，任何一个成功就用它 —— 全屏失败时
自动退回窗口模式，绝不因为显示模式选择失败而启不来。

分层
----
  canvas(1920×1080)  游戏画面，可整体施加"屏幕震动"
  screen             最终窗口；HUD / 摄像头预览 / 覆盖层画在这一层，
                     因此它们不会跟着震动，始终稳定可读。
"""
from __future__ import annotations

import math
import os
import sys
import time
from typing import List, Optional, Tuple

import numpy as np
import pygame

from . import base as B
from . import config as C
from . import icons
from . import theme as U
from .inputs import (BodyController, FaceState, GameInput, HandController, HandState,
                     HeadController)
from .menu import Menu
from .vision import COCO17_EDGES, HAND_EDGES

ZERO = GameInput()


class Shell:
    def __init__(self, vision: str = "auto", cam_index: int = C.CAM_INDEX,
                 no_cam: bool = False, windowed: bool = False,
                 start_game: str = "menu") -> None:
        pygame.init()
        pygame.display.set_caption(C.TITLE)
        self.screen, self.display_mode = self._setup_display(windowed)
        self.canvas = pygame.Surface((C.DESIGN_W, C.DESIGN_H))
        self.clock = pygame.time.Clock()
        U.init_font()

        # ---- 摄像头 ----
        self.tracker = None
        self.tracker_err = ""
        self.no_cam = no_cam
        if not no_cam:
            from .tracker import MotionTracker
            t0 = time.time()
            prefer = None if vision in ("auto", "", None) else vision
            self.tracker = MotionTracker(cam_index, prefer=prefer)
            print(f"[shell] 视觉后端：{self.tracker.backend_name}"
                  f"（手部/全身：{self.tracker.hand_name}）　"
                  f"初始化 {time.time() - t0:.1f}s")
            if not self.tracker.ok:
                self.tracker_err = self.tracker.err
                print(f"[shell] 摄像头不可用：{self.tracker_err}")

        cam_ok = bool(self.tracker and self.tracker.ok)
        self.head_ctl = HeadController(C)
        self.hand_ctl = HandController(C)
        self.body_ctl = BodyController(C)
        self.menu = Menu({
            "cam_ok": cam_ok,
            "hand_ok": cam_ok,
            "backend": self.tracker.backend_name if cam_ok else "-",
            "hand_backend": self.tracker.hand_name if cam_ok else "-",
            "fps": 0.0,
        })

        # ---- 场景 ----
        self.games = {c.KEY: c for c in B.all_games()}
        self.scene = "menu"
        self.game_key = ""
        self.game: Optional[B.BaseGame] = None
        self.paused = False
        self.fullscreen = not windowed
        self.show_prev = True
        # 体感模式：打开后纯头部游戏也会加载全身姿态，
        # 游戏里的 inp.xc / inp.action 会自动优先采用身体动作。
        # 默认关，因为全身姿态检测不便宜（真机 16~29ms/次）。
        self.body_enabled = False
        self.running = True
        self.lost_t = 0.0
        self.toast = ""
        self.toast_t = 0.0
        self.fade = 0.0
        self.toast = ""
        self._prev_frame = None
        self._hands: List[HandState] = []
        self._vision = None
        self._mouse_hand = (0.5, 0.5)
        print(f"[shell] 已就绪：{C.DESIGN_W}x{C.DESIGN_H}　显示模式 {self.display_mode}　"
              f"共 {len(self.games)} 款游戏")

        if start_game != "menu" and start_game in self.games:
            self.start_game(start_game)

    # ------------------------------------------------------------------ 显示
    def _setup_display(self, windowed: bool) -> Tuple[pygame.Surface, str]:
        """
        按优先级尝试显示模式，任何一个成功就用它。

        全屏一律走 `SCALED`：它让 SDL2 用渲染器把 1920×1080 的绘制表面
        硬件缩放到屏幕，而不是 CPU 逐帧 smoothscale，代价几乎为零。
        注意 `pygame.FULLSCREEN_DESKTOP` 在部分 pygame 构建里并不存在，
        所以这里不用它，改用 SCALED + FULLSCREEN。
        """
        size = (C.DESIGN_W, C.DESIGN_H)
        tries = [] if windowed else [
            (pygame.FULLSCREEN | pygame.SCALED | pygame.DOUBLEBUF, 1, "全屏（GPU 缩放 + 垂直同步）"),
            (pygame.FULLSCREEN | pygame.SCALED, 0, "全屏（GPU 缩放）"),
            (pygame.FULLSCREEN | pygame.DOUBLEBUF, 0, "全屏（无缩放）"),
        ]
        tries += [
            (pygame.SCALED | pygame.DOUBLEBUF, 1, "窗口 1920×1080（GPU 缩放）"),
            (pygame.SCALED, 0, "窗口 1920×1080（无垂直同步）"),
            (pygame.DOUBLEBUF, 0, "窗口 1920×1080（无缩放）"),
            (0, 0, "窗口（最简）"),
        ]
        last = None
        for flags, vsync, label in tries:
            try:
                s = pygame.display.set_mode(size, flags, vsync=vsync)
                if s is not None:
                    return s, label
            except Exception as e:                                    # noqa: BLE001
                last = e
                print(f"[shell] 显示模式「{label}」失败：{e}")
        print(f"[shell] 所有显示模式均失败（{last}），退回默认窗口")
        return pygame.display.set_mode(size), "窗口（兜底）"

    def toggle_fullscreen(self) -> None:
        self.fullscreen = not self.fullscreen
        self.screen, self.display_mode = self._setup_display(windowed=self.fullscreen)
        self.canvas = pygame.Surface((C.DESIGN_W, C.DESIGN_H))
        self.toast_msg(U.T(f"显示模式：{self.display_mode}", self.display_mode))

    # ------------------------------------------------------------------ 主循环
    def run(self) -> None:
        while self.running:
            dt = min(0.05, self.clock.tick(C.FPS) / 1000.0)
            self._events()
            inp = self._input(dt)
            self._update_lost(dt, inp)
            if self.toast_t > 0:
                self.toast_t = max(0.0, self.toast_t - dt)
            if self.fade > 0:
                self.fade = max(0.0, self.fade - dt * 3.0)

            if self.scene == "menu":
                self.menu.info["fps"] = self.clock.get_fps()
                self.menu.update(dt, inp)
                if self.menu.chosen:
                    self.start_game(self.menu.chosen)
                self.menu.draw(self.canvas)
            else:
                g = self.game
                frozen = self.paused or self._lost_paused()
                g.tick(0.0 if frozen else dt, ZERO if frozen else inp)
                g.draw(self.canvas)

            self._present()
            pygame.display.flip()

        if self.tracker:
            self.tracker.close()
        pygame.quit()

    def _present(self) -> None:
        """把画布合成到窗口（带震动），再叠 HUD / 预览 / 覆盖层。"""
        off = (0, 0)
        if self.game is not None and self.scene == "game":
            off = self.game.shake_offset()
        if off != (0, 0):
            self.screen.fill((6, 8, 18))
        self.screen.blit(self.canvas, off)

        if self.scene == "game":
            self._draw_hud()
            self._draw_preview()
            self._draw_hints()
            self._draw_result()
        else:
            self._draw_preview()
        self._draw_alerts()
        self._draw_toast()
        if self.fade > 0:
            ov = pygame.Surface((C.DESIGN_W, C.DESIGN_H), pygame.SRCALPHA)
            ov.fill((255, 255, 255, int(130 * self.fade)))
            self.screen.blit(ov, (0, 0))

    # ------------------------------------------------------------------ 事件
    def _events(self) -> None:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.running = False
            elif e.type == pygame.MOUSEMOTION:
                w = max(1, self.screen.get_width())
                h = max(1, self.screen.get_height())
                self._mouse_hand = (e.pos[0] / w, e.pos[1] / h)
            elif e.type == pygame.KEYDOWN:
                self._key(e)

    def _key(self, e) -> None:
        k = e.key
        if k == pygame.K_ESCAPE:
            if self.scene == "game":
                self.back_to_menu()
            else:
                self.running = False
        elif k in (pygame.K_F11, pygame.K_f):
            self.toggle_fullscreen()
        elif self.scene == "menu":
            if k in (pygame.K_RIGHT, pygame.K_d):
                self.menu.move(1)
            elif k in (pygame.K_LEFT, pygame.K_a):
                self.menu.move(-1)
            elif k in (pygame.K_DOWN, pygame.K_s):
                self.menu.move(C.MENU_COLS)
            elif k in (pygame.K_UP, pygame.K_w):
                self.menu.move(-C.MENU_COLS)
            elif k in (pygame.K_RETURN, pygame.K_SPACE):
                self.menu.confirm()
            elif pygame.K_1 <= k <= pygame.K_9:
                self.menu.pick(k - pygame.K_1)
        else:
            if k == pygame.K_r and self.game:
                self.game.reset()
                self.toast_msg(U.T("已重新开始", "Restarted"))
            elif k == pygame.K_c:
                self.head_ctl.reset()
                self.hand_ctl.reset()
                self.toast_msg(U.T("重新校准中性位…", "Recalibrating…"))
            elif k == pygame.K_p:
                self.paused = not self.paused
            elif k == pygame.K_h:
                self.show_prev = not self.show_prev
            elif k == pygame.K_b:
                self.body_enabled = not self.body_enabled
                if self.tracker and self.tracker.ok:
                    self.tracker.set_vision_mode("full" if self.body_enabled else
                                                 ("hand" if self.scene == "menu" else "off"))
                self.toast_msg(U.T(
                    f"体感模式：{'已开启（用身体动作）' if self.body_enabled else '已关闭（用头部）'}",
                    f"Body mode {'ON' if self.body_enabled else 'OFF'}"))
            elif k == pygame.K_TAB:
                # 快速切换下一个游戏
                keys = list(self.games)
                i = (keys.index(self.game_key) + 1) % len(keys)
                self.start_game(keys[i])

    # ------------------------------------------------------------------ 场景
    def start_game(self, key: str) -> None:
        cls = self.games.get(key)
        if cls is None:
            return
        self.game = cls()
        self.game_key = key
        self.scene = "game"
        self.paused = False
        self.lost_t = 0.0
        self.fade = 1.0
        self.menu.reset()
        self._apply_vision_mode(cls)
        need = getattr(cls, "REQUIRES", ("head",))
        tip = " · ".join({"head": "头部", "hand": "手掌", "body": "身体"}.get(x, x)
                         for x in need)
        self.toast_msg(U.T(f"进入「{cls.TITLE}」　用{tip}操作", f"{cls.TITLE}"))

    def _apply_vision_mode(self, cls) -> None:
        """
        按游戏需要开关视觉负载 —— 这是"加了手之后头部变钝"的根治办法。

        真机实测 Vision 在真实图像上要 16~29ms/次，十几个纯头部游戏根本
        不需要它，白白跑就是在抢采集线程的时间。

        体感模式（按 B）打开时，纯头部游戏也会加载全身姿态，
        因为它们的 inp.xc / inp.action 会自动优先采用身体动作。
        """
        if not (self.tracker and self.tracker.ok):
            return
        req = set(getattr(cls, "REQUIRES", ("head",)))
        if "body" in req or self.body_enabled:
            mode = "full"
        elif "hand" in req:
            mode = "hand"
        else:
            mode = "off"
        if mode != self.tracker.vision_mode:
            self.tracker.set_vision_mode(mode)
            print(f"[shell] 视觉负载 → {mode}（{cls.TITLE}，体感模式"
                  f"{'开' if self.body_enabled else '关'}）")

    def back_to_menu(self) -> None:
        self.scene = "menu"
        self.game = None
        self.game_key = ""
        self.paused = False
        self.menu.reset()
        self.fade = 0.7
        # 大厅要显示手部状态，只开手部就够
        if self.tracker and self.tracker.ok:
            self.tracker.set_vision_mode("hand")

    def toast_msg(self, msg: str) -> None:
        self.toast = msg
        self.toast_t = 2.4

    # ------------------------------------------------------------------ 输入
    def _input(self, dt: float) -> GameInput:
        # 键盘优先（现场兜底）
        keys = pygame.key.get_pressed()
        k_axis = (1 if (keys[pygame.K_RIGHT] or keys[pygame.K_d]) else 0) - \
                 (1 if (keys[pygame.K_LEFT] or keys[pygame.K_a]) else 0)
        k_action = bool(keys[pygame.K_SPACE] or keys[pygame.K_UP] or keys[pygame.K_w])

        cam_ok = bool(self.tracker and self.tracker.ok)
        if cam_ok:
            frame, st, hands = self.tracker.get()
            vf = self.tracker.get_vision()
            self._prev_frame = frame
            self._hands = hands
            self._vision = vf
            self.head_ctl.update(st, dt)
            self.hand_ctl.update(hands, dt)
            self.body_ctl.update(vf.pose, dt)
            inp = self.head_ctl.game_input()
            inp = self.hand_ctl.apply(inp, hands)
            inp = self.body_ctl.apply(inp, vf.pose)
        else:
            inp = GameInput()
            # 无摄像头：用鼠标模拟手（左键 = 握拳/捏合），保证游戏仍可演示
            inp.hand_found = True
            inp.hx, inp.hy = self._mouse_hand
            pressed = pygame.mouse.get_pressed()[0]
            inp.hand_open = 0.18 if pressed else 0.92
            inp.hands = [HandState(found=True, x=inp.hx, y=inp.hy, open=inp.hand_open,
                                   area=0.05, span=0.2)]
            inp.grab_hold = pressed
            inp.pinch = pressed
            # 键盘同时模拟身体动作：A/D 横移，S 蹲，W 举手
            k2 = pygame.key.get_pressed()
            inp.body_found = True
            inp.body_x = (1 if (k2[pygame.K_d] or k2[pygame.K_RIGHT]) else 0) - \
                         (1 if (k2[pygame.K_a] or k2[pygame.K_LEFT]) else 0)
            inp.crouch = 1.0 if k2[pygame.K_DOWN] else 0.0
            inp.arm_l = inp.arm_r = 1.0 if k2[pygame.K_w] else 0.0
            inp.hands_up = 2 if k2[pygame.K_w] else 0

        if k_axis or k_action:
            inp.axis = float(k_axis)
            inp.jump = k_action
            inp.up = 1.0 if k_action else 0.0
            inp.found = True
            if not cam_ok:
                inp.hand_found = True
        return inp

    def _update_lost(self, dt: float, inp: GameInput) -> None:
        cam_ok = bool(self.tracker and self.tracker.ok)
        if not cam_ok or inp.found:
            self.lost_t = 0.0
        else:
            self.lost_t += dt

    def _lost_paused(self) -> bool:
        return bool(self.tracker and self.tracker.ok and self.lost_t >= C.LOST_PAUSE_AFTER)

    # ------------------------------------------------------------------ HUD
    def _draw_hud(self) -> None:
        g = self.game
        accent = getattr(g, "ACCENT", (110, 150, 240))
        bar = U.vgrad(C.DESIGN_W, C.HUD_H, (16, 20, 40), (10, 13, 28)).copy()
        self.screen.blit(bar, (0, 0))
        pygame.draw.rect(self.screen, accent, (0, 0, 7, C.HUD_H))
        pygame.draw.line(self.screen, (74, 92, 136), (0, C.HUD_H - 1),
                         (C.DESIGN_W, C.HUD_H - 1), 1)
        gl = U.glow_surface(120, accent, 52, 8)
        self.screen.blit(gl, (-60, C.HUD_H // 2 - 120))

        cls = type(g)
        U.text(self.screen, cls.TITLE, (36, 14), 38, (255, 255, 255), bold=True)
        U.text(self.screen, cls.SUB, (38, 58), 20, (150, 172, 210))

        x = 560
        for item in g.hud_items():
            label, value, col = item[0], item[1], item[2]
            icon = item[3] if len(item) > 3 else None
            U.text(self.screen, label, (x, 16), 20, (146, 168, 204))
            if icon == "heart":
                try:
                    n = int(value)
                except ValueError:
                    n = 0
                for i in range(max(3, n)):
                    self._heart(x + 20 + i * 34, 66, col if i < n else (72, 82, 104), 12)
            else:
                U.text(self.screen, str(value), (x, 40), 32, col, bold=True)
            x += 200

        # 模式
        if not (self.tracker and self.tracker.ok):
            mode, mcol = "键盘 / 鼠标模式", (250, 190, 90)
        elif self.paused:
            mode, mcol = "已暂停", (250, 200, 90)
        elif self._lost_paused():
            mode, mcol = "已暂停（找不到头）", (250, 150, 120)
        elif self._hands:
            mode, mcol = "头部 + 手部", (130, 230, 180)
        else:
            mode, mcol = "头部控制", (110, 220, 170)
        img = U.render_text(mode, 28, mcol, True)
        self.screen.blit(img, (C.DESIGN_W - 40 - img.get_width(), 16))
        fim = U.render_text(f"{self.clock.get_fps():4.0f} FPS", 20, (140, 165, 200))
        self.screen.blit(fim, (C.DESIGN_W - 40 - fim.get_width(), 54))

    def _heart(self, cx, cy, col, s=12):
        r = max(2, int(s * 0.62))
        pygame.draw.circle(self.screen, col, (int(cx - s * 0.5), int(cy - s * 0.35)), r)
        pygame.draw.circle(self.screen, col, (int(cx + s * 0.5), int(cy - s * 0.35)), r)
        pygame.draw.polygon(self.screen, col, [
            (cx - s * 1.05, cy - s * 0.12), (cx + s * 1.05, cy - s * 0.12), (cx, cy + s * 1.2)])

    # ------------------------------------------------------------------ 预览
    def _draw_preview(self) -> None:
        if not self.show_prev:
            return
        pw, ph = C.PREVIEW_W, C.PREVIEW_H
        # 菜单场景把预览放右下角：左下角要留给卡片，挡住一张卡很难看
        if self.scene == "menu":
            px = C.DESIGN_W - 28 - pw
            py = C.DESIGN_H - C.HINT_H - 18 - ph
        else:
            px, py = C.PREVIEW_X, C.PREVIEW_Y
        U.soft_shadow(self.screen, pygame.Rect(px, py, pw, ph), 16, 16, 130, (0, 8))
        panel = pygame.Surface((pw, ph))
        panel.fill((16, 20, 38))
        cam_ok = bool(self.tracker and self.tracker.ok)
        st = FaceState()
        if cam_ok and self._prev_frame is not None:
            frame = self._prev_frame
            rgb = np.ascontiguousarray(frame[:, :, ::-1].swapaxes(0, 1))
            panel = pygame.transform.smoothscale(
                pygame.surfarray.make_surface(rgb), (pw, ph))
            _, st, hands = self.tracker.get()
            sx, sy = pw / C.CAM_W, ph / C.CAM_H
            if st.box:
                bx, by, bw, bh = st.box
                pygame.draw.rect(panel, (110, 230, 170),
                                 (bx * sx, by * sy, bw * sx, bh * sy), 3, border_radius=6)
            if st.nose:
                pygame.draw.circle(panel, (250, 120, 110),
                                   (int(st.nose[0] * sx), int(st.nose[1] * sy)), 4)
            # 手部：画出 21 点骨架（这才是"精度"最直观的证据）
            for h in hands:
                col = (150, 240, 200) if h.open > 0.5 else (250, 180, 130)
                hf = getattr(h, "pose", None)
                if hf is not None and len(hf.joints) >= 8:
                    for a, b in HAND_EDGES:
                        pa, pb = hf.get(a), hf.get(b)
                        if pa.ok and pb.ok:
                            pygame.draw.line(panel, col,
                                             (pa.x * pw, pa.y * ph), (pb.x * pw, pb.y * ph), 2)
                    for jn in hf.joints.values():
                        if jn.ok:
                            pygame.draw.circle(panel, (255, 255, 255),
                                               (int(jn.x * pw), int(jn.y * ph)), 2)
                    hx, hy = hf.center.x * pw, hf.center.y * ph
                else:
                    hx, hy = h.x * pw, h.y * ph
                U.aa_circle(panel, (hx, hy), 30, (col[0], col[1], col[2], 130), 3, ss=2)
                U.aa_circle(panel, (hx, hy), 6, col, 0, ss=2)
                if h.bbox:
                    bx, by, bw, bh = h.bbox
                    pygame.draw.rect(panel, col, (bx * sx, by * sy, bw * sx, bh * sy), 2)
            # 人体骨架
            vf = self._vision
            if vf is not None and vf.pose.found:
                vcol = (120, 220, 255)
                for a, b in COCO17_EDGES:
                    pa, pb = vf.pose.get(a), vf.pose.get(b)
                    if pa.ok and pb.ok:
                        pygame.draw.line(panel, vcol,
                                         (pa.x * pw, pa.y * ph), (pb.x * pw, pb.y * ph), 2)
                for jn in vf.pose.joints.values():
                    if jn.ok:
                        pygame.draw.circle(panel, (255, 240, 170),
                                           (int(jn.x * pw), int(jn.y * ph)), 3)
            # 中性位与死区
            if self.head_ctl.neutral:
                ncx, ncy = self.head_ctl.neutral
                dz0 = int((ncx - C.DEADZONE_X) * pw)
                dz1 = int((ncx + C.DEADZONE_X) * pw)
                band = pygame.Surface((max(1, dz1 - dz0), ph), pygame.SRCALPHA)
                band.fill((90, 200, 130, 55))
                panel.blit(band, (dz0, 0))
                pygame.draw.line(panel, (90, 220, 140), (int(ncx * pw), 0),
                                 (int(ncx * pw), ph), 2)
                jy = int((ncy - C.JUMP_DY) * ph)
                pygame.draw.line(panel, (250, 200, 90), (0, jy), (pw, jy), 2)
        elif cam_ok:
            U.text(panel, "等待画面…", (pw // 2, ph // 2), 24, (200, 200, 200), center=True)
        else:
            U.text(panel, "无摄像头", (pw // 2, ph // 2 - 16), 26, (230, 130, 120), center=True)
            U.text(panel, "鼠标模拟手部", (pw // 2, ph // 2 + 18), 20, (200, 180, 150), center=True)

        self.screen.blit(panel, (px, py))
        U.rr(self.screen, pygame.Rect(px - 3, py - 3, pw + 6, ph + 6), 14,
             None, (86, 108, 156), 3)
        # 状态条
        cap = pygame.Surface((pw, 38), pygame.SRCALPHA)
        cap.fill((8, 11, 24, 216))
        self.screen.blit(cap, (px, py + ph - 38))
        if not cam_ok:
            s, col = "● 键盘 / 鼠标", (245, 170, 150)
        elif st.found:
            n = len(self._hands)
            s = f"● 已锁定头部" + (f"　手 x{n}" if n else "　未看到手")
            col = (110, 230, 170) if n else (250, 210, 130)
        else:
            s, col = "● 搜索头部…", (250, 200, 90)
        U.text(self.screen, s, (px + 10, py + ph - 30), 20, col, bold=True)
        if cam_ok:
            info = f"{self.tracker.fps:.0f}fps"
            img = U.render_text(info, 17, (160, 182, 216))
            self.screen.blit(img, (px + pw - 12 - img.get_width(), py + ph - 28))

    # ------------------------------------------------------------------ 提示条
    def _draw_hints(self) -> None:
        y = C.DESIGN_H - C.HINT_H
        bar = pygame.Surface((C.DESIGN_W, C.HINT_H), pygame.SRCALPHA)
        bar.fill((8, 11, 24, 200))
        self.screen.blit(bar, (0, y))
        pygame.draw.line(self.screen, (60, 76, 116), (0, y), (C.DESIGN_W, y), 1)
        hint = getattr(self.game, "HINT", "") if self.game else ""
        U.text(self.screen, hint, (36, y + 9), 22, (214, 228, 248))
        right = "ESC 返回大厅　R 重开　C 校准　P 暂停　H 预览　TAB 换游戏　F11 全屏"
        img = U.render_text(right, 20, (150, 172, 210))
        self.screen.blit(img, (C.DESIGN_W - 36 - img.get_width(), y + 11))

    # ------------------------------------------------------------------ 结算
    def _draw_result(self) -> None:
        g = self.game
        if g is None or g.state not in ("win", "over"):
            return
        ov = pygame.Surface((C.DESIGN_W, C.DESIGN_H), pygame.SRCALPHA)
        ov.fill((6, 9, 20, 202))
        self.screen.blit(ov, (0, 0))
        win = g.state == "win"
        col = (120, 240, 170) if win else (255, 128, 110)
        cx, cy = C.DESIGN_W // 2, C.DESIGN_H // 2
        U.text(self.screen, g.result_title(), (cx, cy - 150), 96, col, center=True,
               glow=24, glow_color=col, bold=True)
        U.text(self.screen, g.result_sub(), (cx, cy - 44), 34, (255, 255, 255),
               center=True, shadow=3)
        r = pygame.Rect(cx - 420, cy + 30, 840, 84)
        U.rr(self.screen, r, 18, (255, 255, 255, 18), (255, 255, 255, 60), 2)
        U.text(self.screen, "R  重开本局", (cx - 180, cy + 58), 30, (222, 234, 252), center=True)
        U.text(self.screen, "ESC  返回大厅", (cx + 180, cy + 58), 30, (222, 234, 252), center=True)
        U.text(self.screen, "按 ESC 回到大厅可切换其他游戏（TAB 直接换下一个）",
               (cx, cy + 158), 24, (150, 172, 210), center=True)

    # ------------------------------------------------------------------ 提醒
    def _draw_alerts(self) -> None:
        cam_ok = bool(self.tracker and self.tracker.ok)
        if not cam_ok:
            # 菜单自己已经有状态指示，这里只在游戏里提示，避免压住大厅标题
            if self.scene == "game":
                U.text(self.screen, "摄像头不可用 —— 已用鼠标模拟手部（按住左键=握拳），键盘亦可操作",
                       (C.DESIGN_W // 2, C.HUD_H + 22), 26, (255, 210, 140), center=True, shadow=3)
            return
        if self._lost_paused() is False and self.head_ctl.calibrating \
                and self.lost_t < C.LOST_WARN_AFTER:
            U.text(self.screen, "正在校准中性位，请自然正对摄像头…", (C.DESIGN_W // 2, C.HUD_H + 22),
                   28, (255, 255, 255), center=True, shadow=3)
            w, h = 460, 14
            x, y = C.DESIGN_W // 2 - w // 2, C.HUD_H + 58
            U.rr(self.screen, pygame.Rect(x, y, w, h), 7, (60, 70, 94))
            U.rr(self.screen, pygame.Rect(x, y, max(8, int(w * self.head_ctl.progress)), h),
                 7, (110, 220, 150))
            return
        if self.lost_t >= C.LOST_WARN_AFTER:
            ov = pygame.Surface((C.DESIGN_W, C.DESIGN_H), pygame.SRCALPHA)
            ov.fill((70, 10, 10, 122))
            self.screen.blit(ov, (0, 0))
            cx, cy = C.DESIGN_W // 2, C.DESIGN_H // 2
            card = pygame.Rect(cx - 440, cy - 110, 880, 220)
            U.soft_shadow(self.screen, card, 24, 26, 160, (0, 12))
            U.rr(self.screen, card, 24, (152, 34, 34, 240), (255, 190, 180), 3)
            U.text(self.screen, "未检测到头部", (cx, cy - 44), 54, (255, 255, 255),
                   center=True, shadow=3, bold=True)
            U.text(self.screen, "请让面部进入摄像头画面，游戏已暂停", (cx, cy + 24), 30,
                   (255, 234, 230), center=True)
            U.text(self.screen, f"已丢失 {self.lost_t:4.1f} 秒", (cx, cy + 70), 26,
                   (255, 212, 202), center=True)

    def _draw_toast(self) -> None:
        if self.toast_t <= 0 or not self.toast:
            return
        img = U.render_text(self.toast, 30, (255, 255, 255))
        r = pygame.Rect(0, 0, img.get_width() + 64, 62)
        r.center = (C.DESIGN_W // 2, C.HUD_H + 56)
        U.rr(self.screen, r, 16, (12, 16, 34, 232), (120, 150, 210), 2)
        self.screen.blit(img, (r.centerx - img.get_width() // 2,
                               r.centery - img.get_height() // 2))
