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
from dataclasses import replace
from typing import List, Optional, Tuple

import cv2
import numpy as np
import pygame

from . import base as B
from . import config as C
from . import icons
from . import theme as U
from .inputs import (BodyController, FaceState, GameInput, HandController, HandState,
                     HeadController)
from .menu import Menu
from . import ui as UI
from . import sfx
from .avatar import PlayerAvatar
from .feedback import Feedback
from .scene import Atmosphere
from .vision import COCO17_EDGES, HAND_EDGES

ZERO = GameInput()


class Shell:
    def __init__(self, vision: str = "auto", cam_index: int = C.CAM_INDEX,
                 no_cam: bool = False, windowed: bool = False,
                 start_game: str = "menu") -> None:
        # 混音器要在 pygame.init() **之前** pre_init，否则采样率/缓冲会被
        # 默认值锁定，短促的卡通音效会有明显延迟（听感上就是"按了没响"）。
        if C.SFX_ENABLE:
            try:
                pygame.mixer.pre_init(44100, -16, 2, 512)
            except Exception:                                    # noqa: BLE001
                pass
        pygame.init()
        pygame.display.set_caption(C.TITLE)
        if C.SFX_ENABLE:
            sfx.init()
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
        # 默认**不再常驻**摄像头调试画面：玩家看到的是卡通化身卡片。
        # 原始画面 + 骨架 + FPS 归到按 H 打开的诊断层。
        self.show_diag = False
        self.avatar = PlayerAvatar(UI.PRIMARY, "PLAYER 1")
        self.fx = Feedback()
        self.atm = Atmosphere(C.DESIGN_W, C.DESIGN_H, UI.PRIMARY)
        self._face = FaceState()
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
        # 摄像头预览表面：**按目标尺寸分别缓存**。
        # 大厅光球（132）和游戏内卡片（328×228）尺寸不同，共用一个字段会互相
        # 覆盖 —— 现在两个场景不会同帧出现所以看不出问题，但那是隐藏耦合，
        # 一旦以后要同屏显示就会错位。按尺寸分桶就没有这个隐患。
        self._cam_cache: dict = {}
        self._cam_acc = 1.0
        self._hands: List[HandState] = []
        # HUD 的"数值变化 → 弹一下"所需的状态
        self._hud_prev: dict = {}
        self._hud_pop: dict = {}
        self._dt = 1.0 / 60.0
        self._t = 0.0                     # 全局时间（驱动所有 UI 微动画）
        self._enter = 0.0                 # 进入游戏的转场计时（镜头推进 + 淡入）
        self._menu_sel = -1               # 大厅选中项（变化时出声）
        # 结算页：本局是否已结算过 / 结算后的计时 / 本机本次运行的最好成绩
        self._result_key: tuple = ()
        self._result_t = 0.0
        self._best: dict = {}
        self._record = False
        self._score_final = 0
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
            self._dt = dt
            self._t += dt
            self._events()
            inp = self._input(dt)
            self._update_lost(dt, inp)
            self._update_avatar(dt, inp)
            self.fx.update(dt)
            self.atm.update(dt)
            if self._enter > 0:
                self._enter = max(0.0, self._enter - dt)
            if self.scene == "menu" and self.menu.sel != self._menu_sel:
                if self._menu_sel >= 0:
                    sfx.play("move")
                self._menu_sel = self.menu.sel
            if self.toast_t > 0:
                self.toast_t = max(0.0, self.toast_t - dt)
            if self.fade > 0:
                self.fade = max(0.0, self.fade - dt * 3.0)

            if self.scene == "menu":
                self.menu.info["fps"] = self.clock.get_fps()
                self.menu.info["track"] = self._track_state()
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
        # ---- 进入游戏的转场：镜头推进 + 淡入（prompt 第 6 项"转场"）----
        # 一帧一次的 smoothscale，代价约 2~3ms，且只在 0.42 秒内发生。
        # 它替代了"硬切"——硬切正是"网页小游戏"最典型的手感。
        if self._enter > 0:
            k = self._enter / max(1e-3, C.ENTER_ANIM)      # 1 → 0
            e = U.ease_out_cubic(1.0 - k)
            zoom = 1.0 + 0.055 * (1.0 - e)
            self._enter_canvas = pygame.transform.smoothscale(
                self.canvas, (int(C.DESIGN_W * zoom), int(C.DESIGN_H * zoom)))
            off = ((self.screen.get_width() - self._enter_canvas.get_width()) // 2,
                   (self.screen.get_height() - self._enter_canvas.get_height()) // 2)
            self.screen.blit(self._enter_canvas, off)
            if k > 0.02:
                veil = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
                veil.fill((10, 8, 26, int(200 * k ** 1.4)))
                self.screen.blit(veil, (0, 0))
        else:
            self.screen.blit(self.canvas, off)

        # ---- 全屏氛围层：叠在世界之上、UI 之下 ----
        # 这是"让 20 款游戏看起来像同一个游戏"最省力的一刀：统一的空气感、
        # 柔光与暗角，不需要改任何游戏。游戏自己的 HUD/面板在它之上，所以不受影响。
        if self.scene == "game":
            self.atm.draw(self.screen)

        over = bool(self.game is not None and self.game.state in ("win", "over"))
        if self.show_diag:
            self._draw_debug()
        if self.scene == "game":
            if not over:
                self._draw_player_card()
                self._draw_hud()
                self._draw_hints()
            self._draw_score_fx()
            self._draw_result()
            self._draw_pause()
        else:
            self._draw_menu_avatar()
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
            elif k == pygame.K_m:
                m = sfx.toggle_mute()
                self.toast_msg(U.T("已静音" if m else "音效已开启",
                                   "Muted" if m else "Sound on"))
            elif k == pygame.K_h:
                self.show_diag = not self.show_diag
                self.toast_msg(U.T(f"诊断层：{'开' if self.show_diag else '关'}",
                                   f"Diagnostics: {'on' if self.show_diag else 'off'}"))
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
        # 换游戏时清掉基线：否则首帧的"数值变化"会误触发一次反馈
        self._hud_prev.clear()
        self._hud_pop.clear()
        self.fx.reset()
        acc = UI.normalize_accent(getattr(cls, "ACCENT", UI.PRIMARY))
        self.avatar.color = acc
        self.fx.set_accent(acc)
        self._result_key = ()
        self._score_final = 0
        self._enter = C.ENTER_ANIM
        sfx.play("confirm")
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
        self._hud_prev.clear()
        self.fx.reset()
        self.avatar.color = UI.PRIMARY
        self.fx.set_accent(UI.PRIMARY)
        sfx.play("move")
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
            self._face = st
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

    def _track_state(self) -> str:
        """
        头部识别状态：track（正常）/ hold（短暂丢帧，输入冻结）/ lost（未识别，输入归零）。

        HOLD 是防抖的关键：单帧漏检很常见，若直接按"丢失"处理，控制量会在帧
        之间反复重启/停住，表现为角色自己在动。这里把三态显式暴露出来，
        真机上能一眼看出状态机有没有按预期工作。
        """
        if not (self.tracker and self.tracker.ok):
            return "lost"
        hc = self.head_ctl
        if hc.lost_t <= 0.0:
            return "track"
        if hc.lost_t <= C.HOLD_AFTER:
            return "hold"
        return "lost"

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
        """
        游戏内 HUD。

        设计取向是**浮层，不是状态栏**。旧版是一条贯穿全宽、带 1px 分割线的
        深色条，四项 label / value 平铺 —— 那是后台管理系统的语言。现在换成浮在
        画面上的独立卡片：图标 + 小标签 + 大数值，靠"小标签 / 大数值"的强层级
        让 2~4 米外先读到数值。

        同时**移除了给玩家看的 FPS 与快捷键**：那是调试信息，不是游戏信息。
        FPS 只留在按 H 打开的诊断预览里，快捷键移到暂停面板。
        """
        g = self.game
        cls = type(g)

        # ---- 左：标题 ----
        U.text(self.screen, cls.TITLE, (42, 14), UI.T_M, UI.PAPER, bold=True,
               outline=UI.INK, outline_w=4)
        U.text(self.screen, cls.SUB, (46, 68), UI.T_XS, UI.PAPER_DIM, bold=True)

        # ---- 中：状态卡 ----
        items = g.hud_items()
        hx0, hx1 = 452, C.DESIGN_W - 452
        if items:
            gap = UI.GAP_S
            cw = int(min(276, (hx1 - hx0 - gap * (len(items) - 1)) / len(items)))
            ch = 88
            y = (C.HUD_H - ch) // 2
            for i, item in enumerate(items):
                label = str(item[0])
                value = str(item[1])
                col = UI.normalize_accent(item[2])
                icon = item[3] if len(item) > 3 else ""
                # 数值一变就弹一下 —— "我的操作有反馈"里最便宜也最有效的一环
                pop = self._hud_pop.setdefault(label, UI.Pop())
                r = pygame.Rect(hx0 + i * (cw + gap), y, cw, ch)
                if self._hud_prev.get(label) != value:
                    if label in self._hud_prev:
                        pop.hit()
                        self._hud_event(label, value, self._hud_prev[label], r, col)
                    self._hud_prev[label] = value
                amt = pop.step(self._dt)
                if icon == "heart":
                    self._draw_hearts(r, value, amt)
                else:
                    UI.stat(self.screen, r, label, value, col, icon, amt)

        # ---- 右：识别状态（右对齐；用居中摆放会因为文字变长而整体抖动）----
        state = self._track_state()
        if not (self.tracker and self.tracker.ok):
            mode, mcol, micon = "键盘 / 鼠标", UI.WARN, "wave"
        elif self.paused:
            mode, mcol, micon = "已暂停", UI.WARN, "clock"
        elif state == "track":
            n = len(self._hands)
            mode = "头部已锁定" + (f" · 手 {n}" if n else "")
            mcol, micon = UI.ACCENT, "check"
        elif state == "hold":
            mode, mcol, micon = "短暂丢帧 · 输入冻结", UI.WARN, "clock"
        else:
            mode, mcol, micon = "未识别到头 · 已暂停", UI.DANGER, "eye"
        UI.pill(self.screen, (C.DESIGN_W - 42, 56), mode, mcol, micon,
                size=UI.T_XS, align="right", height=60)

    # 时间类数值是**倒计时**，每秒都在变；把它当"得分"会每秒弹一次 +1，
    # 所以显式排除。这是"由数值变化推断反馈"唯一需要人工标注的地方。
    _HUD_QUIET = ("时间", "剩余", "Time", "计时")
    _HUD_LIFE = ("生命", "命", "Lives")

    def _hud_event(self, label: str, value: str, prev: str,
                   r: pygame.Rect, col) -> None:
        """
        由 HUD 数值变化推断"玩家刚完成了一次操作"，并产出反馈。

        这样做的好处是**20 款游戏零改动**就获得了统一的得分反馈，
        而且各游戏的反馈手感完全一致 —— 这正是"像同一个团队做的"整体感来源。
        """
        if label in self._HUD_QUIET:
            return
        try:
            dv = int(value) - int(prev)
        except (TypeError, ValueError):
            return
        x, y = r.centerx, r.bottom + 14
        if dv > 0:
            self.fx.score(x, y, dv, col)
            self.avatar.hit(min(1.2, 0.6 + dv / 60.0))
        elif dv < 0 and label in self._HUD_LIFE:
            self.fx.fail(x, y)

    def _draw_hearts(self, r: pygame.Rect, value: str, pop: float) -> None:
        """生命值：画心形图标而不是数字 —— 图标被识别的速度比数字快一个量级。"""
        UI.card(self.screen, r, UI.R_MD)
        pygame.draw.rect(self.screen, UI.DANGER, (r.x + 2, r.y + 12, 7, r.h - 24),
                         border_radius=4)
        UI.text(self.screen, "生命", (r.x + 22, r.y + 10), UI.T_XS, UI.PAPER_DIM)
        try:
            n = int(value)
        except (TypeError, ValueError):
            n = 0
        total = max(3, min(6, n))
        rr = 20
        step = rr * 2 + 12
        x0 = r.x + 24 + rr
        cy = r.y + 60
        for i in range(total):
            on = i < n
            sz = rr * 2 * (1.0 + 0.22 * pop) if (on and pop > 0.01) else rr * 2
            UI.draw_icon(self.screen, "heart", x0 + i * step, cy, sz,
                         UI.DANGER if on else (86, 78, 128))

    def _update_avatar(self, dt: float, inp: GameInput) -> None:
        """
        驱动玩家化身。

        **只消费识别结果，不产生任何控制量** —— 所以接进来不会改变玩法。
        无摄像头时用鼠标位置驱动，保证演示时画面里始终有"玩家"。
        """
        if self.tracker and self.tracker.ok:
            st = self._face
            self.avatar.update(dt, st.cx, st.cy, self._track_state() == "track")
        else:
            self.avatar.update(dt, inp.hx, inp.hy, True)

    def _draw_score_fx(self) -> None:
        """得分/连击的即时反馈（P5 实现，见 feedback 模块）。"""
        self.fx.draw(self.screen)

    def _draw_menu_avatar(self) -> None:
        """
        大厅里的**紧凑化身**（只有头和能量环，贴在标题右侧）。

        大厅的选择网格占满整宽，左下角没有空间放整张玩家卡片 ——
        但"玩家自己在画面里"这件事在大厅同样重要（否则第一屏又变成了工具界面）。
        所以这里放一个紧凑版：状态一眼可见，又不遮挡任何一张卡。
        """
        cam_ok = bool(self.tracker and self.tracker.ok)
        state = self._track_state() if cam_ok else "track"
        orb = self._cam_preview(132, 132) if cam_ok else None
        # 位置（508, 52）：标题与副标题占 x<420，状态胶囊在右端，
        # 这一带是页眉里唯一干净的空档 —— 放在 648 会顶到英雄区上沿。
        self.avatar.draw_cam_orb(self.screen, 516, 52, 104, orb,
                                 self._face_in_preview((132, 132))
                                 if orb is not None else None, self._t, state)
        self.avatar.draw_particles(self.screen, 648, 56, 150)

    def _cam_preview(self, w: int, h: int) -> Optional[pygame.Surface]:
        """
        把最新一帧摄像头画面缩成预览表面（限频 + 复用）。

        为什么必须限频：把 BGR 的 numpy 帧变成 pygame 表面要走
        「缩放 + 通道序转换 + 拷贝」，实测 4~5ms —— 每帧都做就吃掉 16.7ms
        预算的四分之一，而这个窗口只是"让玩家看见自己在画面里"。
        降到 CAM_PREVIEW_HZ（20Hz）之后均摊不到 1ms，肉眼分辨不出来。
        """
        frame = self._prev_frame
        if frame is None:
            return None
        key = (int(w), int(h))
        slot = self._cam_cache.get(key)
        self._cam_acc += self._dt
        need = (slot is None
                or self._cam_acc >= 1.0 / max(1.0, C.CAM_PREVIEW_HZ))
        if need:
            self._cam_acc = 0.0
            try:
                fh, fw = frame.shape[:2]
                # **等比裁剪再缩放**，而不是直接拉成目标尺寸。
                # 摄像头是 640×480（1.33:1）、卡片画面区是 328×228（1.44:1），
                # 直接 resize 会把脸横向拉宽 8% —— 单看不明显，但它会让"镜子里的我"
                # 有一点点不对劲，而这正是玩家最容易察觉的那类问题。
                ta = w / max(1.0, h)
                if fw / fh > ta:                     # 源更宽 → 裁两侧
                    nw = max(2, int(round(fh * ta)))
                    x0, y0, nh = (fw - nw) // 2, 0, fh
                else:                                # 源更高 → 裁上下
                    nh = max(2, int(round(fw / ta)))
                    x0, y0, nw = 0, (fh - nh) // 2, fw
                crop = frame[y0:y0 + nh, x0:x0 + nw]
                small = cv2.resize(crop, (w, h), interpolation=cv2.INTER_AREA)
                rgb = np.ascontiguousarray(small[:, :, ::-1])
                surf = pygame.image.frombuffer(rgb.tobytes(), (w, h), "RGB")
                # 裁剪参数和表面一起缓存：头部光环的坐标必须按同一个变换
                # 重映射，否则环会偏离真实头部（偏得还很隐蔽 —— 只在人脸靠边时明显）。
                slot = (surf.convert(), (x0, y0, nw, nh, fw, fh))
                self._cam_cache[key] = slot
            except Exception:                                    # noqa: BLE001
                return slot[0] if slot else None
        return slot[0] if slot else None

    def _face_in_preview(self, size) -> FaceState:
        """把 FaceState 的坐标从"整帧"重映射到"裁剪后的预览区"。"""
        st = self._face
        slot = self._cam_cache.get((int(size[0]), int(size[1])))
        crop = slot[1] if slot else None
        if st is None or crop is None or not st.found:
            return st
        x0, y0, nw, nh, fw, fh = crop
        k = fw / max(1, nw)             # 尺度相对放大倍数
        return replace(
            st,
            cx=(st.cx * fw - x0) / max(1, nw),
            cy=(st.cy * fh - y0) / max(1, nh),
            w=st.w * k, h=st.h * k)

    def _draw_player_card(self) -> None:
        """左下角玩家卡片（卡通化身 + 识别位置）。原始画面见 _draw_debug。"""
        r = pygame.Rect(C.PREVIEW_X, C.PREVIEW_Y, C.PREVIEW_W, C.PREVIEW_H)
        cam_ok = bool(self.tracker and self.tracker.ok)
        state = self._track_state() if cam_ok else "track"
        # ---- 有摄像头：画面 + 包住真实头部的能量环（保留玩家想看到的自己）----
        if cam_ok:
            img = pygame.Rect(0, 0, r.w - 24, r.h - 66 - 12)
            cam = self._cam_preview(img.w, img.h)
            self.avatar.draw_cam_card(self.screen, r, cam,
                                      self._face_in_preview(img.size),
                                      self._t, state, "PLAYER 1")
            return
        # ---- 无摄像头：卡通化身 + 识别位置条（键盘/鼠标模式）----
        hc = self.head_ctl
        neutral = hc.neutral[0] if hc.neutral else None
        # 死区是"人脸尺度"（0.26 个脸宽），换算到画面坐标要乘当前脸宽 ——
        # 这样那条绿色区间会随"坐远坐近"自动变窄变宽，
        # 正是"手感与距离无关"最直观的证据。
        dz = C.DEADZONE_FACE * max(0.03, hc.nw)
        self.avatar.draw_card(self.screen, r, self._t, state,
                              hud="键盘 / 鼠标", neutral=neutral,
                              deadzone=dz)

    def _draw_debug(self) -> None:
        """诊断层（按 H 打开）：原始摄像头 + 检测框 + 骨架 + FPS。"""
        pw, ph = C.PREVIEW_W, C.PREVIEW_H
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
            # 中性位与死区（死区是"人脸尺度"，换算到画面要乘当前脸宽）
            hc = self.head_ctl
            if hc.neutral:
                ncx, ncy = hc.neutral
                fw = max(0.03, hc.nw)
                fh = max(0.03, hc.nh)
                dz = C.DEADZONE_FACE * fw
                dz0 = int((ncx - dz) * pw)
                dz1 = int((ncx + dz) * pw)
                band = pygame.Surface((max(1, dz1 - dz0), ph), pygame.SRCALPHA)
                band.fill((90, 200, 130, 55))
                panel.blit(band, (dz0, 0))
                pygame.draw.line(panel, (90, 220, 140), (int(ncx * pw), 0),
                                 (int(ncx * pw), ph), 2)
                # 满速线：让"要移多远才到满速"也能看见
                for sgn in (-1, 1):
                    fx = int((ncx + sgn * C.FULL_SCALE_FACE * fw) * pw)
                    pygame.draw.line(panel, (150, 220, 250), (fx, 0), (fx, ph), 2)
                # 动作键阈值线：换算成"纵向平移需要多少"来画（俯仰分量无法直接画）
                dy_need = C.DEADZONE_FACE_Y + C.JUMP_ON * (
                    C.FULL_SCALE_FACE_Y - C.DEADZONE_FACE_Y)
                jy = int((ncy - dy_need * fh) * ph)
                pygame.draw.line(panel, (250, 200, 90), (0, jy), (pw, jy), 2)
        elif cam_ok:
            U.text(panel, "等待画面…", (pw // 2, ph // 2), 24, (200, 200, 200), center=True)
        else:
            U.text(panel, "无摄像头", (pw // 2, ph // 2 - 16), 26, (230, 130, 120), center=True)
            U.text(panel, "鼠标模拟手部", (pw // 2, ph // 2 + 18), 20, (200, 180, 150), center=True)

        self.screen.blit(panel, (px, py))
        U.rr(self.screen, pygame.Rect(px - 3, py - 3, pw + 6, ph + 6), 14,
             None, (86, 108, 156), 3)

        # 实时读数：摇头/抬头为什么"没反应"还是"太灵"，看这几个数最直接。
        d = self.head_ctl._debug
        if d:
            lines = [
                f"脸宽 {d.get('face_w', 0):.3f}  姿态{'✓' if d.get('pose_ok') else '✗'}",
                f"平移 {d.get('a_move', 0):+.2f}   摇头 {d.get('a_yaw', 0):+.2f}"
                f"  (yaw {d.get('yaw', 0):+.2f})",
                f"俯仰 {d.get('b_pitch', 0):+.2f}   位移 {d.get('b_move', 0):+.2f}"
                f"   抬起 {d.get('lift', 0):+.2f}",
            ]
            y0 = py + ph + 12
            for i, ln in enumerate(lines):
                U.text(self.screen, ln, (px + 4, y0 + i * 26), 19,
                       (206, 216, 240), bold=True, shadow=3)
        # 状态条
        cap = pygame.Surface((pw, 38), pygame.SRCALPHA)
        cap.fill((8, 11, 24, 216))
        self.screen.blit(cap, (px, py + ph - 38))
        if not cam_ok:
            s, col = "● 键盘 / 鼠标", (245, 170, 150)
        else:
            state = self._track_state()
            n = len(self._hands)
            if state == "track":
                s = "● 头部已锁定" + (f"　手 x{n}" if n else "　未看到手")
                col = (110, 230, 170) if n else (250, 210, 130)
            elif state == "hold":
                s, col = "◐ 短暂丢帧 · 输入冻结", (250, 200, 90)
            else:
                s, col = "○ 未识别到头 · 输入归零", (245, 140, 130)
        U.text(self.screen, s, (px + 10, py + ph - 30), 20, col, bold=True)
        if cam_ok:
            info = f"{self.tracker.fps:.0f}fps"
            img = U.render_text(info, 17, (160, 182, 216))
            self.screen.blit(img, (px + pw - 12 - img.get_width(), py + ph - 28))

    # ------------------------------------------------------------------ 提示条
    def _draw_hints(self) -> None:
        """
        底部只手势提示，**不再列键盘快捷键**。

        旧的底部条把 ESC / R / C / P / H / TAB / F11 全列出来 —— 那是开发工具的
        状态栏。玩家站在电视前既不会看、也不需要看，反而一眼就暴露"这是 Demo"。
        快捷键全部移进暂停面板（玩家主动暂停时才有耐心看）。
        """
        hint = getattr(self.game, "HINT", "") if self.game else ""
        if not hint:
            return
        y = C.DESIGN_H - C.HINT_H
        UI.pill(self.screen, (C.DESIGN_W // 2, y + C.HINT_H // 2 + 2),
                hint, UI.SURFACE, size=UI.T_S, alpha=196,
                height=C.HINT_H - 10, pad=44)

    def _draw_pause(self) -> None:
        """暂停面板：快捷键说明的归宿。"""
        if not self.paused:
            return
        ov = pygame.Surface((C.DESIGN_W, C.DESIGN_H), pygame.SRCALPHA)
        ov.fill((14, 10, 34, 208))
        self.screen.blit(ov, (0, 0))
        cx, cy = C.DESIGN_W // 2, C.DESIGN_H // 2
        panel = pygame.Rect(cx - 470, cy - 258, 940, 516)
        UI.ink_card(self.screen, panel, UI.R_XL, 244)
        UI.text(self.screen, "已 暂 停", (cx, cy - 196), UI.T_XL, UI.PAPER,
                center=True, outline=UI.INK, outline_w=5)
        U.text(self.screen, "抬头 · 或按 P 继续", (cx, cy - 112), UI.T_S,
               UI.ACCENT, center=True, bold=True)
        rows = [("P · 抬头", "继续游戏"), ("R", "重开本局"), ("C", "重新校准中性位"),
                ("H", "显示 / 隐藏摄像头预览"), ("TAB", "换下一个游戏"),
                ("ESC", "返回大厅"), ("F11", "全屏 / 窗口")]
        y = cy - 42
        for k, v in rows:
            UI.pill(self.screen, (cx - 176, y), k, UI.PRIMARY, size=UI.T_XS,
                    align="right", height=48, alpha=206)
            U.text(self.screen, v, (cx - 142, y - 16), UI.T_S, UI.PAPER, bold=True)
            y += 58

    # ------------------------------------------------------------------ 结算
    def _game_score(self) -> int:
        """取本局得分：优先找名字里带"分"的 HUD 项，否则取第一个能转成整数的。"""
        items = self.game.hud_items() if self.game else []
        for item in items:
            if "分" in str(item[0]):
                try:
                    return int(item[1])
                except (TypeError, ValueError):
                    return 0
        for item in items:
            try:
                return int(item[1])
            except (TypeError, ValueError):
                continue
        return 0

    def _draw_result(self) -> None:
        """
        结算页。

        旧版是"一行大字 + 两行提示"，没有任何仪式感，玩家感觉不到"这一局结束了"。
        现在按商业游戏的做法给足反馈：弹入的大标题、滚动的得分、星级、
        最高连击、新纪录徽章、庆祝粒子，以及两个大按钮。

        星级与"新纪录"都只用**本局已有的数据**推出来（胜负 / 得分 / 最高连击），
        所以不需要改动任何游戏的玩法逻辑。
        """
        g = self.game
        if g is None or g.state not in ("win", "over"):
            return
        win = g.state == "win"

        # ---- 首次进入结算：记分、判定新纪录、放庆祝 ----
        key = (self.game_key, g.state)
        if self._result_key != key:
            self._result_key = key
            self._result_t = 0.0
            sc = self._game_score()
            prev = self._best.get(self.game_key)
            self._record = (prev is None or sc > prev) and sc > 0
            if prev is None or sc > prev:
                self._best[self.game_key] = sc
            self._score_final = sc
            sfx.play("celebrate" if win else "fail")
            if win:
                self.fx.celebrate()
        self._result_t += max(1e-3, self._dt)
        t = self._result_t

        accent = UI.normalize_accent(getattr(g, "ACCENT", UI.PRIMARY))
        col = UI.ACCENT if win else UI.DANGER

        ov = pygame.Surface((C.DESIGN_W, C.DESIGN_H), pygame.SRCALPHA)
        ov.fill((12, 9, 30, 216))
        self.screen.blit(ov, (0, 0))
        cx = C.DESIGN_W // 2
        U.glow(self.screen, (cx, C.DESIGN_H // 2), 620, col, 44, 9)

        panel = pygame.Rect(cx - 530, 100, 1060, 880)
        enter = U.ease_out_back(U.clamp((t - 0.02) / 0.45, 0.0, 1.0))
        if enter <= 0.01:
            return
        panel = panel.inflate(int(panel.w * (enter - 1) * 0.5),
                              int(panel.h * (enter - 1) * 0.5))
        UI.card(self.screen, panel, UI.R_XL, glow=col, glow_a=64,
                top=U.mix(UI.SURFACE_HI, accent, 0.14),
                bottom=U.mix(UI.SURFACE_LO, accent, 0.05))

        # ---- 大标题 ----
        pop = U.ease_out_back(U.clamp((t - 0.10) / 0.45, 0.0, 1.0))
        title = g.result_title()
        img = U.outline_text(title, int(UI.T_HERO * (0.72 + 0.28 * pop)), col,
                             UI.INK, 7, True)
        U.glow(self.screen, (cx, panel.y + 96), int(200 * pop), col, 90)
        self.screen.blit(img, (cx - img.get_width() // 2, panel.y + 96 - img.get_height() // 2))
        U.text(self.screen, g.result_sub(), (cx, panel.y + 186), UI.T_S,
               (226, 220, 250), center=True)

        # ---- 得分（数字滚动）----
        k = U.clamp((t - 0.30) / 0.85, 0.0, 1.0)
        shown = int(self._score_final * U.ease_out_cubic(k))
        UI.text(self.screen, "本 局 得 分", (cx, panel.y + 246), UI.T_XS,
                UI.PAPER_DIM, center=True)
        num = U.outline_text(str(shown), UI.T_HERO, UI.SECONDARY, UI.INK, 7, True)
        bounce = 1.0 + 0.10 * max(0.0, math.sin(min(1.0, k) * math.pi * 3.2)) * (1 - k)
        if bounce > 1.001:
            num = pygame.transform.rotozoom(num, 0, bounce)
        U.glow(self.screen, (cx, panel.y + 350), 190, UI.SECONDARY, 70)
        self.screen.blit(num, (cx - num.get_width() // 2, panel.y + 350 - num.get_height() // 2))

        # ---- 星级 ----
        stars = 1
        if win:
            stars += 2
        if self.fx.max_combo >= 3:
            stars += 1
        if self._score_final > 0:
            stars += 1
        stars = max(1, min(3, stars))
        if t > 0.55:
            UI.stars(self.screen, (cx, panel.y + 452), stars, 3, 42,
                      max(0.0, t - 0.55))

        # ---- 最高连击 / 新纪录 ----
        # 新纪录徽章单独占一行（放在星级与统计卡之间）。
        # 之前把它压在统计卡上，两块内容互相打架 —— 徽章是"这一局的高光"，
        # 必须有自己的位置。
        if self._record and t > 0.85:
            UI.pill(self.screen, (cx, panel.y + 512), "★  新 纪 录  ★",
                    UI.SECONDARY, size=UI.T_S, height=52, glow=True)
        stats = [(f"×{max(self.fx.max_combo, 1)}", "最高连击", UI.ACCENT),
                 (str(self._best.get(self.game_key, self._score_final)), "本次最好", UI.PRIMARY)]
        bw, gap = 280, 28
        x0 = cx - (len(stats) * bw + (len(stats) - 1) * gap) // 2
        for i, (v, label, c) in enumerate(stats):
            r = pygame.Rect(x0 + i * (bw + gap), panel.y + 560, bw, 112)
            UI.stat(self.screen, r, label, v, c,
                    "combo" if i == 0 else "trophy")

        # ---- 按钮 ----
        UI.big_button(self.screen, pygame.Rect(cx - 470, panel.bottom - 148, 440, 116),
                      "再 来 一 局", accent, t=self._t, hot=True, size=UI.T_M,
                      sub="按 R")
        UI.pill(self.screen, (cx + 250, panel.bottom - 90), "返回大厅　按 ESC",
                UI.PRIMARY, icon="check", size=UI.T_S, height=72, pad=40)

    # ------------------------------------------------------------------ 提醒
    def _draw_alerts(self) -> None:
        # 结算页会盖住整个世界，上面再压一行"键盘/鼠标模式"只会显噪
        if self.game is not None and self.game.state in ("win", "over"):
            return
        cam_ok = bool(self.tracker and self.tracker.ok)
        if not cam_ok:
            # 菜单自己已经有状态指示，这里只在游戏里提示，避免压住大厅标题。
            # 做成靠左的胶囊贴在 HUD 下方 —— 之前是一行横在画面正中的白字，
            # 既压住了 HUD 卡片，也是典型的"调试信息直接给玩家看"。
            if self.scene == "game":
                UI.pill(self.screen, (42, C.HUD_H + 30),
                        "键盘 / 鼠标模式　方向键移动 · 空格动作 · 按住左键 = 握拳",
                        UI.WARN, icon="wave", size=UI.T_XS, align="left",
                        height=52, alpha=196)
            return
        if self._lost_paused() is False and self.head_ctl.calibrating \
                and self.lost_t < C.LOST_WARN_AFTER:
            UI.pill(self.screen, (C.DESIGN_W // 2, C.HUD_H + 34),
                    "正在校准中性位，请自然正对摄像头…", UI.PRIMARY,
                    icon="target", size=UI.T_XS, height=54)
            w, h = 520, 16
            x, y = C.DESIGN_W // 2 - w // 2, C.HUD_H + 70
            U.rr(self.screen, pygame.Rect(x, y, w, h), h // 2, (58, 50, 104))
            U.rr(self.screen, pygame.Rect(x, y, max(h, int(w * self.head_ctl.progress)), h),
                 h // 2, UI.ACCENT)
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
