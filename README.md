# 体感游戏厅 · Motion Arcade

用 **摄像头** 控制的小游戏合集，共 **18 款**。支持三层输入：

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
- [生成式原创素材](#生成式原创素材)
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
| `--vision auto\|apple\|mediapipe\|onnx\|opencv` | 指定视觉后端；默认 `auto` 按平台自动选（macOS→apple，Win/Linux→mediapipe 或 onnx） |
| `--list` | 打印全部游戏后退出 |
| `--list-backends` | 打印本机可用的视觉后端后退出 |
| `--probe [--probe-secs N]` | 诊断模式：真机跑 N 秒，输出检测率、耗时、抖动统计 |

---

## 18 款游戏

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

（原有两款「头部 + 手部」双线游戏 duel / keeper 已下架 —— 同时用头和手
操控对普通用户难度过高；模块文件保留，需要时重新 import 即可恢复。）

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
- **抬头 → 进入**（唯一的进入方式；没有识别到头时不会误触发）
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

### 「没有识别到头的时候别乱动」：识别状态机

这是体感控制里最影响手感的一件事。**单帧漏检非常常见**（转头、眨眼间的遮挡、
曝光突变、模型抖动），如果直接把"这一帧没检测到"当成丢失，控制量会在帧之间
反复重启，看起来就是**角色自己在乱动**。所以"丢失"必须是一个**带迟滞的状态**：

```
TRACKING  正常识别
HOLD      连续丢检 ≤ 0.15s → **冻结**上一次的有效输出（一点不变）
LOST      超过 0.15s      → 轴量立即归零、动作键立即清零（不做缓慢衰减）
```

**HOLD 阶段绝不能用"衰减到 0"** —— 那样每次漏检角色都会往中间滑一下，
下一帧检测回来又弹回去，这正是抖动的来源。实测：闪烁 60 帧后横向量的
最大偏移从"衰减到 0 再弹回"（≈1.00）降到 **0.00000**。

真正丢失之后必须**立即归零**，不留"滑行"的尾巴；否则人已经走了，角色还在
按最后的方向漂。

配套还堵了四个同类漏洞 —— 都是"没检测到却还在动"的来源：

| 漏洞 | 现象 | 处理 |
|---|---|---|
| 人脸框无合理性校验 | 墙上的图案/反光被判成脸，中心贴边 → 归一化后 axis 直接打满，角色瞬间被甩到一边 | 加最小尺寸 / 宽高比 / 面积 / 边缘距离筛选 |
| 身体动作键不按来源门控 | 姿态模型隔帧跑还会退避，陈旧的 `arm_l` 让角色在没人做动作时继续"按键" | `action` 里的手臂/举手分支要求 `body_found` |
| 视觉帧过期仍被消费 | 退避期间交出的是上一帧，`found=True` 与抬臂数值一起陈旧 | `get_vision()` 超过 0.35s 按"什么都没检测到"返回 |
| 手部丢检后重新捕获 | 手一直握着也会立刻误触发一次捏合（根本没有"张开→握拢"的转变） | 捏合边沿要求先观察到"张开" |
| 大厅 `dwell` 不检查识别状态 | **人走开了大厅还会自己翻页、自己进游戏** | 停止累加停留计时并清零；抬头确认同样要求识别中 |

重新捕获那一帧还会限制跳变幅度（`REACQ_STEP=0.62`）——
假阳性往往只出现一两帧，限制住就不会把角色一下甩到边上。

**状态可观测**：摄像头预览面板左下角直接显示三态

```
● 头部已锁定　手 x1     识别正常
◐ 短暂丢帧 · 输入冻结      HOLD（无可见变化）
○ 未识别到头 · 输入归零    LOST
```

**验证方式**（不是靠感觉）：

```bash
# 行为断言：25 项，覆盖冻结/归零/闪烁/重捕获限速/动作门控/手势误触/大厅抬头进入
.venv/bin/python tools/test_input.py

# 头部控制：71 项，覆盖距离无关性/摇头与平移两路/灵敏度标定/静止噪声/尖峰抑制
.venv/bin/python tools/test_head.py

# 游戏层不变量：6 项，含"静止时受控物不得自作主张"（川超足球瞄准点回归）+ 20 款游戏静止输入
.venv/bin/python tools/test_games.py

# 反馈与 HUD 链路：15 项，含 20 款游戏逐个跑 60 帧（这条路上曾崩过，见 run.log）
.venv/bin/python tools/test_feedback.py

# 真机：合成序列自检 + 实机跑，最后统计"未识别期间仍有非零输出的帧数"
.venv/bin/python main.py --probe --probe-secs 20
```

`--probe` 的小结里有一行是结论：
`未识别期间仍有非零输出的帧数：0　→ 通过`。

---

## 全身体感怎么用

### 打开体感模式

默认是**头部模式**（省 CPU：全身姿态检测真机要 16~29ms/次）。游戏里按 **`B`** 切换：

```
B  体感模式：已开启（用身体动作）
```

打开后，游戏里的横向控制 `inp.xc` 会自动在「头部平移」和「身体横移」之间
取幅度更大的那个，动作键 `inp.action` 会接受「抬头 / 举手 / 张嘴」任一触发。
**同一份游戏代码，怎么动都行** —— 这是通过 `GameInput` 的通道融合属性实现的：

```python
inp.xc          # 横向：取头部与身体中更明显的那个
inp.action      # 动作键：抬头 / 举手 / 张嘴 任一
inp.action_l / inp.action_r   # 左右手独立的动作键
inp.crouching   # 是否下蹲
inp.arms_wide   # 双臂是否大幅张开
```

### 体感模式带来的独有解法

| 游戏 | 头部模式 | 体感模式额外能做的 |
|---|---|---|
| 熊猫滚滚 | 只能换道绕开高陶俑 | **下蹲钻过去**（+40 分） |
| 双人守门 | 只能左右挪 | **双臂展开** → 扑救范围 +42% |
| 蜀道攀岩 | 抬头抓 | **举手抓**（左右手可分别控制） |
| 蜀韵鼓点 | 抬头击鼓 | **挥手击鼓** |

### 四川地标场景

`core/sichuan.py` 提供 10 个地标的**程序化剪影**，游戏背景按主题调用：

```python
from core import sichuan as SC
bg.blit(SC.skyline(W, 156, preset="city", base=(34, 44, 74), haze=0.30), (0, 108))
```

| 地标 | 剪影提炼的关键一笔 |
|---|---|
| 都江堰 | 鱼嘴分水堤（前窄后宽的锐角）+ 安澜索桥弧线 |
| 青城山 | 三层递进峰峦 + 山顶道观重檐 |
| 乐山大佛 | 山体里凿出的坐佛：螺髻、宽肩、双手扶膝 |
| 峨眉金顶 | 陡峭主峰 + 顶上金色重檐殿 |
| 九寨沟 | 层叠彩林（扇形树冠）+ 钙化滩横纹 |
| 宽窄巷子 | 川西民居：硬山坡屋顶 + 穿斗木构 + 天井院墙 |
| 锦里 | 三间四柱牌坊 + 檐下成串灯笼 |
| 蜀南竹海 | 竹秆竹节 + 叶簇 |
| 三星堆 | 宽扁面具 + 纵目 + 通天神树 |
| 稻城亚丁 | 三座品字形雪山（仙乃日/央迈勇/夏诺多吉） |

预设组合：`city`（宽窄巷子·锦里·峨眉·青城）、`nature`（九寨·亚丁·峨眉·竹海）、
`culture`（三星堆·都江堰·乐山·锦里）、`mountain`、`panda`。

已接入：足球（成都天际线）、网球（川西自然）、马里奥（川西群山）、岷江捕鱼（都江堰·乐山·三星堆）。

**为什么用剪影而不是照片**：分辨率无关（480p 到 4K 同一份代码）、
风格统一（不会像贴图拼盘）、无版权风险、零体积。

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

### 生成式原创素材

程序化矢量负责"能画的东西"，但角色、文物这类需要造型精度的对象，位图效果更好。
`assets/sprites/` 下有 **12 张生成式原创素材**，全部是四川文旅主题：

| 素材 | 用途 |
|---|---|
| `panda_hero` / `panda_cub` | 大厅吉祥物（熊猫 + 蜀绣马褂） |
| `panda_curl` | 熊猫滚滚主角（蜷成球，跟着滚动量旋转） |
| `mask_red/black/gold/blue/green` | 川剧变脸的 5 张脸谱 |
| `lantern` | 自贡灯会的灯笼（一张素材派生 6 种配色） |
| `bronze_tree` / `sanxingdui` | 熊猫滚滚的隧道尽头、高陶俑镶嵌 |
| `gaiwan` | 大厅的盖碗茶 |

**为什么不用素材站的图**

素材站上"免费"的图多数只授权个人使用，商用要单独买。这个项目要嵌进四川观察
客户端，直接扒图等于把风险埋在后面。生成式素材是自己产出的，没有第三方权利
负担；风格也能统一到与矢量美术同一套语言（cel-shading + 粗描边），不会出现
"照片贴进矢量画面"的割裂感。

原始生成图留在 `assets/sprites/_raw/`（JPEG 存证，3.8MB），`tools/matte.py`
可以从它重新产出全部精灵。

**抠底不是简单阈值**

生成图是浅色背景的 RGB（**没有 alpha 通道**，即使请求了透明背景），必须自己抠。
难点在于：**主体内部也有大量近白色区域** —— 熊猫的白毛、盖碗的青白瓷、脸谱的
白色纹样。按"亮 = 背景"抠，这些部位会被抠穿成一个个空洞。

正确做法见 `tools/matte.py`，核心三步：

```
1. 四边估背景色 → 低分辨率 inpaint 插值出「背景色场」
   （有些图的背景是渐变的，单一常数色抠不干净）
2. 距离够近的算"疑似背景"，再做连通域分析 ——
   只有与画布边缘相连的那一片才是真背景
   ↑ 关键一步：内部白毛颜色与背景一样，但被粗描边封闭、与画布边缘不连通，
     因此会被正确保留（实测内部空洞率 0.00%）
3. 二值前景 + 只在轮廓处羽化 1~2px
```

另有两处收尾：反混合去掉边缘白边（否则精灵贴到深色游戏背景上会有一圈白晕）、
按 alpha 包围盒裁边并降采样到 600px。

```bash
.venv/bin/python tools/matte.py            # 重新抠底全部素材
.venv/bin/python tools/matte.py --sheet    # 附带一张深底 / 棋盘底的检查图
```

**素材缺失不会崩**

`core/sprites.py` 的 `draw()` 取不到图时返回 `False`，调用方据此回退到原来的
矢量画法：

```python
if SP.draw(surf, "panda_curl", x, cy, height=r * 2.2, anchor="center",
           rot=-math.degrees(self.roll)):
    return                        # 用上了素材
surf.blit(A.shade_ball(r, ...))   # 没有素材就走老路
```

所以仓库即使不带 `assets/sprites/` 也能跑 —— 素材是"增强"而不是"依赖"。

**一张素材派生多种配色**

自贡灯会要 6 盏颜色不同的灯，素材只有一张。用 `BLEND_RGB_MULT` 染色不行：
多颜色相乘必然掉亮度，红灯笼乘绿直接变黑。所以 `sprites.hued()` 做的是真正的
色相旋转（RGB 色相旋转矩阵，numpy 一次算完并按角度缓存）。

---

## 商业级视觉升级（本轮）

目标是把它从"工程 Demo"抬到"可发布的家庭体感游戏"。不是换配色和字体，
而是从**场景 / 角色 / HUD / 动画 / 粒子 / 光照 / 材质 / 按钮 / 反馈 / 转场 /
开始界面 / 结束界面**整条链上重做。核心玩法、头部与动作识别逻辑、交互流程
一律未动。

### 先做的诊断：最影响"廉价感"的 10 条

对着实际渲染逐帧看，真正拉低质感的是这十条（按影响排序）：

| # | 问题 | 处理 |
|---|---|---|
| 1 | 19/20 的背景只有"渐变 + 几个色块"，**无前中后三层、无雾、无纵深** | `scene.depth_pass` 统一深度合成 |
| 2 | 无统一光照方向、无环境光遮蔽、无 bloom → 画面"平、塑料" | 同上（方向光 + 边缘光 + AO） |
| 3 | 顶栏是"表格式状态栏"（label/value 平铺，带分割线） | 重做为浮层卡片 HUD |
| 4 | 玩家头部是工程调试框 + FPS/坐标文字 | 换成卡通化身 + 能量环 |
| 5 | 每个页面各写一套配色/圆角/字体 | 建 `core/ui.py` 设计系统 |
| 6 | 无得分反馈、无粒子、无 Combo | `core/feedback.py` |
| 7 | 大厅是"卡片墙 + 纯色底"，没有仪式感 | 重做为 Start Screen（英雄区） |
| 8 | 结算页只有一行字 | 重做（数字滚动 / 星级 / 新纪录 / 庆祝） |
| 9 | 底部列着 ESC/R/C/P/H 快捷键（开发工具状态栏） | 移进暂停面板 |
| 10 | 关键元素静态，无微动画；场景切换是硬切 | 微动画 + 入场转场 + 音效 |

### 1. 设计系统 `core/ui.py`

所有 UI 都必须走这套 token，这是"所有页面像来自同一个游戏"的前提：

- **语义色**：`PRIMARY / SECONDARY / ACCENT / SUCCESS / WARN / DANGER / INFO`，
  外加 `BG_DEEP / SURFACE_HI / SURFACE_LO / OUTLINE / PAPER`
- **圆角阶梯** `R_SM/R_MD/LG/XL`、**字号阶梯** `T_XS → T_HERO`
- **组件**：`card / ink_card / stat / pill / big_button / stars / draw_icon`
- **缓动与弹簧**：`Pop`（命中弹跳）、`Tween`、`ease_out_back / ease_out_cubic`
- `normalize_accent()` 把各游戏自报的主题色归一化到统一饱和区间 ——
  否则 20 个游戏的强调色会各亮各暗，一眼就是"不同人做的"

### 2. 世界深度合成 `scene.depth_pass`

**一次升级全部 20 个背景，同时保证风格统一。** 给任何已画好的主题背景叠六层：

```
色彩分级(通道配平+饱和度) → 方向光 + 边缘光 → 雾带
  → 接触阴影 AO → 前景失焦剪影 → 暗角
```

10 套世界预设（`meadow/alpine/stadium/court/night/stage/teahouse/river/temple/forest`），
各自有光源方向、雾色、前景剪影色与强度。游戏只需声明一行：

```python
class Mario(BaseGame):
    WORLD = "meadow"      # 世界预设
    WORLD_Y = None        # 地平线；None = 自动从模块的 GROUND/FLOOR 推断
```

地平线是**自动推断**的（读游戏模块里的 `GROUND`/`FLOOR`/`WATER_Y`/`HORIZON`），
所以 20 款游戏一行都不用额外声明。

踩过的两个坑（都写进代码注释了）：

- **`BLEND_RGBA_ADD` 忽略源 alpha** —— 边缘光那条带被按 RGB 满值整体加上去，
  整片天空直接过曝成白色。必须先画到"不透明黑底"上做成**预乘亮度**再加法叠加。
- **前景剪影必须锚在画面边缘、且被裁切在画外**。第一版在两侧画了悬空的窄竖椭圆，
  模糊之后看起来就是两块"脏抹布"抹在山上 —— 没有形状也不贴边，
  读不出"近景物体"，只读得出"画面脏了"。

### 3. 全屏氛围层 `scene.Atmosphere`

叠在**世界之上、UI 之下**，给 20 款游戏统一的空气感：斜洒光柱（预烘焙 + 平移摆动）、
浮尘、暗角、色调分级。实测 **1.85ms/帧**。

刻意只做 4 个动态元素而不做动态天空盒 —— 它必须能被"随意叠加"而不抢戏。

### 4. 玩家化身 `core/avatar.py`

原来的左下角是**摄像头原图 + 绿色人脸框 + fps 文字**，最典型的工程调试界面。
现在替换为：

- **卡通化身**：能量环（颜色即识别状态、两段反向旋转的亮弧、轨道上的能量点）、
  高光轮廓、柔光投影、随输入呼吸浮动
- **拖尾与粒子**：头部快速移动时喷 trail；命中目标时 burst
- **识别位置条**：不是 bounding box，而是一条游戏化的位置指示 ——
  发光点 = 真实检测位置、竖线 = 校准中性位、浅色带 = 死区。
  既是给玩家的"我在被捕捉"的确认，也让中性位准不准一眼可见
- 原始画面 + 骨架 + FPS **降级为按 H 才出的诊断层**

### 5. HUD

顶栏从"表格式状态栏"改成**浮在画面上的独立卡片**：图标 + 小标签 + 大数值，
靠"小标签 / 大数值"的强层级让 2~4 米外先读到数值。数值一变化就弹一下。
生命值画心形图标而不是数字（图标被识别的速度比数字快一个量级）。

**删掉了给玩家看的 FPS 与快捷键栏** —— 那是调试信息，不是游戏信息。
FPS 只留在诊断层，快捷键移进暂停面板。

### 6. 反馈与音效

`core/feedback.py`：分数飞出数字、`PERFECT` 标签、星星粒子、闪光、光晕、
UI 弹性缩放、Combo 增长动画（递进强化）、命中 burst、通关庆祝。

**关键设计：反馈由 HUD 数值变化驱动**，所以 20 款游戏**一行都不用改**就获得了
统一的得分反馈，手感还完全一致。
（唯一需要人工标注的是"时间/剩余"这类倒计时数值，它们每秒都变，不能当得分。）

音效是**纯程序化合成**（`core/sfx.py`，正弦 + 谐波 + 噪声 + 快速包络），
零素材文件、零版权、零体积。连击越高中越高音（同一音效变频播放）。
无头 / 无声卡环境自动退化为空操作。按 `M` 静音。

### 7. 开始界面 / 结束界面 / 转场

- 大厅改成 **英雄区 + 选择网格**：选中游戏的详细信息只在英雄区讲一次，
  卡片只留图标与名称。旧版每张卡都重复一遍图标/名称/副标题/分类/难度，
  十张铺开就是一片噪点 —— **信息的价值来自"只出现一次"**。
- 背景是黄昏天空 + 星 + 四川地标剪影 + 雾 + 地面，大厅本身就是一个游戏世界。
- 结算页：弹入的大标题、滚动的得分、星级、最高连击、新纪录徽章、
  庆祝粒子、两个大按钮。
- 进入游戏时有 **0.42s 的镜头推进 + 淡入**，替代原来的硬切。

### 8. 性能

| 环节 | 代价 |
|---|---|
| 全屏氛围层（每帧） | 1.85 ms |
| 世界深度合成（切游戏时一次） | 首次 ~75ms / 复用叠加层 ~38ms（被淡入遮住） |
| 20 款游戏单帧最慢中位 | **6.8 ms**（预算 16.7 ms） |

所有视觉开销都走**烘焙 + 缓存 + 量化键**：光晕半径、图标尺寸、卡片尺寸全部
量化后进缓存，避免连续值把缓存冲爆（这一条在早期把帧耗时从 92ms 拉到 1.3ms）。
表面缓存统一按**总像素**封顶（按条数封顶控不住 —— 一张全屏渐变就 8MB）。

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
│   ├── sprites.py          生成素材精灵层：加载 / 缩放缓存 / 锚点贴图 / 色相旋转
│   ├── sichuan.py          10 个四川地标的程序化剪影 + 天际线组合
│   ├── icons.py            20 个矢量图标（大厅卡片用）
│   ├── inputs.py           FaceState / HandState / GameInput + 头部与手部控制器
│   ├── tracker.py          摄像头采集线程 + 人脸后端 + 手部后端
│   ├── vision/             跨平台视觉层：COCO-17 + 手部 21 点规范与多后端
│   ├── base.py             游戏基类（特效、计时、HUD、结算、手部光标辅助）
│   ├── menu.py             20 款游戏的分页卡片大厅（含吉祥物）
│   └── shell.py            显示模式、场景路由、HUD、预览、覆盖层
│
├── games/                  20 款游戏，每款一个文件，继承 BaseGame
│   └── __init__.py         导入即注册
│
├── assets/models/          人脸检测模型（YuNet / Haar 入库；MediaPipe 的 .task 需自行下载）
├── assets/sprites/         12 张生成式原创素材（_raw/ 为原始生成图）
├── packaging/              launcher.m + Info.plist + build_app.sh
├── tools/                  无头测试工具（截图 / 性能 / 假玩家 / 抠底 / 行为断言）
└── screenshots/            各游戏与大屏截图（git 忽略，由 tools/shots.py 生成）
```

### 模型文件：哪几个入库、哪几个要自己下

仓库里**只留运行时必需的小文件**，其余是可按需下载的大模型（不然 `.git` 会到 200MB+）：

| 文件 | 大小 | 是否入库 | 用途 |
|---|---|---|---|
| `face_detection_yunet_2023mar.onnx` | 227 KB | ✅ 入库 | **人脸检测主力**，每帧都跑 |
| `haarcascade_frontalface_default.xml` | 0.9 MB | ✅ 入库 | 兜底检测器（某些机器 YuNet 不可用时） |
| `face_landmarker.task` | 3.6 MB | ⬇️ 自行下载 | MediaPipe 人脸（本机 SIGABRT，见下） |
| `hand_landmarker.task` | 6.5 MB | ⬇️ 自行下载 | MediaPipe 手部 21 点 |
| `pose_landmarker_full.task` | 9.0 MB | ⬇️ 自行下载 | MediaPipe 全身 33 点 |

需要 Windows / Linux 上的 MediaPipe 后端时，把三个 `.task` 下载到 `assets/models/`：

```bash
cd assets/models
B=https://storage.googleapis.com/mediapipe-models
curl -O $B/face_landmarker/face_landmarker/float16/1/face_landmarker.task
curl -O $B/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
curl -O $B/pose_landmarker_full/pose_landmarker_full/float16/1/pose_landmarker_full.task
```

`assets/models/rtmpose_body.onnx`（ONNX Runtime 后端）不随仓库分发，下载地址见
`core/vision/backend_onnx.py` 文件头。

`screenshots/` 同理不入库：它是 `tools/shots.py` / `tools/shell_shots.py` 的产物，
本机随时可重新生成（约 45MB，历史里曾有 183MB）。

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
- **`surfarray.blit_array()` 会把透明通道一起写成不透明**。给精灵做色相旋转时
  用它写回 RGB，结果每个灯笼背后都多出一个黑矩形。改用 `surfarray.pixels3d()`
  拿到**视图**后原地写入，只改 RGB、alpha 原样保留。
- **抠底不要用"距离越近越透明"的宽软过渡**。AI 生成的背景自带细噪点，距离会在
  10~40 之间波动，而软过渡的容差区间（9~46）正好把整片背景拉成 20~40% 不透明度的
  灰雾 —— 表现为主体边缘外一圈脏边、而且包围盒裁不掉。二值前景 + 只在轮廓处
  羽化 1~2px 才是对的。
- **`Rect.bottom` / `top` / `left` / `right` 是标量，不是点**。
  `surface.get_rect(bottom=(x, y))` 会抛 `invalid rect assignment`。
  想要"底部中心对齐"要用 `midbottom`。
- **改配置项名字时，一定要全局搜一遍引用**。把"每帧平滑系数"统一改成时间常数
  （`SMOOTH_TAU` → `HAND_TAU`）时漏了 `HandController` 里的一处，而它只在
  "检测到手"那条分支上才会执行 —— 于是**一检测到手就 AttributeError 崩**，
  平时完全看不出来。这类错误静态就能查，现在由 `tools/test_input.py`
  的第 7 项守着（扫描 core/ 与 games/ 下全部 `C.XXX` 引用）。
- **游戏的"自动行为"要按同一把尺子审**。川超足球里有一条"玩家不操作时让瞄准点
  250px/s 来回扫"（注释写着"避免玩家完全不参与"），于是玩家看到的是
  **头一动没动，瞄准点自己在球门里滑**，直接读成"识别飘了"。它和已经删掉的
  大厅"停留自动进入"、以及输入层的 LOST 归零尾巴是同一类问题：
  **静止时任何受控物都不许自作主张**。外壳层的测试看不到游戏自己的自动行为，
  所以单独有 `tools/test_games.py` 按游戏断言（含"别把真实操作一起删掉"的反向断言）。
- **HUD 数值驱动的反馈链路，只有真进游戏才会被执行**。`core/feedback.py` 里
  `_bump_combo` 引用了不存在的 `amt`（调用方手里有 `delta` 却没传），
  单元测试全过、一进游戏加分就 `NameError` 整个进程退出；`.app` 没有终端，
  现象只是"窗口突然没了"。现在由 `tools/test_feedback.py` 压着
  （20 款游戏 × 60 帧，人为推高分数逼它走这条路）。
- **`git filter-branch` 会顺手删掉工作区里被剔除的文件**。想"把截图从历史里剔掉、
  文件留在本机"时，`--index-filter 'git rm -r --cached …'` 看着只动索引，
  但 filter-branch 结束后会 `checkout -f` 到重写后的 HEAD —— 那些文件于是从
  工作区一起消失了（本次真踩到：`screenshots/` 39MB 与三个 `.task` 模型）。
  **动手前先把要剔除的路径备份到仓库外**，重写后再放回来；
  这类"删历史不删文件"的诉求，安全顺序永远是：备份 → 重写 → 还原 → 核对。
  核对要用文件清单逐个比，不要只看 `git status`（被 ignore 的路径删了它也不报）。
  另外 `--prune-empty` 会把"只动了被剔除文件"的提交整条丢掉（本次少了一条只加截图的
  `docs:` 提交），这是预期行为，但要知道。
- **`.git` 涨到 200MB+ 通常是"把产物提交进去了"**。本项目历史上 183MB 是
  `screenshots/`（`tools/shots.py` 的产物，可随时重新生成）、19MB 是 MediaPipe 的
  `.task` 模型。剔掉后 `.git` 从 **207MB 降到 9MB**。判断方法：
  `git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectsize) %(rest)'`
  按 `%(rest)` 分组求和，一眼就能看出是谁占的。

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

# 输入层行为断言（识别状态机 / 动作门控 / 手势误触 / 大厅抬头进入）
.venv/bin/python tools/test_input.py

# 头部控制敏感度 / 静止噪声 / 转头耦合（71 项）
.venv/bin/python tools/test_head.py

# 反馈与 HUD 链路（15 项，含 20 款游戏各 60 帧）
.venv/bin/python tools/test_feedback.py

# 游戏层不变量：静止时受控物不得自作主张（6 项）
.venv/bin/python tools/test_games.py

# 真机：识别状态机 + 检测率 + 各环节耗时
.venv/bin/python main.py --probe --probe-secs 20

# 真机：全屏启动
open MotionArcade.app && tail -f run.log
```

日志里应当看到：

```
[launcher] 摄像头授权状态已存在：3（… 3=允许）
[shell] 人脸后端：YuNet　手部后端：SkinContour　初始化 0.9s
[shell] 已就绪：1920x1080　显示模式 全屏（GPU 缩放 + 垂直同步）　共 18 款游戏
```
