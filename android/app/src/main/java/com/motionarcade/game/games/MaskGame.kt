package com.motionarcade.game.games

import com.motionarcade.game.BaseGame
import com.motionarcade.game.Design
import com.motionarcade.game.HudItem
import com.motionarcade.render.Canvas2D
import com.motionarcade.render.Col
import com.motionarcade.render.SpriteManager
import com.motionarcade.audio.Sfx
import com.motionarcade.vision.GameInput
import com.motionarcade.vision.InputChannel
import kotlin.math.sin
import kotlin.random.Random

/**
 * 川剧变脸 —— 手掌横扫过脸 = 变脸（手控）。
 *
 * **动词来自文化动作本身**：真实演员变脸就是"手在脸前一抹"，玩家零学习成本。
 * 操作：手掌抬到脸的高度，快速横扫 → 脸谱切换；
 * 变出屏幕上方提示的目标脸谱 → 得分（连击加成）。
 * 目标：60 秒内匹配越多越好。
 */
class MaskGame(private val sprites: SpriteManager) : BaseGame() {

    override val key = "mask"
    override val title = "川剧变脸"
    override val sub = "手扫过脸 · 一秒换脸"
    override val category = "手控"
    override val hint = "手掌抬到脸的高度 · 快速横扫变脸 · 变出目标脸谱"
    override val how = "扫脸换妆，匹配目标脸谱，60 秒看你能对几次"
    override val accent = Col.rgb(226, 68, 92)
    override val difficulty = 2
    override val requires = setOf(InputChannel.HAND)

    private companion object {
        const val ROUND = 60f
        const val WIN_SCORE = 600
        const val FACE_X = 960f
        const val FACE_Y = 560f
        const val FACE_H = 420f
        const val SWAP_T = 0.22f
        const val LOCK_CD = 0.5f

        /** 五张脸谱（素材池里有同名精灵）。 */
        val FACES = listOf("mask_red", "mask_gold", "mask_green", "mask_black", "mask_blue")

        /** 缺图回退的脸谱底色。 */
        val FALLBACK = intArrayOf(
            Col.rgb(198, 40, 40), Col.rgb(216, 168, 52), Col.rgb(46, 140, 86),
            Col.rgb(34, 34, 40), Col.rgb(44, 96, 190)
        )
    }

    private var cur = 0            // 当前脸谱
    private var target = 0         // 目标脸谱
    private var mScore = 0
    private var combo = 0
    private var bestCombo = 0
    private var matches = 0
    private var left = ROUND
    private var swapT = 0f
    private var lockCd = 0f
    private var lastMsg = ""
    private var msgT = 0f

    // 手掌位置缓存（draw 用；update 时从 GameInput 取）
    private var handOk = false
    private var handX = 0.5f
    private var handY = 0.5f

    override val score: Int get() = mScore

    override fun reset() {
        state = STATE_PLAY
        cur = Random.nextInt(FACES.size)
        do { target = Random.nextInt(FACES.size) } while (target == cur)
        mScore = 0; combo = 0; bestCombo = 0; matches = 0
        left = ROUND; swapT = 0f; lockCd = 0f; lastMsg = ""; msgT = 0f
        particles.clear()
    }

    private fun pickNextTarget() {
        do { target = Random.nextInt(FACES.size) } while (target == cur)
    }

    override fun update(dt: Float, inp: GameInput) {
        if (state != STATE_PLAY) return

        handOk = inp.handFound
        handX = inp.hx
        handY = inp.hy

        left -= dt
        if (left <= 0f) {
            state = if (mScore >= WIN_SCORE) STATE_WIN else STATE_OVER
            return
        }
        swapT = maxOf(0f, swapT - dt)
        lockCd = maxOf(0f, lockCd - dt)
        msgT = maxOf(0f, msgT - dt)

        // ---- 变脸：手在脸的高度 + 横扫边沿 ----
        val handAtFace = inp.handFound && inp.hy < 0.52f   // 摄像头画面上半部 ≈ 脸的高度
        if (handAtFace && inp.swing != 0 && lockCd <= 0f) {
            lockCd = LOCK_CD
            swapT = SWAP_T
            var next: Int
            do { next = Random.nextInt(FACES.size) } while (next == cur)
            cur = next
            addShake(4f)
            particles.burst(FACE_X, FACE_Y, 14, Col.rgb(255, 214, 96),
                speed = 300f, spread = 360f)

            if (cur == target) {
                combo++
                bestCombo = maxOf(bestCombo, combo)
                matches++
                mScore += 100 + combo * 10
                lastMsg = "变！"
                msgT = 0.8f
                Sfx.play("gong")
                flash(Col.rgb(255, 226, 140), 0.30f)
                particles.burst(FACE_X, FACE_Y, 30, Col.rgb(255, 214, 96),
                    speed = 420f, spread = 360f)
                pickNextTarget()
            } else {
                combo = 0
                lastMsg = "没对上"
                msgT = 0.8f
                Sfx.play("fail")
            }
        }
    }

    override fun draw(d: Canvas2D) {
        // ---- 戏台：深红幕布 + 两侧灯笼 ----
        d.rect(0f, 0f, Design.W, Design.H, Col.rgb(30, 12, 16))
        for (k in 0 until 8) {
            val x = k * Design.W / 7f
            d.rect(x - 26f, 0f, 52f, Design.H.toFloat(),
                if (k % 2 == 0) Col.rgb(74, 20, 26) else Col.rgb(58, 16, 22))
        }
        d.rect(0f, 0f, Design.W, 70f, Col.rgb(48, 14, 18))
        // 追光
        d.polygon(floatArrayOf(
            FACE_X - 120f, 0f, FACE_X + 120f, 0f,
            FACE_X + 320f, Design.H.toFloat(), FACE_X - 320f, Design.H.toFloat()
        ), Col.rgb(255, 232, 190, 26))
        for (lx in floatArrayOf(140f, Design.W - 140f)) {
            drawLantern(d, lx, 170f)
        }

        // ---- 演员身段（肩 + 领口）----
        d.ellipse(FACE_X, FACE_Y + 330f, 330f, 200f, Col.rgb(40, 26, 44))
        d.ellipse(FACE_X, FACE_Y + 300f, 250f, 130f, Col.rgb(120, 34, 48))
        d.roundRect(FACE_X - 130f, FACE_Y + 150f, 260f, 110f, 30f, Col.rgb(226, 186, 120))

        // ---- 当前脸谱（切换时做一个"压缩-弹开"）----
        val pop = if (swapT > 0f) 1f + 0.18f * sin(swapT / SWAP_T * Math.PI.toFloat()) else 1f
        val h = FACE_H * pop
        val drawn = sprites.draw(d, FACES[cur], FACE_X, FACE_Y, h)
        if (!drawn) drawFallbackFace(d, FACE_X, FACE_Y, h, cur)

        // ---- 目标脸谱（上方小窗）----
        d.roundRect(Design.W / 2 - 110f, Design.TOP + 8f, 220f, 250f, 20f,
            Col.rgb(16, 10, 12, 215))
        d.roundRect(Design.W / 2 - 110f, Design.TOP + 8f, 220f, 250f, 20f,
            Col.rgb(255, 214, 96), 3f)
        d.text("目标", Design.W / 2, Design.TOP + 44f, 26f, Col.rgb(255, 214, 96),
            align = "center", bold = true)
        val tDrawn = sprites.draw(d, FACES[target], Design.W / 2,
            Design.TOP + 172f, 150f)
        if (!tDrawn) drawFallbackFace(d, Design.W / 2, Design.TOP + 172f, 150f, target)

        // ---- 手掌光标（让玩家确信"手被看到了"；绿色=在变脸高度区内）----
        if (handOk) {
            val hx = handX * Design.W
            val hy = Design.TOP + handY * Design.GAME_H
            val zone = handY < 0.52f
            d.circle(hx, hy, 34f, if (zone) Col.rgb(126, 231, 135, 120)
            else Col.rgb(255, 184, 84, 120))
            d.circle(hx, hy, 34f, if (zone) Col.rgb(126, 231, 135)
            else Col.rgb(255, 184, 84), 3f)
        }

        particles.draw(d)

        // ---- 连击 / 反馈 ----
        if (combo >= 2) {
            d.text("连击 ×$combo", 150f, Design.TOP + 40f, 34f,
                Col.rgb(255, 214, 96), bold = true)
        }
        if (msgT > 0f && lastMsg.isNotEmpty()) {
            d.text(lastMsg, Design.W / 2, Design.H - 180f, 56f,
                if (lastMsg == "变！") Col.rgb(255, 226, 140) else Col.rgb(255, 140, 120),
                align = "center", bold = true)
        }
        // 计时条
        val tw = 300f * (left / ROUND).coerceIn(0f, 1f)
        d.roundRect(Design.W / 2 - 150f, Design.BOT - 40f, 300f, 12f, 6f,
            Col.rgb(16, 10, 12, 200))
        d.roundRect(Design.W / 2 - 150f, Design.BOT - 40f, tw, 12f, 6f,
            if (left < 10f) Col.rgb(255, 140, 120) else Col.rgb(255, 214, 96))
    }

    /** 缺图回退：按索引画一张有辨识度的矢量脸谱。 */
    private fun drawFallbackFace(d: Canvas2D, cx: Float, cy: Float, h: Float, idx: Int) {
        val r = h * 0.42f
        d.ellipse(cx, cy, r * 0.86f, r, FALLBACK[idx])
        d.ellipse(cx, cy, r * 0.86f, r, Col.rgb(0, 0, 0, 60), 4f)
        // 眼白 + 瞳
        for (s in floatArrayOf(-1f, 1f)) {
            val ex = cx + s * r * 0.34f
            d.ellipse(ex, cy - r * 0.12f, r * 0.20f, r * 0.13f, Col.rgb(244, 238, 226))
            d.circle(ex, cy - r * 0.12f, r * 0.055f, Col.rgb(20, 18, 24))
        }
        // 额头纹样（按脸谱区分）
        when (idx) {
            0 -> d.circle(cx, cy - r * 0.44f, r * 0.10f, Col.rgb(255, 226, 140))
            1 -> d.polygon(floatArrayOf(cx, cy - r * 0.58f, cx + r * 0.12f, cy - r * 0.36f,
                cx - r * 0.12f, cy - r * 0.36f), Col.rgb(30, 26, 30))
            2 -> d.rect(cx - r * 0.10f, cy - r * 0.58f, r * 0.20f, r * 0.22f,
                Col.rgb(244, 238, 226))
            3 -> d.rect(cx - r * 0.30f, cy - r * 0.46f, r * 0.60f, r * 0.07f,
                Col.rgb(244, 238, 226))
            4 -> d.circle(cx, cy - r * 0.44f, r * 0.09f, Col.rgb(244, 238, 226))
        }
        // 嘴
        d.ellipse(cx, cy + r * 0.38f, r * 0.16f, r * 0.09f, Col.rgb(120, 30, 30))
    }

    private fun drawLantern(d: Canvas2D, x: Float, y: Float) {
        d.line(x, y - 90f, x, y - 40f, Col.rgb(120, 60, 40), 3f)
        d.ellipse(x, y, 46f, 58f, Col.rgb(214, 60, 52))
        d.ellipse(x, y, 46f, 58f, Col.rgb(255, 190, 120, 90), 3f)
        for (k in -1..1) d.line(x + k * 22f, y - 56f, x + k * 22f, y + 56f,
            Col.rgb(255, 190, 120, 70), 2f)
        d.rect(x - 10f, y - 64f, 20f, 10f, Col.rgb(220, 180, 90))
        for (k in 0 until 3) d.line(x - 8f + k * 8f, y + 58f, x - 8f + k * 8f, y + 84f,
            Col.rgb(220, 180, 90), 2f)
    }

    override fun hudItems(): List<HudItem> = listOf(
        HudItem("得分", "$mScore", accent),
        HudItem("匹配", "$matches", Col.rgb(126, 231, 135)),
        HudItem("连击", "$combo", Col.rgb(255, 226, 140)),
        HudItem("时间", "${maxOf(0f, left).toInt()}", Col.rgb(226, 232, 240)),
    )
}
