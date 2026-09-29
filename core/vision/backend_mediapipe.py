"""
core/vision/backend_mediapipe.py
================================
跨平台主力后端：MediaPipe Tasks（Pose 33 点 + Hand 21 点）。

适用平台
--------
Windows / Linux / Android 上这是**最主流**的选择：Apache 2.0、模型小、
TFLite 跑得动，而且和移动端一致（未来做 Android 体感应用可以复用一套逻辑）。

⚠ macOS 上的坑（本项目实测）
----------------------------
MediaPipe 1.x 的 macOS 构建里，`TensorsToDetectionsCalculator` 硬编码了
Metal helper（`DrishtiMetalHelper`）。即使显式传
`BaseOptions.Delegate.CPU`，它仍然会去要 GPU service，拿不到就
`Fatal: Check failed: service_ Service is unavailable.` → **SIGABRT（rc=-6）**。

这不是 Python 异常，try/except 抓不住，整个进程会直接死。
所以：
  1) 在本后端的 available() 里用**子进程探测**，避免主进程被打死；
  2) macOS 上优先用 apple 后端，MediaPipe 只作为不可用时的后备。

33 点 → COCO-17 的映射按 BlazePose 的官方索引表。
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np

from .types import HAND_JOINTS, HandFrame, Joint, PoseFrame, VisionFrame

NAME = "mediapipe"

_HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODELS = os.path.join(_HERE, "assets", "models")
POSE_MODEL = os.path.join(MODELS, "pose_landmarker_full.task")
HAND_MODEL = os.path.join(MODELS, "hand_landmarker.task")

# BlazePose 33 点 → COCO-17
_BLAZE_TO_COCO = {
    0: "nose",
    2: "left_eye", 5: "right_eye",
    7: "left_ear", 8: "right_ear",
    11: "left_shoulder", 12: "right_shoulder",
    13: "left_elbow", 14: "right_elbow",
    15: "left_wrist", 16: "right_wrist",
    23: "left_hip", 24: "right_hip",
    25: "left_knee", 26: "right_knee",
    27: "left_ankle", 28: "right_ankle",
}

# MediaPipe Hand 的 21 点顺序与我们的规范一致，直接按序映射
_HAND_ORDER = HAND_JOINTS


_PROBE = r"""
import sys
try:
    import numpy as np
    from mediapipe.tasks import python as _p
    from mediapipe.tasks.python import vision
    from mediapipe.tasks.python.core.base_options import BaseOptions
    pos = vision.PoseLandmarker.create_from_options(
        vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=sys.argv[1]),
            running_mode=vision.RunningMode.VIDEO, num_poses=1))
    hnd = vision.HandLandmarker.create_from_options(
        vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=sys.argv[2]),
            running_mode=vision.RunningMode.VIDEO, num_hands=2))
    print("OK")
except Exception as e:
    print("ERR", type(e).__name__, e)
"""


_CACHE: Optional[Tuple[bool, str]] = None


def available() -> Tuple[bool, str]:
    """必须用子进程探测 —— MediaPipe 失败时是 abort，会带走整个进程。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        import mediapipe  # noqa: F401
    except Exception as e:                                           # noqa: BLE001
        _CACHE = (False, f"未安装 mediapipe（{e}）")
        return _CACHE
    missing = [p for p in (POSE_MODEL, HAND_MODEL) if not os.path.exists(p)]
    if missing:
        _CACHE = (False, "缺少模型：" + ",".join(os.path.basename(p) for p in missing))
        return _CACHE
    try:
        r = subprocess.run([sys.executable, "-c", _PROBE, POSE_MODEL, HAND_MODEL],
                           capture_output=True, text=True, timeout=90)
        if r.returncode == 0 and "OK" in r.stdout:
            _CACHE = (True, "MediaPipe Tasks（33 点人体 + 21 点手）")
        elif r.returncode == -6:
            _CACHE = (False, "MediaPipe 在本机 SIGABRT（Metal helper 缺陷），改用其他后端")
        else:
            _CACHE = (False, f"探测失败 rc={r.returncode} {r.stdout.strip()[:60]}")
    except Exception as e:                                           # noqa: BLE001
        _CACHE = (False, f"探测异常：{e}")
    return _CACHE


class MediaPipeEngine:
    def __init__(self, max_hands: int = 2, body: bool = True, hands: bool = True,
                 min_hand_conf: float = 0.30, **_kw) -> None:
        # **_kw 的用意见 backend_opencv 同名注释：不能因为不认识的参数
        # 就构造失败，否则整条后端退化链会断。
        import mediapipe as mp
        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python.core.base_options import BaseOptions
        self._mp = mp
        self._min_conf = min_hand_conf
        self._pose = None
        self._hand = None
        if body:
            self._pose = vision.PoseLandmarker.create_from_options(
                vision.PoseLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=POSE_MODEL),
                    running_mode=vision.RunningMode.VIDEO, num_poses=1))
        if hands:
            self._hand = vision.HandLandmarker.create_from_options(
                vision.HandLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=HAND_MODEL),
                    running_mode=vision.RunningMode.VIDEO, num_hands=max_hands,
                    min_hand_detection_confidence=0.35))
        self._t = 0

    def infer(self, bgr: np.ndarray) -> VisionFrame:
        self._t += 33
        rgb = np.ascontiguousarray(bgr[:, :, ::-1])
        img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        pose = self._read_pose(img)
        hands = self._read_hands(img)
        return VisionFrame(pose=pose, hands=hands, source=NAME)

    # ------------------------------------------------------------------ 人体
    def _read_pose(self, img) -> PoseFrame:
        if self._pose is None:
            return PoseFrame(found=False, source=NAME)
        res = self._pose.detect_for_video(img, self._t)
        if not res.pose_landmarks:
            return PoseFrame(found=False, source=NAME)
        lms = res.pose_landmarks[0]
        joints: Dict[str, Joint] = {}
        for idx, name in _BLAZE_TO_COCO.items():
            if idx >= len(lms):
                continue
            p = lms[idx]
            # MediaPipe 的 visibility / presence 用来当置信度
            vis = float(getattr(p, "visibility", 0.0) or 0.0)
            pres = float(getattr(p, "presence", 0.0) or 0.0)
            conf = max(vis, pres) if (vis or pres) else 1.0
            joints[name] = Joint(float(p.x), float(p.y), conf)
        found = len([j for j in joints.values() if j.ok]) >= 3
        return PoseFrame(found=found, joints=joints, source=NAME)

    # ------------------------------------------------------------------ 手部
    def _read_hands(self, img) -> List[HandFrame]:
        if self._hand is None:
            return []
        res = self._hand.detect_for_video(img, self._t)
        out: List[HandFrame] = []
        for i, lms in enumerate(res.hand_landmarks or []):
            joints: Dict[str, Joint] = {}
            for k, name in enumerate(_HAND_ORDER):
                if k >= len(lms):
                    break
                p = lms[k]
                joints[name] = Joint(float(p.x), float(p.y), 1.0)
            if len(joints) < 8:
                continue
            hf = HandFrame(found=True, joints=joints, source=NAME)
            # handedness 在镜像画面下语义会反，同样用位置判断，保持与 apple 后端一致
            hf.side = "left" if hf.center.x < 0.5 else "right"
            out.append(hf)
        return out


def make_engine(**kw) -> MediaPipeEngine:
    return MediaPipeEngine(**kw)
