"""
core/filters.py
===============
体感信号的自适应滤波。

为什么不能用固定时间常数
------------------------
头部这类信号有一个**无法两全**的矛盾：

    · 静止时要**重**滤波 —— 否则检测噪声会变成控制量。
      （本项目真机事故："头没动，选游戏的地方一直不停在左右选择"）
    · 移动时要**轻**滤波 —— 否则快速转头会明显拖后路，
      用户感知就是"识别迟钝 / 怎么动都没反应"。

固定时间常数（旧的 YAW_TAU=0.20）只能在这两头取一个折中：
取小了噪声漏进来，取大了手感发钝。**这不是调参能解决的**，
因为同一个常数在"静止"和"快速移动"两种状态下必然有一边是错的。

One Euro Filter（Casiez / Roussel / Vogel, CHI 2012）的解法非常朴素：
**按当前速度实时调节截止频率** ——

    截止频率 = 最小截止 + beta × |当前速度|
      · 速度为 0        → 截止很低 → 重滤波 → 噪声出不来
      · 速度变大        → 截止抬高 → 轻滤波 → 跟手，不再拖后路

它之所以特别适合体感：这里的"速度"本来就是**我们想要保留的真实运动**，
而噪声是无规律的、速度估算里会被低通压掉的那部分。于是两者被自动分开，
不需要设阈值去猜"玩家现在是不是在动"。

和旧实现的兼容
--------------
beta = 0 时它严格退化为固定截止频率的低通，与旧的
`k = 1 - exp(-dt/tau)` 等价（`cutoff = 1/(2·π·tau)`）。
所以引入它是**纯增益**：关掉 beta 就回到原来的行为，没有任何语义变化。
"""
from __future__ import annotations

import math


class OneEuroFilter:
    """
    One Euro Filter（单参数自适应低通）。

    参数
    ----
    min_cutoff  静止时的截止频率（Hz）。越小越稳、延迟越大。
                换算到旧的时间常数：cutoff = 1/(2·π·tau)
                  · YAW_TAU 0.20s  → 0.80 Hz
                  · HEAD_TAU 0.075s → 2.12 Hz
    beta        速度系数（Hz per 单位/秒）。**这是"越快越跟手"的旋钮**：
                beta=0 → 退化成固定低通；beta 越大，快速移动时越灵敏。
    d_cutoff    速度估计本身的低通截止（Hz）。它决定"多快算是在移动"，
                取值不必很准，通常 ~1Hz 即可；过大会把噪声当成速度。

    已知的选取原则（本项目真机标定）：
      · beta 太大会把抖动误判成"正在移动" → 噪声重新漏进来；
      · beta 太小则在快速转头时没有收益。
      所以对**噪声大的通道**（摇头 yaw）给中等 beta，
      对**本来就很干净**的通道（平移后的 axis）给更小的 beta。
    """

    __slots__ = ("min_cutoff", "beta", "d_cutoff", "beta_dead",
                 "_prev", "_dx", "value", "speed", "initialized")

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.0,
                 d_cutoff: float = 1.0, beta_dead: float = 0.0) -> None:
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self.beta_dead = float(beta_dead)
        self._prev: float | None = None
        self._dx = 0.0
        self.value = 0.0
        self.speed = 0.0
        self.initialized = False

    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        """清空状态。重校准 / 重新捕获之后必须调用，否则会带着旧数据起步。"""
        self._prev = None
        self._dx = 0.0
        self.value = 0.0
        self.speed = 0.0
        self.initialized = False

    def reseed(self, value: float) -> None:
        """
        直接把内部状态设成某个值（跳过建立过程）。

        用于"重建基线"这类场景：前一帧的输出已经不可信，但我们**确实**
        希望从当下这个值继续，而不是被当成一次巨大的跳变慢慢追上去。
        """
        self._prev = float(value)
        self._dx = 0.0
        self.value = float(value)
        self.speed = 0.0
        self.initialized = True

    # ------------------------------------------------------------------ #
    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        """
        截止频率 → 平滑系数。

        用 `1 - exp(-dt/tau)`（而不是论文的 `1/(1+tau/dt)`）是为了与
        项目其余地方的时间常数写法保持一致；两者在 dt ≪ tau 时等价，
        而这个形式永远落在 (0,1] 内，帧率抖动时不会越界。
        """
        if cutoff <= 0.0:
            return 1.0
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 - math.exp(-dt / tau)

    def filter(self, x: float, dt: float) -> float:
        """
        喂一个新采样值，返回滤波结果。dt 是距上次调用的秒数。

        用 dt（而不是"每帧固定系数"）是必须的：摄像头帧率会波动，
        固定系数会让实际滤波强度随帧率变化，手感忽快忽慢。
        """
        x = float(x)
        dt = max(1e-4, float(dt))

        if self._prev is None:
            # 第一帧：没有历史，不存在"跳变"，直接采纳
            self._prev = x
            self._dx = 0.0
            self.value = x
            self.speed = 0.0
            self.initialized = True
            return x

        # 1) 速度 = （新值 − 上一次滤波输出）/ dt，再低通
        #    注意减的是**滤波输出**而不是上一次的原始值 —— 这正是原论文
        #    的做法：噪声已经上一次的输出里被压掉了，用它做差不会把噪声
        #    重新引入到速度里（这是 One Euro 抗噪的关键一环）。
        raw_dx = (x - self._prev) / dt
        self._dx += self._alpha(self.d_cutoff, dt) * (raw_dx - self._dx)

        # 2) 按速度抬高截止频率 → 快速移动时自动减少滤迟
        excess = abs(self._dx)
        if self.beta_dead > 0.0:
            # 速度死区：噪声同样有"速度"，只是它明显小于真实运动。
            # 不设这条门槛的话，逐帧噪声会持续抬高截止频率 —— 等于把
            # 噪声地板跟着抬起来（实测大偏置噪声场景的抖动翻转从 2 次涨到 4 次）。
            # 有了它：噪声区间内 cutoff 恒等于 min_cutoff，**与原来的固定低通严格等价**，
            # 噪声地板一动不动；只有速度明显超过噪声水平时才提速。
            excess = max(0.0, excess - self.beta_dead)
        cutoff = self.min_cutoff + self.beta * excess
        a = self._alpha(cutoff, dt)

        # 3) 对**原始值**做低通（不是在已滤值上叠加），保证稳态收敛到真值
        self._prev += a * (x - self._prev)
        self.value = self._prev
        self.speed = self._dx
        return self._prev

    # ------------------------------------------------------------------ #
    @property
    def cutoff_now(self) -> float:
        """当前实际使用的截止频率（Hz）。诊断时用：静止/噪声时应等于 min_cutoff。"""
        excess = abs(self._dx)
        if self.beta_dead > 0.0:
            excess = max(0.0, excess - self.beta_dead)
        return self.min_cutoff + self.beta * excess

    @property
    def tau_now(self) -> float:
        """当前等效时间常数（秒）。比截止频率更直观：越小越跟手。"""
        c = self.cutoff_now
        return 1.0 / (2.0 * math.pi * c) if c > 0 else float("inf")


# =========================================================================== #
def lowpass_towards(cur: float, target: float, tau: float, dt: float) -> float:
    """
    固定时间常数的一阶低通（原来的做法），保留给不需要自适应的通道。

    用时间常数而不是"每帧系数"：摄像头帧率从 30 掉到 15 时，
    每帧系数会让实际跟随速度翻倍变慢，手感明显发钝；
    这里 dt 显式参与，帧率变化不影响手感。
    """
    if tau <= 1e-6:
        return target
    k = 1.0 - math.exp(-dt / tau)
    return cur + k * (target - cur)


# =========================================================================== #
class RateLimiter:
    """
    **运动学速率限制**：限制信号每单位时间最多变化多少。

    为什么必须有这一层（血泪教训）
    ------------------------------
    原本以为加了 One Euro 就够了，结果测试立刻打脸：一帧孤立误检尖峰
    （yaw 突然读到 0.95）会让 One Euro 的**速度估计**暴涨 ——
    它无法区分"极快的真实运动"和"单次跳变"，于是把截止频率抬高到几乎直通，
    尖峰几乎原封不动地穿了过去（孤立尖峰峰值从严格的 0 涨到 0.067，
    两帧尖峰更是到 0.40，直接越过所有后续门限）。

    解法不是调 beta 或 d_cutoff：那条路会在"压住尖峰"和"保留快速转头的
    跟手性"之间反复拉扯（把 d_cutoff 压到 0.1Hz 能让尖峰消失，但真实
    转头的速度估计要几秒才建立，One Euro 的收益也就没了）。

    真正的区分点在于**连续性**：
        · 真实的头部运动是连续的 —— 再快也有物理上限，且会持续好几帧；
        · 误检跳变 / 单帧噪声是孤立的 —— 它只在一帧里离群。
    所以给信号加一条硬性速度上限即可：孤立的离群值被削幅，持续的
    真实运动（速度本来就在上限内）完全不受影响。

    这不是"又一道 hack"，而是把"人头的转动不可能比 x 更快"这条先验
    明明白白写进代码 —— 它同时防护了误检尖峰、关键点跳变、临时遮挡
    恢复时的位置突跳这三类问题。

    上限怎么定
    ----------
    本项目 yaw 读数 ≈ 2.14·sin(转头角)，实测一次快速转头约 0.3 秒内转过
    40°，对应读数变化 1.37 → 速度约 4.6/秒。留出余量取 5.0：
        · 真实运动（≤5/秒）无损通过；
        · 单帧 0.95 的尖峰被削到 5.0×dt ≈ 0.17/帧，低于摇头死区 0.24
          → 尖峰连死区都进不去，后续起振门限根本不需要出手。
    """

    __slots__ = ("max_rate", "_prev")

    def __init__(self, max_rate: float) -> None:
        self.max_rate = float(max_rate)
        self._prev: float | None = None

    def reset(self) -> None:
        self._prev = None

    def reseed(self, value: float) -> None:
        self._prev = float(value)

    def filter(self, x: float, dt: float) -> float:
        """
        限制变化速率后的值。

        注意判据是相对**上一次的输出**（而不是上一次的原始输入）：
        真值时 intervention 只会拦住"离群那一帧"，不会因为一次跳变
        永久抬高/压低后续基线。
        """
        x = float(x)
        dt = max(1e-4, float(dt))
        if self._prev is None:
            self._prev = x
            return x
        step = self.max_rate * dt
        d = x - self._prev
        if d > step:
            d = step
        elif d < -step:
            d = -step
        self._prev += d
        return self._prev
