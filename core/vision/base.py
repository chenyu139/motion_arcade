"""
core/vision/base.py
===================
视觉后端统一接口 + 注册表 + 自动选择。

设计目标：**同一套游戏代码，在 Mac / Windows / Linux 上都能跑**。
每个平台用自己最主流的方案，但对上层暴露完全一致的 VisionFrame。

后端一览
--------
    apple      Apple Vision     macOS/iOS   19 点人体 + 21 点手，ANE 加速
    mediapipe  MediaPipe Tasks  Win/Linux/Android  33 点人体 + 21 点手，TFLite
    onnx       ONNX Runtime    全平台      RTMPose/YOLO-Pose，可挂任意 EP
    opencv     OpenCV 兜底      全平台      人脸框 + 肤色手部（精度最低）

选择顺序按平台自动决定，也可以用 --vision 强制指定。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .types import VisionFrame


class BaseBackend:
    """所有后端实现这个接口。"""

    NAME = "base"
    PLATFORMS: Tuple[str, ...] = ()

    @staticmethod
    def available() -> Tuple[bool, str]:
        return False, "未实现"

    def __init__(self, **kw) -> None:
        self.cfg = kw

    def infer(self, bgr) -> VisionFrame:
        raise NotImplementedError

    def close(self) -> None:
        pass

    @property
    def name(self) -> str:
        return self.NAME


# --------------------------------------------------------------------------- #
# 注册表：每个后端模块只需暴露 NAME / available() / make_engine()
# --------------------------------------------------------------------------- #
_REGISTRY: Dict[str, object] = {}


class _ModuleBackend(BaseBackend):
    """把一个后端模块包装成统一的引擎对象。"""

    def __init__(self, mod, **kw) -> None:
        self._mod = mod
        self.NAME = mod.NAME
        self._engine = mod.make_engine(**kw)

    def infer(self, bgr) -> VisionFrame:
        return self._engine.infer(bgr)

    def close(self) -> None:
        closer = getattr(self._engine, "close", None)
        if callable(closer):
            closer()


def register_module(mod) -> None:
    _REGISTRY[mod.NAME] = mod


def get(name: str):
    return _REGISTRY.get(name)


def all_backends() -> Dict[str, object]:
    return dict(_REGISTRY)


def describe() -> str:
    """打印所有后端的可用性，排查用。"""
    lines = []
    for n, mod in _REGISTRY.items():
        ok, why = mod.available()
        lines.append(f"  {'✓' if ok else '✗'} {n:10s} {why}")
    return "\n".join(lines)


def preferred_order() -> List[str]:
    """按当前平台给出后端优先级。"""
    import sys
    if sys.platform == "darwin":
        return ["apple", "onnx", "mediapipe", "opencv"]
    if sys.platform.startswith("win"):
        return ["mediapipe", "onnx", "opencv"]
    return ["mediapipe", "onnx", "opencv"]


class AutoEngine:
    """
    自动挑选可用后端并包装成统一入口。

    探测是**惰性**的：只有真正 infer 时才初始化后端，
    这样即使某个后端在当前平台初始化失败，也能干净地退化到下一个。
    """

    def __init__(self, prefer: Optional[str] = None, **kw) -> None:
        self._prefer = prefer
        self._kw = kw
        self._engine: Optional[BaseBackend] = None
        self._tried: List[str] = []
        self._err = ""

    def _ensure(self) -> bool:
        if self._engine is not None:
            return True
        order = [self._prefer] if self._prefer else preferred_order()
        cands = list(order)
        if not self._prefer:
            cands += [n for n in _REGISTRY if n not in cands]
        for name in cands:
            if not name or name not in _REGISTRY:
                continue
            mod = _REGISTRY[name]
            ok, why = mod.available()
            self._tried.append(f"{name}:{'ok' if ok else why}")
            if not ok:
                continue
            try:
                self._engine = _ModuleBackend(mod, **self._kw)
                return True
            except Exception as e:                                   # noqa: BLE001
                self._tried[-1] = f"{name}:初始化失败 {e}"
                self._engine = None
        self._err = "没有可用的视觉后端"
        return False

    def infer(self, bgr) -> VisionFrame:
        if not self._ensure():
            return VisionFrame(source="none")
        try:
            return self._engine.infer(bgr)
        except Exception as e:                                       # noqa: BLE001
            return VisionFrame(source=f"error:{e}")

    @property
    def name(self) -> str:
        if self._engine is None:
            self._ensure()
        return self._engine.name if self._engine else "none"

    @property
    def probe_log(self) -> str:
        return " | ".join(self._tried) or "（未探测）"

    def close(self) -> None:
        if self._engine is not None:
            self._engine.close()


# 把各后端注册进来（导入即注册）
from . import backend_apple      # noqa: E402,F401
from . import backend_mediapipe  # noqa: E402,F401
from . import backend_onnx       # noqa: E402,F401
from . import backend_opencv     # noqa: E402,F401

for _m in (backend_apple, backend_mediapipe, backend_onnx, backend_opencv):
    if hasattr(_m, "make_engine"):
        register_module(_m)
