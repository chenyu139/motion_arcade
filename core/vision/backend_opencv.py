"""
core/vision/backend_opencv.py
=============================
最后的兜底后端：只用 OpenCV，不依赖任何模型下载与系统视觉 API。

能力（诚实说明）
----------------
    人体  → 只有头部 4 个点（YuNet 人脸框 + 5 个关键点推出鼻/双眼），
            没有四肢，所以做不了真正的体感动作；
    手部  → 掌心位置（距离变换）与张开度（solidity + 凸包缺陷），
            拿不到 21 个关节点，所以捏合、伸出手指数这类精细手势给不出。

它的价值是"**永远可用**"：在装不上任何视觉库的机器上，游戏至少还能玩，
不会白屏。真要用体感玩法，请用 apple / mediapipe / onnx 后端。
"""
from __future__ import annotations

import os
from typing import Dict, List, Tuple

import numpy as np

from .types import HandFrame, Joint, PoseFrame, VisionFrame

NAME = "opencv"

_HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODELS = os.path.join(_HERE, "assets", "models")
YUNET = os.path.join(MODELS, "face_detection_yunet_2023mar.onnx")
HAAR = os.path.join(MODELS, "haarcascade_frontalface_default.xml")


def available() -> Tuple[bool, str]:
    try:
        import cv2  # noqa: F401
    except Exception as e:                                           # noqa: BLE001
        return False, f"未安装 opencv（{e}）"
    if not os.path.exists(YUNET) and not os.path.exists(HAAR):
        return False, "缺少人脸检测模型"
    return True, "OpenCV 兜底（仅头部 + 掌心，无四肢/手指）"


class OpenCVEngine:
    def __init__(self, max_hands: int = 2, body: bool = True, hands: bool = True,
                 min_hand_conf: float = 0.30, **_kw) -> None:
        # **_kw：AutoEngine 会把同一套参数发给**所有**后端。
        # 后端不该因为收到一个自己不认识的参数就构造失败 —— 那会让整条
        # 退化链断掉：apple 初始化失败时 opencv 也跟着失败 → 没有任何后端可用。
        from ..tracker import FaceBackendHaar, FaceBackendYuNet, HandBackendSkin
        self._face = None
        for factory in (FaceBackendYuNet, FaceBackendHaar):
            try:
                self._face = factory()
                break
            except Exception:                                        # noqa: BLE001
                continue
        self._hand = HandBackendSkin() if hands else None
        self._max_hands = max_hands

    def infer(self, bgr: np.ndarray) -> VisionFrame:
        from .. import config as C
        h, w = bgr.shape[:2]
        # 检测统一在缩略图上做（和 tracker 里的策略一致）
        det_w = min(w, C.DETECT_W)
        det_h = int(h * det_w / w)
        import cv2
        small = cv2.resize(bgr, (det_w, det_h)) if (det_w, det_h) != (w, h) else bgr

        pose = PoseFrame(found=False, source=NAME)
        face_box = None
        if self._face is not None:
            st = self._face.detect(small, det_w, det_h)
            if st.found:
                face_box = st.box
                joints: Dict[str, Joint] = {}
                if st.nose:
                    joints["nose"] = Joint(st.nose[0] / det_w, st.nose[1] / det_h, 1.0)
                if st.landmarks and len(st.landmarks) >= 3:
                    # YuNet 的 5 点顺序：右眼、左眼、鼻尖、右嘴角、左嘴角
                    er, el = st.landmarks[0], st.landmarks[1]
                    nx, ny = st.nose if st.nose else (st.cx * det_w, st.cy * det_h)
                    joints["right_eye"] = Joint(er[0] / det_w, er[1] / det_h, 1.0)
                    joints["left_eye"] = Joint(el[0] / det_w, el[1] / det_h, 1.0)
                    # 用脸框宽度反推一个"肩宽等价尺度"，让 type.py 的归一化能工作
                    fw = st.box[2] if st.box else det_w * 0.2
                    sx = nx + fw * 1.25
                    joints["left_shoulder"] = Joint(sx / det_w, (ny + fw * 0.42) / det_h, 0.5)
                    joints["right_shoulder"] = Joint((nx - fw * 1.25) / det_w,
                                                     (ny + fw * 0.42) / det_h, 0.5)
                pose = PoseFrame(found=True, joints=joints, source=NAME)

        hands: List[HandFrame] = []
        if self._hand is not None:
            for st in self._hand.detect(small, face_box, det_w, det_h)[:self._max_hands]:
                hf = HandFrame(found=True, source=NAME, open_hint=float(st.open))
                # 只有掌心一个点；其余关键点不敢编，留空
                hf.joints["wrist"] = Joint(st.x, st.y, 1.0)
                hf.joints["middle_mcp"] = Joint(
                    st.x + (0.02 if st.x < 0.5 else -0.02), st.y - 0.03, 1.0)
                hf.side = "left" if st.x < 0.5 else "right"
                hands.append(hf)
        return VisionFrame(pose=pose, hands=hands, source=NAME)


def make_engine(**kw) -> OpenCVEngine:
    return OpenCVEngine(**kw)
