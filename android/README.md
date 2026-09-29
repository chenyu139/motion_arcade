# Motion Arcade · Android 端

把 Python/pygame 的摄像头体感游戏厅迁移到 Android 的原生实现。

## 一、技术选型：为什么是原生 Kotlin，而不是让 Python 直接跑在 Android 上

这是本次迁移最关键的决策，先把事实摆清楚。

### 三个候选方案的实际边界

| 方案 | 能否跑 pygame 渲染 | 摄像头 | ML 推理 | 结论 |
|---|---|---|---|---|
| **Chaquopy**（嵌入式 CPython） | ❌ 不提供 SDL 窗口系统，pygame 拿不到 surface | 需自己写原生再桥接 | 需自己写原生 | 只能当"算法库"，撑不起游戏主循环 |
| **p4a / Buildozer + pygame**（真·Python 跑 Android） | ⚠️ 能跑，但 recipe 自述 *"untested… freetype, portmidi, libjpeg **not part of the build**. It's usable, but not complete"* | ❌ `cv2.VideoCapture` 在 Android 拿不到画面，必须用 pyjnius 调 CameraX | ❌ MediaPipe pip 包是桌面编译版，Android 跑不了 | 能跑起来，但不是工业级 |
| **原生 Kotlin + MediaPipe + CameraX**（本方案） | ✅ Canvas 硬件加速 | ✅ CameraX | ✅ MediaPipe Tasks | ✅ 全链路官方支持 |

### 决定性的三个点

1. **freetype 缺失是致命的**。p4a 的 pygame recipe 明确不含 freetype，而本项目
   HUD、菜单、提示条重度依赖**中文文字渲染**。没有它，界面直接废掉。
2. **摄像头和 ML 这两块在任何方案里都必须写原生**。
   Python 的 `cv2.VideoCapture` 在 Android 上拿不到画面；MediaPipe 的 pip 包是桌面编译的。
   也就是说"直接跑 Python"省掉的只有游戏逻辑 —— 而这部分恰恰是最容易机械翻译的
   （pygame 的 `draw.circle/rect/line/polygon/blit` 与 Android Canvas 一一对应）。
3. **构建链脆弱性**。p4a 在 2026 年仍需锁 Python 3.11（3.12 删了 distutils 会炸 recipe）
   + Cython<3.0（3.0 删了 `longintrepr.h`）+ 手工 sanitize 编译器 flags。

### 最终技术栈（全部是 Google 官方 / 正式版）

| 层 | 选型 | 版本 | 说明 |
|---|---|---|---|
| 语言 | Kotlin | 2.2.21 | — |
| 构建 | AGP + Gradle | 8.13.2 / 8.13 | compileSdk 36（CameraX 1.6.2 要求 ≥36） |
| 相机 | **CameraX**（Jetpack） | 1.6.2 | ImageAnalysis，RGBA_8888，KEEP_ONLY_LATEST |
| 姿态/手/脸 | **MediaPipe Tasks Vision** | **1.0.0**（正式版） | Pose 33 点 / Hand 21 点 / Face 468 点，GPU delegate |
| 渲染 | **Android Canvas**（HWUI 硬件加速） | — | 对应 pygame 的绘制 API |
| 模型 | pose/hand/face landmarker `.task` | 共 16.6MB | 打包在 `assets/models/` |

---

## 二、架构分层

```
MainActivity（权限 / 窗口 / 生命周期）
        │
        ▼
GameSurfaceView ── 独立渲染线程 60fps，1920×1080 设计坐标 → 屏幕等比 contain 映射
        │
        ├─ 场景机： menu（大厅） → game → result → menu
        │
        ├─ vision/    CameraManager(CameraX) → LandmarkerHub(MediaPipe) → VisionPipeline → GameInput
        │
        ├─ render/    Canvas2D（绘制封装） / SpriteManager（精灵） / BackgroundManager（背景）
        │
        ├─ game/      BaseGame（基类+粒子+屏震） / GameRegistry / games/（5 款）
        │
        └─ ui/        Menu（大厅）
```

**线程模型**：渲染跑独立线程；CameraX 的 analyzer 用单线程 executor（保证 MediaPipe
LIVE_STREAM 的时间戳单调）；两者通过 `GameInput` 这个共享可变对象交换数据（60fps 下
不产生垃圾，避免 GC 造成操作顿挫）。

---

## 三、Python → Kotlin 模块对照表

| Python 端 | Android 端 | 说明 |
|---|---|---|
| `core/config.py` | `game/Design` | 设计坐标系常量（1920×1080 / HUD 112 / 提示条 56） |
| `core/base.py` | `game/BaseGame` | `reset / update / draw` 三接口 + 粒子/屏震/闪白 |
| `core/inputs.py`（GameInput） | `vision/GameInput` | **契约逐字段对齐** |
| `core/inputs.py`（OneEuro/RateLimiter） | `vision/OneEuroFilter` | 自适应滤波，参数对齐 |
| `core/tracker.py` + `core/vision/*` | `vision/CameraManager` + `LandmarkerHub` + `VisionPipeline` | 相机 + MediaPipe + 校准/滤波/边沿 |
| `core/vision/types.py` | `vision/Landmarks` | Joint / HandState / PoseFrame（COCO-17） |
| `core/theme.py`（颜色/缓动） | `render/Col` + `render/Num` | shade / mix / clamp / smoothK |
| pygame 绘制 API | `render/Canvas2D` | circle / rect / roundRect / line / polygon / arc / blit / text |
| `core/sprites.py` | `render/SpriteManager` | 缺图回退 + 降采样缓存 + 色相派生 |
| `core/scene.py`（sky_img/sky_or） | `render/BackgroundManager` | cover 适配 + 三段渐变兜底 |
| `core/menu.py` | `ui/Menu` | 卡片网格，触摸 + 头部双通道选择 |
| `core/shell.py`（主循环） | `game/GameSurfaceView.loop()` | 固定帧率对齐 + dt 上限保护 |

### GameInput 契约（两端一致）

- 头部：`axis`(-1~1 水平) / `up`(0~1 抬头) / `headY`(-1~1) / `yaw` / `jump` / `mouth`
- 手部：`handFound` / `hx`,`hy` / `handOpen` / `fingers` / `pinch`（边沿）/ `release`（边沿）/ `grabHold`
- 全身：`bodyX` / `crouch` / `armL` / `armR` / `armLExt` / `armRExt`
- 质量：`confidence` / `quality` / `hint`

---

## 四、"手感"是怎么保证的

这几条是体感游戏的命门，两条端都按同一套实现：

1. **中性位校准**：正脸对着镜头时读数并不为 0，进游戏先采样 24 帧记下中性位，
   之后所有控制量都是"相对中性位"的偏移。没有它，玩家得歪着头才能保持不动。
2. **尺度归一**：位移一律除以眼距/肩宽，坐得远的人和坐得近的人得到相同的控制量。
3. **One Euro 滤波**：静止时压抖动、快速动时保持跟手（普通 EMA 做不到二者兼得）。
4. **边沿量不丢帧**：检测约 20~30fps、渲染 60fps，捏合/张开用 pending 标志过渡，
   保证每个边沿**恰好被消费一次**。
5. **按需启停检测器**：头控游戏不跑手部模型，手控游戏不跑姿态模型（省算力、降发热）。

---

## 五、已移植的游戏（首轮 5 款，覆盖两类输入通道）

| 游戏 | 输入 | 玩法 | 状态 |
|---|---|---|---|
| `mario` 超级马里奥 | 头控 | 横版平台跳跃，吃金币踩敌人 | ✅ 物理常量逐项对齐 Python 端 |
| `panda_roll` 熊猫滚滚 | 头控 | 三星堆伪 3D 管道跑酷，三车道 | ✅ 透视曲线与 Python 端同一条 |
| `ski` 川西滑雪 | 头控 | S 形雪道速降，穿旗门 | ✅ |
| `slice` 川果切切 | 手控 | 挥手劈果，速度不够切不开 | ✅ 保留"挥砍速度"判定 |
| `hoop` 手控投篮 | 手控 | 握拳蓄力、掌心定弧线、张开出手 | ✅ |

**待补（13 款）**：football / tennis / hotpot / mask / climb / lantern / dino / drum /
fishing / handcatch / balloon / shoot / puzzle。
补充方式：在 `game/games/` 新建类继承 `BaseGame`，在 `GameRegistry.createAll` 加一行即可，
菜单、输入通���、按需启停全部自动生效。

---

## 六、构建与运行

### 环境要求
- JDK 17+（本项目用 JDK 21）
- Android SDK：platform **android-36** + build-tools 36（CameraX 1.6.2 要求 compileSdk ≥36）
- 真机（前置摄像头 + Android 8.0/API 26 以上）。模拟器可能没有可用前置摄像头。

### 首次构建前：准备资产
运行期资产（模型 17MB + 图 16MB）**不入库**，由脚本从官方地址下载 + 从项目
`assets/` 复制并降采样生成：
```bash
cd android && ./scripts/prepare_assets.sh
```

### 构建
```bash
cd android
./gradlew :app:assembleDebug      # 或 gradle :app:assembleDebug
```
产物：`app/build/outputs/apk/debug/app-debug.apk`（当前约 54MB）

### 安装
```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

### 首次运行
授权摄像头 → 进入大厅 → 正对镜头保持不动约 0.4 秒完成校准 → 点卡片（或用头左右转选择、抬头确认）进入游戏。

---

## 七、体积与性能

当前 debug APK ≈ 54MB，构成：
- MediaPipe native `.so`（arm64-v8a / armeabi-v7a / x86_64）≈ 30MB
- 三个 landmarker 模型 ≈ 17MB
- 精灵 30 张（已降到 512px）≈ 8MB
- 背景 11 张（bevouliin 降到 1920 宽，绘制天空降到 1280 宽）≈ 8MB

**发布时建议**：
- ABI 只保留 `arm64-v8a` + `armeabi-v7a`（去掉 x86_64 可省约 14MB）；
- 改用 App Bundle（`.aab`）让商店按设备下发；
- 精灵层已按 512px 上限降采样并缓存，避免 30 张 1024 PNG 全量解码（那会 ≈120MB，中低端机直接 OOM）。

---

## 八、已知限制与后续项

1. **只在真机验证过构建与静态检查**，尚未在真机跑通完整手感（需要你装到手机上实测）。
   校准阈值（AXIS_RANGE / PITCH_RANGE / JUMP_UP / PINCH_ON 等）可能需要按真机微调。
2. **GPU delegate 有 CPU 兜底**：部分设备 GPU 初始化会失败，代码里已自动降级。
3. 大厅菜单目前是首轮 5 款的网格；补齐 13 款后需确认布局（现为 3 列）。
4. 未做：音效（`core/sfx.py`）、完整 HUD 外壳、结算统计持久化。
