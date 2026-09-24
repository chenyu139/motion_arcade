"""
core/vision/backend_apple.py
============================
macOS / iOS 后端：Apple Vision framework（通过 pyobjc）。

为什么它是 Mac 上的首选
-----------------------
· 系统原生、免费、无模型文件，直接跑在 **神经引擎（ANE）** 上；
· 人体 19 点 + 手部 21 点，精度是工业级（同一套引擎驱动系统相机的
  "人体姿态"功能）；
· **不碰 MediaPipe 那个坑**：MediaPipe 1.x 在 macOS 上会在
  TensorsToDetectionsCalculator 里硬编码 Metal helper，即使指定 CPU delegate
  也 `CHECK failed` 直接 SIGABRT；Vision 自己管理 Metal/ANE，没有这个问题。

性能实测（M4，640×480，含 numpy→CGImage 转换，中位值）
    手部单独                     4.8 ms
    人体单独                     8.3 ms
    人体 + 手部                  8.3 ms   ← 两者共享一次推理，不叠加
    人体 + 手部 + 人脸矩形       19.7 ms  ← 所以坚决不要把 face 请求塞进来
因此本后端的策略是：**只跑人体 + 手部**，人脸交给 OpenCV YuNet（2ms，
在线程里独立跑，不占用 Vision 的这条流水线）。
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from .types import (COCO17, HAND_JOINTS, HandFrame, Joint, PoseFrame, VisionFrame)

# ---- pyobjc 延迟导入：非 macOS 上导入本模块不应报错 ----
try:
    import Quartz
    import Vision as _V
    _AVAILABLE = True
    _IMPORT_ERR = ""
except Exception as _e:                                              # noqa: BLE001
    Quartz = None
    _V = None
    _AVAILABLE = False
    _IMPORT_ERR = str(_e)


NAME = "apple"


def available() -> Tuple[bool, str]:
    if not _AVAILABLE:
        return False, f"pyobjc/Vision 不可用：{_IMPORT_ERR}"
    if not hasattr(_V, "VNDetectHumanBodyPoseRequest"):
        return False, "系统 Vision 缺少人体姿态请求（需要 macOS 11+）"
    return True, "Apple Vision（ANE 加速）"


# --------------------------------------------------------------------------- #
# 关键点名字映射
# --------------------------------------------------------------------------- #
# Vision 返回的 key 是 "VNHumanBodyPoseObservationJointNameNose" 这类常量。
# 为了不依赖 pyobjc 导出的常量名细节，这里统一做「后缀匹配」。
_BODY_MAP = {
    "nose": "nose",
    "lefteye": "left_eye", "righteye": "right_eye",
    "leftear": "left_ear", "rightear": "right_ear",
    "leftshoulder": "left_shoulder", "rightshoulder": "right_shoulder",
    "leftelbow": "left_elbow", "rightelbow": "right_elbow",
    "leftwrist": "left_wrist", "rightwrist": "right_wrist",
    "lefthip": "left_hip", "righthip": "right_hip",
    "leftknee": "left_knee", "rightknee": "right_knee",
    "leftankle": "left_ankle", "rightankle": "right_ankle",
}
_HAND_MAP = {
    "wrist": "wrist",
    "thumbcmc": "thumb_cmc", "thumbmp": "thumb_mcp",
    "thumbip": "thumb_ip", "thumbtip": "thumb_tip",
    "indexmcp": "index_mcp", "indexpip": "index_pip",
    "indexdip": "index_dip", "indextip": "index_tip",
    "middlemcp": "middle_mcp", "middlepip": "middle_pip",
    "middledip": "middle_dip", "middletip": "middle_tip",
    "ringmcp": "ring_mcp", "ringpip": "ring_pip",
    "ringdip": "ring_dip", "ringtip": "ring_tip",
    "littlemcp": "little_mcp", "littlepip": "little_pip",
    "littledip": "little_dip", "littletip": "little_tip",
}


def _canon(key, table: Dict[str, str]) -> Optional[str]:
    s = str(key).lower()
    for prefix in ("vnhumanbodyposeobservationjointname",
                   "vnhumanhandposeobservationjointname"):
        if prefix in s:
            s = s.split(prefix, 1)[1]
    s = s.replace("_", "").replace(" ", "")
    return table.get(s)


def to_cgimage(bgr: np.ndarray):
    """numpy BGR → CGImage（BGRA）。转换本身约 0.17ms，不是瓶颈。"""
    h, w = bgr.shape[:2]
    bgra = _bgra(bgr)
    provider = Quartz.CGDataProviderCreateWithData(None, bgra.tobytes(), bgra.nbytes, None)
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    return Quartz.CGImageCreate(
        w, h, 8, 32, w * 4, cs,
        Quartz.kCGImageAlphaNoneSkipFirst | Quartz.kCGBitmapByteOrder32Little,
        provider, None, False, Quartz.kCGRenderingIntentDefault)


def _bgra(bgr: np.ndarray) -> np.ndarray:
    h, w = bgr.shape[:2]
    out = np.empty((h, w, 4), dtype=np.uint8)
    out[:, :, 0] = bgr[:, :, 0]
    out[:, :, 1] = bgr[:, :, 1]
    out[:, :, 2] = bgr[:, :, 2]
    out[:, :, 3] = 255
    return out


# --------------------------------------------------------------------------- #
class AppleVisionEngine:
    """
    一次 performRequests 同时拿到人体 + 双手。

    ⚠ 不要往里加人脸请求：实测「人体+手+人脸矩形」的组合要 19.7ms，
    而「人体+手」只要 8.3ms —— 人脸请求会打乱 ANE 的调度。
    """

    def __init__(self, max_hands: int = 2, body: bool = True, hands: bool = True,
                 min_hand_conf: float = 0.30) -> None:
        self._body_req = None
        self._hand_req = None
        reqs = []
        if body:
            self._body_req = _V.VNDetectHumanBodyPoseRequest.alloc().init()
            reqs.append(self._body_req)
        if hands:
            self._hand_req = _V.VNDetectHumanHandPoseRequest.alloc().init()
            self._hand_req.setMaximumHandCount_(max_hands)
            reqs.append(self._hand_req)
        if not reqs:
            raise ValueError("至少启用一个请求")
        self._reqs = reqs
        self.min_hand_conf = min_hand_conf
        self._handler_cache = None

    # ------------------------------------------------------------------ 推理
    def infer(self, bgr: np.ndarray) -> VisionFrame:
        cg = to_cgimage(bgr)
        handler = _V.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, None)
        ok, err = handler.performRequests_error_(self._reqs, None)
        if not ok:
            return VisionFrame(source=NAME)
        pose = self._read_body() if self._body_req is not None else PoseFrame()
        hands = self._read_hands() if self._hand_req is not None else []
        return VisionFrame(pose=pose, hands=hands, source=NAME)

    # ------------------------------------------------------------------ 人体
    def _read_body(self) -> PoseFrame:
        results = self._body_req.results() or []
        if not results:
            return PoseFrame(found=False, source=NAME)
        obs = results[0]
        pts = obs.recognizedPoints()
        joints: Dict[str, Joint] = {}
        for k, p in pts.items():
            name = _canon(k, _BODY_MAP)
            if name is None:
                continue
            loc = p.location()
            # Vision 是左下原点，转成内部的左上原点
            joints[name] = Joint(float(loc.x), 1.0 - float(loc.y), float(p.confidence()))
        found = len([j for j in joints.values() if j.ok]) >= 3
        return PoseFrame(found=found, joints=joints, source=NAME)

    # ------------------------------------------------------------------ 手部
    def _read_hands(self) -> List[HandFrame]:
        out: List[HandFrame] = []
        for obs in (self._hand_req.results() or []):
            pts = obs.recognizedPoints()
            joints: Dict[str, Joint] = {}
            for k, p in pts.items():
                name = _canon(k, _HAND_MAP)
                if name is None:
                    continue
                loc = p.location()
                joints[name] = Joint(float(loc.x), 1.0 - float(loc.y), float(p.confidence()))
            if len(joints) < 8:
                continue
            w = joints.get("wrist")
            if w is None or w.conf < self.min_hand_conf:
                continue
            hf = HandFrame(found=True, joints=joints, source=NAME)
            # 左右手：不用 chirality —— 我们的画面是镜像的，chirality 语义会反过来。
            # 直接用掌心的横向位置判断，和"镜像后左边就是用户的左手"一致。
            hf.side = "left" if hf.center.x < 0.5 else "right"
            out.append(hf)
        return out


# --------------------------------------------------------------------------- #
def make_engine(**kw) -> AppleVisionEngine:
    return AppleVisionEngine(**kw)
