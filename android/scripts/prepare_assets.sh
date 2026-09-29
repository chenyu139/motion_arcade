#!/usr/bin/env bash
#
# 准备 Android 端运行所需的资产：MediaPipe 模型 + 精灵 + 背景。
#
# 为什么用脚本而不是把资产直接提交进仓库：
#   · 三个模型 17MB、精灵+背景 16MB，全量入库会让仓库平白胖 30MB+，
#     而它们要么能从官方地址下载、要么在项目 assets/ 里已经有一份；
#   · 与本项目一贯约定一致（MediaPipe .task 模型、截图、构建产物都不入库）。
# 所以 clone 之后、首次构建之前，先跑一次这个脚本。
#
# 用法：  cd android && ./scripts/prepare_assets.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_ASSETS="$(cd "$ROOT/../assets" && pwd)"          # Python 端的美术资产
DST="$ROOT/app/src/main/assets"
MODELS_URL="https://storage.googleapis.com/mediapipe-models"

mkdir -p "$DST/models" "$DST/sprites" "$DST/bg"

# ---------------------------------------------------------------- 1) 模型
echo "==> 下载 MediaPipe landmarker 模型"
dl() {   # dl <url> <out>
    if [ -s "$2" ]; then echo "    已存在，跳过：$(basename "$2")"; return; fi
    echo "    $(basename "$2")"
    curl -fsSL --retry 2 --max-time 180 "$1" -o "$2"
}
dl "$MODELS_URL/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task" \
   "$DST/models/pose_landmarker_lite.task"
dl "$MODELS_URL/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task" \
   "$DST/models/hand_landmarker.task"
dl "$MODELS_URL/face_landmarker/face_landmarker/float16/1/face_landmarker.task" \
   "$DST/models/face_landmarker.task"

# ---------------------------------------------------------------- 2) 精灵
# 游戏里单个精灵最大也就显示 200px 左右，1024 的原图纯属浪费：
# 30 张全量解码 ≈120MB，中低端机直接 OOM。这里统一压到 512。
echo "==> 复制并降采样精灵（原图 1024 → 512）"
if [ -d "$SRC_ASSETS/sprites" ]; then
    for f in "$SRC_ASSETS"/sprites/*.png; do
        [ -e "$f" ] || continue
        out="$DST/sprites/$(basename "$f")"
        cp "$f" "$out"
        sips -Z 512 "$out" >/dev/null 2>&1 || true
    done
else
    echo "    警告：未找到 $SRC_ASSETS/sprites，精灵将缺失（代码会自动回退到矢量画法）"
fi

# ---------------------------------------------------------------- 3) 背景
# bevouliin 视差背景是 3072×1536，压到 1920 宽足够全屏；
# 程序绘制的天空是 1536×1024，压到 1280 宽。
echo "==> 复制并降采样背景"
if [ -d "$SRC_ASSETS/bg" ]; then
    for f in "$SRC_ASSETS"/bg/*.png; do
        [ -e "$f" ] || continue
        name="$(basename "$f")"
        out="$DST/bg/$name"
        cp "$f" "$out"
        case "$name" in
            bg_bev_*) sips --resampleWidth 1920 "$out" >/dev/null 2>&1 || true ;;
            *)        sips --resampleWidth 1280 "$out" >/dev/null 2>&1 || true ;;
        esac
    done
else
    echo "    警告：未找到 $SRC_ASSETS/bg，背景将走渐变兜底"
fi

echo ""
echo "==> 完成"
du -sh "$DST/models" "$DST/sprites" "$DST/bg" 2>/dev/null || true
echo "现在可以构建： cd $ROOT && ./gradlew :app:assembleDebug"
