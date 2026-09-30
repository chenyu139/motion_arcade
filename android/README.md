# Motion Arcade · Android 端

摄像头体感游戏厅的 Android 原生实现：**头 / 手即手柄**，CameraX 取帧 +
MediaPipe 推理 + Canvas 硬件加速自绘。技术栈全部是 Google 官方正式版：

| 层 | 选型 | 说明 |
|---|---|---|
| 语言 / 构建 | Kotlin 2.2 / AGP 8.13 / Gradle 8.13 | compileSdk 36（CameraX 1.6.2 要求 ≥36） |
| 相机 | **CameraX** 1.6.2 | ImageAnalysis，RGBA_8888，KEEP_ONLY_LATEST，只用分析流不绑 Preview |
| ML | **MediaPipe Tasks Vision** 1.0.0 | Pose 33 / Hand 21 / Face 468，GPU delegate + CPU 运行时降级 |
| 渲染 | Android Canvas（HWUI） | 1920×1080 设计坐标，独立渲染线程 60fps |
| 音效 | 程序合成（AudioTrack） | 零音频资产，连击音高可联动 |

历史决策记录（为什么是原生 Kotlin 而不是 Python 跑 Android、p4a 的 freetype 缺陷等）
见 git 历史中的旧版 README。

## 架构分层

```
MainActivity（权限 / 窗口 / 生命周期，刻意保持很薄）
        │
        ▼
GameSurfaceView ── 独立渲染线程 60fps，设计坐标 → 屏幕等比 contain 映射
        │
        ├─ 场景机： menu（大厅） → game → result → menu
        │
        ├─ vision/    CameraManager(CameraX) → LandmarkerHub(MediaPipe) → VisionPipeline → GameInput
        │
        ├─ render/    Canvas2D（绘制封装） / SpriteManager（精灵） / BackgroundManager（背景）
        │
        ├─ game/      BaseGame（基类+粒子+屏震+闪白） / GameRegistry / games/（8 款）
        │
        └─ ui/        Menu（大厅，触摸 + 头部双通道选择）
```

**线程模型**：渲染独立线程；CameraX analyzer 用单线程 executor（保证 MediaPipe
LIVE_STREAM 时间戳单调）；两者通过 `GameInput` 共享可变对象交换数据（60fps 零分配，
避免 GC 顿挫）。

**MediaPipe 串行化（踩过坑）**：landmarker 的创建/释放（主线程）与推理提交（相机线程）
必须经 `LandmarkerHub.mpLock` 串行 —— 否则 `close()` 落在在飞推理上，原生层直接
SIGSEGV。GPU→CPU 降级重建也必须在推理线程内做。

## GameInput 契约

- 头部：`axis`(-1~1 水平) / `up`(0~1 抬头) / `headY`(-1~1) / `yaw` / `jump` / `mouth`
- 手部：`handFound` / `hx`,`hy` / `handOpen` / `fingers` / `pinch`（边沿）/ `release`（边沿）/ `grabHold`
- 全身：`bodyX` / `crouch` / `armL` / `armR` / `armLExt` / `armRExt`
- 质量：`confidence` / `quality` / `hint`

## 手感五原则

1. **中性位校准**：进游戏采样 24 帧记中性位，控制量全是"相对偏移"。
2. **尺度归一**：位移除以眼距/肩宽，坐远坐近手感一致。
3. **One Euro 滤波**：静止压抖、快动跟手。
4. **边沿量不丢帧**：pending 标志过渡，捏合/张开恰好消费一次。
5. **按需启停检测器**：头控游戏不跑手部模型，反之亦然（省算力降发热）。

## 游戏（8 / 18）

| 游戏 | 输入 | 玩法 |
|---|---|---|
| `mario` 超级马里奥 | 头控 | 横版平台跳跃，吃金币踩敌人 |
| `football` 川超·点球王 | 头控 | 头部瞄准死角，抬头起脚，10 球进 6 |
| `tennis` 川网·底线对拉 | 头控 | 跑位挥拍，拍面与球的距离定完美/良好/勉强 |
| `panda_roll` 熊猫滚滚 | 头控 | 三星堆伪 3D 管道跑酷，三车道 |
| `hotpot` 火锅大作战 | 头控 | 移动筷子捞指定食材，辣椒扣命 |
| `ski` 川西滑雪 | 头控 | S 形雪道速降，穿旗门加分 |
| `slice` 川果切切 | 手控 | 挥手劈果，速度不够切不开 |
| `hoop` 手控投篮 | 手控 | 握拳蓄力、掌心定弧线、张开出手 |

**待补 10 款**：mask / climb / lantern / dino / drum / fishing / handcatch /
balloon / shoot / puzzle。补法：`game/games/` 新建类继承 `BaseGame` →
`GameRegistry.games` 列表加一行 → `prepare_assets.sh` 的 SPRITES 白名单补精灵名。

## 构建与运行

```bash
cd android
./scripts/prepare_assets.sh        # 首次构建前：下载 3 个模型(17MB) + 白名单复制/降采样资产
./gradlew :app:assembleDebug       # 产物约 33.6MB
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

- 环境：JDK 17+，Android SDK platform 36。
- 依赖解析走阿里云镜像（`settings.gradle.kts`）——本机直连 Maven Central 的 TLS 会被掐。
- `gradlew` 是 shell 薄封装：优先用 `~/gradle-dist/gradle-8.13`，缺失时 curl 下载。

## 面向低成本设备的既定裁剪

目标设备两档：Android 手机（测试档）→ Amlogic A311D2 级板卡（Mali-G52 /
LPDDR4X，最终档）。已完成：

- **ABI 只留 `arm64-v8a`**（armeabi-v7a / x86_64 各约 9MB 的 .so 已去掉）；
- **精灵/背景白名单**：只打包已移植游戏用到的资产（运行期 15.8MB → 6.1MB）；
- 精灵统一 512px 上限降采样（全量 1024 解码 ≈120MB，中低端机会 OOM）；
- release 构建已配 R8 + 资源收缩（`proguard-rules.pro`）。

**真机/板卡注意**：

- GPU delegate 在部分设备上初始化成功但推理报 GL 错误，代码已运行时降级 CPU；
  模拟器（swiftshader GL 不完整）直接走 CPU。
- 校准阈值（`VisionPipeline` 里 AXIS_RANGE / PITCH_RANGE / JUMP_UP / PINCH_ON）
  换设备类要实测微调。
- 屏幕常亮由 manifest `keepScreenOn` 保证；投屏场景（scrcpy `--no-control` 或
  系统投屏）下游戏照常运行，手机当"处理+摄像头"设备、外部屏幕当显示。
- HyperOS/MIUI：adb 注入输入事件被拦（`input tap`、scrcpy 控制均不可用），
  需开「USB 调试（安全设置）」；`pm grant` 授权同理。

## 已知限制与后续项

1. 模拟器端到端 8/8 通过；真机（骁龙 8 Gen 3 / HyperOS）头控实测正常。
2. 结算统计持久化未做。
3. 补齐 18 款后确认大厅布局（现 3 列网格，触摸 + 头部双通道）。
