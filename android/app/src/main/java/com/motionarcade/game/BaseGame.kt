package com.motionarcade.game

import com.motionarcade.render.Canvas2D
import com.motionarcade.render.Col
import com.motionarcade.vision.GameInput
import com.motionarcade.vision.InputChannel
import kotlin.math.cos
import kotlin.math.sin
import kotlin.random.Random

/**
 * 设计坐标系常量 —— 与 Python 端 `core/config.py` 严格一致。
 * 所有游戏都按这套坐标画，缩放到真实屏幕由外层 Canvas 矩阵统一处理。
 */
object Design {
    const val W = 1920f
    const val H = 1080f
    const val HUD_H = 112f
    const val HINT_H = 56f
    const val TOP = HUD_H                 // 游戏区顶部（上方留给 HUD）
    const val BOT = H - HINT_H            // 游戏区底部（下方留给提示条）
    const val GAME_H = BOT - TOP

    // 左下角摄像头预览面板（游戏关键元素要避开它）
    const val PW = 300f
    const val PH = 240f
    const val PX = 24f
    const val PY = BOT - 18f - PH
}

/**
 * 粒子系统（对应 Python 端 `U.Particles`）。
 *
 * 用**平行数组 + 对象池**而不是 List<Particle>：60fps 下每帧几百个粒子，
 * 若用对象会带来明显的 GC 压力，体感上就是"命中时卡一下"。
 */
class Particles(cap: Int = 400) {
    private val x = FloatArray(cap)
    private val y = FloatArray(cap)
    private val vx = FloatArray(cap)
    private val vy = FloatArray(cap)
    private val life = FloatArray(cap)
    private val maxLife = FloatArray(cap)
    private val size = FloatArray(cap)
    private val color = IntArray(cap)
    private var cursor = 0
    private var active = 0

    fun burst(cx: Float, cy: Float, n: Int, col: Int, speed: Float = 420f,
              spread: Float = 360f, dirDeg: Float = 0f, sizeRange: Float = 8f) {
        for (i in 0 until n) {
            val idx = cursor
            cursor = (cursor + 1) % x.size
            val ang = Math.toRadians(dirDeg + (Random.nextFloat() - 0.5f) * spread.toDouble())
            val sp = speed * (0.45f + Random.nextFloat() * 0.75f)
            x[idx] = cx; y[idx] = cy
            vx[idx] = (cos(ang) * sp).toFloat()
            vy[idx] = (sin(ang) * sp).toFloat()
            maxLife[idx] = 0.35f + Random.nextFloat() * 0.55f
            life[idx] = maxLife[idx]
            size[idx] = sizeRange * (0.5f + Random.nextFloat())
            color[idx] = col
            if (active < x.size) active++
        }
    }

    fun update(dt: Float) {
        for (i in x.indices) {
            if (life[i] <= 0f) continue
            life[i] -= dt
            x[i] += vx[i] * dt
            y[i] += vy[i] * dt
            vy[i] += 1400f * dt          // 重力
            vx[i] *= (1f - 1.6f * dt)    // 阻尼
        }
    }

    fun draw(d: Canvas2D) {
        for (i in x.indices) {
            if (life[i] <= 0f) continue
            val k = life[i] / maxLife[i]
            d.circle(x[i], y[i], size[i] * k.coerceIn(0.2f, 1f),
                Col.alphaF(color[i], k))
        }
    }

    fun clear() {
        life.fill(0f)
        active = 0
    }

    val count: Int get() = active
}

/**
 * HUD 上的一张状态卡：小标签 + 大数值（+ 可选图标）。
 * 对应 Python 端 `BaseGame.hud_items()` 返回的三/四元组。
 */
data class HudItem(
    val label: String,
    val value: String,
    val color: Int,
    val icon: String = "",       // "heart" 画心形，其余走通用卡
)

/**
 * 所有小游戏的基类（对应 Python 端 `core/base.BaseGame`）。
 *
 * 子类只实现三件事：[reset] / [update] / [draw]，其余（HUD、暂停、结算、
 * 震动、粒子、计时、屏震、闪白）由外壳与基类提供。
 */
abstract class BaseGame {

    // ---- 元信息（子类覆盖）----
    abstract val key: String
    abstract val title: String
    open val sub: String = ""
    open val category: String = "头部控制"
    open val accent: Int = Col.rgb(108, 148, 236)
    open val hint: String = ""
    open val how: String = ""
    open val difficulty: Int = 2          // 1 轻松 / 2 适中 / 3 硬核
    open val requires: Set<InputChannel> = setOf(InputChannel.HEAD)

    // ---- 状态 ----
    var state: String = STATE_PLAY        // play | win | over
    var t: Float = 0f                     // 本局累计时间
    var timeScale: Float = 1f             // 顿帧用
    val particles = Particles()

    protected var shake: Float = 0f
    protected var shakeT: Float = 0f
    protected var flashA: Float = 0f
    protected var flashCol: Int = Col.rgb(255, 255, 255)

    var msg: String = ""
    var msgSub: String = ""

    /** 得分（子类自己维护，这里给外壳读取用于结算）。 */
    open val score: Int get() = 0

    /**
     * HUD 中间要显示哪些数值。子类返回自己的 [HudItem] 列表；
     * 数值变化时 HUD 会自动"弹一下"（最便宜也最有效的操作反馈）。
     */
    open fun hudItems(): List<HudItem> = emptyList()

    companion object {
        const val STATE_PLAY = "play"
        const val STATE_WIN = "win"
        const val STATE_OVER = "over"
    }

    // ---- 子类实现 ----
    abstract fun reset()
    abstract fun update(dt: Float, inp: GameInput)
    abstract fun draw(d: Canvas2D)

    // ---- 基类提供的效果 ----
    fun addShake(amount: Float) {
        shake = (shake + amount).coerceAtMost(28f)
    }

    fun flash(color: Int, alpha: Float = 0.55f) {
        flashCol = color
        flashA = alpha
    }

    /** 由外壳每帧调用：推进时间、粒子、屏震、闪白衰减。 */
    fun tickEffects(dt: Float) {
        t += dt
        particles.update(dt)
        shake = (shake - shake * 6f * dt).coerceAtLeast(0f)
        shakeT += dt
        flashA = (flashA - flashA * 4.5f * dt).coerceAtLeast(0f)
    }

    /**
     * 外壳调用的绘制入口：套上屏震与闪白，再调子类 [draw]。
     * 这样子类完全不用关心"镜头在抖"这件事。
     */
    fun render(d: Canvas2D) {
        val save = d.save()
        if (shake > 0.2f) {
            val ox = sin(shakeT * 61f) * shake
            val oy = cos(shakeT * 47f) * shake * 0.6f
            d.translate(ox, oy)
        }
        draw(d)
        d.restore()
        if (flashA > 0.01f) {
            d.rect(0f, 0f, Design.W, Design.H, Col.alphaF(flashCol, flashA))
        }
    }
}
