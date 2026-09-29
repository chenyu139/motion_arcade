package com.motionarcade.game.games

import com.motionarcade.game.BaseGame
import com.motionarcade.game.Design
import com.motionarcade.game.HudItem
import com.motionarcade.render.Canvas2D
import com.motionarcade.render.Col
import com.motionarcade.render.SpriteManager
import com.motionarcade.vision.GameInput
import com.motionarcade.vision.InputChannel
import kotlin.math.abs
import kotlin.math.exp
import kotlin.random.Random

/**
 * 熊猫滚滚 —— 三星堆主题伪 3D 管道跑酷（头控）。
 *
 * 操作：头部左右平移 → 三条道之间切换；抬头 → 跳过矮障碍（陶俑）。
 *
 * 伪 3D 的核心是 [project]：z∈[0,1]（0=最近，1=地平线）映射到屏幕 y 与缩放，
 * 与 Python 端完全同一条曲线，保证透视观感一致。
 */
class PandaRollGame(private val sprites: SpriteManager) : BaseGame() {

    override val key = "panda_roll"
    override val title = "熊猫滚滚"
    override val sub = "三星堆管道疾走"
    override val category = "头部控制"
    override val hint = "头部左右换道 · 抬头跳过陶俑 · 竹笋 +10"
    override val how = "在管道里换道躲障碍，越跑越快"
    override val accent = Col.rgb(120, 226, 198)
    override val difficulty = 3
    override val requires = setOf(InputChannel.HEAD)

    private companion object {
        const val HORIZON = 436f
        const val GROUND = 986f
        val LANES = floatArrayOf(0.30f, 0.50f, 0.70f)
        const val TUNNEL_R = 0.44f
        const val BALL_Z = 0.055f
        const val TARGET_M = 1200
    }

    private class Item {
        var z = 1f
        var lane = 1
        var kind = 0          // 0=面具(必须换道) 1=陶俑(可跳) 2=竹笋
        var alive = true
        var ph = 0f
    }

    private val items = ArrayList<Item>(32)
    private var lane = 1
    private var laneF = 1f
    private var jumpT = 0f
    private var jumpCd = 0f
    private var speed = 0.34f
    private var dist = 0f
    private var lives = 2
    private var bamboo = 0
    private var spawnCd = 0.9f
    private var roll = 0f
    private var invuln = 0f
    private var mScore = 0

    override val score: Int get() = mScore

    override fun reset() {
        state = STATE_PLAY
        lane = 1; laneF = 1f
        jumpT = 0f; jumpCd = 0f
        speed = 0.34f; dist = 0f
        lives = 2; bamboo = 0
        spawnCd = 0.9f; roll = 0f; invuln = 0f
        mScore = 0
        items.clear()
        particles.clear()
    }

    /** z → (屏幕 y, 缩放)。与 Python 端同一条透视曲线。 */
    private fun project(z: Float): Pair<Float, Float> {
        val k = z.coerceIn(0f, 1f)
        val p = k * k * 0.84f + k * 0.16f
        val y = GROUND - (GROUND - HORIZON) * p
        return y to (1f - 0.87f * p)
    }

    override fun update(dt: Float, inp: GameInput) {
        if (state != STATE_PLAY) return

        // ---- 速度随距离递增 ----
        speed = (0.34f + dist * 0.00022f).coerceAtMost(0.85f)
        dist += speed * 78f * dt
        mScore = dist.toInt()

        // ---- 换道：把连续 axis 映射到最近车道 ----
        val axis = inp.axis.coerceIn(-1f, 1f)
        val want = when {
            axis > 0.28f -> 2
            axis < -0.28f -> 0
            else -> lane
        }
        if (want != lane) { lane = want }
        laneF += (lane - laneF) * (1f - exp(-9f * dt))

        // ---- 跳跃 ----
        jumpCd = maxOf(0f, jumpCd - dt)
        if (inp.jump && jumpT <= 0f && jumpCd <= 0f) {
            jumpT = 0.52f
            jumpCd = 0.62f
        }
        if (jumpT > 0f) jumpT -= dt

        // ---- 滚动动画 ----
        roll += speed * 900f * dt
        invuln = maxOf(0f, invuln - dt)

        // ---- 生成 ----
        spawnCd -= dt
        if (spawnCd <= 0f) {
            spawnCd = (0.72f - speed * 0.28f).coerceAtLeast(0.26f)
            val it = Item()
            it.z = 1f
            it.lane = Random.nextInt(3)
            val r = Random.nextFloat()
            it.kind = when {
                r < 0.46f -> 0      // 面具
                r < 0.80f -> 1      // 陶俑
                else -> 2           // 竹笋
            }
            it.ph = Random.nextFloat() * 6f
            items.add(it)
        }

        // ---- 推进 + 碰撞 ----
        val jumping = jumpT > 0f
        var i = 0
        while (i < items.size) {
            val it = items[i]
            it.z -= speed * dt
            if (it.z < -0.05f) { items.removeAt(i); continue }

            val near = abs(it.z - BALL_Z) < 0.055f
            if (near && it.alive && it.lane == lane) {
                when (it.kind) {
                    2 -> {                       // 竹笋
                        bamboo++
                        mScore += 10
                        it.alive = false
                        particles.burst(Design.W * 0.5f, GROUND - 120f, 10,
                            Col.rgb(150, 226, 120), speed = 260f, spread = 360f)
                    }
                    1 -> {                       // 陶俑：跳过去
                        if (jumping) { it.alive = false }
                        else hit()
                    }
                    0 -> {                       // 面具：只能换道
                        if (jumping && jumpT > 0.30f) { /* 跳不过高面具 */ }
                        hit()
                    }
                }
            }
            i++
        }
        items.removeAll { !it.alive && it.z < BALL_Z }

        // ---- 通关 ----
        if (mScore >= TARGET_M) {
            state = STATE_WIN
            particles.burst(Design.W / 2, GROUND - 200f, 40,
                Col.rgb(255, 214, 96), speed = 420f, spread = 360f)
        }
    }

    private fun hit() {
        if (invuln > 0f) return
        lives--
        invuln = 1.2f
        addShake(14f)
        flash(Col.rgb(255, 90, 70), 0.4f)
        particles.burst(Design.W / 2, GROUND - 140f, 24,
            Col.rgb(255, 120, 90), speed = 380f, spread = 360f)
        if (lives <= 0) state = STATE_OVER
    }

    override fun draw(d: Canvas2D) {
        // 隧道背景（夜色遗址）
        d.rect(0f, 0f, Design.W, Design.H, Col.rgb(14, 18, 34))
        val (hy, _) = project(1f)
        d.rect(0f, hy, Design.W, Design.H - hy, Col.rgb(24, 30, 52))

        // 管道环（由远及近，制造纵深）
        for (k in 0 until 14) {
            val z = k / 14f
            val (y, s) = project(z)
            val rx = Design.W * TUNNEL_R * s
            val ry = rx * 0.62f
            d.ellipse(Design.W / 2, y, rx, ry, Col.rgb(30, 38, 62), 3f)
        }

        // 车道分隔线
        for (k in 0 until 10) {
            val z = k / 10f
            val (y, s) = project(z)
            for (l in 0..3) {
                val lx = Design.W * (0.22f + l * 0.19f)
                val x = Design.W / 2 + (lx - Design.W / 2) * s
                d.circle(x, y + 6f, 3f * s + 1f, Col.rgb(60, 74, 110))
            }
        }

        // ---- 物体：远的先画 ----
        val sorted = items.sortedByDescending { it.z }
        for (it in sorted) {
            if (!it.alive) continue
            val (y, s) = project(it.z)
            val laneX = Design.W * LANES[it.lane]
            val x = Design.W / 2 + (laneX - Design.W / 2) * s
            val h = 150f * s
            when (it.kind) {
                0 -> if (!sprites.draw(d, "sanxingdui", x, y - h * 0.35f, h)) {
                    d.ellipse(x, y - h * 0.35f, 52f * s, 46f * s, Col.rgb(190, 150, 70))
                }
                1 -> if (!sprites.draw(d, "bronze", x, y - h * 0.22f, h * 0.7f)) {
                    d.roundRect(x - 40f * s, y - h * 0.5f, 80f * s, h * 0.55f, 10f * s,
                        Col.rgb(150, 110, 78))
                }
                2 -> if (!sprites.draw(d, "bronze_tree", x, y - h * 0.3f, h * 0.8f)) {
                    d.roundRect(x - 16f * s, y - h * 0.5f, 32f * s, h * 0.5f, 12f * s,
                        Col.rgb(140, 210, 120))
                }
            }
        }

        // ---- 玩家（熊猫球）----
        val (by, bs) = project(BALL_Z)
        val bx = Design.W / 2 + (Design.W * LANES[lane.coerceIn(0, 2)] - Design.W / 2) * bs
        val jumpH = if (jumpT > 0f) kotlin.math.sin((1f - jumpT / 0.52f) * Math.PI.toFloat()) * 150f else 0f
        val size = 230f * bs
        val blink = if (invuln > 0f && (invuln * 8f).toInt() % 2 == 0) 90 else 255
        if (!sprites.draw(d, "panda_curl", bx, by - size * 0.4f - jumpH, size,
                rotateDeg = roll, alpha = blink)) {
            d.circle(bx, by - size * 0.4f - jumpH, size * 0.45f, Col.alpha(Col.rgb(250, 250, 252), blink))
            d.circle(bx, by - size * 0.4f - jumpH, size * 0.45f, Col.rgb(60, 56, 66), 4f)
        }

        particles.draw(d)
    }

    override fun hudItems(): List<HudItem> = listOf(
        HudItem("距离", "${mScore}m", Col.rgb(180, 240, 220)),
        HudItem("竹笋", "$bamboo", Col.rgb(226, 232, 240)),
        HudItem("生命", "$lives", Col.rgb(255, 140, 120), icon = "heart"),
    )
}
