package com.motionarcade.game.games

import com.motionarcade.game.BaseGame
import com.motionarcade.game.Design
import com.motionarcade.game.HudItem
import com.motionarcade.render.BackgroundManager
import com.motionarcade.render.Canvas2D
import com.motionarcade.render.Col
import com.motionarcade.render.SpriteManager
import com.motionarcade.vision.GameInput
import com.motionarcade.vision.InputChannel
import kotlin.math.abs
import kotlin.math.hypot
import kotlin.random.Random

/**
 * 川果切切 —— 手掌劈果（手控代表游戏）。
 *
 * 操作：手掌快速划过水果即切开；**速度不够只会把水果推歪**（这条判定是手感关键，
 * 少了它游戏会变成"摸一下就切"，完全失去挥砍的爽感）。
 * 目标：60 秒内 2200 分；切到花椒扣命，水果掉出画面扣分。
 *
 * 常量与 Python 端一致：TIME 60 / GOAL 2200 / FLOOR 1010。
 */
class SliceGame(
    private val sprites: SpriteManager,
    private val bg: BackgroundManager,
) : BaseGame() {

    override val key = "slice"
    override val title = "川果切切"
    override val sub = "手掌劈果"
    override val category = "手部控制"
    override val hint = "手掌快速划过水果才能切开 · 花椒扣命"
    override val how = "挥手劈开飞起来的水果，别切到花椒"
    override val accent = Col.rgb(246, 176, 76)
    override val requires = setOf(InputChannel.HAND)

    private companion object {
        const val TIME = 60f
        const val GOAL = 2200
        const val FLOOR = 1010f
        const val SLICE_SPEED = 900f       // 挥砍最小速度（px/s）
        const val GRAV = 1500f

        // name, color, size, score；score<0 表示炸弹（花椒）
        val FRUIT_NAME = arrayOf("橙子", "猕猴桃", "蜜桃", "西瓜", "枇杷", "花椒")
        val FRUIT_SPRITE = arrayOf("fruit", "kiwi", "peach", "watermelon", "loquat", "pepper")
        val FRUIT_COL = intArrayOf(
            Col.rgb(240, 152, 56), Col.rgb(168, 196, 92), Col.rgb(248, 158, 150),
            Col.rgb(86, 178, 96), Col.rgb(246, 190, 76), Col.rgb(108, 74, 52)
        )
        val FRUIT_SIZE = floatArrayOf(58f, 52f, 56f, 76f, 44f, 50f)
        val FRUIT_SCORE = intArrayOf(120, 130, 140, 180, 100, -1)
    }

    private class Fruit {
        var x = 0f; var y = 0f
        var vx = 0f; var vy = 0f
        var spec = 0
        var rot = 0f; var spin = 0f
        var alive = true
    }

    private class Half {
        var x = 0f; var y = 0f
        var vx = 0f; var vy = 0f
        var spec = 0
        var life = 1f
        var rot = 0f
    }

    private val fruits = ArrayList<Fruit>(16)
    private val halves = ArrayList<Half>(24)
    private val trail = ArrayList<Pair<Float, Float>>(24)

    private var left = TIME
    private var mScore = 0
    private var cut = 0
    private var lives = 3
    private var combo = 0
    private var bestCombo = 0
    private var spawnT = 0.5f

    /** 上一帧是否看到手（绘制手掌光标用）。 */
    private var inpHandFoundCache = false

    // 手掌（屏幕坐标）
    private var hx = Design.W / 2
    private var hy = Design.BOT - 300f
    private var phx = hx
    private var phy = hy
    private var handSpeed = 0f

    override val score: Int get() = mScore

    override fun reset() {
        state = STATE_PLAY
        left = TIME
        mScore = 0; cut = 0; lives = 3
        combo = 0; bestCombo = 0
        spawnT = 0.5f
        fruits.clear(); halves.clear(); trail.clear()
        particles.clear()
    }

    override fun update(dt: Float, inp: GameInput) {
        if (state != STATE_PLAY) return

        left -= dt
        if (left <= 0f) { state = if (mScore >= GOAL) STATE_WIN else STATE_OVER; return }

        inpHandFoundCache = inp.handFound

        // ---- 手掌位置（归一化 → 设计坐标）----
        hx = inp.hx * Design.W
        hy = Design.TOP + inp.hy * Design.GAME_H
        handSpeed = if (dt > 0f) hypot(hx - phx, hy - phy) / dt else 0f
        phx = hx; phy = hy

        trail.add(hx to hy)
        if (trail.size > 18) trail.removeAt(0)

        // ---- 抛水果 ----
        spawnT -= dt
        if (spawnT <= 0f) {
            spawnT = (0.62f - (1f - left / TIME) * 0.22f).coerceAtLeast(0.3f)
            val n = 1 + (Random.nextFloat() * 2).toInt()
            repeat(n) { spawnFruit() }
        }

        // ---- 水果运动 + 切割判定 ----
        val canSlice = handSpeed > SLICE_SPEED && inp.handFound
        var i = 0
        while (i < fruits.size) {
            val f = fruits[i]
            f.vy += GRAV * dt
            f.x += f.vx * dt
            f.y += f.vy * dt
            f.rot += f.spin * dt

            if (canSlice && f.alive) {
                val r = FRUIT_SIZE[f.spec] * 0.75f + 16f
                if (hypot(f.x - hx, f.y - hy) < r) {
                    sliceFruit(f)
                    fruits.removeAt(i)
                    continue
                }
            }
            // 掉出画面
            if (f.y > FLOOR + 120f) {
                if (FRUIT_SCORE[f.spec] > 0) {
                    combo = 0
                    mScore -= 40
                }
                fruits.removeAt(i)
                continue
            }
            i++
        }

        // ---- 半块飞行 ----
        var j = 0
        while (j < halves.size) {
            val h = halves[j]
            h.vy += GRAV * dt
            h.x += h.vx * dt
            h.y += h.vy * dt
            h.rot += 3f * dt
            h.life -= dt
            if (h.life <= 0f || h.y > FLOOR + 200f) { halves.removeAt(j); continue }
            j++
        }

        if (mScore >= GOAL) state = STATE_WIN
        if (lives <= 0) state = STATE_OVER
    }

    private fun spawnFruit() {
        val f = Fruit()
        val bombChance = 0.16f
        f.spec = if (Random.nextFloat() < bombChance) 5 else Random.nextInt(5)
        f.x = 260f + Random.nextFloat() * (Design.W - 520f)
        f.y = FLOOR + 60f
        val peak = 260f + Random.nextFloat() * 320f
        f.vy = -kotlin.math.sqrt(2f * GRAV * (peak + 300f))
        f.vx = (Design.W / 2 - f.x) * (0.28f + Random.nextFloat() * 0.3f)
        f.spin = (Random.nextFloat() - 0.5f) * 6f
        fruits.add(f)
    }

    private fun sliceFruit(f: Fruit) {
        val sc = FRUIT_SCORE[f.spec]
        if (sc < 0) {
            // 花椒炸弹
            lives--
            combo = 0
            addShake(18f)
            flash(Col.rgb(255, 90, 70), 0.45f)
            particles.burst(f.x, f.y, 30, Col.rgb(120, 80, 60), speed = 460f, spread = 360f)
            return
        }
        cut++
        combo++
        bestCombo = maxOf(bestCombo, combo)
        mScore += sc + (combo - 1) * 10
        particles.burst(f.x, f.y, 14, FRUIT_COL[f.spec], speed = 340f, spread = 360f, sizeRange = 9f)
        addShake(3f)
        // 两半飞出
        for (s in intArrayOf(-1, 1)) {
            val h = Half()
            h.x = f.x; h.y = f.y
            h.vx = f.vx * 0.5f + s * 220f
            h.vy = f.vy * 0.45f - 120f
            h.spec = f.spec
            halves.add(h)
        }
    }

    override fun draw(d: Canvas2D) {
        // 茶馆暖调背景（缺图时 drawOr 自动回退到下面的渐变色）
        bg.drawOr(d, "sky_teahouse", Design.W, Design.H,
            Col.rgb(52, 40, 60), Col.rgb(96, 72, 84), Col.rgb(40, 32, 46))

        // 半块
        for (h in halves) {
            val r = FRUIT_SIZE[h.spec] * 0.5f
            d.ellipse(h.x, h.y, r, r * 0.62f, FRUIT_COL[h.spec])
        }

        // 水果
        for (f in fruits) {
            val size = FRUIT_SIZE[f.spec]
            if (!sprites.draw(d, FRUIT_SPRITE[f.spec], f.x, f.y, size * 1.5f,
                    rotateDeg = Math.toDegrees(f.rot.toDouble()).toFloat())) {
                d.circle(f.x, f.y, size * 0.5f, FRUIT_COL[f.spec])
                d.circle(f.x, f.y, size * 0.5f, Col.shade(FRUIT_COL[f.spec], 0.6f), 3f)
            }
        }

        // 手掌轨迹（速度越快越亮 —— 给玩家"挥够快才能切"的即时反馈）
        val hot = (handSpeed / SLICE_SPEED).coerceIn(0f, 1.4f)
        for (k in 1 until trail.size) {
            val a = trail[k - 1]
            val b = trail[k]
            val t = k / trail.size.toFloat()
            val w = (4f + hot * 14f) * t
            d.line(a.first, a.second, b.first, b.second,
                Col.alphaF(if (hot > 1f) Col.rgb(255, 240, 190) else Col.rgb(255, 255, 255),
                    0.18f + 0.62f * t * hot.coerceAtMost(1f)), w)
        }
        if (inpHandFoundCache) {
            d.circle(hx, hy, 22f + hot * 10f,
                Col.alphaF(if (hot > 1f) Col.rgb(255, 230, 150) else Col.rgb(255, 255, 255), 0.85f))
        }

        particles.draw(d)
    }

    override fun hudItems(): List<HudItem> = listOf(
        HudItem("得分", "$mScore", Col.rgb(255, 226, 150)),
        HudItem("连击", "$combo", Col.rgb(126, 231, 135)),
        HudItem("生命", "$lives", Col.rgb(255, 140, 120), icon = "heart"),
        HudItem("时间", "${maxOf(0f, left).toInt()}", Col.rgb(226, 232, 240)),
    )
}
