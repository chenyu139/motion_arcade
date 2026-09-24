"""
main.py
=======
体感游戏厅入口。

运行
    python main.py                  # 全屏启动，进入游戏大厅
    python main.py --windowed       # 窗口模式
    python main.py --game mario     # 直接进某个游戏
    python main.py --no-cam         # 不用摄像头（鼠标模拟手部 + 键盘）
    python main.py --list           # 列出全部游戏

大厅操作
    头部左右切卡片 · 抬头进入（或在卡片上停留 2.4 秒）
    键盘：←→↑↓ 移动 / 回车进入 / 数字键快速选 / TAB 换游戏
    游戏内：ESC 返回大厅　R 重开　C 校准　P 暂停　H 摄像头预览　F11 全屏
"""
from __future__ import annotations

import argparse
import os
import sys

# 以 .app 启动时 stdout 被重定向到日志文件，默认块缓冲会让日志严重滞后，
# 改成行缓冲便于实时排查摄像头/后端问题。
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core import config as C  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="体感游戏厅 · Motion Arcade")
    ap.add_argument("--vision", default="auto",
                    choices=["auto", "apple", "mediapipe", "onnx", "opencv"],
                    help="视觉后端：auto 按平台自动选（macOS→apple，Win/Linux→mediapipe）")
    ap.add_argument("--cam", type=int, default=C.CAM_INDEX, help="摄像头索引")
    ap.add_argument("--no-cam", action="store_true", help="不使用摄像头")
    ap.add_argument("--windowed", action="store_true", help="窗口模式启动（默认全屏）")
    ap.add_argument("--game", default="menu", help="启动后直接进入的游戏 key")
    ap.add_argument("--list", action="store_true", help="列出全部游戏后退出")
    ap.add_argument("--list-backends", action="store_true",
                    help="列出视觉后端在当前机器的可用性后退出")
    ap.add_argument("--probe", action="store_true",
                    help="诊断模式：跑 20 秒并把各后端可用性、检测率、耗时写入日志")
    args = ap.parse_args()

    import games  # noqa: F401  导入即完成注册
    from core import base as B
    from core.vision import describe, preferred_order

    if args.list_backends:
        print("=== 视觉后端可用性 ===")
        print(describe())
        print(f"=== 本平台优先级：{preferred_order()} ===")
        return 0

    if args.list:
        print(f"共 {len(B.all_games())} 款游戏：\n")
        print(f"{'key':<12}{'名称':<18}{'分类':<14}{'难度':<6}玩法")
        for c in B.all_games():
            print(f"{c.KEY:<12}{c.TITLE:<18}{c.CATEGORY:<14}{'★' * c.DIFFICULTY:<6}{c.HOW}")
        return 0

    print("=== 视觉后端可用性 ===")
    print(describe())
    print(f"=== 本平台优先级：{preferred_order()} ===")

    if args.probe:
        return run_probe(args)

    from core.shell import Shell
    shell = Shell(vision=args.vision, cam_index=args.cam, no_cam=args.no_cam,
                  windowed=args.windowed, start_game=args.game)
    shell.run()
    return 0


def run_probe(args) -> int:
    """
    诊断模式：真机跑 N 秒，周期性打印检测统计。

    之所以要这么个模式：真机画面截不到图（沙箱通常没有屏幕录制权限），
    只能靠日志里的"检测率 / 关键点数 / 各环节耗时"来判断方案到底行不行。
    """
    import time
    from core.tracker import MotionTracker

    tr = MotionTracker(args.cam, prefer=None if args.vision == "auto" else args.vision)
    if not tr.ok:
        print(f"[probe] 摄像头不可用：{tr.err}")
        return 1
    print(f"[probe] 视觉后端 {tr.hand_name}　人脸后端 {tr.backend_name}")
    base = time.time()
    last = base
    try:
        while time.time() - base < 20:
            time.sleep(1.0)
            f, st, hands = tr.get()
            vf = tr.get_vision()
            p = vf.pose
            rate = lambda v: f"{v:.0%}"                                  # noqa: E731
            print(f"[probe] t={time.time() - base:4.1f}s  "
                  f"cam {tr.fps:4.1f}fps  脸{'✓' if st.found else '·'}  "
                  f"人体{'✓' if p.found else '·'}({p.coverage():2d}点)  "
                  f"手{len(vf.hands)}  "
                  f"face {tr.timings['face']:4.1f}ms vision {tr.timings['vision']:5.1f}ms  "
                  f"| 举{inp_dbg(p)}")
    except KeyboardInterrupt:
        pass
    finally:
        tr.close()
    return 0


def inp_dbg(p) -> str:
    if not p.found:
        return "-"
    parts = []
    if p.lower_body_visible():
        parts.append(f"蹲{p.crouch:.1f}")
    parts.append(f"臂L{p.arm_raised('left'):.1f}/R{p.arm_raised('right'):.1f}")
    parts.append(f"举{p.hands_up()}")
    return " ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
