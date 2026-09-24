"""
tools/vision_probe.py
=====================
验证 Apple Vision framework 在 M4 上的可用性与性能。

为什么走 Vision：
  · 它是 Mac 上的**原生 SOTA**：手部 21 关键点、人体 19 关键点、
    人脸 76 关键点，全部由系统提供，跑在神经引擎（ANE）+ GPU 上；
  · 不依赖任何第三方模型文件，也就不存在 MediaPipe 那种
    "Metal helper 初始化失败直接 SIGABRT" 的问题；
  · 相对肤色-轮廓方案，它给出的是**真实关节点**，捏合、握拳、
    伸出手指数、指向都能精确算出来，而不是近似估计。

用法：
    python tools/vision_probe.py [图片路径 ...]
不给路径时用合成图做通路与性能测试。
"""
from __future__ import annotations

import os
import statistics
import sys
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import Quartz  # noqa: E402
import Vision  # noqa: E402


# --------------------------------------------------------------------------- #
def to_cgimage(bgr: np.ndarray):
    """numpy BGR → CGImage。Vision 要求 sRGB 的 RGBA/BGRA。"""
    h, w = bgr.shape[:2]
    rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)
    rgba = np.ascontiguousarray(rgba)
    data = rgba.tobytes()
    provider = Quartz.CGDataProviderCreateWithData(None, data, len(data), None)
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    return Quartz.CGImageCreate(
        w, h, 8, 32, w * 4, cs,
        Quartz.kCGImageAlphaNoneSkipLast | Quartz.kCGBitmapByteOrderDefault,
        provider, None, False, Quartz.kCGRenderingIntentDefault)


class VisionEngine:
    """一次 perform 同时跑三个请求，共享一次图像转换。"""

    def __init__(self, hands: int = 2, body: bool = True, face: bool = True):
        self._hand = Vision.VNDetectHumanHandPoseRequest.alloc().init()
        self._hand.setMaximumHandCount_(hands)
        reqs = [self._hand]
        self._body_req = None
        self._face_req = None
        if body:
            self._body_req = Vision.VNDetectHumanBodyPoseRequest.alloc().init()
            reqs.append(self._body_req)
        if face:
            self._face_req = Vision.VNDetectFaceLandmarksRequest.alloc().init()
            reqs.append(self._face_req)
        self._reqs = reqs

    def run(self, bgr: np.ndarray):
        img = to_cgimage(bgr)
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
        ok, err = handler.performRequests_error_(self._reqs, None)
        if not ok:
            return None
        return {
            "hands": self._hand.results() or [],
            "body": (self._body_req.results() or []) if self._body_req else [],
            "face": (self._face_req.results() or []) if self._face_req else [],
        }


# 21 个手部关节
HAND_JOINTS = [
    "wrist",
    "thumbCMC", "thumbMP", "thumbIP", "thumbTip",
    "indexMCP", "indexPIP", "indexDIP", "indexTip",
    "middleMCP", "middlePIP", "middleDIP", "middleTip",
    "ringMCP", "ringPIP", "ringDIP", "ringTip",
    "littleMCP", "littlePIP", "littleDIP", "littleTip",
]


def hand_summary(obs) -> str:
    pts = obs.recognizedPoints()
    conf = obs.confidence()
    out = {}
    for j in HAND_JOINTS:
        p = pts.get(j)
        if p is None:
            continue
        out[j] = (float(p.location().x), float(p.location().y), float(p.confidence()))
    if "wrist" not in out:
        return f"（关键点不足，仅 {len(out)}/21）"
    wx, wy, _ = out["wrist"]
    # 捏合 = 拇指尖与食指尖的距离 / 掌宽
    scale = max(1e-4, np.hypot(out.get("middleMCP", (wx, wy, 0))[0] - wx,
                               out.get("middleMCP", (wx, wy, 0))[1] - wy))
    pinch = np.hypot(out.get("thumbTip", (wx, wy, 0))[0] - out.get("indexTip", (wx, wy, 0))[0],
                     out.get("thumbTip", (wx, wy, 0))[1] - out.get("indexTip", (wx, wy, 0))[1]) / scale
    # 伸出手指数：指尖到腕的距离显著大于对应 PIP 到腕的距离
    extended = 0
    for fin in ("index", "middle", "ring", "little"):
        tip, pip = out.get(fin + "Tip"), out.get(fin + "PIP")
        if not tip or not pip:
            continue
        d_tip = np.hypot(tip[0] - wx, tip[1] - wy)
        d_pip = np.hypot(pip[0] - wx, pip[1] - wy)
        if d_tip > d_pip * 1.18:
            extended += 1
    return (f"掌心({out['wrist'][0]:.2f},{out['wrist'][1]:.2f})　"
            f"捏合比 {pinch:.2f}　伸出 {extended}/4　confidence {conf:.2f}")


def make_synth_hand() -> np.ndarray:
    """合成一张带"手"的图，仅用于验证 API 通路（不会真的有检测结果）。"""
    img = np.zeros((480, 640, 3), np.uint8)
    img[:] = (118, 122, 128)
    cv2.ellipse(img, (320, 300), (70, 92), 0, 0, 360, (108, 140, 186), -1)
    for i in range(4):
        cv2.line(img, (320 - 45 + i * 30, 220), (320 - 55 + i * 30, 120),
                 (108, 140, 186), 26)
    cv2.line(img, (255, 300), (200, 250), (108, 140, 186), 28)
    return img


def main() -> int:
    paths = sys.argv[1:]
    engine = VisionEngine(hands=2, body=True, face=True)

    frames = []
    names = []
    if paths:
        for p in paths:
            img = cv2.imread(p)
            if img is None:
                print(f"  ✗ 读不到 {p}")
                continue
            if img.shape[1] > 960:
                s = 960 / img.shape[1]
                img = cv2.resize(img, (960, int(img.shape[0] * s)))
            frames.append(img)
            names.append(os.path.basename(p))
            print(f"  ✓ 载入 {os.path.basename(p)}  {img.shape[1]}x{img.shape[0]}")
    else:
        frames = [make_synth_hand()]
        names = ["synth"]
        print("  · 未提供图片，使用合成图（只验证 API 通路与性能）")

    print()
    for name, fr in zip(names, frames):
        res = engine.run(fr)
        if res is None:
            print(f"[{name}] performRequests 失败")
            continue
        print(f"[{name}] 手 {len(res['hands'])}　人 {len(res['body'])}　脸 {len(res['face'])}")
        for i, hobs in enumerate(res["hands"]):
            print(f"    手#{i + 1}: {hand_summary(hobs)}")
        for bobs in res["body"]:
            pts = bobs.recognizedPoints()
            keys = list(pts.keys())
            print(f"    人体: {len(keys)} 点可用，例如 {keys[:6]}")

    # ---- 性能 ----
    args = {".jpg": cv2.IMWRITE_JPEG_QUALITY}
    buf = cv2.imencode(".jpg", frames[0], [cv2.IMWRITE_JPEG_QUALITY, 92])[1]
    fr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    for _ in range(10):
        engine.run(fr)
    ts = []
    for _ in range(120):
        t0 = time.perf_counter()
        engine.run(fr)
        ts.append((time.perf_counter() - t0) * 1000.0)
    med, mx = statistics.median(ts), max(ts)
    print(f"\n性能（640×480，含 numpy→CGImage 转换）：")
    print(f"    中位 {med:.2f} ms　最差 {mx:.2f} ms　→ 理论 {1000 / med:.0f} fps")
    print(f"    30Hz 下占用约 {med * 30 / 10:.0f}% 单核")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
