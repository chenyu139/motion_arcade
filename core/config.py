"""
core/config.py
==============
全局配置：显示、摄像头、头部/手部映射、各游戏参数。

坐标约定
--------
所有游戏统一在 **1920×1080 设计坐标系** 中绘制，由 SDL2 的 SCALED 模式
（GPU 缩放）映射到实际屏幕，因此：

  · 游戏代码永远不用关心真实分辨率；
  · 真机全屏 / 窗口缩放都不改变布局；
  · 需要"更高清"就把设计分辨率往上调，美术代码无需改动。

安全区
------
  GAME_TOP   = HUD_H                 游戏画面顶部（HUD 之下）
  GAME_BOT   = H - HINT_H            游戏画面底部（提示条之上）
  PREVIEW_*  左下角摄像头预览面板，会遮挡游戏左下角，
             游戏的关键元素请避开 PREVIEW_RECT。
"""
from __future__ import annotations

# =========================================================================== #
# 显示
# =========================================================================== #
DESIGN_W = 1920          # 设计分辨率（所有游戏坐标都基于它）
DESIGN_H = 1080
FPS = 60
TITLE = "体感游戏厅 · Motion Arcade"
FULLSCREEN = True        # 默认全屏；F11 可切换
VSYNC = 1

HUD_H = 96               # 顶部状态栏高度
HINT_H = 44              # 底部提示条高度

GAME_TOP = HUD_H
GAME_BOT = DESIGN_H - HINT_H
GAME_H = GAME_BOT - GAME_TOP
CENTER = (DESIGN_W // 2, GAME_TOP + GAME_H // 2)

# 左下角摄像头预览面板（游戏请避开）
PREVIEW_W = 352
PREVIEW_H = 264
PREVIEW_X = 28
PREVIEW_Y = GAME_BOT - 18 - PREVIEW_H
PREVIEW_RECT = (PREVIEW_X, PREVIEW_Y, PREVIEW_W, PREVIEW_H)

# =========================================================================== #
# 摄像头
# =========================================================================== #
CAM_INDEX = 0
CAM_W = 960
CAM_H = 720
CAM_FPS = 30
DETECT_W = 320           # 人脸检测在缩略图上做，保证实时

# =========================================================================== #
# 头部映射
# =========================================================================== #
CALIB_FRAMES = 24        # 校准采样帧数
DEADZONE_X = 0.06        # 水平死区（占画面宽比例）
FULL_SCALE_X = 0.22      # 偏离中性多少算满速
JUMP_DY = 0.10           # 头部相对中性抬高多少触发动作（占画面高比例）
MOUTH_OPEN_THRESHOLD = 0.045   # 张嘴触发（MediaPipe 后端）
SMOOTH = 0.35            # 输入平滑系数

# =========================================================================== #
# 手部映射
# =========================================================================== #
HAND_ENABLE = True
HAND_MAX_NUM = 2         # 最多同时跟踪的手数
HAND_DEADZONE = 0.012    # 掌心位置死区
HAND_SMOOTH = 0.42
HAND_OPEN_THRESHOLD = 0.62   # 张合度高于此 → 判定为"张开"
HAND_CLOSE_THRESHOLD = 0.34  # 低于此 → 判定为"握拳"
HAND_PINCH_THRESHOLD = 0.34  # 拇指-食指距离 / 掌宽，低于此 → 捏合
HAND_FIST_COOLDOWN = 0.30    # 握拳/捏合触发后的冷却（防连触）
HAND_LOST_AFTER = 0.6        # 多久没检测到手就认为"手离开"

# =========================================================================== #
# 未检测提示
# =========================================================================== #
LOST_WARN_AFTER = 1.5
LOST_PAUSE_AFTER = 0.7

# =========================================================================== #
# 通用游戏参数
# =========================================================================== #
START_LIVES = 3

# ---- 马里奥（横版平台跳跃）----
WORLD_H = DESIGN_H
GROUND_Y = 900
LEVEL_W = 6200
DEATH_Y = 1240
PLAYER_W = 54
PLAYER_H = 74
GRAVITY = 2600.0
MAX_FALL = 1500.0
MAX_RUN = 430.0
MOVE_ACCEL = 3000.0
GROUND_DECEL = 3200.0
AIR_DECEL = 1100.0
JUMP_VELOCITY = -920.0
STOMP_BOUNCE = -620.0
COYOTE_TIME = 0.10
JUMP_COOLDOWN = 0.18
LEVEL_TIME = 150
COIN_SCORE = 10
STOMP_SCORE = 100
GOAL_SCORE = 500
TIME_BONUS_PER_SEC = 5

# ---- 川超足球（点球大战）----
FB_SHOTS = 10
FB_AIM_SPEED = 1.05
FB_KEEPER_MIN = 190.0
FB_KEEPER_MAX = 460.0
FB_READ_CHANCE = 0.22
FB_BALL_SPEED = 1750.0
FB_COMBO_STEP = 2
FB_SCORE_GOAL = 100
FB_SCORE_CORNER = 60
FB_SCORE_COMBO = 50

# ---- 川网网球（底线对拉）----
TN_WIN_SCORE = 5
TN_COURT_LEFT = 96
TN_COURT_RIGHT = 1824
TN_NET_X = 960
TN_PLAYER_MIN_X = 400
TN_PLAYER_MAX_X = 720
TN_BALL_GRAVITY = 2100.0
TN_HIT_PERFECT = 58
TN_HIT_GOOD = 118
TN_HIT_RANGE = 196

# =========================================================================== #
# 主菜单
# =========================================================================== #
MENU_SWITCH_AXIS = 0.55
MENU_SWITCH_COOLDOWN = 0.40
MENU_CONFIRM_LOCK = 0.55
MENU_DWELL = 2.4
MENU_ENTRY_TIME = 0.9
MENU_COLS = 4            # 大厅每行卡片数
MENU_ROWS = 2            # 每页行数
MENU_PAGE_DWELL = 1.1    # 翻页停留
