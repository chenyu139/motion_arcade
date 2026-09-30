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
import kotlin.random.Random

/**
 * 川超 · 点球王 —— 头部瞄准 + 抬头起脚（头控）。
 *
 * 操作：头部左右平移 → 横向瞄准；抬头 → 起脚射门，
 * **抬头高度决定打上角还是下角**（这是本作唯一的操作深度）。
 * 目标：10 次射门打进 6 球；死角额外加分，连击有加成。
 */
class FootballGame(private val sprites: SpriteManager) : BaseGame() {

    override val key = "football"
    override val title = "川超 · 点球王"
    override val sub = "四川省城市足球联赛"
    override val category = "头部控制"
    override val hint = "头部左右瞄准 · 抬头射门 · 死角 +60"
    override val how = "瞄准球门死角，抬头起脚，10 球进 6 球"
    override val accent = Col.rgb(72, 196, 138)
    override val requires = setOf(InputChannel.HEAD)

    private companion object {
        const val CROSSBAR_Y = 392f
        const val GOAL_LINE_Y = 700f
        const val GOAL_L = 660f
        const val GOAL_R = 1260f
        const val SHOTS = 10
        const val WIN = 6
        const val BALL_X0 = 960f
        const val BALL_Y0 = 880f
    }

    private var shotI = 0
    private var goals = 0
    private var mScore = 0
    private var combo = 0
    private var aimX = 960f
    private var aimY = 560f
    private var flying = false
    private var ballX = 0f
    private var ballY = 0f
    private var ballVx = 0f
    private var ballVy = 0f
    private var keeperX = 960f
    private var keeperDive = 0f
    private var phaseT = 0f
    private var lastMsg = ""

    override val score: Int get() = mScore

    override fun reset() {
        state = STATE_PLAY
        shotI = 0; goals = 0; mScore = 0; combo = 0
        aimX = 960f; aimY = 560f
        flying = false
        keeperX = 960f; keeperDive = 0f
        phaseT = 0f; lastMsg = ""
        particles.clear()
    }

    override fun update(dt: Float, inp: GameInput) {
        if (state != STATE_PLAY) return
        phaseT += dt

        if (flying) {
            ballX += ballVx * dt
            ballY += ballVy * dt
            // 守门员扑救
            keeperDive += dt * 3f
            keeperX += (ballX - keeperX) * (1f - kotlin.math.exp(-3.2f * dt))

            if (ballY <= CROSSBAR_Y + 40f || ballY <= GOAL_LINE_Y && abs(ballX - GOAL_L) < 8f) {
                resolveShot()
            } else if (ballY < GOAL_LINE_Y - 20f && (ballX < GOAL_L || ballX > GOAL_R)) {
                // 打偏出门框
                resolveShot()
            }
            if (ballY < CROSSBAR_Y - 60f) resolveShot()
            return
        }

        // ---- 瞄准 ----
        aimX = (960f + inp.axis.coerceIn(-1f, 1f) * 430f).coerceIn(300f, 1620f)
        aimY = (560f - inp.headY.coerceIn(-1f, 1f) * 150f).coerceIn(CROSSBAR_Y + 40f, GOAL_LINE_Y - 30f)

        if (inp.jump) shoot()
    }

    private fun shoot() {
        flying = true
        ballX = BALL_X0
        ballY = BALL_Y0
        val dur = 0.52f
        ballVx = (aimX - BALL_X0) / dur
        ballVy = (aimY - BALL_Y0) / dur
        keeperX = 960f
        keeperDive = 0f
        addShake(4f)
        particles.burst(BALL_X0, BALL_Y0, 10, Col.rgb(240, 244, 252),
            speed = 260f, spread = 160f, dirDeg = 270f)
    }

    private fun resolveShot() {
        flying = false
        shotI++

        val inX = ballX > GOAL_L + 6f && ballX < GOAL_R - 6f
        val inY = ballY > CROSSBAR_Y && ballY < GOAL_LINE_Y
        // 守门员扑救范围
        val saved = abs(ballX - keeperX) < 90f && ballY > CROSSBAR_Y + 60f

        when {
            inX && inY && !saved -> {
                // 死角：靠近门框边角
                val edge = (ballX - GOAL_L < 110f) || (GOAL_R - ballX < 110f) ||
                    (ballY - CROSSBAR_Y < 90f)
                goals++
                combo++
                mScore += if (edge) 60 + combo * 10 else 40 + combo * 10
                lastMsg = if (edge) "死角！" else "进球"
                addShake(if (edge) 12f else 8f)
                flash(Col.rgb(255, 226, 140), 0.35f)
                particles.burst(ballX, ballY, if (edge) 30 else 18,
                    Col.rgb(255, 214, 96), speed = 380f, spread = 360f)
            }
            saved -> {
                combo = 0
                lastMsg = "被扑出"
                addShake(6f)
                particles.burst(ballX, ballY, 14, Col.rgb(200, 210, 226),
                    speed = 300f, spread = 360f)
            }
            else -> {
                combo = 0
                lastMsg = "打偏了"
                particles.burst(ballX, ballY, 12, Col.rgb(160, 170, 190),
                    speed = 260f, spread = 360f)
            }
        }

        if (shotI >= SHOTS) state = if (goals >= WIN) STATE_WIN else STATE_OVER
        phaseT = 0f
    }

    override fun draw(d: Canvas2D) {
        // 球场
        d.rect(0f, 0f, Design.W, Design.H, Col.rgb(34, 74, 52))
        for (i in 0 until 10) {
            if (i % 2 == 0) d.rect(0f, 300f + i * 78f, Design.W, 78f, Col.rgb(38, 82, 58))
        }
        d.rect(0f, 300f, Design.W, 6f, Col.rgb(240, 244, 250, 160))

        // 球门（透视：上窄下宽）
        val topL = GOAL_L + 40f
        val topR = GOAL_R - 40f
        d.rect(topL, CROSSBAR_Y, topR - topL, 14f, Col.rgb(240, 244, 252))
        d.rect(GOAL_L, CROSSBAR_Y, 14f, GOAL_LINE_Y - CROSSBAR_Y, Col.rgb(240, 244, 252))
        d.rect(GOAL_R - 14f, CROSSBAR_Y, 14f, GOAL_LINE_Y - CROSSBAR_Y, Col.rgb(240, 244, 252))
        // 网
        for (x in (GOAL_L.toInt() + 20)..(GOAL_R.toInt() - 20) step 40) {
            d.line(x.toFloat(), CROSSBAR_Y, x.toFloat(), GOAL_LINE_Y, Col.rgb(255, 255, 255, 70), 2f)
        }
        for (y in (CROSSBAR_Y.toInt() + 20)..(GOAL_LINE_Y.toInt() - 10) step 40) {
            d.line(GOAL_L, y.toFloat(), GOAL_R, y.toFloat(), Col.rgb(255, 255, 255, 70), 2f)
        }

        // 守门员
        val kx = keeperX
        d.roundRect(kx - 46f, GOAL_LINE_Y - 150f, 92f, 150f, 20f, Col.rgb(250, 214, 96))
        d.circle(kx, GOAL_LINE_Y - 176f, 26f, Col.rgb(246, 226, 200))

        // 球 / 瞄准准星
        if (flying) {
            if (!sprites.draw(d, "football", ballX, ballY, 56f, rotateDeg = ballX * 0.5f % 360f)) {
                d.circle(ballX, ballY, 28f, Col.rgb(250, 250, 252))
                d.circle(ballX, ballY, 28f, Col.rgb(40, 44, 56), 3f)
            }
        } else {
            // 准星
            d.arc(aimX, aimY, 26f, 0f, 360f, Col.rgb(255, 226, 140), 5f)
            d.line(aimX - 40f, aimY, aimX + 40f, aimY, Col.rgb(255, 226, 140), 4f)
            d.line(aimX, aimY - 40f, aimX, aimY + 40f, Col.rgb(255, 226, 140), 4f)
            if (!sprites.draw(d, "football", BALL_X0, BALL_Y0, 56f)) {
                d.circle(BALL_X0, BALL_Y0, 28f, Col.rgb(250, 250, 252))
            }
        }

        particles.draw(d)

        if (lastMsg.isNotEmpty()) {
            d.text(lastMsg, Design.W / 2, Design.TOP + 150f, 52f, Col.rgb(255, 226, 150),
                align = "center", bold = true)
        }
    }

    override fun hudItems(): List<HudItem> = listOf(
        HudItem("进球", "$goals / $WIN", Col.rgb(126, 231, 135)),
        HudItem("射门", "${(shotI + 1).coerceAtMost(SHOTS)}/$SHOTS", Col.rgb(226, 232, 240)),
        HudItem("连击", "$combo", Col.rgb(255, 226, 140)),
        HudItem("得分", "$mScore", accent),
    )
}
