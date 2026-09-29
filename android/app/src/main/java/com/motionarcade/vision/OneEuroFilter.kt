package com.motionarcade.vision

import kotlin.math.PI
import kotlin.math.cos

/**
 * One Euro Filter（一欧元滤波器）。
 *
 * 为什么不用普通低通（EMA）：
 *  - EMA 的平滑系数固定 ⇒ 静止时抖、快速动时迟滞，二者只能二选一；
 *  - One Euro 让截止频率**随速度自适应**：动得快就少滤波（跟手），
 *    动得慢就多滤波（压抖）。这正是体感操控需要的特性，
 *    也是 Python 端 `core/inputs.py` 用的同一套算法（参数也对齐）。
 *
 * 参考：Casiez et al., "1€ Filter: A Simple Speed-based Low-pass Filter
 * for Noisy Input in Interactive Systems"（CHI 2012）。
 */
class OneEuroFilter(
    private val minCutoff: Float = 1.0f,
    private val beta: Float = 0.007f,
    private val dCutoff: Float = 1.0f,
) {
    private var xPrev: Float? = null
    private var dxPrev = 0f
    private var initialized = false

    fun reseed(value: Float) {
        xPrev = value
        dxPrev = 0f
        initialized = true
    }

    fun reset() {
        xPrev = null
        dxPrev = 0f
        initialized = false
    }

    private fun alpha(cutoff: Float, dt: Float): Float {
        val tau = 1f / (2f * PI.toFloat() * cutoff)
        return 1f / (1f + tau / dt)
    }

    fun filter(value: Float, dt: Float): Float {
        if (dt <= 0f) return value
        val prev = xPrev
        if (!initialized || prev == null) {
            xPrev = value
            dxPrev = 0f
            initialized = true
            return value
        }

        // 1) 对速度做低通
        val dxRaw = (value - prev) / dt
        val aD = alpha(dCutoff, dt)
        val dxHat = aD * dxRaw + (1f - aD) * dxPrev

        // 2) 截止频率随速度上升
        val cutoff = minCutoff + beta * kotlin.math.abs(dxHat)

        // 3) 对位置做低通
        val a = alpha(cutoff, dt)
        val xHat = a * value + (1f - a) * prev

        xPrev = xHat
        dxPrev = dxHat
        return xHat
    }
}

/**
 * 速率限制器：限制输出每秒最大变化量，防止单点跳变把角色甩飞。
 * 与 Python 端 `RateLimiter` 语义一致。
 */
class RateLimiter(private val maxRate: Float) {
    private var last = 0f
    private var hasLast = false

    fun reseed(v: Float) {
        last = v
        hasLast = true
    }

    fun limit(v: Float, dt: Float): Float {
        if (!hasLast) {
            last = v
            hasLast = true
            return v
        }
        val maxDelta = maxRate * dt
        val delta = (v - last).coerceIn(-maxDelta, maxDelta)
        last += delta
        return last
    }
}

/** 帧率无关的指数平滑：k 越大跟得越紧。 */
fun expSmooth(current: Float, target: Float, k: Float): Float =
    current + (target - current) * k.coerceIn(0f, 1f)

/** 把 dt 归一到 60fps 的平滑系数，保证不同帧率下手感一致。 */
fun smoothK(halfLifeFrames: Float, dt: Float): Float {
    val k60 = 1f - kotlin.math.exp(-0.6931f / halfLifeFrames)
    return (k60 * (dt * 60f)).coerceIn(0f, 1f)
}

/** 余弦缓动，用于 UI 动画。 */
fun easeOutCubic(t: Float): Float {
    val x = t.coerceIn(0f, 1f)
    return 1f - (1f - x) * (1f - x) * (1f - x)
}

fun easeInOut(t: Float): Float {
    val x = t.coerceIn(0f, 1f)
    return if (x < 0.5f) 2f * x * x else 1f - (-2f * x + 2f).let { it * it } / 2f
}

/** 线性插值。 */
fun lerp(a: Float, b: Float, t: Float): Float = a + (b - a) * t
