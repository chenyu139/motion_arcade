"""
core/tracker.py
===============
摄像头采集 + 人脸/手部检测，跑在独立线程里，主线程只取最新一帧。

后端选择
--------
人脸（按优先级）：
  1) MediaPipe FaceLandmarker —— 精度最高、还能给"张嘴"信号。
     但 MediaPipe 1.x 的 macOS 构建在 TensorsToDetectionsCalculator 里
     硬编码了 Metal helper（DrishtiMetalHelper），即使显式指定 CPU delegate
     也会 `Check failed: service_ Service is unavailable` 直接 abort，
     所以默认关闭，仅当子进程探测通过才启用。
  2) OpenCV YuNet —— 纯 CPU、约 2ms，给出脸框 + 5 个关键点（含鼻尖），
     可用于估计头部转向。**本项目的默认后端**。
  3) OpenCV Haar —— 兜底，仅脸框。

手部：
  纯 OpenCV 的肤色-轮廓方案（见 HandBackendSkin）。不用 MediaPipe 的原因同上。
  算法链路：
      肤色分割(YCrCb∩HSV) → 剔除人脸区域 → 形态学 → 轮廓筛选
      → 距离变换求掌心 → 凸包缺陷数指缝 → solidity 估张合度
  能稳定给出：掌心位置、张合度（握拳/张开）、伸展手指数、手的远近。
  注意：它对光照与背景较敏感，需要光线均匀、背景不出现大面积近肤色物体。
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import List, Optional, Tuple

os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

import cv2
import numpy as np

from .inputs import FaceState, HandState
from . import config as C

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(os.path.dirname(HERE), "assets", "models")
YUNET_PATH = os.path.join(MODELS_DIR, "face_detection_yunet_2023mar.onnx")
HAAR_PATH = os.path.join(MODELS_DIR, "haarcascade_frontalface_default.xml")
MP_MODEL_PATH = os.path.join(MODELS_DIR, "face_landmarker.task")

try:
    cv2.setLogLevel(0)
except Exception:
    pass


# =========================================================================== #
# 人脸后端
# =========================================================================== #
class FaceBackendYuNet:
    name = "YuNet"

    def __init__(self) -> None:
        if not os.path.exists(YUNET_PATH):
            raise FileNotFoundError(YUNET_PATH)
        self._det = cv2.FaceDetectorYN.create(YUNET_PATH, "", (320, 240), 0.65, 0.3, 5000)
        self._size = None

    def detect(self, frame: np.ndarray, w: int, h: int) -> FaceState:
        if self._size != (w, h):
            self._det.setInputSize((w, h))
            self._size = (w, h)
        _, faces = self._det.detect(frame)
        if faces is None or len(faces) == 0:
            return FaceState(found=False)
        f = max(faces, key=lambda r: float(r[2]) * float(r[3]))
        x, y, bw, bh = float(f[0]), float(f[1]), float(f[2]), float(f[3])
        # YuNet 的 5 个关键点：右眼、左眼、鼻尖、右嘴角、左嘴角
        pts = [(float(f[i]), float(f[i + 1])) for i in (4, 6, 8, 10, 12)]
        eye_r, eye_l, nose = pts[0], pts[1], pts[2]
        return FaceState(
            found=True,
            cx=min(1.0, max(0.0, (x + bw / 2) / w)),
            cy=min(1.0, max(0.0, (y + bh / 2) / h)),
            w=bw / w, h=bh / h,
            yaw=self._yaw(nose, eye_r, eye_l),
            pitch=self._pitch(nose, eye_l, eye_r, pts[3], pts[4]),
            roll=float(np.arctan2(eye_l[1] - eye_r[1], max(1.0, eye_l[0] - eye_r[0]))),
            box=(int(x), int(y), int(bw), int(bh)),
            landmarks=pts,
            nose=nose,
        )

    @staticmethod
    def _yaw(nose, eye_r, eye_l) -> float:
        """头部左右转向：比较鼻尖到左右眼的水平距离（正脸时基本对称）。"""
        d_r = abs(nose[0] - eye_r[0])
        d_l = abs(eye_l[0] - nose[0])
        tot = d_r + d_l
        if tot < 1e-3:
            return 0.0
        return float(np.clip((d_r - d_l) / tot * 1.6, -1.0, 1.0))

    @staticmethod
    def _pitch(nose, eye_l, eye_r, mouth_r, mouth_l) -> float:
        """俯仰：鼻尖到"眼线"的距离占"眼线到嘴线"的比例。"""
        eye_y = (eye_l[1] + eye_r[1]) / 2.0
        mouth_y = (mouth_r[1] + mouth_l[1]) / 2.0
        span = mouth_y - eye_y
        if span < 2:
            return 0.0
        k = (nose[1] - eye_y) / span
        return float(np.clip((0.52 - k) * 2.4, -1.0, 1.0))


class FaceBackendHaar:
    name = "Haar"

    def __init__(self) -> None:
        if not os.path.exists(HAAR_PATH):
            raise FileNotFoundError(HAAR_PATH)
        self._clf = cv2.CascadeClassifier(HAAR_PATH)
        if self._clf.empty():
            raise RuntimeError("Haar 级联加载失败")

    def detect(self, frame: np.ndarray, w: int, h: int) -> FaceState:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._clf.detectMultiScale(gray, 1.15, 5, minSize=(60, 60))
        if len(faces) == 0:
            return FaceState(found=False)
        x, y, bw, bh = max(faces, key=lambda r: r[2] * r[3])
        return FaceState(found=True,
                         cx=min(1.0, max(0.0, (x + bw / 2) / w)),
                         cy=min(1.0, max(0.0, (y + bh / 2) / h)),
                         w=bw / w, h=bh / h,
                         box=(int(x), int(y), int(bw), int(bh)),
                         nose=(x + bw / 2, y + bh / 2))


class FaceBackendMediaPipe:
    name = "MediaPipe"

    def __init__(self) -> None:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
        if not os.path.exists(MP_MODEL_PATH):
            raise FileNotFoundError(MP_MODEL_PATH)
        opts = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=MP_MODEL_PATH),
            running_mode=vision.RunningMode.VIDEO, num_faces=1,
            output_face_blendshapes=True)
        self._lm = vision.FaceLandmarker.create_from_options(opts)
        self._mp = mp
        self._t = 0

    def detect(self, frame: np.ndarray, w: int, h: int) -> FaceState:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB,
                             data=np.ascontiguousarray(rgb))
        self._t += 33
        res = self._lm.detect_for_video(img, self._t)
        if not res.face_landmarks:
            return FaceState(found=False)
        lms = res.face_landmarks[0]
        xs = [p.x for p in lms]
        ys = [p.y for p in lms]
        mouth = 0.0
        if res.face_blendshapes:
            for c in res.face_blendshapes[0]:
                if c.category_name == "jawOpen":
                    mouth = float(c.score)
                    break
        nose = lms[1]
        return FaceState(found=True,
                         cx=min(1.0, max(0.0, (min(xs) + max(xs)) / 2)),
                         cy=min(1.0, max(0.0, (min(ys) + max(ys)) / 2)),
                         w=max(xs) - min(xs), h=max(ys) - min(ys),
                         mouth_open=mouth,
                         box=(int(min(xs) * w), int(min(ys) * h),
                              int((max(xs) - min(xs)) * w), int((max(ys) - min(ys)) * h)),
                         nose=(nose.x * w, nose.y * h))


_MP_PROBE = r"""
import sys
try:
    import numpy as np, mediapipe as mp
    from mediapipe.tasks import python as mpp
    from mediapipe.tasks.python import vision
    o = vision.FaceLandmarkerOptions(
        base_options=mpp.BaseOptions(model_asset_path=sys.argv[1]),
        running_mode=vision.RunningMode.VIDEO, num_faces=1)
    lm = vision.FaceLandmarker.create_from_options(o)
    print("OK")
except Exception as e:
    print("ERR", e)
"""


def mediapipe_usable() -> bool:
    """子进程探测，避免其原生 abort 拖垮主程序。"""
    if not os.path.exists(MP_MODEL_PATH):
        return False
    try:
        r = subprocess.run([sys.executable, "-c", _MP_PROBE, MP_MODEL_PATH],
                           capture_output=True, text=True, timeout=60)
        return r.returncode == 0 and "OK" in r.stdout
    except Exception:
        return False


# =========================================================================== #
# 手部后端：肤色 + 轮廓几何
# =========================================================================== #
class HandBackendSkin:
    """
    不使用深度学习模型的手部跟踪。

    在光线均匀、背景无大面积近肤色物体的前提下足够稳，能给出：
      · 掌心位置（距离变换的最大内切圆圆心，比轮廓质心稳）
      · 张合度 open（solidity 与凸包缺陷数融合）
      · 伸展手指数 fingers（深凹陷 ≈ 指缝）
    不能给出拇指/食指捏合这类精细手势（那需要关键点模型）。
    """

    name = "SkinContour"

    def __init__(self) -> None:
        self._k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self._k7 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))

    def skin_mask(self, bgr: np.ndarray) -> np.ndarray:
        ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        m_y = cv2.inRange(ycrcb, (36, 132, 74), (255, 182, 132))
        m_h1 = cv2.inRange(hsv, (0, 22, 58), (28, 200, 255))
        m_h2 = cv2.inRange(hsv, (156, 22, 58), (180, 200, 255))
        m_h = cv2.bitwise_or(m_h1, m_h2)
        mask = cv2.bitwise_and(m_y, m_h)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._k3)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._k7)
        return mask

    def detect(self, frame: np.ndarray, face_box: Optional[Tuple[int, int, int, int]],
               w: int, h: int) -> List[HandState]:
        mask = self.skin_mask(frame)
        # 排除人脸：脸同样属于肤色，不排掉会把头当成手
        if face_box is not None:
            fx, fy, fw, fh = face_box
            px, py = int(fw * 0.22), int(fh * 0.26)
            x0, y0 = max(0, fx - px), max(0, fy - py)
            x1 = min(w, fx + fw + px)
            y1 = min(h, fy + fh + int(fh * 0.35))
            if x1 > x0 and y1 > y0:
                mask[y0:y1, x0:x1] = 0

        frame_area = float(w * h)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cands = []
        for c in cnts:
            a = cv2.contourArea(c)
            if a < frame_area * 0.006 or a > frame_area * 0.34:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            if bw <= 0 or bh <= 0:
                continue
            ar = bw / float(bh)
            if ar > 2.6 or ar < 0.26:            # 细长条 → 多半是家具边缘
                continue
            if max(bw, bh) > min(w, h) * 0.94:   # 几乎铺满 → 背景
                continue
            cands.append(c)
        if not cands:
            return []
        cands.sort(key=cv2.contourArea, reverse=True)

        out: List[HandState] = []
        for c in cands[:C.HAND_MAX_NUM]:
            st = self._analyze(c, w, h)
            if st is not None:
                out.append(st)
        out.sort(key=lambda s: s.x)
        return out

    def _analyze(self, cnt, w: int, h: int) -> Optional[HandState]:
        area = float(cv2.contourArea(cnt))
        if area < 1.0:
            return None
        hull_pts = cv2.convexHull(cnt, returnPoints=True)
        hull_area = float(cv2.contourArea(hull_pts))
        if hull_area < 1.0:
            return None
        solidity = float(np.clip(area / hull_area, 0.0, 1.0))

        # --- 掌心：轮廓内做距离变换，最大值处即最大内切圆圆心 ---
        x, y, bw, bh = cv2.boundingRect(cnt)
        x0, y0 = max(0, x - 2), max(0, y - 2)
        x1, y1 = min(w, x + bw + 3), min(h, y + bh + 3)
        if x1 - x0 < 3 or y1 - y0 < 3:
            return None
        roi = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
        shifted = cnt - np.array([[[x0, y0]]], dtype=cnt.dtype)
        cv2.drawContours(roi, [shifted], -1, 255, -1)
        dist = cv2.distanceTransform(roi, cv2.DIST_L2, 5)
        if dist.max() < 1.0:
            return None
        _, _, _, max_loc = cv2.minMaxLoc(dist)
        palm_x = (x0 + max_loc[0]) / w
        palm_y = (y0 + max_loc[1]) / h
        palm_r = float(dist.max()) / max(1.0, min(w, h))

        # --- 凸包缺陷：深凹陷的个数约等于"张开的指缝数" ---
        deep = 0
        try:
            hull_i = cv2.convexHull(cnt, returnPoints=False)
            if hull_i is not None and len(hull_i) > 3:
                defects = cv2.convexityDefects(cnt, hull_i)
                if defects is not None:
                    feas = max(5.0, dist.max() * 1.05)
                    for i in range(defects.shape[0]):
                        _, _, _, d = defects[i, 0]
                        if d / 256.0 > feas:
                            deep += 1
        except cv2.error:
            deep = 0

        # --- 张合度：solidity 为主（握拳≈0.95，张开≈0.6），指缝数为辅 ---
        open_s = float(np.clip((0.94 - solidity) / 0.30, 0.0, 1.0))
        open_d = float(np.clip(deep / 3.0, 0.0, 1.0))
        open_v = 0.62 * open_s + 0.38 * open_d
        fingers = int(np.clip(deep + (1 if open_v > 0.30 else 0), 0, 5))
        if open_v < 0.16:
            fingers = 0

        angle = 0.0
        if len(cnt) >= 5:
            try:
                _, _, ang = cv2.fitEllipse(cnt)[1]
                angle = float(np.radians(ang))
            except cv2.error:
                angle = 0.0

        return HandState(
            found=True,
            x=float(np.clip(palm_x, 0.0, 1.0)),
            y=float(np.clip(palm_y, 0.0, 1.0)),
            open=open_v,
            fingers=fingers,
            area=area / (w * h),
            span=bw / w,
            angle=angle,
            palm_r=palm_r,
            bbox=(x, y, bw, bh),
        )


# =========================================================================== #
# 采集 + 检测
# =========================================================================== #
class MotionTracker:
    """摄像头采集线程：输出最新一帧 + 人脸结果 + 手部结果。"""

    def __init__(self, cam_index: int = C.CAM_INDEX, prefer_mediapipe: bool = False,
                 hands: bool = True) -> None:
        self.ok = False
        self.err = ""
        self.backend_name = "-"
        self.hand_name = "-"
        self._face = None
        self._hand = None
        self._cap = None
        self._thread = None
        self._running = False
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._state = FaceState()
        self._hands: List[HandState] = []
        self._fps = 0.0
        self._hand_ms = 0.0

        if prefer_mediapipe and mediapipe_usable():
            try:
                self._face = FaceBackendMediaPipe()
            except Exception as e:                                  # noqa: BLE001
                print(f"[tracker] MediaPipe 不可用，回退：{e}")
        if self._face is None:
            for factory in (FaceBackendYuNet, FaceBackendHaar):
                try:
                    self._face = factory()
                    break
                except Exception as e:                              # noqa: BLE001
                    print(f"[tracker] {factory.__name__} 不可用：{e}")
        if self._face is None:
            self.err = "没有可用的人脸检测后端（缺少模型文件）"
            return
        self.backend_name = self._face.name

        if hands:
            try:
                self._hand = HandBackendSkin()
                self.hand_name = self._hand.name
            except Exception as e:                                  # noqa: BLE001
                print(f"[tracker] 手部后端不可用：{e}")

        if not self._open_camera(cam_index):
            self.err = f"无法打开摄像头（索引 {cam_index}）。请检查授权或被占用。"
            return
        self.ok = True
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _open_camera(self, index: int) -> bool:
        for api in (cv2.CAP_AVFOUNDATION, cv2.CAP_ANY):
            try:
                cap = cv2.VideoCapture(index, api)
            except Exception:
                continue
            if cap is not None and cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, C.CAM_W)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, C.CAM_H)
                cap.set(cv2.CAP_PROP_FPS, C.CAM_FPS)
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:
                    pass
                self._cap = cap
                return True
        return False

    def _loop(self) -> None:
        dt_hist: List[float] = []
        last = time.time()
        det_h = int(C.CAM_H * C.DETECT_W / C.CAM_W)
        while self._running:
            try:
                ok, frame = self._cap.read()
            except Exception:
                ok, frame = False, None
            if not ok or frame is None:
                time.sleep(0.01)
                continue
            frame = cv2.flip(frame, 1)                      # 镜像：头/手往右 → 画面往右
            if frame.shape[1] != C.CAM_W or frame.shape[0] != C.CAM_H:
                frame = cv2.resize(frame, (C.CAM_W, C.CAM_H))

            small = cv2.resize(frame, (C.DETECT_W, det_h))
            try:
                st = self._face.detect(small, C.DETECT_W, det_h)
            except Exception:                                # noqa: BLE001
                st = FaceState(found=False)
            st.backend = self.backend_name

            hands: List[HandState] = []
            if self._hand is not None:
                t0 = time.time()
                try:
                    hands = self._hand.detect(small, st.box if st.found else None,
                                              C.DETECT_W, det_h)
                except Exception:                            # noqa: BLE001
                    hands = []
                self._hand_ms = (time.time() - t0) * 1000.0

            with self._lock:
                self._frame = frame
                self._state = st
                self._hands = hands

            now = time.time()
            dt_hist.append(now - last)
            last = now
            if len(dt_hist) > 30:
                dt_hist.pop(0)
            avg = sum(dt_hist) / max(1, len(dt_hist))
            self._fps = 1.0 / avg if avg > 0 else 0.0

    # ---------- 对外 ----------
    def get(self):
        with self._lock:
            return self._frame, self._state, list(self._hands)

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def hand_ms(self) -> float:
        return self._hand_ms

    def close(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass


# =========================================================================== #
# 手部 → 屏幕坐标映射
# =========================================================================== #
class HandCursor:
    """
    把归一化手部坐标映射到设计坐标系，带中性位与增益放大。

    为什么需要增益：摄像头视野比屏幕窄，手在视野里移动同样的比例，
    映射到屏幕上位移会偏小，玩家会觉得"够不到边缘"。以中性位置为中心
    放大 1.55 倍即可显著改善手感。
    """

    def __init__(self, w: float, h: float, gain: float = 1.55,
                 margin_x: float = 0.10, margin_y: float = 0.10) -> None:
        self.w, self.h = w, h
        self.gain = gain
        self.margin_x = margin_x
        self.margin_y = margin_y
        self.cx = 0.5
        self.cy = 0.5

    def set_neutral(self, x: float, y: float) -> None:
        # 只在第一次或显式调用时设定，避免每帧漂移
        self.cx, self.cy = x, y

    def map(self, hx: float, hy: float) -> Tuple[float, float]:
        nx = min(1.0, max(0.0, 0.5 + (hx - self.cx) * self.gain))
        ny = min(1.0, max(0.0, 0.5 + (hy - self.cy) * self.gain))
        sx = self.margin_x * self.w + nx * (1 - 2 * self.margin_x) * self.w
        sy = self.margin_y * self.h + ny * (1 - 2 * self.margin_y) * self.h
        return (sx, sy)
