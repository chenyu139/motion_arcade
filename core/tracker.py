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

import math
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
from .vision import VisionFrame
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
def _plausible_face(f, w: int, h: int) -> bool:
    """
    人脸框合理性筛选。

    只挡掉"明显不像脸"的框。宁可偶尔漏掉一个真脸也不能放进一个假阳性 ——
    漏检走的是冻结/归零逻辑（安全的失败方向），而假阳性的中心经常贴边，
    归一化后 cx 直接打到 0 或 1，角色会被瞬间甩到最边上。
    """
    bw, bh = float(f[2]), float(f[3])
    if bw <= 0 or bh <= 0:
        return False
    rw, rh = bw / w, bh / h
    if min(rw, rh) < C.FACE_MIN_REL:
        return False
    if rw * rh > C.FACE_MAX_AREA:
        return False
    ar = rw / max(1e-6, rh)
    if not (C.FACE_ASPECT_MIN <= ar <= C.FACE_ASPECT_MAX):
        return False
    cx = (float(f[0]) + bw / 2) / w
    cy = (float(f[1]) + bh / 2) / h
    m = C.FACE_EDGE_MARGIN
    return (m <= cx <= 1.0 - m) and (m <= cy <= 1.0 - m)


def _face_score(f) -> float:
    """
    YuNet 每行的第 15 个值是检测置信度（0~1）。

    防御式取值：不同 OpenCV 版本 / 模型文件的输出列数可能不一致，
    取不到时返回 1.0（= 这一层过滤不生效），而不是 0（= 全部候选被丢掉）。
    **失败方向必须是"少一层保护"，绝不能是"整个后端失效"。**
    """
    try:
        v = float(f[14])
    except Exception:                                           # noqa: BLE001
        return 1.0
    return v if v == v else 1.0                                 # NaN 也当作取不到


class IlluminationGuard:
    """
    光照自适应：在把画面**送进检测器之前**把它规整到模型习惯的分布。

    YuNet 是在常规光照的数据集上训练的。实际使用里有三类常见场景会让它
    明显掉点，而被用户读成"识别不准"：
        · 晚上只开一盏灯 / 背光坐    → 整体偏暗，细节埋在噪声里
        · 背对着窗户                 → 逆光，脸几乎是一块剪影
        · 均匀的顶光                 → 对比度极低，五官没有可判别的结构
    修法不是重训练模型，而是把画面先提亮/增强局部对比（gamma + CLAHE）。

    两个刻意的取舍
    --------------
    1. **只在真的需要时才处理。** 正常光照下做 CLAHE 会放大噪点，
       还会把肤色 pushed 到阈值之外 —— 对手部肤色检测是负收益。
       所以这里先用亮度/对比度统计判断，不够则下一档。
    2. **带迟滞。** 如果逐帧判断"要不要增强"，在阈值附近的画面会
       明暗来回闪 —— 那比一直不增强更难看。判定之后锁定若干帧。
    """

    def __init__(self) -> None:
        self._on = False
        self._frames = 0
        self._mode = "normal"
        self._clahe = None

    def _get_clahe(self):
        if self._clahe is None:
            self._clahe = cv2.createCLAHE(
                clipLimit=C.CLAHE_CLIP,
                tileGridSize=(C.CLAHE_GRID, C.CLAHE_GRID))
        return self._clahe

    def ensure(self, frame: np.ndarray) -> Tuple[np.ndarray, str]:
        """返回 (可能已增强的画面, 模式串)。模式串进日志，方便真机对照。"""
        if not C.ILLUM_ENABLE:
            return frame, "off"
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mean = float(gray.mean())
        std = float(gray.std())

        need_dark = mean < C.ILLUM_DARK_T
        need_bright = mean > C.ILLUM_BRIGHT_T
        need_flat = std < C.ILLUM_LOW_CONTRAST_T
        if need_dark or need_bright or need_flat:
            self._on = True
            self._frames = C.ILLUM_HYST_FRAMES
            self._mode = "dark" if need_dark else (
                "bright" if need_bright else "flat")
        elif self._frames > 0:
            self._frames -= 1                       # 迟滞期：延续上一次的判定
        else:
            self._on = False
            self._mode = "normal"

        if not self._on:
            return frame, self._mode
        return self._apply(frame, mean, std), self._mode

    def _apply(self, frame: np.ndarray, mean: float, std: float) -> np.ndarray:
        # 只动亮度通道，色度原样保留 —— 否则肤色会被推离手部检测用的阈值区间
        ycc = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
        y = ycc[:, :, 0]
        if mean < C.ILLUM_DARK_T:
            gamma = C.ILLUM_GAMMA_DARK
        elif mean > C.ILLUM_BRIGHT_T:
            gamma = C.ILLUM_GAMMA_BRIGHT
        else:
            gamma = 1.0
        if abs(gamma - 1.0) > 0.01:
            # 注意指数是 gamma **本身**，不是它的倒数。
            # 归一化像素 x∈[0,1]：x^γ 在 γ<1 时变大（提亮）、γ>1 时变小（压暗）。
            # 写成 x^(1/γ) 会把暗画面压得更暗 —— 校验时被 Eclipseبان 出来的：
            # 平均亮度 38 反而掉到 35，与"提亮"完全相反。
            lut = np.array([((i / 255.0) ** gamma) * 255.0
                            for i in range(256)], dtype=np.uint8)
            y = cv2.LUT(y, lut)
        # 低对比或偏暗时再叠 CLAHE：它做的是局部对比，能把逆光下的五官结构拉回来
        if std < C.ILLUM_LOW_CONTRAST_T or mean < C.ILLUM_DARK_T:
            y = self._get_clahe().apply(y)
        ycc[:, :, 0] = y
        return cv2.cvtColor(ycc, cv2.COLOR_YCrCb2BGR)


class FaceTargetSelector:
    """
    多人 / 多候选场景下的主目标选择。

    原来每帧取"面积最大的框"，这在只有一个人时没问题，多人时会坏得很明显：
      · 两个人的脸面积此消彼长（谁稍微往前坐一点），目标就在两人之间来回跳；
      · 有人从背景里走过时可能短暂地比玩家更靠前，主角会被抢走。
    体感控制的可用性取决于**目标不漂移**，至于某几帧里谁更靠近镜头根本不重要。

    所以这里引入"所有权"：现任目标享有优势，挑战者必须
        **明显更优（HYST 倍）且连续领先若干帧** 才允许夺权；
    目标短暂消失（手挡脸、低头捡东西）之后回到原位置还能立刻认回来，
    而不是走一遍"完整丢失 → 重新初始化"的流程。
    """

    def __init__(self) -> None:
        self._w = 1.0
        self._h = 1.0
        self._cx: Optional[float] = None
        self._cy: Optional[float] = None
        self._size: Optional[float] = None
        self._last = 0
        self._miss = 0
        self._chall: Optional[Tuple[int, int]] = None

    def reset(self) -> None:
        self._cx = self._cy = self._size = None
        self._last = 0
        self._miss = 0
        self._chall = None

    # ------------------------------------------------------------------ #
    def _cand_info(self, f) -> Tuple[float, float, float, float, float]:
        """解一个候选：(面积, 面积分, 中心x, 中心y, 连续性分)。"""
        x, y, bw, bh = float(f[0]), float(f[1]), float(f[2]), float(f[3])
        area = (bw * bh) / max(1.0, self._w * self._h)
        # 饱和度取 0.12（而不是最初的 0.05）：0.05 会让两个正常人脸框
        # **都顶到满分**，面积里携带的信息被抹平，"谁更靠近"就看不出来了。
        area_t = min(1.0, area / 0.12)
        cx = (x + bw / 2.0) / max(1.0, self._w)
        cy = (y + bh / 2.0) / max(1.0, self._h)

        if self._cx is None:
            return area, area_t, cx, cy, 0.0

        # 连续性：位置要近、尺度也要接近。
        # 位置用线性衰减（0.35 个画面宽内都当作"可能还是同一个人"）；
        # 尺度用对数比 —— 距离变一点点，面积是平方级变化的，用线性比不公平。
        d = math.hypot(cx - self._cx, cy - self._cy)
        pos_t = max(0.0, 1.0 - d / 0.35)
        sr = area / max(1e-6, self._size or 1e-6)
        size_t = max(0.0, 1.0 - abs(math.log(max(1e-3, sr))) / 0.7)
        return area, area_t, cx, cy, pos_t * (0.4 + 0.6 * size_t)

    def pick(self, cands, w: int, h: int) -> int:
        """
        返回选中下标。四条规则按优先级排列，每一条对应一类真实场景。
        """
        self._w, self._h = float(w), float(h)
        n = len(cands)
        infos = [self._cand_info(f) for f in cands]
        areas = [i[0] for i in infos]
        area_ts = [i[1] for i in infos]
        conts = [i[4] for i in infos]

        # ① 刚经历过"没有任何候选"（手挡脸 / 低头 / 眨眼被判丢）
        #    这时的问题不是"谁来抢位置"，而是"要把刚才那个人认回来"，
        #    所以按连续性直接选，**不走下面那套防抢夺的迟滞** ——
        #    否则遮挡结束后的前几帧会停在错误的人身上。
        if self._miss > 0:
            best = max(range(n), key=lambda i: conts[i] + area_ts[i] * 0.05)
            self._miss = 0
            self._commit(cands[best], best)
            return best

        # ② 没有历史（第一次出现 / 记忆已过期）→ 按显著性选最大的
        if self._cx is None:
            best = max(range(n), key=lambda i: area_ts[i])
            self._commit(cands[best], best)
            return best

        cur = min(self._last, n - 1)

        # ③ 出现**明显更大**的目标 → 不是同一层次的竞争，允许接管。
        #    连续性天然偏向现任，没有这条的话目标会被永久锁死。
        if C.FACE_TAKEOVER_RATIO > 1.0 and areas[cur] > 1e-9:
            big = [i for i in range(n)
                   if areas[i] > areas[cur] * C.FACE_TAKEOVER_RATIO]
            if big:
                b = max(big, key=lambda i: areas[i])
                if self._chall is not None and self._chall[0] == b:
                    cnt = self._chall[1] + 1
                else:
                    cnt = 1
                self._chall = (b, cnt)
                if cnt >= C.FACE_SWITCH_FRAMES:      # 连续确认，挡住单帧误检框篡位
                    self._chall = None
                    self._commit(cands[b], b)
                    return b
                return cur

        # ④ 面积相近 → 维持现任不动。
        #    这是"多人同框不再来回甩"的关键：谁这一刻稍大一点也不重要，
        #    重要的是目标不要漂到别人身上去。
        self._chall = None
        self._commit(cands[cur], cur)
        return cur

    def note_missing(self) -> None:
        """
        这一帧没有任何可用候选。

        不清零 —— 保留一段记忆，好让"手挡脸 / 低头"这类短暂遮挡结束后
        立刻认回同一个人（避免重新初始化、避免再来一遍校准）。
        """
        self._miss += 1
        if self._miss > C.FACE_TRACK_MISS:
            self.reset()

    def _commit(self, f, idx: int) -> None:
        area, _, cx, cy, _ = self._cand_info(f)
        self._cx, self._cy, self._size = cx, cy, area
        self._last = idx


class FaceBackendYuNet:
    name = "YuNet"

    def __init__(self) -> None:
        if not os.path.exists(YUNET_PATH):
            raise FileNotFoundError(YUNET_PATH)
        self._det = cv2.FaceDetectorYN.create(YUNET_PATH, "", (320, 240), 0.65, 0.3, 5000)
        self._size = None
        self._sel = FaceTargetSelector()

    def detect(self, frame: np.ndarray, w: int, h: int) -> FaceState:
        if self._size != (w, h):
            self._det.setInputSize((w, h))
            self._size = (w, h)
        _, faces = self._det.detect(frame)
        if faces is None or len(faces) == 0:
            self._sel.note_missing()
            return FaceState(found=False)
        # ---- 双重候选过滤 ----
        #  1) 几何合理性（尺寸 / 宽高比 / 面积 / 离边距）
        #  2) **检测器自己的置信度** —— 这一层以前完全没用到。
        #     YuNet 每行的第 15 个值是 score；低于阈值的框多半是背景纹理，
        #     而漏掉它们走的是安全的冻结/归零路径。
        cands = []
        for f in faces:
            if not _plausible_face(f, w, h):
                continue
            if _face_score(f) < C.FACE_MIN_SCORE:
                continue
            cands.append(f)
        if not cands:
            self._sel.note_missing()
            return FaceState(found=False)
        # 主目标选择（多人场景不再每帧取最大 —— 那样会把目标在几个人之间来回甩）
        f = cands[self._sel.pick(cands, w, h)]
        conf = _face_score(f)
        x, y, bw, bh = float(f[0]), float(f[1]), float(f[2]), float(f[3])
        # YuNet 的 5 个关键点：右眼、左眼、鼻尖、右嘴角、左嘴角
        pts = [(float(f[i]), float(f[i + 1])) for i in (4, 6, 8, 10, 12)]
        eye_r, eye_l, nose = pts[0], pts[1], pts[2]
        # 关键点可信度：5 个点都得落在框内，且双眼间距相对于框宽足够大。
        # 侧脸时 YuNet 的关键点会明显退化（眼距压得很扁、点跑到框外），
        # 这时算出来的 yaw/pitch 完全不可信 —— 宁可这一帧不用姿态量，
        # 也不要让它污染控制量（这是"摇头/抬头误判"的来源之一）。
        eye_span = math.hypot(eye_l[0] - eye_r[0], eye_l[1] - eye_r[1])
        pose_ok = (
            eye_span >= max(4.0, bw * 0.16)
            and all(-bw * 0.15 <= p[0] - x <= bw * 1.15
                    and -bh * 0.15 <= p[1] - y <= bh * 1.15 for p in pts)
        )
        return FaceState(
            found=True,
            cx=min(1.0, max(0.0, (x + bw / 2) / w)),
            cy=min(1.0, max(0.0, (y + bh / 2) / h)),
            w=bw / w, h=bh / h,
            yaw=self._yaw(nose, eye_r, eye_l),
            pitch=self._pitch(nose, eye_l, eye_r, pts[3], pts[4]),
            roll=float(np.arctan2(eye_l[1] - eye_r[1], max(1.0, eye_l[0] - eye_r[0]))),
            pose_ok=pose_ok,
            box=(int(x), int(y), int(bw), int(bh)),
            landmarks=pts,
            nose=nose,
            score=conf,
        )

    @staticmethod
    def _yaw(nose, eye_a, eye_b) -> float:
        """
        头部左右转向（**旋转不变**）。

        做法：把"鼻尖 − 双眼中点"的位移**投影到眼线方向**上，再除以半个眼距。

        为什么不能像旧版那样直接比 |鼻尖−左眼| 与 |鼻尖−右眼| 的差值：
        头稍微一歪（roll），这两个距离就同时变化，于是会读出一个虚假的转向 ——
        而"点头/歪头"在真实使用里几乎每帧都在发生，噪声因此长期存在。

        符号约定：画面已镜像，所以"往右转 → 鼻尖在画面里右移 → 返回正值"，
        与横向控制量的正方向一致。
        """
        ax, ay = float(eye_a[0]), float(eye_a[1])
        bx, by = float(eye_b[0]), float(eye_b[1])
        # 统一成"画面左眼 / 画面右眼"，不依赖模型对 landmark 的命名顺序
        if ax <= bx:
            (lx, ly), (rx, ry) = (ax, ay), (bx, by)
        else:
            (lx, ly), (rx, ry) = (bx, by), (ax, ay)
        span = math.hypot(rx - lx, ry - ly)
        if span < 1e-3:
            return 0.0
        ux, uy = (rx - lx) / span, (ry - ly) / span           # 眼线单位向量
        mx, my = (lx + rx) * 0.5, (ly + ry) * 0.5
        along = (float(nose[0]) - mx) * ux + (float(nose[1]) - my) * uy
        return float(np.clip(along / (span * 0.5), -1.0, 1.0))

    @staticmethod
    def _pitch(nose, eye_a, eye_b, mouth_a, mouth_b) -> float:
        """
        俯仰（**旋转不变**，且与画面距离无关）。

        把鼻尖投影到"眼线中点 → 嘴线中点"这条轴上，取归一化位置。
        抬头时下半张脸被透视压缩，鼻尖相对位置前移，读数随之变大。
        头歪（roll）不会污染它，因为它用的是投影而不是纯垂直距离。
        """
        ex = (float(eye_a[0]) + float(eye_b[0])) * 0.5
        ey = (float(eye_a[1]) + float(eye_b[1])) * 0.5
        mx = (float(mouth_a[0]) + float(mouth_b[0])) * 0.5
        my = (float(mouth_a[1]) + float(mouth_b[1])) * 0.5
        dx, dy = mx - ex, my - ey
        span = math.hypot(dx, dy)
        if span < 3.0:
            return 0.0
        ux, uy = dx / span, dy / span
        k = ((float(nose[0]) - ex) * ux + (float(nose[1]) - ey) * uy) / span
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
                # fitEllipse 返回 ((cx,cy), ((MA),(ma)), angle) —— 角度是第 3 项。
                # 之前误写成 [1]（那是 (size, angle) 二元组），解包就抛 ValueError；
                # 而外层只 catch 了 cv2.error，于是异常一路上抛被采集线程吞掉，
                # 结果是"只要画面里出现任何肤色候选，手部结果就永远是空"。
                angle = float(np.radians(cv2.fitEllipse(cnt)[2]))
            except Exception:                                    # noqa: BLE001
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
    """
    摄像头采集线程。

    分工（这是本项目视觉方案的最终形态）：
      · **头部主信号**：OpenCV YuNet 人脸检测，每帧跑（约 2ms）。
        它只依赖"看到脸"，用户只露个头也能稳定工作 —— 比人体姿态模型更耐用。
      · **全身 + 手部**：core.vision 的 AutoEngine（macOS 上就是 Apple Vision），
        每 vision_every 帧跑一次。给出 COCO-17 骨骼与手部 21 关键点。
      · 两者结果合并成统一的 VisionFrame + 兼容旧接口的 FaceState / HandState。

    为什么不全用人体姿态做头部：VNDetectHumanBodyPoseRequest 需要看到足够多的
    身体部位才会出结果，坐在桌前只露头肩时容易整帧丢失；
    而 YuNet 只要一张脸。用 YuNet 保底、Vision 增强，手感最稳。
    """

    def __init__(self, cam_index: int = C.CAM_INDEX, prefer: str = None,
                 hands: bool = True, vision_every: int = None) -> None:
        self.ok = False
        self.err = ""
        self.backend_name = "-"
        self.hand_name = "-"
        self._face = None
        self._engine = None
        self._use_yunet = False
        # 纯手部游戏把推理间隔提到每帧（apple 只跑手部请求仅 4.8ms）；
        # 全身模式维持 VISION_EVERY（body+hand 共享推理 8.3ms，隔帧跑）。
        # 注意 _base_interval 会随 set_vision_mode 切换而更新。
        self._vision_every = max(1, int(vision_every or C.VISION_EVERY))
        self._base_interval = self._vision_every
        self._vision_interval = self._base_interval
        self._vision_mode = "full"        # off / hand / body / full，由 shell 按游戏切换
        self._miss_streak = 0
        self._vision_t = 0.0              # 上一次**真正推理**的时间（判断新鲜度用）
        self._prefer = prefer
        self._cap = None
        self._thread = None
        self._running = False
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._state = FaceState()
        self._hands: List[HandState] = []
        self._vision = VisionFrame()
        self._fps = 0.0
        self._hand_ms = 0.0
        self._face_ms = 0.0
        self._vision_ms = 0.0
        self._frame_i = 0
        self._illum = IlluminationGuard()
        self._illum_mode = "normal"
        # 手部兜底用的肤色方案（HandBackendSkin）—— 早已实现但一直没被接上，
        # 这里真正实例化它，作为 Vision 手部不可用时的后备。
        self._skin = None
        self._last_hand_t = 0.0        # 上一次**真的**检测到手的时间
        self._hand_src = "-"           # 当前手部来源：vision / skin / -
        self._stats = {"pose": 0, "hand": 0, "n": 0}

        # ---- 视觉引擎（自动按平台选后端）----
        try:
            from .vision import AutoEngine
            self._engine = AutoEngine(prefer=prefer, max_hands=C.HAND_MAX_NUM,
                                      body=True, hands=hands,
                                      min_hand_conf=C.HAND_MIN_CONF,
                                      min_hand_joints=C.HAND_MIN_JOINTS)
            self.hand_name = self._engine.name
            # opencv 后端内部已经含人脸检测，不要再叠一层 YuNet
            self._use_yunet = self._engine.name != "opencv"
        except Exception as e:                                      # noqa: BLE001
            print(f"[tracker] 视觉引擎初始化失败：{e}")
            self._use_yunet = True

        # ---- YuNet（头部主信号）----
        if self._use_yunet:
            for factory in (FaceBackendYuNet, FaceBackendHaar):
                try:
                    self._face = factory()
                    break
                except Exception as e:                              # noqa: BLE001
                    print(f"[tracker] {factory.__name__} 不可用：{e}")
        if self._face is None and self._engine is None:
            self.err = "没有可用的视觉后端"
            return
        self.backend_name = self._face.name if self._face else self._engine.name

        if not self._open_camera(cam_index):
            self.err = f"无法打开摄像头（索引 {cam_index}）。请检查授权或被占用。"
            return
        try:
            self._skin = HandBackendSkin()        # 手部兜底：不依赖任何模型文件
        except Exception as e:                    # noqa: BLE001
            print(f"[tracker] 手部兜底不可用：{e}")
            self._skin = None
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
            # ---- 光照自适应 ----
            # 只给人脸检测的那一份画面做增强：手部用的是 YCrCb/HSV 肤色阈值，
            # 过度校正会把肤色推出判定区间，所以要绕开它（ILLUM_FACE_ONLY）。
            face_img = small
            if C.ILLUM_ENABLE:
                enh, mode = self._illum.ensure(small)
                self._illum_mode = mode
                if not C.ILLUM_FACE_ONLY:
                    small = enh
                    face_img = enh
                else:
                    face_img = enh

            # ---- 骨骼 / 手部的送检分辨率 ----
            # 人脸用 320 缩略图就够了（脸在画面里大），但 21 个手部关节不是：
            # 手在 320 宽的画面里只有几十像素，指关节间距是个位数，
            # 检测器没有可判别的结构。这里是"一直检测不到手"的主因。
            if C.VISION_W >= C.CAM_W:
                vision_img = frame              # 直接用原始帧，还省一次 resize
            else:
                vh = int(round(C.CAM_H * C.VISION_W / float(max(1, C.CAM_W))))
                vision_img = cv2.resize(frame, (C.VISION_W, vh))

            # ---- 1) 头部主信号：YuNet 每帧跑，只露头也能稳（约 2ms）----
            st = FaceState(found=False)
            if self._face is not None:
                t0 = time.time()
                try:
                    st = self._face.detect(face_img, C.DETECT_W, det_h)
                except Exception:                                # noqa: BLE001
                    st = FaceState(found=False)
                self._face_ms += 0.25 * (((time.time() - t0) * 1000.0) - self._face_ms)
                st.backend = self.backend_name

            # ---- 2) 全身 + 手部：按需 + 自适应降频 ----
            #  真机实测：Vision 在**真实图像**上要 16~29ms（实验室用空白图测是 8ms），
            #  而 YuNet 人脸要 7~8ms。两个加起来就把采集线程压到 21~30fps 且抖动，
            #  头部控制的手感就是这么被拖坏的。
            #  所以策略是：
            #    · 按当前游戏的需要决定跑不跑（头部游戏完全不用跑）；
            #    · 连续检测不到目标时逐步拉长间隔（坐着只露头的人不会白白烧 CPU）；
            #    · 一旦检测到就立刻恢复高频。
            self._frame_i += 1
            vf = self.get_vision()
            if self._engine is not None and self._vision_mode != "off" and \
                    self._frame_i % self._vision_interval == 0:
                t0 = time.time()
                vf = self._engine.infer(vision_img)      # 注意：不是 small（见 VISION_W）
                ms = (time.time() - t0) * 1000.0
                self._vision_ms += 0.25 * (ms - self._vision_ms)
                got = vf.pose.found or bool(vf.hands)
                if got:
                    self._miss_streak = 0
                    self._vision_interval = max(1, self._base_interval)
                else:
                    self._miss_streak += 1
                    if self._miss_streak > 4:
                        # 连续 5 次没东西 → 退避。
                        # ⚠ 上限**必须**小于 VISION_STALE_AFTER 对应的帧数：
                        # 原值 12 帧（≈0.4s @30fps）已经超过过期判定 0.35s，
                        # 于是退避期间每一帧都被判过期、按"没检测到"返回 ——
                        # 越退避越检测不到，永远回不去。这就是"一旦检测不到
                        # 就一直检测不到"的死锁。
                        self._vision_interval = min(C.VISION_BACKOFF_MAX,
                                                    self._vision_interval + 1)
                self._stats["pose"] += 1 if vf.pose.found else 0
                self._stats["hand"] += len(vf.hands)
                self._stats["n"] += 1
                with self._lock:
                    self._vision = vf
                    self._vision_t = time.time()

            # ---- 3) 合并：YuNet 定头部，Vision 补朝向与全身 ----
            if st.found and vf.pose.found:
                st.yaw = vf.pose.head_yaw
                st.pitch = vf.pose.head_pitch
                st.roll = vf.pose.head_roll
            elif not st.found and vf.pose.found:
                st = self._face_from_pose(vf.pose, C.DETECT_W, det_h,
                                          self.backend_name + "+" + vf.source)

            hands = [self._hand_state(h) for h in vf.hands]
            # ---- 手部来源分层（第二版核心约束：skin 永不与 Vision 同帧竞争）----
            # 第一版让 skin 与 Vision 的手进入同一个候选列表，结果肤色误检块
            # （脖子/窗帘/木桌，面积常大于真手）抢走主手且真手永远夺不回 ——
            # 这是"完全不跟"的根因。现在分层：
            #   · Vision 有手 → 只用 Vision 的（21 点，可信）；
            #   · Vision 连续 HANDSKIN_AFTER 完全没有手 → 才递入 skin 的结果
            #     作为降级坐标源；Vision 一恢复立即让位。
            if hands:
                self._last_hand_t = time.time()
                self._hand_src = "vision"
            elif (C.HANDSKIN_FALLBACK and self._skin is not None
                  and self._vision_mode in ("hand", "full")
                  and time.time() - self._last_hand_t > C.HANDSKIN_AFTER):
                fbox = None
                if st.found and st.box is not None:
                    sx = vision_img.shape[1] / float(C.DETECT_W)
                    sy = vision_img.shape[0] / float(max(1, det_h))
                    bx, by, bw, bh = st.box
                    fbox = (int(bx * sx), int(by * sy),
                            int(bw * sx), int(bh * sy))
                skin = self._skin.detect(vision_img, fbox,
                                         vision_img.shape[1], vision_img.shape[0])
                if skin:
                    hands = skin
                    self._hand_src = "skin"
                else:
                    self._hand_src = "-"

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

    # ------------------------------------------------------------------ 转换
    @staticmethod
    def _face_from_pose(pose, w: int, h: int, backend: str) -> FaceState:
        """人体姿态的头部 → 兼容的 FaceState（YuNet 丢失时的兜底）。"""
        head = pose.head
        le, re = pose.get("left_eye"), pose.get("right_eye")
        ww = abs(re.x - le.x) if (le.ok and re.ok) else 0.14
        hh = ww * 1.32
        return FaceState(found=True, cx=head.x, cy=head.y, w=ww, h=hh,
                         yaw=pose.head_yaw, pitch=pose.head_pitch, roll=pose.head_roll,
                         box=(int((head.x - ww / 2) * w), int((head.y - hh / 2) * h),
                              int(ww * w), int(hh * h)),
                         nose=(head.x * w, head.y * h), backend=backend)

    @staticmethod
    def _hand_state(hf) -> HandState:
        """
        HandFrame（21 点）→ 兼容的 HandState。

        ⚠ area **必须**填。HandController 是靠 `max(hands, key=area)` 选主手的，
        而这里原来一直没给它赋值 —— 于是每只手的 area 都是默认的 0.0，
        评分全部相同，`max` 就固定返回**第一个**。
        Apple Vision 返回多只手（或一真一误检）时的顺序并不稳定，
        结果就是主手每帧在不同手之间跳 → 游戏里的光标轨迹完全对不上。
        """
        c = hf.center
        ok = [j for j in hf.joints.values() if getattr(j, "ok", False)]
        if ok:
            xs = [j.x for j in ok]
            ys = [j.y for j in ok]
            area = max(0.0, (max(xs) - min(xs))) * max(0.0, (max(ys) - min(ys)))
        else:
            area = max(1e-6, hf.palm_width * hf.palm_width)
        return HandState(found=True, x=c.x, y=c.y, open=hf.openness,
                         fingers=hf.extended_count, area=area,
                         span=hf.palm_width, pose=hf)

    # ---------- 对外 ----------
    def get(self):
        with self._lock:
            return self._frame, self._state, list(self._hands)

    def get_vision(self) -> VisionFrame:
        """
        取最新一帧的全身骨骼 + 手部关键点。

        **过期的帧按"什么都没有"返回。** 视觉引擎是按需降频跑的（丢检时还会
        退避到 1/12 帧），两次推理之间会把上一帧一直交出去；如果这期间人已经
        离开，消费者就会拿着那帧陈旧的 `found=True` 和抬臂数值，让角色在没人
        做动作时继续"按键"。加一层新鲜度判断后，过期等同于没检测到。
        """
        with self._lock:
            if time.time() - self._vision_t > C.VISION_STALE_AFTER:
                return VisionFrame(source="stale")
            return self._vision

    # ------------------------------------------------------------------ 模式
    def set_vision_mode(self, mode: str) -> None:
        """
        按当前游戏切换视觉负载：

            off   不跑（纯头部游戏）—— 省下全部的 Vision 开销
            hand  只跑手部
            body  只跑人体
            full  人体 + 手部（体感游戏）

        这是"加了手之后头部反而变钝"的根治办法：
        玩马里奥的时候根本不需要跑手部检测，就别跑。
        """
        self._vision_mode = mode
        self._miss_streak = 0
        # 纯手部模式用更密的间隔（apple 只跑手部 4.8ms，每帧都跑得起）；
        # 全身模式维持构造时的间隔（body+hand 共享推理 8.3ms，隔帧）。
        base = C.HAND_VISION_EVERY if mode == "hand" else self._vision_every
        self._base_interval = max(1, base)
        self._vision_interval = max(1, self._base_interval)
        want = {"off": (False, False), "hand": (False, True),
                "body": (True, False), "full": (True, True)}.get(mode)
        if want is None or self._engine is None:
            return
        cur = getattr(self._engine, "_mod_names", None)
        if cur != (mode,):
            try:
                # 重建引擎以换掉请求集合（请求对象是绑定在引擎里的）
                from .vision import AutoEngine
                self._engine.close()
                self._engine = AutoEngine(prefer=self._prefer, max_hands=C.HAND_MAX_NUM,
                                          body=want[0], hands=want[1],
                                          min_hand_conf=C.HAND_MIN_CONF,
                                          min_hand_joints=C.HAND_MIN_JOINTS)
                self._engine._mod_names = (mode,)
            except Exception as e:                                  # noqa: BLE001
                print(f"[tracker] 切换视觉模式失败：{e}")

    def _want_body(self) -> bool:
        return self._vision_mode in ("body", "full")

    @property
    def vision_mode(self) -> str:
        return self._vision_mode

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def hand_ms(self) -> float:
        return self._hand_ms

    @property
    def timings(self) -> dict:
        """各环节耗时（毫秒），排查性能问题时用。"""
        n = max(1, self._stats["n"])
        return {
            "face": self._face_ms,
            "vision": self._vision_ms,
            "fps": self._fps,
            "illum": self._illum_mode,      # 当前光照判定：normal/dark/bright/flat
            "hand_src": self._hand_src,     # 手部来源：vision / skin / -
            "hands": len(self._hands),      # 当前实际交给游戏的手数
            "pose_rate": self._stats["pose"] / n,
            "hands_rate": self._stats["hand"] / n,
        }

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
