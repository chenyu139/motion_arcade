# 体感游戏厅 · Motion Arcade

用 **摄像头** 控制的小游戏合集，共 **20 款**。头部左右平移、抬头作为动作键；
手部则作为第二套输入通道，可以控制掌心光标、张开/握拳手势。
全部美术程序化生成（无任何图片素材），1920×1080 设计分辨率 + 全屏 GPU 缩放。

```
open MotionArcade.app        # 全屏启动，进入游戏大厅
```

---

## 目录

- [快速开始](#快速开始)
- [20 款游戏](#20-款游戏)
- [操作方式](#操作方式)
- [手部识别的原理与限制](#手部识别的原理与限制)
- [显示与分辨率](#显示与分辨率)
- [工程结构](#工程结构)
- [它跑起来有多快](#它跑起来有多快)
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

## 手部识别的原理与限制

**这是本项目最需要如实说明的部分。**

原本计划用 MediaPipe HandLandmarker，但它在 macOS 上**完全不可用**（原因见后文），
所以手部改成了一套纯 OpenCV 的几何方案：

```
肤色分割（YCrCb ∩ HSV 双空间取交）
  → 剔除人脸区域（脸也是肤色，不排掉会把头当成手）
  → 形态学开闭 + 轮廓面积/长宽比筛选
  → 距离变换求掌心（最大内切圆圆心，比轮廓质心稳得多）
  → 凸包缺陷数指缝 + solidity 估张合度
```

能稳定给出：

| 输出 | 可靠性 | 说明 |
|---|---|---|
| 掌心位置 | ★★★★ | 距离变换定位，很稳 |
| 张合度 `open`（握拳↔张开） | ★★★☆ | solidity 与指缝数融合 |
| 伸展手指数 | ★★☆☆ | 近似值，只用于显示 |
| 手的远近 / 面积 | ★★★★ | 可用于力度类玩法 |

**给不出**的东西：拇指-食指捏合、手势数字、手指指向。那需要关键点模型。

**使用建议**：

- 手要**出现在摄像头画面内**（建议在胸前到面部之间活动）；
- **光线尽量均匀**，避免手被阴影切碎；
- **背景不要有大面积近肤色物体**（米色墙面、木桌、纸箱都会误检）；
- 手静止时也能检测（不依赖运动），但快速挥动时更准。

如果这些条件不满足，游戏依然能玩 —— 无摄像头时鼠标会接管手部
（鼠标位置 = 手的位置，按住左键 = 握拳）。

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
