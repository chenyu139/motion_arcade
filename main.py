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
    ap.add_argument("--backend", choices=["auto", "mediapipe"], default="auto",
                    help="人脸检测后端；mediapipe 需要额外依赖且可能崩溃，默认 auto")
    ap.add_argument("--cam", type=int, default=C.CAM_INDEX, help="摄像头索引")
    ap.add_argument("--no-cam", action="store_true", help="不使用摄像头")
    ap.add_argument("--windowed", action="store_true", help="窗口模式启动（默认全屏）")
    ap.add_argument("--game", default="menu", help="启动后直接进入的游戏 key")
    ap.add_argument("--list", action="store_true", help="列出全部游戏后退出")
    args = ap.parse_args()

    import games  # noqa: F401  导入即完成注册
    from core import base as B

    if args.list:
        print(f"共 {len(B.all_games())} 款游戏：\n")
        print(f"{'key':<12}{'名称':<18}{'分类':<14}{'难度':<6}玩法")
        for c in B.all_games():
            print(f"{c.KEY:<12}{c.TITLE:<18}{c.CATEGORY:<14}{'★' * c.DIFFICULTY:<6}{c.HOW}")
        return 0

    from core.shell import Shell
    shell = Shell(backend=args.backend, cam_index=args.cam, no_cam=args.no_cam,
                  windowed=args.windowed, start_game=args.game)
    shell.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
