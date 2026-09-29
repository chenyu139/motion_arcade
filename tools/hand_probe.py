#!/usr/bin/env python3
"""
tools/hand_probe.py — 手部链路真机诊断（15 秒拿到决定性证据）

用法（终端跑；若摄像头授权失败，改用 open MotionArcade.app 后看 run.log）：
    .venv/bin/python tools/hand_probe.py            # 默认 15 秒
    .venv/bin/python tools/hand_probe.py --secs 30

做什么：同时运行 Apple Vision（21 点）与肤色兜底（skin），逐帧记录
    · 每个来源各自看到了几只手、位置、面积、张合度
    · HandController（ID 跟踪 + 控制权）选了谁、为什么
    · 最终交给游戏的光标坐标 (sx, sy)

你只需要：伸手、握拳、张开、快速挥动几下。
结束自动生成一份诊断报告，把输出发回即可精确定位"不跟"在哪一层。
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2  # noqa: E402
from core import config as C                    # noqa: E402
from core.inputs import HandController          # noqa: E402
from core.tracker import (HandBackendSkin,      # noqa: E402
                          MotionTracker)


def main() -> int:
    ap = argparse.ArgumentParser(description="手部链路真机诊断")
    ap.add_argument("--secs", type=int, default=15)
    ap.add_argument("--cam", type=int, default=C.CAM_INDEX)
    args = ap.parse_args()

    print("=" * 70)
    print("手部链路诊断 —— 请对着摄像头：伸手 → 握拳 → 张开 → 快速挥动几下")
    print("=" * 70)

    tr = MotionTracker(args.cam, prefer="apple", hands=True)
    if not tr.ok:
        print(f"[probe] 摄像头不可用：{tr.err}")
        print("        若授权失败：macOS 终端默认没有摄像头权限，")
        print("        请改跑 open MotionArcade.app（其日志在 run.log），")
        print("        或给 Terminal/Idea 授予摄像头权限后重试。")
        return 1
    print(f"[probe] Vision 后端: {tr.hand_name}　人脸: {tr.backend_name}")

    skin = HandBackendSkin()
    hc = HandController(C)

    log = []
    t0 = time.time()
    last = t0
    try:
        while time.time() - t0 < args.secs:
            time.sleep(1 / 60)
            frame, st, hands = tr.get()
            if frame is None:
                continue
            now = time.time()
            dt = now - last
            last = now
            if dt <= 0 or dt > 0.2:
                continue

            # 与 MotionTracker 内部相同的流程：vision 的手 vs skin 的手
            vw = C.VISION_W
            vh = int(round(frame.shape[0] * vw / float(frame.shape[1])))
            vimg = cv2.resize(frame, (vw, vh)) if vw < frame.shape[1] else frame
            vf = tr.get_vision()
            vhands = [tr._hand_state(h) for h in vf.hands]
            # skin（独立跑一份，看它自己会说什么 —— 不接管，只记录）
            fbox = None
            if st.found and st.box is not None:
                sx_ = vimg.shape[1] / float(C.DETECT_W)
                sy_ = vimg.shape[0] / float(max(1, st.box[3]))
                bx, by, bw, bh = st.box
                fbox = (int(bx * sx_), int(by * sy_), int(bw * sx_), int(bh * sy_))
            shands = skin.detect(vimg, fbox, vimg.shape[1], vimg.shape[0])

            hc.update(hands, dt)
            d = hc._debug
            row = {
                "t": now - t0,
                "face": st.found,
                "vh": len(vhands), "sh": len(shands),
                "vhands": [(round(h.x, 2), round(h.y, 2), round(h.area, 4),
                            round(h.open, 2)) for h in vhands[:2]],
                "shands": [(round(h.x, 2), round(h.y, 2), round(h.area, 4))
                           for h in shands[:2]],
                # 第二版 HandController 的诊断字段（最近邻跟随，无 _main/tid）
                "src": getattr(hc, "hand_src", "-"),
                "raw": d.get("raw", None),
                "hold": d.get("hold", 0.0),
                "seen": hc.seen,
                "sx": round(hc.sx, 3), "sy": round(hc.sy, 3),
            }
            log.append(row)
            if len(log) % 30 == 0:
                print(f"  t={row['t']:5.1f}s vision手{row['vh']} skin手{row['sh']} "
                      f"→ 跟随[{row['src']}] 原始={row['raw']} "
                      f"光标=({row['sx']:.2f},{row['sy']:.2f}) "
                      f"{'·丢失' if not row['seen'] else ''}")
    except KeyboardInterrupt:
        pass
    finally:
        tr.close()

    # ---- 统计 ----
    n = max(1, len(log))
    v_on = sum(1 for r in log if r["vh"] > 0)
    s_on = sum(1 for r in log if r["sh"] > 0)
    both = sum(1 for r in log if r["vh"] > 0 and r["sh"] > 0)
    only_s = sum(1 for r in log if r["vh"] == 0 and r["sh"] > 0)
    seen = sum(1 for r in log if r["seen"])
    skin_pct = sum(1 for r in log if r["src"] == "skin") / n
    # 光标与最近 Vision 手的偏差（跟随质量的核心指标）
    devs = []
    for r in log:
        if r["vh"] > 0 and r["seen"] and r["raw"]:
            rx, ry = r["raw"]
            near = min((math.hypot(h[0] - r["sx"], h[1] - r["sy"])
                        for h in r["vhands"]), default=99)
            devs.append(near)
    dev_med = sorted(devs)[len(devs) // 2] if devs else -1
    print("\n" + "=" * 70)
    print(f"样本 {len(log)} 帧（{args.secs}s）")
    print(f"  Vision 21点 看到手: {v_on:4d} 帧 {v_on/n:6.1%}")
    print(f"  skin 肤色   看到手: {s_on:4d} 帧 {s_on/n:6.1%}")
    print(f"  两者同时:           {both:4d} 帧")
    print(f"  仅 skin（误检高危）:{only_s:4d} 帧")
    print(f"  HandController 判定可见: {seen:4d} 帧 {seen/n:6.1%}")
    print(f"  光标来源 skin 占比: {skin_pct:6.1%}（高=Vision 长期缺席）")
    if dev_med >= 0:
        print(f"  光标↔最近Vision手 中位偏差: {dev_med:.3f}（<0.10=跟得上）")
    print("=" * 70)
    diag = []
    if v_on / n < 0.2:
        diag.append("⚠ Vision 21点检出率 <20%：手部主路径基本没工作。"
                    "可能是距离/光照/分辨率问题。")
    if only_s / n > 0.3:
        diag.append("⚠ 大量帧只有 skin 看到'手'：肤色兜底在独撑，"
                    "而这意味着误检风险很高（脖子/木桌/窗帘都是肤色）。")
    if seen / n < 0.3:
        diag.append("⚠ 光标大部分时间不可见：链路在'丢失'状态。")
    if dev_med > 0.12:
        diag.append(f"⚠ 光标与 Vision 手的偏差偏大（{dev_med:.3f}）："
                    "跟随层在跟别的东西（误检）或滤波滞后过大。")
    if not diag:
        diag.append("✓ 各层看起来都在工作 —— 若仍'不跟'，"
                    "请把这份输出发回，并描述手往哪边动、光标往哪边动。")
    for d in diag:
        print("  " + d)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
