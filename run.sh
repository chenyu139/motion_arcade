#!/usr/bin/env bash
#
# run.sh — 直接运行（不打包 App）
#
# 适合开发调试：日志直接打在终端上。
# 注意：这种方式启动时，摄像头授权会归到「终端/IDE」名下，
#       而它们通常没有 NSCameraUsageDescription，macOS 会**静默拒绝**。
#       需要在真机上用摄像头，请改用 open MotionArcade.app。
#
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -x ".venv/bin/python" ]; then
    echo "[run] 没有找到 .venv，先执行：./packaging/build_app.sh"
    exit 1
fi

exec .venv/bin/python main.py "$@"
