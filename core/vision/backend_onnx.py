"""
core/vision/backend_onnx.py
===========================
跨平台万能后端：ONNX Runtime + RTMPose。

为什么留这条路
--------------
· **任何平台都能跑**：ONNX Runtime 提供 CoreML / DirectML / CUDA / CPU
  多种执行提供者（Execution Provider），同一份模型在 Mac 上走 ANE、
  在 Windows 上走 DirectML、在 Linux 上走 CUDA；
· **RTMPose 是当前姿态估计的 SOTA 之一**（自顶向下，COCO 上 AP 高于
  BlazePose 一大截），而且直接输出 COCO-17，不需要索引映射；
· 不依赖任何系统 API，也就不受 MediaPipe 那种平台构建缺陷影响。

模型放置
--------
把 OpenMMLab 的 ONNX SDK 解出来的模型放到 assets/models/ 下：

    rtmpose_body.onnx       人体（含检测 + 姿态，end2end）
    rtmpose_hand.onnx       手部

下载（任一能通的源）：
    https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/
        rtmpose-m_simcc-body7_pt-body7_420e-256x192-026a1439_20230504.zip
    https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/
        rtmpose-m_simcc-hand5_pt-aic-coco_210e-256x256-74fb594_20230320.zip

没有模型时 available() 返回 False，AutoEngine 会自动跳到下一个后端，
不会影响程序启动。
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np

from .types import COCO17, HAND_JOINTS, HandFrame, Joint, PoseFrame, VisionFrame

NAME = "onnx"

_HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODELS = os.path.join(_HERE, "assets", "models")
BODY_MODEL = os.path.join(MODELS, "rtmpose_body.onnx")
HAND_MODEL = os.path.join(MODELS, "rtmpose_hand.onnx")


def _pick_providers() -> List[str]:
    """
    按平台挑最优执行提供者。CoreML 在 Mac 上会走 ANE/GPU，
    DirectML 在 Windows 上走任何显卡，CUDA 在 Linux 上走 N 卡。
    """
    try:
        import onnxruntime as ort
    except Exception:                                                # noqa: BLE001
        return ["CPUExecutionProvider"]
    avail = set(ort.get_available_providers())
    if sys.platform == "darwin":
        order = ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    elif sys.platform.startswith("win"):
        order = ["DmlExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]
    else:
        order = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    picked = [p for p in order if p in avail]
    return picked or ["CPUExecutionProvider"]


_CACHE: Optional[Tuple[bool, str]] = None


def available() -> Tuple[bool, str]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        import onnxruntime as ort
    except Exception as e:                                           # noqa: BLE001
        _CACHE = (False, f"未安装 onnxruntime（{e}）")
        return _CACHE
    if not os.path.exists(BODY_MODEL):
        _CACHE = (False, "缺少 rtmpose_body.onnx（见本文件头部说明）")
        return _CACHE
    prov = _pick_providers()
    _CACHE = (True, f"ONNX Runtime {ort.__version__} [{', '.join(prov)}]")
    return _CACHE


class OnnxPoseEngine:
    """
    RTMPose 的 ONNX SDK 是 end2end 的：输入 BGR 图，输出
    keypoints(N,17,3) + bboxes(N,4)。所以不需要自己接检测器。
    """

    def __init__(self, max_hands: int = 2, body: bool = True, hands: bool = True,
                 min_hand_conf: float = 0.30) -> None:
        import onnxruntime as ort
        prov = _pick_providers()
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        so.intra_op_num_threads = 2          # 别让推理线程把渲染线程挤掉
        self._body = None
        self._hand = None
        if body and os.path.exists(BODY_MODEL):
            self._body = ort.InferenceSession(BODY_MODEL, so, providers=prov)
        if hands and os.path.exists(HAND_MODEL):
            self._hand = ort.InferenceSession(HAND_MODEL, so, providers=prov)
        if self._body is None and self._hand is None:
            raise RuntimeError("没有任何 RTMPose 模型")
        self._min_conf = min_hand_conf
        self._prov = prov

    # ------------------------------------------------------------------ 预处理
    @staticmethod
    def _prep(bgr: np.ndarray, size: Tuple[int, int]):
        import cv2
        inp = cv2.resize(bgr, size)
        x = inp[:, :, ::-1].astype(np.float32)          # BGR → RGB
        x = np.ascontiguousarray(x.transpose(2, 0, 1)[None])
        return x, bgr.shape[1], bgr.shape[0]

    def infer(self, bgr: np.ndarray) -> VisionFrame:
        pose = self._run_body(bgr) if self._body is not None else PoseFrame()
        hands = self._run_hand(bgr) if self._hand is not None else []
        return VisionFrame(pose=pose, hands=hands, source=NAME)

    # ------------------------------------------------------------------ 人体
    def _run_body(self, bgr) -> PoseFrame:
        size = tuple(self._body.get_inputs()[0].shape[2:4][::-1]) or (192, 256)
        x, w0, h0 = self._prep(bgr, size)
        kps, scores = self._body.run(None, {self._body.get_inputs()[0].name: x})[:2]
        if len(kps) == 0:
            return PoseFrame(found=False, source=NAME)
        kp = kps[0]                                     # (17, 2)
        sc = scores[0]                                  # (17,)
        joints: Dict[str, Joint] = {}
        for i, name in enumerate(COCO17):
            if i >= len(kp):
                break
            # RTMPose 输出的是输入尺寸下的像素坐标，归一化回去
            joints[name] = Joint(float(kp[i][0]) / size[0], float(kp[i][1]) / size[1],
                                 float(sc[i]))
        found = len([j for j in joints.values() if j.ok]) >= 3
        return PoseFrame(found=found, joints=joints, source=NAME)

    # ------------------------------------------------------------------ 手部
    def _run_hand(self, bgr) -> List[HandFrame]:
        size = tuple(self._hand.get_inputs()[0].shape[2:4][::-1]) or (256, 256)
        x, _, _ = self._prep(bgr, size)
        kps, scores = self._hand.run(None, {self._hand.get_inputs()[0].name: x})[:2]
        out: List[HandFrame] = []
        for kp, sc in zip(kps, scores):
            if float(np.mean(sc)) < self._min_conf:
                continue
            joints = {}
            for i, name in enumerate(HAND_JOINTS):
                if i >= len(kp):
                    break
                joints[name] = Joint(float(kp[i][0]) / size[0], float(kp[i][1]) / size[1],
                                     float(sc[i]))
            if len(joints) < 8:
                continue
            hf = HandFrame(found=True, joints=joints, source=NAME)
            hf.side = "left" if hf.center.x < 0.5 else "right"
            out.append(hf)
        return out


def make_engine(**kw) -> OnnxPoseEngine:
    return OnnxPoseEngine(**kw)
