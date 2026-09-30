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

# sprites/bg 整目录重建：白名单之外的旧文件不留存（模型目录只增不删）
rm -rf "$DST/sprites" "$DST/bg"
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
# 白名单制：只打包已移植游戏用到的精灵。仓库 assets/sprites 是全部 32 张的
# 素材池（供后续游戏移植），运行期没必要带着用不到的图。
#   · 单个精灵最大也就显示 200px 左右，统一压到 512（原图 1024）；
#   · 缺图时代码会自动回退到矢量画法，不会崩。
# **移植新游戏时**：把新游戏用到的精灵名加进 SPRITES，再重跑本脚本。
# 当前归属：mario(panda_hero/panda_curl/coin/enemy) panda_roll(sanxingdui/
# bronze/bronze_tree) slice(fruit 六件) hoop(basketball) football(football)
# tennis(tennis_ball) mask(mask 五张)；hotpot/ski/drum 纯程序绘制，无精灵。
SPRITES=(
    panda_hero panda_curl coin enemy
    sanxingdui bronze bronze_tree
    fruit kiwi peach watermelon loquat pepper
    basketball football tennis_ball
    mask_red mask_gold mask_green mask_black mask_blue
)
echo "==> 复制并降采样精灵（原图 1024 → 512，白名单 ${#SPRITES[@]} 张）"
if [ -d "$SRC_ASSETS/sprites" ]; then
    copied=0
    for name in "${SPRITES[@]}"; do
        src="$SRC_ASSETS/sprites/$name.png"
        if [ ! -e "$src" ]; then
            echo "    警告：精灵不存在 $name.png（将回退矢量画法）"
            continue
        fi
        out="$DST/sprites/$name.png"
        cp "$src" "$out"
        sips -Z 512 "$out" >/dev/null 2>&1 || true
        copied=$((copied+1))
    done
    echo "    已复制 $copied 张"
else
    echo "    警告：未找到 $SRC_ASSETS/sprites，精灵将缺失（代码会自动回退到矢量画法）"
fi

# ---------------------------------------------------------------- 3) 背景
# 同样白名单制：menu(bg_bev_mist) mario(bg_bev_game) ski(bg_bev_mountain)
# hotpot 菜馆内景(sky_teahouse)。其余素材池背景等对应游戏移植时再加。
# bevouliin 视差背景 3072×1536 → 1920 宽；程序绘制天空 1536×1024 → 1280 宽。
BGS=(bg_bev_mist bg_bev_game bg_bev_mountain sky_teahouse)
echo "==> 复制并降采样背景（白名单 ${#BGS[@]} 张）"
if [ -d "$SRC_ASSETS/bg" ]; then
    for name in "${BGS[@]}"; do
        src="$SRC_ASSETS/bg/$name.png"
        if [ ! -e "$src" ]; then
            echo "    警告：背景不存在 $name.png（将走渐变兜底）"
            continue
        fi
        out="$DST/bg/$name.png"
        cp "$src" "$out"
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
