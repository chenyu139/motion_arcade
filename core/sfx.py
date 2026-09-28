"""
core/sfx.py
===========
**纯程序化音效** —— 不引入任何音频素材文件。

为什么要自己合成：prompt 第 5 项明确要求"音效触发"（命中 / Combo / 过关），
而项目里没有任何音频资源。合成的好处是：零体积、零版权、可精确控制时长与
音高，而且能和 Combo 等级联动（连击越高音越高）。

设计要点
--------
· 全部是短促的**电子音色**（正弦 + 轻微噪声 + 快速包络），卡通游戏里最常见。
· 每个音效在首次播放时合成一次并缓存 —— 合成要算几万个采样点，
  放在帧内会掉帧，放在启动/首次触发则完全无感。
· `pygame.mixer` 初始化失败（无声卡 / 无头环境）时，**所有调用退化为空操作**，
  绝不抛异常。这一点很重要：测试工具与 CI 都是无头环境。

静音开关：游戏内按 M。整体音量在 config.SFX_VOLUME。
"""
from __future__ import annotations

import math
from typing import Dict, Optional

import numpy as np
import pygame

from . import config as C

_RATE = 44100
_cache: Dict[str, pygame.mixer.Sound] = {}
_ok: Optional[bool] = None
_muted = False


# --------------------------------------------------------------------------- #
# 波形合成
# --------------------------------------------------------------------------- #
def _env(n: int, attack: float = 0.008, decay: float = 0.42,
         power: float = 2.0) -> np.ndarray:
    """
    音量包络：极短的起音 + 指数衰减。

    起音必须够短（几毫秒），否则听起来"软"、"糊"；衰减用幂函数而不是
    线性，尾巴才干净 —— 卡通音效全靠这个包络撑起"脆"的感觉。
    """
    t = np.arange(n, dtype=np.float32) / _RATE
    a = np.clip(t / max(1e-4, attack), 0.0, 1.0)
    d = np.clip(1.0 - t / max(1e-4, decay), 0.0, 1.0) ** power
    return a * d


def _tone(freq: float, dur: float, *, vol: float = 0.5, harm: float = 0.28,
          noise: float = 0.0, slide: float = 0.0, attack: float = 0.008,
          power: float = 2.0) -> np.ndarray:
    """
    一段单音。

    harm    ：叠加二次谐波的比例（让音色不是纯正弦那么"电子玩具"）
    slide   ：频率滑动（Hz/秒）。上升音用于"命中/得分"，下降音用于"失败"
    noise   ：掺入的噪声比例（打击类音效需要一点噪声才有"质感"）
    """
    n = max(16, int(dur * _RATE))
    t = np.arange(n, dtype=np.float32) / _RATE
    f = freq + slide * t
    phase = 2.0 * math.pi * np.cumsum(f) / _RATE
    w = np.sin(phase) + harm * np.sin(2.0 * phase)
    if noise > 0:
        rng = np.random.default_rng(7)
        w = w + noise * rng.standard_normal(n).astype(np.float32)
    return (w * _env(n, attack, dur, power) * vol).astype(np.float32)


def _mix(*parts: np.ndarray) -> np.ndarray:
    n = max(p.size for p in parts)
    out = np.zeros(n, dtype=np.float32)
    for p in parts:
        out[: p.size] += p
    return out


def _chord(freqs, dur: float, **kw) -> np.ndarray:
    return _mix(*[_tone(f, dur, **kw) for f in freqs])


def _arpeggio(freqs, step: float, **kw) -> np.ndarray:
    """琶音：把一串音依次往后错开叠加（过关/庆祝用）。"""
    parts = []
    for i, f in enumerate(freqs):
        parts.append(np.pad(_tone(f, step * 2.2, **kw), (int(i * step * _RATE), 0)))
    return _mix(*parts)


# --------------------------------------------------------------------------- #
# 音效表
# --------------------------------------------------------------------------- #
def _build(name: str) -> Optional[pygame.mixer.Sound]:
    """合成一个音效。返回 None 表示这个名字不存在。"""
    if name == "move":              # 大厅选游戏：轻微的一声"嗒"
        w = _tone(660, 0.055, vol=0.30, harm=0.15, attack=0.003, power=3.0)
    elif name == "confirm":         # 确认进入：上行两音
        w = _arpeggio([523.25, 783.99], 0.075, vol=0.36, harm=0.22, power=2.2)
    elif name == "hit":             # 得分：短促上滑
        w = _tone(880, 0.13, vol=0.38, harm=0.30, slide=2600.0,
                  attack=0.003, power=2.6)
    elif name == "hit_big":         # 大额得分：更厚一点
        w = _mix(_tone(660, 0.20, vol=0.36, harm=0.34, slide=1800.0, power=2.4),
                 _tone(990, 0.16, vol=0.22, harm=0.22, slide=2400.0, power=2.6))
    elif name == "combo":           # 连击：音高随等级升（见 play_combo）
        w = _chord([784.0, 1174.7], 0.16, vol=0.32, harm=0.24, power=2.4)
    elif name == "fail":            # 失误：下行 + 一点噪声
        w = _tone(360, 0.34, vol=0.34, harm=0.30, slide=-520.0, noise=0.05,
                  attack=0.004, power=1.6)
    elif name == "celebrate":       # 过关：上行琶音
        w = _arpeggio([523.25, 659.25, 783.99, 1046.50], 0.105,
                      vol=0.34, harm=0.26, power=2.0)
    elif name == "start":           # 开始：厚一点的和弦
        w = _chord([392.0, 523.25, 659.25], 0.40, vol=0.28, harm=0.20, power=1.8)
    elif name == "pause":
        w = _tone(420, 0.10, vol=0.26, harm=0.18, attack=0.004, power=2.6)
    else:
        return None

    # 峰值归一化到 -3dB 以内，避免叠加时爆音
    peak = float(np.max(np.abs(w))) or 1.0
    w = w * (0.70 / peak) * float(getattr(C, "SFX_VOLUME", 0.5))
    stereo = np.repeat(np.clip(w, -1.0, 1.0)[:, None], 2, axis=1)
    return pygame.sndarray.make_sound((stereo * 32767.0).astype(np.int16))


# --------------------------------------------------------------------------- #
# 对外
# --------------------------------------------------------------------------- #
def init() -> bool:
    """初始化混音器。无头 / 无声卡环境下返回 False，之后所有播放都是空操作。"""
    global _ok
    if _ok is not None:
        return _ok
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=_RATE, size=-16, channels=2, buffer=512)
        pygame.mixer.set_num_channels(24)
        _ok = pygame.mixer.get_init() is not None
    except Exception:                                        # noqa: BLE001
        _ok = False
    return _ok


def available() -> bool:
    return bool(_ok)


def play(name: str, vol: float = 1.0) -> None:
    """播放一个音效。任何失败都静默忽略 —— 音效绝不该影响游戏运行。"""
    if _muted or not init():
        return
    s = _cache.get(name)
    if s is None:
        try:
            s = _build(name)
        except Exception:                                    # noqa: BLE001
            s = None
        if s is None:
            return
        _cache[name] = s
    try:
        ch = pygame.mixer.find_channel(True)
        if ch is not None:
            ch.set_volume(max(0.0, min(1.0, vol)))
            ch.play(s)
    except Exception:                                        # noqa: BLE001
        pass


def play_combo(level: int) -> None:
    """
    连击音：**音高随等级上升**（prompt 第 5 项"反馈逐渐增强"）。

    与其为 8 个等级各做一个音效，不如把同一个音效变频播放 ——
    音高上升本身就传达"越连越顺"，这是最省也最有效的做法。
    """
    if _muted or not init():
        return
    key = f"combo{min(6, max(1, level))}"
    s = _cache.get(key)
    if s is None:
        try:
            semis = min(6, max(1, level)) - 1
            freq = 784.0 * (2.0 ** (semis / 12.0))
            w = _chord([freq, freq * 1.5], 0.15, vol=0.30, harm=0.24, power=2.4)
            peak = float(np.max(np.abs(w))) or 1.0
            w = w * (0.70 / peak) * float(getattr(C, "SFX_VOLUME", 0.5))
            st = np.repeat(np.clip(w, -1.0, 1.0)[:, None], 2, axis=1)
            s = pygame.sndarray.make_sound((st * 32767.0).astype(np.int16))
        except Exception:                                    # noqa: BLE001
            return
        _cache[key] = s
    try:
        ch = pygame.mixer.find_channel(True)
        if ch is not None:
            ch.play(s)
    except Exception:                                        # noqa: BLE001
        pass


def toggle_mute() -> bool:
    """切换静音，返回切换后的静音状态。"""
    global _muted
    _muted = not _muted
    return _muted


def is_muted() -> bool:
    return _muted
