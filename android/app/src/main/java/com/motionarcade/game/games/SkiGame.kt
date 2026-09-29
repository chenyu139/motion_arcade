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
import kotlin.math.exp
import kotlin.math.sin
import kotlin.random.Random

/**
 * 川西滑雪 —— S 形雪道速降（头控）。
 *
 * 操作：头部左右平移 → 横移；抬头 → 跳过雪包。
 * 目标：60 秒内滑完 5000 米；冲出雪道撞树减速，穿过旗门得分。
 * 常量与 Python 端一致：PLAYER_Y 742 / TRACK_W 660 / GOAL_M 5000 / TIME 60 / speed 430。
 */
class SkiGame(
    private val sprites: SpriteManager,
    private val bg: BackgroundManager,
) : BaseGame() {

    override val key = "ski"
    override val title = "川西滑雪"
    override val sub = "S 形雪道速降"
    override val category = "头部控制"
    override val hint = "头部左右转向 · 抬头跳过雪包"
    override val how = "跟着雪道走，别撞树，穿旗门加分"
    override val accent = Col.rgb(108, 190, 246)
    override val requires = setOf(InputChannel.HEAD)

    private companion object {
        const val PLAYER_Y = 742f
        const val TRACK_W = 660f
        const val GOAL_M = 5000
        const val TIME = 60f
        const val BASE_SPEED = 430f
    }

    private var left = TIME
    private var dist = 0f
    private var px = Design.W / 2
    private var vx = 0f
    private var scoreGates = 0
    private var lives = 3
    private var crashCd = 0f
    private var jumpT = 0f
    private var jumpCd = 0f
    private var speed = BASE_SPEED

    private class Prop {
        var z = 0f          // 剩余距离（米），0 = 到玩家
        var side = 0        // -1 左 / +1 右 / 0 中间
        var kind = 0        // 0=树 1=旗门 2=雪包
        var alive = true
    }

    private val props = ArrayList<Prop>(48)
    private var nextGate = 300f
    private var nextProp = 200f
    private var nextBump = 620f

    override val score: Int get() = dist.toInt() + scoreGates * 50

    override fun reset() {
        state = STATE_PLAY
        left = TIME
        dist = 0f
        px = Design.W / 2
        vx = 0f
        scoreGates = 0
        lives = 3
        crashCd = 0f
        jumpT = 0f
        jumpCd = 0f
        speed = BASE_SPEED
        props.clear()
        nextGate = 300f
        nextProp = 200f
        nextBump = 620f
        particles.clear()
    }

    /** 雪道中心随距离做 S 形摆动。 */
    private fun trackCenter(d: Float): Float =
        Design.W / 2 + sin(d / 900f) * 300f + sin(d / 2600f) * 180f

    override fun update(dt: Float, inp: GameInput) {
        if (state != STATE_PLAY) return

        left -= dt
        if (left <= 0f) { state = STATE_OVER; return }

        // ---- 横移（头部 axis 直接驱动速度）----
        val axis = inp.axis.coerceIn(-1f, 1f)
        val target = axis * 620f
        vx += (target - vx) * (1f - exp(-8f * dt))
        px = (px + vx * dt).coerceIn(120f, Design.W - 120f)

        // ---- 跳跃 ----
        jumpCd = maxOf(0f, jumpCd - dt)
        if (inp.jump && jumpT <= 0f && jumpCd <= 0f) { jumpT = 0.5f; jumpCd = 0.6f }
        if (jumpT > 0f) jumpT -= dt

        // ---- 推进 ----
        crashCd = maxOf(0f, crashCd - dt)
        speed = if (crashCd > 0f) BASE_SPEED * 0.45f else BASE_SPEED
        dist += speed * dt

        // ---- 生成 ----
        if (dist > nextProp) {
            nextProp += 140f + Random.nextFloat() * 120f
            val p = Prop()
            p.z = 2400f
            p.side = if (Random.nextBoolean()) -1 else 1
            p.kind = 0
            props.add(p)
        }
        if (dist > nextGate) {
            nextGate += 380f + Random.nextFloat() * 160f
            val p = Prop(); p.z = 2400f; p.side = 0; p.kind = 1
            props.add(p)
        }
        if (dist > nextBump) {
            nextBump += 520f + Random.nextFloat() * 260f
            val p = Prop(); p.z = 2400f; p.side = 0; p.kind = 2
            props.add(p)
        }

        // ---- 推进物体 + 判定 ----
        val jumping = jumpT > 0f
        var i = 0
        while (i < props.size) {
            val p = props[i]
            p.z -= speed * dt
            if (p.z < -80f) { props.removeAt(i); continue }

            if (p.alive && p.z < 40f && p.z > -40f) {
                val center = trackCenter(dist + p.z)
                when (p.kind) {
                    1 -> {   // 旗门：在门内穿过得分
                        if (abs(px - center) < 110f) {
                            scoreGates++
                            p.alive = false
                            particles.burst(px, PLAYER_Y, 12, Col.rgb(255, 214, 96),
                                speed = 260f, spread = 360f)
                        }
                    }
                    2 -> {   // 雪包：不跳就摔
                        if (abs(px - center) < 90f && !jumping) crash()
                    }
                    0 -> {   // 树：在雪道边界外，撞上说明冲出赛道
                        val treeX = center + p.side * (TRACK_W / 2 + 40f)
                        if (abs(px - treeX) < 46f) crash()
                    }
                }
            }
            i++
        }
        props.removeAll { !it.alive }

        // ---- 冲出雪道 ----
        val centerNow = trackCenter(dist)
        if (abs(px - centerNow) > TRACK_W / 2 + 120f) crash()

        if (dist >= GOAL_M) {
            state = STATE_WIN
            particles.burst(px, PLAYER_Y, 40, Col.rgb(150, 220, 255),
                speed = 420f, spread = 360f)
        }
    }

    private fun crash() {
        if (crashCd > 0f) return
        lives--
        crashCd = 1.1f
        addShake(15f)
        flash(Col.rgb(255, 255, 255), 0.35f)
        particles.burst(px, PLAYER_Y + 20f, 22, Col.rgb(240, 248, 255),
            speed = 360f, spread = 360f)
        if (lives <= 0) state = STATE_OVER
    }

    override fun draw(d: Canvas2D) {
        // 雪山背景
        bg.drawOr(d, "bg_bev_mountain", Design.W, Design.H,
            Col.rgb(150, 190, 226), Col.rgb(206, 226, 240), Col.rgb(240, 248, 252))

        // ---- 雪道（由远及近的多段梯形）----
        for (k in 12 downTo 0) {
            val z = k * 200f
            val dd = dist + z
            val c = trackCenter(dd)
            val t = (1f - z / 2400f).coerceIn(0f, 1f)
            val half = TRACK_W * 0.5f * (0.22f + 0.78f * t)
            val y = 300f + (PLAYER_Y - 300f) * t
            val h = 60f + 140f * t
            d.polygon(floatArrayOf(
                c - half * 1.5f, y, c + half * 1.5f, y,
                c + half, y + h, c - half, y + h
            ), if (k % 2 == 0) Col.rgb(238, 246, 252) else Col.rgb(226, 238, 248))
        }

        // ---- 物体（远的先画）----
        val sorted = props.sortedByDescending { it.z }
        for (p in sorted) {
            if (!p.alive) continue
            val dd = dist + p.z
            val c = trackCenter(dd)
            val t = (1f - p.z / 2400f).coerceIn(0f, 1f)
            val y = 300f + (PLAYER_Y - 300f) * t
            val s = 0.25f + 0.75f * t
            when (p.kind) {
                0 -> {
                    val tx = c + p.side * (TRACK_W / 2 + 40f) * (0.22f + 0.78f * t)
                    d.polygon(floatArrayOf(tx, y - 90f * s, tx + 34f * s, y + 10f * s,
                        tx - 34f * s, y + 10f * s), Col.rgb(46, 92, 62))
                    d.rect(tx - 6f * s, y + 6f * s, 12f * s, 22f * s, Col.rgb(96, 68, 44))
                }
                1 -> {
                    val gw = 110f * s
                    d.rect(c - gw, y - 90f * s, 10f * s, 90f * s, Col.rgb(232, 96, 72))
                    d.rect(c + gw - 10f * s, y - 90f * s, 10f * s, 90f * s, Col.rgb(232, 96, 72))
                    d.rect(c - gw, y - 96f * s, gw * 2, 10f * s, Col.rgb(255, 214, 96))
                }
                2 -> {
                    d.ellipse(c, y + 8f * s, 90f * s, 34f * s, Col.rgb(214, 232, 248))
                    d.ellipse(c, y + 2f * s, 70f * s, 24f * s, Col.rgb(250, 252, 255))
                }
            }
        }

        // ---- 玩家 ----
        val jumpH = if (jumpT > 0f) sin((1f - jumpT / 0.5f) * Math.PI.toFloat()) * 90f else 0f
        val py = PLAYER_Y - jumpH
        if (!sprites.draw(d, "panda_hero", px, py + 30f, 150f)) {
            d.roundRect(px - 26f, py, 52f, 74f, 16f, accent)
            d.circle(px, py - 6f, 22f, Col.rgb(250, 240, 226))
        }
        // 滑板
        d.roundRect(px - 46f, py + 76f, 92f, 12f, 6f, Col.rgb(240, 120, 60))

        particles.draw(d)
    }

    override fun hudItems(): List<HudItem> = listOf(
        HudItem("距离", "${dist.toInt()}m", Col.rgb(200, 234, 255)),
        HudItem("旗门", "$scoreGates", Col.rgb(255, 226, 140)),
        HudItem("生命", "$lives", Col.rgb(255, 140, 120), icon = "heart"),
        HudItem("时间", "${maxOf(0f, left).toInt()}", Col.rgb(226, 232, 240)),
    )
}
