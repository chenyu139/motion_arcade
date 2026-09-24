#!/usr/bin/env bash
#
# build_app.sh — 打包 MotionArcade.app
# ====================================
# 做四件事：
#   1. 确保项目内有 .venv 并装好依赖
#   2. 用 clang 编译 Mach-O 启动器（不能是 shell 脚本，否则会丢掉签名身份）
#   3. 组装 .app 包结构 + Info.plist
#   4. ad-hoc 签名（TCC 要求必须有签名，哪怕不公证）
#
# 关于摄像头授权：
#   TCC 授权绑定的是**二进制指纹**，所以每次重新编译启动器都要重新授权一次。
#   因此：只改 Python 代码时**不要**重跑本脚本 —— .app 里封印的是启动器，
#   Python 源码在包外，改了不影响签名有效性（可用 codesign --verify 确认）。
#
# 用法：
#   ./packaging/build_app.sh              正常构建
#   RESET_TCC=1 ./packaging/build_app.sh  额外清掉旧授权记录，强制重新弹窗
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
APP="$ROOT/MotionArcade.app"
BUNDLE_ID="cn.sichuan.motionarcade"
PY_BOOT="${PY_BOOT:-/Users/chenyu/.workbuddy/binaries/python/versions/3.13.12/bin/python3}"

cd "$ROOT"
echo "[build] 项目目录：$ROOT"

# ---------------------------------------------------------------- 1. 虚拟环境
if [ ! -x "$ROOT/.venv/bin/python" ]; then
    echo "[build] 创建 .venv …"
    if [ -x "$PY_BOOT" ]; then
        "$PY_BOOT" -m venv "$ROOT/.venv"
    else
        python3 -m venv "$ROOT/.venv"
    fi
fi
echo "[build] 安装依赖 …"
"$ROOT/.venv/bin/python" -m pip install -q --disable-pip-version-check \
    -r "$ROOT/requirements.txt"

# ---------------------------------------------------------------- 2. 编译启动器
echo "[build] 编译 Mach-O 启动器 …"
mkdir -p "$ROOT/build"
clang -fobjc-arc -O2 -framework Foundation -framework AVFoundation \
      -o "$ROOT/build/MotionArcade" "$HERE/launcher.m"
file "$ROOT/build/MotionArcade" | sed 's/^/[build] /'

# ---------------------------------------------------------------- 3. 组装 .app
echo "[build] 组装 App 包 …"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$ROOT/build/MotionArcade" "$APP/Contents/MacOS/MotionArcade"
chmod +x "$APP/Contents/MacOS/MotionArcade"
cp "$HERE/Info.plist" "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"

# ---------------------------------------------------------------- 4. 签名
echo "[build] ad-hoc 签名 …"
codesign --force --deep --sign - "$APP" 2>&1 | sed 's/^/[build] /' || true
codesign --verify --verbose=1 "$APP" 2>&1 | sed 's/^/[build] /' || true

if [ "${RESET_TCC:-0}" = "1" ]; then
    echo "[build] 清除旧的摄像头授权记录（下次启动会重新弹窗）…"
    tccutil reset Camera "$BUNDLE_ID" 2>/dev/null || true
fi

echo
echo "[build] 完成。启动："
echo "        open \"$APP\""
echo "        日志：$ROOT/run.log"
echo
echo "提示：只改 Python 代码时无需重新构建，直接 open 即可。"
