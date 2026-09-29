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

/**
 * 手控投篮 —— 用掌心高度与握拳力度控制出手（手控）。
 *
 * 操作：手掌上下 → 出手高度/弧线；握拳蓄力 → 张开出手。
 * 目标：10 次出手命中 6 次；空心入网额外加分。
 *
 * 常量与 Python 端一致：FLOOR 946 / HOOP_X 1470 / HOOP_Y 470 / RIM_R 66 /
 * BALL 起点 (380,700) / SHOTS 10 / WIN 6 / GRAV 1900。
 */
class HoopGame(
    private val sprites: SpriteManager,
    private val bg: BackgroundManager,
) : BaseGame() {

    override val key = "hoop"
    override val title = "手控投篮"
    override val sub = "掌上准星"
    override val category = "手部控制"
    override val hint = "手掌高低决定弧线 · 握拳蓄力 · 张开出手"
    override val how = "握拳蓄力，掌心抬高，松开出手"
    override val accent = Col.rgb(238, 148, 62)
    override val requires = setOf(InputChannel.HAND)

    private companion object {
        const val FLOOR = 946f
        const val HOOP_X = 1470f
        const val HOOP_Y = 470f
        const val RIM_R = 66f
        const val BALL_X0 = 380f
        const val BALL_Y0 = 700f
        const val SHOTS = 10
        const val WIN = 6
        const val GRAV = 1900f
        const val CLOSE_HOLD = 0.35f       // 小于它算握拳
        const val OPEN_RELEASE = 0.62f     // 大于它算张开出手
    }

    private var shotI = 0
    private var goals = 0
    private var mScore = 0
    private var swish = 0
    private var charge = 0f
    private var charging = false
    private var ballX = 0f
    private var ballY = 0f
    private var ballVx = 0f
    private var ballVy = 0f
    private var flying = false
    private var phase = "aim"             // aim | result
    private var phaseT = 0f
    private var hitFlash = 0f
    private var hoopY = HOOP_Y
    private var lastMsg = ""

    // 手掌（归一化 + 屏幕）
    private var handYNorm = 0.6f
    private var handScreenY = 0f

    override val score: Int get() = mScore

    override fun reset() {
        state = STATE_PLAY
        shotI = 0; goals = 0; mScore = 0; swish = 0
        charge = 0f; charging = false
        flying = false
        phase = "aim"; phaseT = 0f
        hitFlash = 0f
        hoopY = HOOP_Y
        lastMsg = ""
        particles.clear()
    }

    override fun update(dt: Float, inp: GameInput) {
        hitFlash = maxOf(0f, hitFlash - dt)

        // 手掌高度（0=顶部 1=底部）
        handYNorm = inp.hy.coerceIn(0f, 1f)
        handScreenY = Design.TOP + handYNorm * Design.GAME_H

        if (state != STATE_PLAY) return

        if (flying) {
            // ---- 球飞行 ----
            ballVy += GRAV * dt
            val prevY = ballY
            ballX += ballVx * dt
            ballY += ballVy * dt

            // 判定：球下落穿过篮筐平面时是否在筐内
            if (ballVy > 0f && prevY < hoopY && ballY >= hoopY) {
                val dx = abs(ballX - HOOP_X)
                if (dx < RIM_R * 0.92f) {
                    onGoal(dx < RIM_R * 0.36f)
                }
                flying = false
                phaseT = 0f
                shotI++
                if (shotI >= SHOTS) {
                    state = if (goals >= WIN) STATE_WIN else STATE_OVER
                }
                return
            }
            if (ballY > FLOOR || ballX > Design.W + 200f) {
                flying = false
                phaseT = 0f
                shotI++
                if (shotI >= SHOTS) {
                    state = if (goals >= WIN) STATE_WIN else STATE_OVER
                }
            }
            return
        }

        // ---- 瞄准：握拳蓄力，张开出手 ----
        val open = inp.handOpen.coerceIn(0f, 1f)
        val closed = inp.grabHold || open < CLOSE_HOLD

        if (inp.handFound && closed) {
            charging = true
            charge = (charge + dt * 1.35f).coerceAtMost(1f)
        } else if (charging && (open > OPEN_RELEASE || inp.release)) {
            shoot()
        } else if (!inp.handFound) {
            charging = false
        }
        phaseT += dt
    }

    private fun shoot() {
        // 出手角度由掌心高度决定：手越高弧线越平
        val power = (0.45f + charge * 0.55f)
        val baseSpeed = 1180f + charge * 620f
        val ang = (-52f + (1f - handYNorm) * 26f) * (Math.PI.toFloat() / 180f)
        ballVx = kotlin.math.cos(ang) * baseSpeed * power * 1.35f
        ballVy = kotlin.math.sin(ang) * baseSpeed
        ballX = BALL_X0
        ballY = BALL_Y0
        flying = true
        charging = false
        charge = 0f
        addShake(3f)
        particles.burst(BALL_X0, BALL_Y0, 10, Col.rgb(255, 200, 120),
            speed = 240f, spread = 200f, dirDeg = 300f)
    }

    private fun onGoal(perfect: Boolean) {
        goals++
        mScore += if (perfect) 3 else 2
        if (perfect) swish++
        hitFlash = 0.5f
        addShake(if (perfect) 10f else 6f)
        flash(Col.rgb(255, 220, 140), if (perfect) 0.4f else 0.25f)
        particles.burst(HOOP_X, hoopY, if (perfect) 26 else 16,
            Col.rgb(255, 214, 96), speed = 320f, spread = 360f)
        lastMsg = if (perfect) "空心！" else "命中"
    }

    override fun draw(d: Canvas2D) {
        bg.drawOr(d, "bg_bev_mist", Design.W, Design.H,
            Col.rgb(26, 30, 52), Col.rgb(52, 58, 88), Col.rgb(34, 38, 60))

        // 地板
        d.rect(0f, FLOOR, Design.W, Design.H - FLOOR, Col.rgb(58, 44, 40))
        d.rect(0f, FLOOR, Design.W, 8f, Col.rgb(150, 96, 60))

        // 篮板 + 篮筐
        d.roundRect(HOOP_X + RIM_R, hoopY - 190f, 16f, 210f, 6f, Col.rgb(70, 78, 96))
        d.roundRect(HOOP_X + RIM_R - 6f, hoopY - 120f, 28f, 90f, 6f, Col.rgb(240, 244, 250))
        d.rect(HOOP_X + RIM_R + 2f, hoopY - 70f, 12f, 46f, Col.rgb(232, 96, 72))
        // 筐（椭圆，命中时高亮）
        val rimCol = if (hitFlash > 0f) Col.rgb(255, 226, 140) else Col.rgb(232, 96, 72)
        d.arc(HOOP_X, hoopY, RIM_R, 0f, 360f, rimCol, 10f)
        // 网
        for (k in 0..6) {
            val t = k / 6f
            d.line(HOOP_X - RIM_R + 2f * RIM_R * t, hoopY,
                HOOP_X - RIM_R * 0.5f + RIM_R * t, hoopY + 62f,
                Col.rgb(240, 246, 252), 3f)
        }

        // 出手预览虚线（瞄准辅助）
        if (!flying) {
            val ang = (-52f + (1f - handYNorm) * 26f) * (Math.PI.toFloat() / 180f)
            for (k in 1..12) {
                val tt = k * 0.055f
                val px = BALL_X0 + kotlin.math.cos(ang) * 900f * tt
                val py = BALL_Y0 + kotlin.math.sin(ang) * 900f * tt + 0.5f * GRAV * tt * tt
                d.circle(px, py, 3f, Col.alphaF(Col.rgb(255, 255, 255), 0.30f))
            }
        }

        // 球
        val bx = if (flying) ballX else BALL_X0
        val by = if (flying) ballY else BALL_Y0
        if (!sprites.draw(d, "basketball", bx, by, 68f, rotateDeg = (bx * 0.4f) % 360f)) {
            d.circle(bx, by, 34f, Col.rgb(232, 132, 60))
            d.circle(bx, by, 34f, Col.rgb(120, 60, 24), 3f)
            d.line(bx - 34f, by, bx + 34f, by, Col.rgb(90, 48, 20), 3f)
        }

        // 手掌光标 + 蓄力环
        if (handScreenY > 0f) {
            d.circle(Design.W * 0.5f, handScreenY, 20f,
                Col.alphaF(if (charging) Col.rgb(255, 190, 90) else Col.rgb(255, 255, 255), 0.8f))
            if (charge > 0.01f) {
                d.arc(Design.W * 0.5f, handScreenY, 34f, -90f, 360f * charge,
                    Col.rgb(255, 200, 90), 8f)
            }
        }

        particles.draw(d)

        if (lastMsg.isNotEmpty()) {
            d.text(lastMsg, Design.W / 2, Design.TOP + 120f, 46f, Col.rgb(255, 226, 150),
                align = "center", bold = true)
        }
        if (!flying && state == STATE_PLAY) {
            d.text(if (charging) "松开出手" else "握拳蓄力", Design.W / 2,
                Design.BOT - 40f, 28f, Col.rgb(200, 210, 226), align = "center")
        }
    }

    override fun hudItems(): List<HudItem> = listOf(
        HudItem("命中", "$goals / $WIN", Col.rgb(255, 214, 140)),
        HudItem("第", "${(shotI + 1).coerceAtMost(SHOTS)}/$SHOTS", Col.rgb(226, 232, 240)),
        HudItem("空心", "$swish", Col.rgb(126, 231, 135)),
        HudItem("得分", "$mScore", accent),
    )
}
