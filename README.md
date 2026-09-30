# 体感游戏厅 · Motion Arcade（Android 原生）

摄像头体感游戏厅：**头 / 手即手柄**。用户正对前置摄像头，靠头部平移、抬头、
张嘴与手掌轨迹操控游戏 —— 无需任何外设。

当前唯一主线是 **Android 原生（Kotlin）**：CameraX 取帧 + MediaPipe Tasks
Vision 推理（姿态 33 / 手 21 / 脸 468）+ Canvas 硬件加速自绘。
原 Python/pygame 桌面版已完成使命并移除，逻辑与美术沿用于 Android 端
（git 历史可查）。

## 快速开始

```bash
cd android
./scripts/prepare_assets.sh          # 下载 3 个 MediaPipe 模型(17MB) + 复制/降采样资产
./gradlew assembleDebug              # 产物 app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

技术选型、分层架构、踩坑记录见 [android/README.md](android/README.md)。

## 18 款游戏（已移植 8 / 18）

### 头部控制

| Key | 名称 | 状态 |
|---|---|---|
| `mario` | 超级马里奥 | ✅ 已移植 |
| `football` | 川超 · 点球王 | ✅ 已移植 |
| `tennis` | 川网 · 底线对拉 | ✅ 已移植 |
| `panda_roll` | 熊猫滚滚 | ✅ 已移植 |
| `hotpot` | 火锅大作战 | ✅ 已移植 |
| `ski` | 川西滑雪 | ✅ 已移植 |
| `mask` | 川剧变脸 | 待移植 |
| `climb` | 蜀道攀岩 | 待移植 |
| `lantern` | 自贡灯会 | 待移植 |
| `dino` | 太阳神鸟 | 待移植 |
| `drum` | 蜀韵鼓点 | 待移植 |
| `fishing` | 岷江捕鱼 | 待移植 |

### 手部控制

| Key | 名称 | 状态 |
|---|---|---|
| `slice` | 川果切切 | ✅ 已移植 |
| `shoot` | 手控射箭 | 待移植 |
| `hoop` | 手控投篮 | ✅ 已移植 |
| `handcatch` | 手抓青铜 | 待移植 |
| `balloon` | 熊猫气球 | 待移植 |
| `puzzle` | 蜀绣拼图 | 待移植 |

补移植一个游戏的步骤：在 `android/app/.../game/games/` 新建类继承
[BaseGame]，再到 [GameRegistry] 列表加一行。

## 目标设备

1. **Android 手机**（当前测试档）：任意 arm64 机型，Android 8.0+。
   真机验证：骁龙 8 Gen 3 / HyperOS，三模型全 GPU delegate，头控实测正常。
2. **低成本板卡**（最终档）：如 Amlogic A311D2（Mali-G52 / LPDDR4X），
   届时游戏直接 HDMI 出图。已完成裁剪：ABI 只留 `arm64-v8a`、精灵/背景
   白名单打包、release 配 R8，debug APK 33.6MB。

**手机当"处理+摄像头"设备投屏**：无需改代码，游戏是全屏渲染，任何镜像
通道都可用。电脑端用 `scrcpy -s <ip>:5555 --no-control`（约 50–100ms 延迟，
可再接电视）；电视端用系统自带投屏（Miracast）。

## 运行期资产约定

模型（.task）与图片资产不入库，由 `android/scripts/prepare_assets.sh`
在首次构建前生成；精灵与背景来自 `assets/`（仓内素材池），按**白名单**
只打包已移植游戏用到的部分——移植新游戏时记得补白名单。
