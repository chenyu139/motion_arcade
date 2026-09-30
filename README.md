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

## 7 款精选游戏

选品标准：**交互体验好 + 四川文化特色鲜明**，双达标才上架——动词取自文化动作
本身（变脸=手扫过脸、鼓点=握拳下砸、火锅=低头捞、挥拍=手臂横扫），主题就是
四川符号。不达标的游戏（无文化属性的通用玩法）直接不进大厅。

| 游戏 | 输入 | 动词（文化动作即操作） |
|---|---|---|
| `mask` 川剧变脸 | 手控 | **手掌扫过脸=变脸**，匹配目标脸谱 |
| `drum` 蜀韵鼓点 | 手控 | **握拳下砸=击鼓**，跟川剧锣鼓点（含音频延迟校准） |
| `hotpot` 火锅大作战 | 头控 | 头部移动筷子 · **低头=下筷**（头就是筷子） |
| `football` 川超·点球王 | 头控 | 头部瞄准死角 · 点头起脚 |
| `tennis` 川网·底线对拉 | 头+手 | 头部跑位 · **手掌横扫=挥拍** |
| `panda_roll` 熊猫滚滚 | 头控 | 转头换道躲障碍（熊猫·三星堆） |
| `slice` 川果切切 | 手控 | 挥手劈四川水果，切到花椒扣分 |

补一款新游戏：`game/games/` 新建类继承 [BaseGame] → [GameRegistry] 列表加一行；
同样按选品标准过一遍再上。

## 目标设备

1. **Android 手机**（当前测试档）：任意 arm64 机型，Android 8.0+。
   真机验证：骁龙 8 Gen 3 / HyperOS，三模型全 GPU delegate，头控实测正常。
2. **低成本板卡**（最终档）：如 Amlogic A311D2（Mali-G52 / LPDDR4X），
   届时游戏直接 HDMI 出图。已完成裁剪：ABI 只留 `arm64-v8a`、精灵/背景
   白名单打包、release 配 R8，debug APK 33.6MB。
   检测到外接显示时相机自动切后置镜头，并锁定 AE/AWB/AF（对标游戏机摄像头
   的稳定成像）；热节流/推理吃紧时自动降档（分析跳帧 + 渲染 30fps）。

**手机当"处理+摄像头"设备投屏**：无需改代码，游戏是全屏渲染，任何镜像
通道都可用。电脑端用 `scrcpy -s <ip>:5555 --no-control`（约 50–100ms 延迟，
可再接电视）；电视端用系统自带投屏（Miracast）。

## 运行期资产约定

模型（.task）与图片资产不入库，由 `android/scripts/prepare_assets.sh`
在首次构建前生成；精灵与背景来自 `assets/`（仓内素材池），按**白名单**
只打包已移植游戏用到的部分——移植新游戏时记得补白名单。
