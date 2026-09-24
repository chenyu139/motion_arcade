"""
core.vision —— 跨平台骨骼感知层
===============================

对外只暴露一套东西：

    from core.vision import AutoEngine, VisionFrame

    eng = AutoEngine()                 # 自动按平台挑后端
    frame = eng.infer(bgr)             # 一帧
    frame.pose.arm_raised("left")      # 左手举多高
    frame.pose.crouch                  # 蹲多深
    frame.main_hand().pinch            # 捏合度

后端按平台自动选择（也可以在 main.py 用 --vision 强制）：

    macOS          apple  → onnx → mediapipe → opencv
    Windows        mediapipe → onnx → opencv
    Linux/Android  mediapipe → onnx → opencv

游戏代码永远只认 VisionFrame，换平台不用改一行。
"""
from __future__ import annotations

from .base import (AutoEngine, all_backends, describe, get, preferred_order)
from .types import (COCO17, COCO17_EDGES, CONF_MIN, FINGERS, HAND_EDGES, HAND_JOINTS,
                    HandFrame, Joint, PoseFrame, VisionFrame)

__all__ = [
    "AutoEngine", "all_backends", "describe", "get", "preferred_order",
    "COCO17", "COCO17_EDGES", "HAND_JOINTS", "HAND_EDGES", "FINGERS", "CONF_MIN",
    "Joint", "PoseFrame", "HandFrame", "VisionFrame",
]
