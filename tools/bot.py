"""
tools/bot.py
============
无头测试用的"假玩家输入"。让每个游戏都能被驱动起来，
从而在没有真人和摄像头的情况下验证玩法逻辑与渲染。

提供三档水平：
    bot_input(...)          全能机器人（头 + 手都有，动作精准）
    human_input(...)        模拟真人（带抖动与延迟，用于难度校准）
    zero_input()            完全静止（用于验证"不操作"不会崩）
"""
from __future__ import annotations

import math
import random

from core.inputs import GameInput, HandState


def _hand(x: float, y: float, op: float, area: float = 0.05) -> HandState:
    return HandState(found=True, x=x, y=y, open=op, fingers=3, area=area, span=0.2)


def bot_input(g=None, i: int = 0, frames: int = 240) -> GameInput:
    inp = GameInput()
    inp.found = True
    inp.axis = math.sin(i * 0.021) * 0.75
    inp.up = 0.5 + 0.5 * math.sin(i * 0.013)
    inp.head_y = math.sin(i * 0.013)
    inp.yaw = math.sin(i * 0.017) * 0.6
    inp.jump = (i % 46) < 3
    inp.hand_found = True
    inp.hx = 0.5 + 0.34 * math.sin(i * 0.019)
    inp.hy = 0.42 + 0.22 * math.cos(i * 0.023)
    inp.hand_open = 0.5 + 0.5 * math.sin(i * 0.011)
    inp.fingers = 3
    inp.pinch = (i % 53) == 0
    inp.release = (i % 53) == 12
    inp.grab_hold = (i % 53) < 10
    h = _hand(inp.hx, inp.hy, inp.hand_open)
    inp.hands = [h]
    inp.hand_l = h
    inp.hand_r = h
    return inp


class _Lagged:
    """简单一阶延迟 + 噪声，模拟真人反应。"""

    def __init__(self, lag: float = 0.35, noise: float = 0.16, seed: int = 1):
        self.lag = lag
        self.noise = noise
        self.rng = random.Random(seed)
        self.v = {}

    def get(self, k: str, target: float) -> float:
        cur = self.v.get(k, target)
        cur += (target - cur) * (1 - self.lag)
        cur += self.rng.uniform(-self.noise, self.noise) * 0.32
        self.v[k] = cur
        return cur


def human_input(lag: _Lagged, i: int, aim_axis: float = 0.0, aim_jump: bool = False) -> GameInput:
    """
    模拟真人：给定"想做什么"（aim_axis / aim_jump），
    经过延迟与噪声后输出实际输入。用于难度校准。
    """
    inp = GameInput()
    inp.found = True
    inp.axis = max(-1.0, min(1.0, lag.get("ax", aim_axis)))
    inp.up = max(0.0, min(1.0, lag.get("up", 0.6 if aim_jump else 0.3)))
    inp.jump = lag.get("jp", 1.0 if aim_jump else 0.0) > 0.55
    inp.hand_found = True
    inp.hx = max(0.0, min(1.0, lag.get("hx", 0.5)))
    inp.hy = max(0.0, min(1.0, lag.get("hy", 0.4)))
    inp.hand_open = max(0.0, min(1.0, lag.get("ho", 0.5)))
    inp.pinch = inp.hand_open < 0.3
    inp.grab_hold = inp.hand_open < 0.35
    h = _hand(inp.hx, inp.hy, inp.hand_open)
    inp.hands = [h]
    inp.hand_l = h
    inp.hand_r = h
    return inp


def zero_input() -> GameInput:
    return GameInput()
