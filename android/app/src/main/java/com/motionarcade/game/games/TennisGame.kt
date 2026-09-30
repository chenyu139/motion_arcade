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
import kotlin.math.hypot
import kotlin.random.Random

/**
 * 川网 · 底线对拉 —— 头部跑位 + 手掌横扫挥拍（头 + 手分工）。
 *
 * 操作：头部左右平移 → 沿底线跑位；手掌横扫 → 挥拍（身体动作即挥拍本身），
 * **拍面与球的距离决定 完美 / 良好 / 勉强**（判定深度所在）。
 * 目标：先得 5 分。
 */
class TennisGame(private val sprites: SpriteManager) : BaseGame() {

    override val key = "tennis"
    override val title = "川网 · 底线对拉"
    override val sub = "2026 四川城市网球联赛"
    override val category = "头部 + 手部"
    override val hint = "头部左右跑位 · 手掌横扫挥拍 · 看准拍面与球的距离"
    override val how = "跑到位、扫手挥拍，先到 5 分"
    override val accent = Col.rgb(96, 196, 244)
    override val requires = setOf(InputChannel.HEAD, InputChannel.HAND)

    private companion object {
        const val GROUND = 892f
        const val NET_X = 960f
        const val NET_TOP = GROUND - 214
        const val WIN_SCORE = 5
        const val PLAYER_Y = GROUND - 60f
    }

    private var px = 960f
    private var vx = 0f
    private var scoreMe = 0
    private var scoreOp = 0
    private var rally = 0
    private var swing = 0f             // 挥拍动画 0~1
    private var swingCd = 0f

    // 球
    private var ballX = 960f
    private var ballY = 500f
    private var ballVx = 0f
    private var ballVy = 0f
    private var ballLive = false
    private var incoming = false       // true = 球朝玩家飞来
    private var lastMsg = ""

    // 球拖尾（最近 9 个位置，渐隐）
    private val trail = ArrayList<Pair<Float, Float>>(9)

    override val score: Int get() = scoreMe * 100 + rally * 10

    override fun reset() {
        state = STATE_PLAY
        px = 960f; vx = 0f
        scoreMe = 0; scoreOp = 0; rally = 0
        swing = 0f; swingCd = 0f
        ballLive = false; incoming = false
        lastMsg = ""
        particles.clear()
        serve()
    }

    private fun serve() {
        ballX = 960f + Random.nextFloat() * 300f - 150f
        ballY = 460f
        ballVx = (Random.nextFloat() - 0.5f) * 300f
        ballVy = 420f
        ballLive = true
        incoming = true
        trail.clear()
    }

    override fun update(dt: Float, inp: GameInput) {
        if (state != STATE_PLAY) return

        // ---- 跑位 ----
        val target = 960f + inp.axis.coerceIn(-1f, 1f) * 700f
        px += (target - px) * (1f - exp(-7f * dt))
        px = px.coerceIn(180f, Design.W - 180f)

        // ---- 挥拍 ----
        swingCd = maxOf(0f, swingCd - dt)
        if (swing > 0f) swing = (swing - dt * 3.2f).coerceAtLeast(0f)

        if (inp.swing != 0 && swingCd <= 0f) {
            swing = 1f
            swingCd = 0.42f
            tryHit()
        }

        // ---- 球飞行 ----
        if (ballLive) {
            ballVy += 1450f * dt
            ballX += ballVx * dt
            ballY += ballVy * dt
            trail.add(ballX to ballY)
            if (trail.size > 9) trail.removeAt(0)

            // 玩家侧底线：没接到 → 对手得分
            if (incoming && ballY > GROUND) {
                scoreOp++
                rally = 0
                lastMsg = "没接到"
                addShake(6f)
                particles.burst(ballX, GROUND, 12, Col.rgb(200, 210, 226),
                    speed = 240f, spread = 300f)
                ballLive = false
                checkEnd()
                if (state == STATE_PLAY) serve()
                return
            }
            // 对手侧：飞过网且落地 → 玩家得分
            if (!incoming && ballY > GROUND - 120f) {
                scoreMe++
                rally++
                lastMsg = "得分"
                addShake(5f)
                particles.burst(ballX, GROUND - 120f, 14, Col.rgb(255, 226, 140),
                    speed = 300f, spread = 360f)
                ballLive = false
                checkEnd()
                if (state == STATE_PLAY) serve()
                return
            }
            // 打到网上
            if (abs(ballX - NET_X) < 30f && ballY in NET_TOP..(GROUND - 40f) && ballVx * (NET_X - ballX) < 0f) {
                lastMsg = "下网"
                rally = 0
                ballLive = false
                if (state == STATE_PLAY) serve()
            }
        }
    }

    /** 挥拍判定：拍面与球的距离 → 完美 / 良好 / 勉强。 */
    private fun tryHit() {
        if (!ballLive || !incoming) return
        val rx = px + 72f
        val ry = GROUND - 150f
        val d = hypot(ballX - rx, ballY - ry)
        when {
            d < 90f -> {   // 完美
                rally++
                lastMsg = "完美击球"
                ballVy = -1000f
                ballVx = (NET_X + (Random.nextFloat() * 500f - 250f) - ballX) * 1.5f
                incoming = false
                addShake(7f)
                particles.burst(ballX, ballY, 18, Col.rgb(255, 226, 140),
                    speed = 340f, spread = 360f)
            }
            d < 180f -> {  // 良好
                rally++
                lastMsg = "良好"
                ballVy = -880f
                ballVx = (NET_X - ballX) * 1.3f
                incoming = false
                addShake(4f)
                particles.burst(ballX, ballY, 10, Col.rgb(200, 226, 250),
                    speed = 280f, spread = 360f)
            }
            else -> {      // 勉强（够不着）
                lastMsg = "够不着"
            }
        }
    }

    private fun checkEnd() {
        if (scoreMe >= WIN_SCORE) state = STATE_WIN
        else if (scoreOp >= WIN_SCORE) state = STATE_OVER
    }

    override fun draw(d: Canvas2D) {
        // 球场
        d.vGradient(0f, 0f, Design.W, Design.H,
            Col.rgb(22, 48, 74), Col.rgb(30, 62, 92), Col.rgb(44, 92, 130))
        d.rect(0f, NET_TOP, Design.W, GROUND - NET_TOP + 60f, Col.rgb(38, 96, 140))
        // 底线白线
        d.line(180f, GROUND, Design.W - 180f, GROUND, Col.rgb(240, 244, 250, 200), 6f)
        d.line(180f, GROUND - 120f, Design.W - 180f, GROUND - 120f, Col.rgb(240, 244, 250, 120), 4f)
        d.line(180f, GROUND, 180f, GROUND - 120f, Col.rgb(240, 244, 250, 160), 4f)
        d.line(Design.W - 180f, GROUND, Design.W - 180f, GROUND - 120f,
            Col.rgb(240, 244, 250, 160), 4f)

        // 网
        d.rect(NET_X - 6f, NET_TOP, 12f, 100f, Col.rgb(240, 244, 250))
        for (y in (NET_TOP.toInt())..(NET_TOP.toInt() + 100) step 12) {
            d.line(NET_X - 6f, y.toFloat(), NET_X + 6f, y.toFloat(), Col.rgb(200, 210, 226), 2f)
        }

        // 对手（上方）
        d.roundRect(960f - 26f, NET_TOP - 150f, 52f, 110f, 16f, Col.rgb(232, 96, 72))
        d.circle(960f, NET_TOP - 172f, 24f, Col.rgb(246, 226, 200))

        // 玩家
        d.roundRect(px - 26f, PLAYER_Y - 100f, 52f, 100f, 16f, accent)
        d.circle(px, PLAYER_Y - 122f, 24f, Col.rgb(246, 226, 200))
        // 球拍
        val sw = (1f - swing) * 0f + swing
        val rx = px + 72f + sw * 46f
        val ry = GROUND - 150f - sw * 66f
        d.ellipse(rx, ry, 30f, 40f, Col.rgb(24, 30, 46))
        d.ellipse(rx, ry, 24f, 34f, Col.rgb(60, 200, 236))

        // 球（拖尾渐隐）
        if (ballLive) {
            for ((ti, p) in trail.withIndex()) {
                val t = (ti + 1f) / trail.size
                d.circle(p.first, p.second, 7f + 8f * t,
                    Col.alpha(Col.rgb(214, 236, 96), (70 * t).toInt()))
            }
            if (!sprites.draw(d, "tennis_ball", ballX, ballY, 40f)) {
                d.circle(ballX, ballY, 20f, Col.rgb(214, 236, 96))
                d.circle(ballX, ballY, 20f, Col.rgb(180, 200, 60), 3f)
            }
        }

        particles.draw(d)

        if (lastMsg.isNotEmpty()) {
            d.text(lastMsg, Design.W / 2, Design.TOP + 150f, 46f, Col.rgb(255, 226, 150),
                align = "center", bold = true)
        }
    }

    override fun hudItems(): List<HudItem> = listOf(
        HudItem("本方", "$scoreMe", accent),
        HudItem("对手", "$scoreOp", Col.rgb(255, 140, 120)),
        HudItem("回合", "$rally", Col.rgb(255, 226, 140)),
    )
}
