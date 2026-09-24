# 体感游戏厅 · Motion Arcade

用 **摄像头** 控制的小游戏合集，共 **20 款**。支持三层输入：

| 层级 | 内容 | 需要的后端能力 |
|---|---|---|
| 头部 | 左右平移 / 抬头 / 转头 | 只要有张脸就行（最稳） |
| 手部 | 掌心位置 + 21 关键点（捏合、握拳、伸出手指数、指向） | 手部关键点模型 |
| 全身 | COCO-17 骨骼：身体横移、下蹲、举手、抬臂、抬腿 | 人体姿态模型（需上半身入镜） |

**跨平台**：视觉层是多后端的，Mac 上用 Apple Vision（ANE 加速），
Windows / Linux 上用 MediaPipe 或 ONNX Runtime，游戏代码完全不用改。

```
open MotionArcade.app        # 全屏启动，进入游戏大厅
```

---

## 目录

- [快速开始](#快速开始)
- [20 款游戏](#20-款游戏)
- [视觉架构（跨平台）](#视觉架构跨平台)
- [操作方式](#操作方式)
- [全身体感怎么用](#全身体感怎么用)
- [显示与分辨率](#显示与分辨率)
- [工程结构](#工程结构)
- [性能](#性能)
- [已知限制](#已知限制)
- [踩过的坑（重要）](#踩过的坑重要)

---

## 快速开始

```bash
cd motion_arcade

# 1) 打包 App（会自建 .venv、装依赖、编译启动器、ad-hoc 签名）
./packaging/build_app.sh

# 2) 启动
open MotionArcade.app

# 3) 看日志（.app 没有终端，日志落在 run.log）
tail -f run.log
```

只改了 `.py` 代码时**不需要重新构建**：`.app` 里封印的只是启动器，
Python 源码在包外，改完直接 `open` 即可（可用 `codesign --verify MotionArcade.app` 确认签名仍有效）。

开发调试可以直接跑（但摄像头授权会归到终端名下，见下文）：

```bash
./run.sh                 # 全屏
./run.sh --windowed      # 窗口模式
./run.sh --no-cam        # 不用摄像头，鼠标模拟手部
./run.sh --game mario    # 直接进某个游戏
./run.sh --list          # 列出全部游戏
```

命令行参数：

| 参数 | 说明 |
|---|---|
| `--windowed` | 窗口模式启动（默认全屏） |
| `--no-cam` | 不用摄像头；鼠标位置映射手部，按住左键 = 握拳 |
| `--game KEY` | 启动后直接进入指定游戏（如 `mario`） |
| `--cam N` | 指定摄像头索引，默认 0 |
| `--backend auto\|mediapipe` | 人脸检测后端；`mediapipe` 额外给"张嘴"触发（本机不可用，见下） |
| `--list` | 打印全部游戏后退出 |

---

## 20 款游戏

### 头部控制（12 款）

| Key | 名称 | 主题 | 玩法 | 难度 |
|---|---|---|---|---|
| `mario` | 超级马里奥 | 横版平台跳跃 | 踩着敌人往右冲到旗杆，别掉坑 | ★★ |
| `football` | 川超 · 点球王 | 四川省城市足球联赛 | 瞄准死角，抬头起脚，10 球进 6 球 | ★★ |
| `tennis` | 川网 · 底线对拉 | 四川城市网球联赛 | 跑到位、抬头挥拍，先到 5 分 | ★★ |
| `panda_roll` | 熊猫滚滚 | 三星堆管道疾走 | 伪 3D 换道躲障碍，越跑越快 | ★★★ |
| `hotpot` | 火锅大作战 | 红油锅 | 按提示捞指定食材，别夹到辣椒 | ★★ |
| `mask` | 川剧变脸 | 川剧 | 挑中同一张脸谱，越答越快 | ★★ |
| `ski` | 川西滑雪 | S 形雪道 | 跟着雪道走，别撞树，穿旗门加分 | ★★ |
| `climb` | 蜀道攀岩 | 剑门关崖壁 | 挪到抓点下方抬头抓，别被碎石砸中 | ★★★ |
| `lantern` | 自贡灯会 | 彩灯记忆 | 记住灯笼亮起的顺序并复现 | ★★★ |
| `dino` | 太阳神鸟 | 金沙遗址 | 抬头扇翅穿金杖立柱（Flappy 式） | ★★★ |
| `drum` | 蜀韵鼓点 | 节奏打击 | 音符落到判定线时击鼓 | ★★★ |
| `fishing` | 岷江捕鱼 | 撒网 | 把网撒到鱼群上，垃圾别捞 | ★★ |

### 手部控制（6 款）

| Key | 名称 | 玩法 | 难度 |
|---|---|---|---|
| `handcatch` | 手抓青铜 | 张开手掌接住落下的青铜器，握拳会打飞 | ★★ |
| `balloon` | 熊猫气球 | 用手掌把气球拍回空中，落地就丢命 | ★★ |
| `slice` | 川果切切 | 手掌快速划过水果才能切开，别切花椒 | ★★ |
| `shoot` | 手控射箭 | 移动手掌瞄准，握拳放箭，靶心 100 分 | ★★ |
| `hoop` | 手控投篮 | 掌心高度定弧线，握拳蓄力，张开出手 | ★★ |
| `puzzle` | 蜀绣拼图 | 握拳抓起绣片，拖到正确位置松开 | ★★ |

### 头部 + 手部（2 款）

| Key | 名称 | 玩法 | 难度 |
|---|---|---|---|
| `duel` | 双线太极 | 上面用头、下面用手，两条线同时躲障碍 | ★★★ |
| `keeper` | 双人守门 | 头管左门将、手管右门将，20 球扑出 12 个 | ★★★ |

---

## 操作方式

### 通用

- **校准**：进入任何游戏的瞬间会自动采集 24 帧建立"中性位"（你正常的坐姿），
  所以不用刻意坐正。想重新校准按 `C`。
- **头部水平平移** → 横向控制（带 ±6% 死区与指数平滑，避免抖动）
- **抬头** → 动作键（跳 / 射门 / 挥拍 / 击鼓 / 扇翅…）
- **头部转向** → 部分游戏用于细腻瞄准（由鼻尖相对眼线的偏移估计）
- **键盘随时可用且优先级更高**（`←→/AD` 移动，`空格/↑/W` 动作），现场演示的保命手段。

### 游戏内快捷键

| 键 | 作用 |
|---|---|
| `ESC` | 返回大厅（在大厅里则退出） |
| `R` | 重开本局 |
| `C` | 重新校准中性位 |
| `P` | 暂停 |
| `H` | 显示/隐藏摄像头预览 |
| `TAB` | 直接切换到下一个游戏 |
| `F11` / `F` | 切换全屏 |

### 大厅

- 头部左右 → 切卡片（到页边自动翻页）
- 抬头 → 进入；或在卡片上**停留 2.4 秒**自动进入（卡片右下角有进度环）
- 键盘：`←→↑↓` 移动、`回车` 进入、`1-9` 快速选

### 手部

掌心位置直接映射为一个"手心光标"（带 1.3 倍增益，避免"够不到屏幕边缘"），
张开度体现在光标手指的开合上 —— 你一眼就能看出系统有没有正确读到手势。

- **张开手掌**：多数游戏里是"接住 / 稳住"的状态
- **握拳**：`handcatch` 里会打飞器物；`shoot`/`hoop` 里是"放箭 / 蓄力"；`puzzle` 里是"抓起"

---

## 视觉架构（跨平台）

### 为什么是多后端

不同平台上的"主流 SOTA"完全不同，绑死任何一家都会把项目钉死在一个平台上：

| 后端 | 平台 | 人体 | 手部 | 加速 |
|---|---|---|---|---|
| `apple` **Apple Vision** | macOS / iOS | 19 点 | 21 点 | 神经引擎 ANE |
| `mediapipe` MediaPipe Tasks | Win / Linux / Android | 33 点（BlazePose） | 21 点 | TFLite |
| `onnx` ONNX Runtime + RTMPose | **全平台** | 17/133 点 | 21 点 | CoreML / DirectML / CUDA |
| `opencv` 兜底 | 全平台 | 仅头部 | 仅掌心 | CPU |

所以内部定了一套规范（`core/vision/types.py`）：

```
人体  →  COCO-17（业界最通用的 17 关键点）
手部  →  21 点（与 MediaPipe / Vision 一致）
坐标  →  图像归一化，左上原点
```

各后端只负责"把自己的格式翻译成规范"，游戏代码只认规范。
换平台不用改游戏，加平台只要再加一个后端文件。

```bash
python main.py --vision auto        # 默认：按平台自动选
python main.py --vision apple       # 强制 Apple Vision
python main.py --vision mediapipe   # 强制 MediaPipe
python main.py --vision onnx        # 强制 ONNX Runtime
python main.py --list-backends      # 看各后端在当前机器的可用性
python main.py --probe              # 真机跑 20 秒，打印检测率与耗时
```

### 分工：头部交给 YuNet，身体交给姿态模型

实测发现一个反直觉的事实：**人体姿态模型对"坐在桌前只露头肩"的人不友好**。
`VNDetectHumanBodyPoseRequest` 需要看到足够多的身体部位才会出结果，
只露个头时整帧返回空 —— 如果拿它当头部控制的主信号，用户会觉得"突然失灵"。

所以最终是这样分工的：

```
每帧        OpenCV YuNet 人脸检测（7~8ms）
            → 头部位置 / 朝向 / 俯仰。只要有脸就稳。
每 N 帧     core.vision AutoEngine（macOS 上是 Apple Vision）
            → 全身 COCO-17 骨骼 + 手部 21 关键点
```

两者结果合并成统一的 `VisionFrame`，同时兼容旧的 `FaceState / HandState`。

### 按需 + 自适应降频（这是"加了手之后头部变钝"的根治办法）

真机实测：Vision 在**真实图像**上要 **16~29ms/次**（实验室用空白图测只要 8ms，
因为纯色图走了快速路径），而 YuNet 要 7~8ms。两个叠加会把采集线程压到
21~30fps 且抖动，头部控制的手感就是这么坏掉的。

现在改成：

```python
# 1) 按当前游戏的需要决定跑不跑
REQUIRES = ("head",)          → vision_mode = "off"   完全不跑
REQUIRES = ("hand",)          → vision_mode = "hand"  只跑手部
REQUIRES = ("head","body")    → vision_mode = "full"  人体 + 手部

# 2) 连续 5 次检测不到目标就退避，最多拉到 1/12 帧
#    （坐着只露头的人不会白白烧 CPU，一检测到就立刻恢复高频）
```

12 款纯头部游戏现在完全不启动姿态模型 —— CPU 从 90~110% 降回 **77%**。


---

## 全身体感怎么用

### 先确认身体入镜

体感玩法需要**摄像头看到你的上半身**（至少到胸口，下蹲/抬腿类玩法需要看到腰胯）。

```bash
python main.py --probe        # 真机跑 20 秒，日志里会打印：
                              #   cam 28.6fps  脸✓  人体✓(14点)  手1  ...
```

- `人体·( 0点)` = 姿态模型没看到你的身体 → **退后一点**，或把摄像头抬高
- `手 0` = 没看到手 → 把手抬到胸前到面部之间
- 游戏里按 `H` 打开摄像头预览，能看到骨骼火柴人叠在画面上，最直观

### 可用的全身动作原语

`core/vision/types.py` 里的 `PoseFrame` 已经把几何算好了，游戏直接用语义量：

| 属性 | 含义 | 典型用法 |
|---|---|---|
| `body_center` | 身体中心（肩髋中点） | 横移类控制 |
| `body_x`（GameInput） | 身体横移 -1~1，已按肩宽归一 | 左右躲、换道 |
| `crouch` | 下蹲程度 0~1 | 蹲下躲障碍、蓄力 |
| `arm_raised(side)` | 单臂举起 0~1 | 举手答题、拍球、击鼓 |
| `arm_extended(side)` | 单臂伸展 0~1（弯曲↔伸直） | 推、挥、投 |
| `arm_direction(side)` | 手臂指向单位向量 | 瞄准 |
| `hands_up()` | 举起了几只手 | 双手举 = 特殊动作 |
| `arms_spread()` | 双手张开度 | 张开双臂类动作 |
| `leg_lifted(side)` | 抬腿 0~1 | 踢腿（需下半身入镜） |
| `torso_lean` | 躯干侧倾 | 转向、倾斜控制 |
| `head_yaw / head_pitch / head_roll` | 头部转向 / 俯仰 / 倾斜 | 瞄准、点头 |

所有量都经过 **中性位校准 + 身体尺度归一**（除以肩宽），
所以个子高矮、离摄像头远近都不会改变手感。

### 姿态参数化的美术

`core/art.py` 的人物是**骨架驱动**的：给一组关节角度就能画出跑、跳、
挥拍、扑救、踢球等动作，不需要为每个动作单独做素材。

```python
pose = A.pose(lean=0.3, arm_l=-2.4, arm_r=1.2, leg_l=-0.5, leg_r=0.6, crouch=0.3)
spr = A.figure_cached(220, style, pose)      # 带姿态量化的缓存，热路径安全
A.draw_figure(surf, spr, x, foot_y)          # 按脚底对齐贴图
```

---

## 显示与分辨率

- **设计分辨率 1920×1080**。所有游戏代码只认这个坐标系，不用关心真实屏幕。
- 全屏通过 SDL2 的 `SCALED` 模式交给 **渲染器（GPU）** 缩放，
  而不是 CPU 逐帧 `smoothscale` —— 后者在 1080p 下每帧要多花 6~10ms。
- 启动时按优先级尝试一系列显示模式，任何一个成功就用它：

  ```
  全屏（GPU 缩放 + 垂直同步） → 全屏（GPU 缩放） → 全屏（无缩放）
   → 窗口 1920×1080（GPU 缩放） → … → 窗口（最简）
  ```

  全屏失败会自动退回窗口，**绝不会因为显示模式选择失败而启不来**。
- `Info.plist` 里声明了 `NSHighResolutionCapable`，Retina 屏按物理像素渲染，不会被放大成 2 倍糊。
- 分层：游戏画在 `canvas`（可整体施加屏幕震动），HUD / 摄像头预览 / 覆盖层画在 `screen`，
  所以**画面会震、HUD 不震**，信息始终稳定可读。

---

## 工程结构

```
motion_arcade/
├── main.py                 入口（参数解析 + 启动 Shell）
├── requirements.txt        依赖（含"为什么钉这个版本"的注释）
├── run.sh                  开发用启动脚本
├── MotionArcade.app        构建产物（git 忽略）
│
├── core/                   运行时框架
│   ├── config.py           全部可调参数集中在此（分辨率/映射/各游戏数值）
│   ├── theme.py            基础视觉工具箱：渐变、抗锯齿图元、光晕、粒子、模糊、缓存烘焙
│   ├── art.py              高清美术库：卡通着色的球/人物/看台/草坪/球场
│   ├── icons.py            20 个矢量图标（大厅卡片用）
│   ├── inputs.py           FaceState / HandState / GameInput + 头部与手部控制器
│   ├── tracker.py          摄像头采集线程 + 人脸后端 + 手部后端
│   ├── base.py             游戏基类（特效、计时、HUD、结算、手部光标辅助）
│   ├── menu.py             20 款游戏的分页卡片大厅
│   └── shell.py            显示模式、场景路由、HUD、预览、覆盖层
│
├── games/                  20 款游戏，每款一个文件，继承 BaseGame
│   └── __init__.py         导入即注册
│
├── assets/models/          人脸检测模型（YuNet / Haar / MediaPipe）
├── packaging/              launcher.m + Info.plist + build_app.sh
├── tools/                  无头测试工具（截图 / 性能 / 假玩家）
└── screenshots/            各游戏与大屏截图
```

### 加一个新游戏

```python
# games/my_game.py
from core.base import BaseGame, register
from core import theme as U, art as A

@register
class MyGame(BaseGame):
    KEY = "mygame"
    TITLE = "我的游戏"
    SUB = "一句话副标题"
    CATEGORY = "头部控制"      # 或 "手部控制" / "头部 + 手部"
    ACCENT = (120, 200, 255)   # 卡片主色
    ICON = "mushroom"          # 见 core/icons.py
    HOW = "大厅展示的一句话玩法"
    HINT = "游戏底部一行的操作提示"
    DIFFICULTY = 2
    ACHIEVEMENT = "通关条件"
    REQUIRES = ("head",)       # 或 ("hand",) / ("head", "hand")

    def reset(self): ...
    def update(self, dt, inp): ...   # inp 是 GameInput
    def draw(self, surf): ...
    def hud_items(self): return [("分数", "0", (255,255,255))]
```

在 `games/__init__.py` 里加一行 import 就出现在大厅了。

---

## 它跑起来有多快

单帧预算 16.7ms（60fps）。`python tools/perf.py` 实测（无摄像头，纯渲染）：

| 游戏 | 中位耗时 |
|---|---|
| mario | 1.66 ms |
| panda_roll | 1.33 ms |
| ski | 2.28 ms |
| tennis | 0.61 ms |
| hotpot | 1.96 ms |
| drum | ~2 ms |
| mask | ~3 ms（修缓存后） |

真机开着摄像头时整体 CPU 约 90~110%（人脸检测 + 手部检测 + 渲染），
摄像头管线本身占大头。

**性能上的三条铁律**（都是踩坑踩出来的）：

1. **抗锯齿图元的尺寸必须量化**。`aa_circle/aa_ellipse/aa_line` 的缓存键里带尺寸，
   游戏里的球半径是连续变化的 —— 不量化就每帧产生几十个新缓存条目，
   缓存被反复清空，**比不缓存更慢**（熊猫滚滚一度因此跑到 92ms/帧）。
2. **面积超过 5 万像素的图形不进烘焙缓存**，直接绘制。
   超采样一张 1500×1000 的图要 6ms，为雪道这种大面积色块做 AA 完全不划算。
3. **每帧位置都在变的装饰线用 `pygame.draw.line`**，不要走 `aa_line`。

---

## 已知限制

- **手部精度有限**：如上文，只有掌心位置 / 张合度 / 大小是可靠的，
  没有捏合与手指指向。这是纯肤色方案的物理上限。
- **MediaPipe 在本机不可用**，所以"张嘴"触发用不了（用抬头代替）。
- **手部检测对背景与光线敏感**，办公桌场景通常没问题，杂乱背景会误检。
- **真机画面无法自动截屏验证**（当前环境没有屏幕录制权限），
  只能靠日志（`not authorized` 计数 = 0）+ CPU 占用间接确认摄像头链路正常。
  想自证的话：对着镜头左右移动头部，预览面板里的绿框会跟着动。
- **没有音效**。加音频会引入额外的设备初始化风险，这次没做。

---

## 踩过的坑（重要）

### 1. macOS 摄像头授权：为什么"完全磁盘访问"也没用

macOS 的 TCC 授权是按**责任进程的代码签名**判定的。
从 IDE / 终端启动 python 时，责任进程就是 IDE 本身；而 IDE 的 Info.plist 里
没有 `NSCameraUsageDescription`，于是系统**静默拒绝** —— 不弹窗、不报错，
只留下 OpenCV 的 `OpenCV: not authorized to capture video (status 0)`。
这是内核层面的保护，给 IDE 配完全磁盘访问也绕不过去。

**解法**：让一个真正的 `.app` 来发起请求。三个必要条件：

1. 可执行文件必须是**真正的 Mach-O**（不能是 shell 脚本 ——
   `exec python` 会把签名身份丢掉，授权依然失败）；
2. `Info.plist` 里声明 `NSCameraUsageDescription`；
3. ad-hoc 签名（`codesign --force --deep --sign -`），TCC 要求必须有签名。

`packaging/launcher.m` 就干这三件事：请求权限 → 把日志落盘 → `execv` 换进 python。

**推论**：TCC 授权绑定二进制指纹，所以**每次重新编译启动器都要重新授权**。
只改 Python 代码时别重跑 `build_app.sh`。

### 2. MediaPipe 1.x 在 macOS 上是硬崩，不是异常

```
F0000 graph_service.h:139] Check failed: service_ Service is unavailable.
    @ -[DrishtiMetalHelper initWithCalculatorContext:]
    @ mediapipe::api2::TensorsToDetectionsCalculator::Open()
```

`TensorsToDetectionsCalculator` 里**硬编码**了 Metal helper，
即使显式指定 `BaseOptions.Delegate.CPU`，它依然会去要 GPU service，
拿不到就 `CHECK` 失败 → **SIGABRT（rc = -6）**。

这是 abort 不是 Python 异常，`try/except` 抓不住，会直接把整个进程带走。
所以：探测必须放在**子进程**里做（`core/tracker.py: mediapipe_usable()`）。

试过降级到 `mediapipe==0.10.x`（有 `mp.solutions.hands`，纯 CPU TFLite），
但在本机 Python 3.9 下 pip 拉不到可用版本，放弃。

### 3. 其他

- **`opencv-python` 必须用 headless 版，且钉在 4.10**：非 headless 包自带一份 libSDL2，
  与 pygame 的 SDL2 冲突；5.x 的 headless 包内部仍捆绑 SDL2，同样冲突。
- **`pygame.FULLSCREEN_DESKTOP` 不一定存在**（pygame 2.6.1 就没有），
  用 `FULLSCREEN | SCALED` 替代。
- **`♥` 在部分中文字体里没有字形**，会渲染成方块 —— HUD 里的心形是手绘的。
- **`pygame.draw` 系列对 alpha 越界很敏感**：算出来的负 alpha 会抛
  `invalid color argument`，而且是在 `draw` 里报错，很难定位。
  `theme._safe()` 统一做了 clamp。
- **`.app` 没有终端**，python 默认块缓冲会让日志严重滞后，
  入口处 `sys.stdout.reconfigure(line_buffering=True)` 改成行缓冲。
  同理，`launcher.m` 里 stdout / stderr 要用**各自独立**的文件描述符，
  两个 `freopen(..., "w")` 会互相覆盖。

---

## 验收清单

```bash
cd motion_arcade

# 列出 20 款游戏
.venv/bin/python main.py --list

# 全部游戏无头渲染一遍（会输出到 screenshots/）
.venv/bin/python tools/shots.py

# 带完整 HUD/预览的最终形态截图
.venv/bin/python tools/shell_shots.py --menu

# 性能体检
.venv/bin/python tools/perf.py

# 真机：全屏启动
open MotionArcade.app && tail -f run.log
```

日志里应当看到：

```
[launcher] 摄像头授权状态已存在：3（… 3=允许）
[shell] 人脸后端：YuNet　手部后端：SkinContour　初始化 0.9s
[shell] 已就绪：1920x1080　显示模式 全屏（GPU 缩放 + 垂直同步）　共 20 款游戏
```
