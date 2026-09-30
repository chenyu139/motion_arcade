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
import kotlin.math.exp
import kotlin.math.hypot
import kotlin.random.Random

/**
 * 火锅大作战 —— 头部移动筷子 + 低头下筷（头控，头就是筷子本筷）。
 *
 * 操作：头部左右平移 → 移动筷子；低头 → 下筷（保持低头 = 连续捞）。
 * 按提示捞出**指定食材**，夹到辣椒扣命。60 秒内夹够 12 个目标食材。
 */
class HotpotGame(
    private val sprites: SpriteManager,
    private val bg: BackgroundManager,
) : BaseGame() {

    override val key = "hotpot"
    override val title = "火锅大作战"
    override val sub = "红油锅里捞目标"
    override val category = "头部控制"
    override val hint = "头部左右移动筷子 · 低头下筷 · 辣椒 = 扣命"
    override val how = "按提示捞出指定食材，别夹到辣椒"
    override val accent = Col.rgb(236, 92, 72)
    override val requires = setOf(InputChannel.HEAD)

    private companion object {
        const val POT_CX = 960f
        const val POT_CY = 690f
        const val POT_RX = 396f
        const val POT_RY = 300f
        const val TIME = 60f
        const val TARGET_GOALS = 12

        // kind, 显示名, 颜色
        val FOODS = arrayOf(
            intArrayOf(0, 0, 0) // 占位，实际用下面三个数组
        )
        val FOOD_NAME = arrayOf("毛肚", "鸭肠", "黄喉", "藕片", "土豆", "辣椒")
        val FOOD_COL = intArrayOf(
            Col.rgb(198, 120, 96), Col.rgb(226, 156, 120), Col.rgb(240, 226, 190),
            Col.rgb(236, 226, 176), Col.rgb(232, 206, 120), Col.rgb(226, 68, 52)
        )
        const val PEPPER = 5
    }

    private class Food {
        var x = 0f; var y = 0f
        var kind = 0
        var alive = true
        var bob = 0f
    }

    private val foods = ArrayList<Food>(14)
    private var left = TIME
    private var got = 0
    private var lives = 3
    private var mScore = 0
    private var chopX = 960f
    private var chopY = 520f
    private var dipping = false
    private var dipT = 0f
    private var targetKind = 0
    private var spawnCd = 0f

    override val score: Int get() = mScore

    override fun reset() {
        state = STATE_PLAY
        left = TIME; got = 0; lives = 3; mScore = 0
        chopX = 960f; chopY = 520f
        dipping = false; dipT = 0f
        spawnCd = 0f
        foods.clear()
        particles.clear()
        pickTarget()
        repeat(7) { spawnFood() }
    }

    private fun pickTarget() {
        targetKind = Random.nextInt(PEPPER)      // 不含辣椒
    }

    private fun spawnFood() {
        val f = Food()
        val a = Random.nextFloat() * 6.283f
        val r = Random.nextFloat()
        f.x = POT_CX + kotlin.math.cos(a) * POT_RX * 0.82f * r
        f.y = POT_CY + kotlin.math.sin(a) * POT_RY * 0.82f * r
        f.kind = if (Random.nextFloat() < 0.22f) PEPPER else Random.nextInt(PEPPER)
        f.bob = Random.nextFloat() * 6.28f
        foods.add(f)
    }

    override fun update(dt: Float, inp: GameInput) {
        if (state != STATE_PLAY) return

        left -= dt
        if (left <= 0f) { state = if (got >= TARGET_GOALS) STATE_WIN else STATE_OVER; return }

        // ---- 筷子移动 ----
        chopX = (960f + inp.axis.coerceIn(-1f, 1f) * 620f).coerceIn(260f, 1660f)
        if (!dipping) chopY = 500f

        // ---- 下筷 ----
        if (dipping) {
            dipT -= dt
            chopY += (POT_CY - chopY) * (1f - exp(-14f * dt))
            if (dipT <= 0f) {
                // 判定夹取
                var best: Food? = null
                var bestD = 140f
                for (f in foods) {
                    if (!f.alive) continue
                    val d = hypot(f.x - chopX, f.y - chopY)
                    if (d < bestD) { bestD = d; best = f }
                }
                val f = best
                if (f != null) {
                    if (f.kind == PEPPER) {
                        lives--
                        addShake(14f)
                        flash(Col.rgb(255, 90, 70), 0.4f)
                        particles.burst(f.x, f.y, 20, Col.rgb(226, 68, 52),
                            speed = 360f, spread = 360f)
                        lastMsg = "辣椒！"
                    } else if (f.kind == targetKind) {
                        got++
                        mScore += 100
                        particles.burst(f.x, f.y, 16, FOOD_COL[f.kind],
                            speed = 320f, spread = 360f)
                        addShake(4f)
                        lastMsg = "捞到了"
                        pickTarget()
                    } else {
                        mScore += 20
                        particles.burst(f.x, f.y, 10, FOOD_COL[f.kind],
                            speed = 240f, spread = 360f)
                        lastMsg = "不是这个"
                    }
                    f.alive = false
                }
                dipping = false
            }
        } else if (inp.duck) {
            // 低头 = 筷子往下：头就是筷子，保持低头就是"在锅里捞"
            dipping = true
            dipT = 0.45f
        }

        // ---- 食材漂浮 + 补充 ----
        for (f in foods) f.bob += dt * 1.6f
        foods.removeAll { !it.alive }
        spawnCd -= dt
        if (spawnCd <= 0f && foods.size < 12) {
            spawnCd = 0.5f
            spawnFood()
        }

        if (lives <= 0) state = STATE_OVER
        if (got >= TARGET_GOALS) state = STATE_WIN
    }

    private var lastMsg = ""

    override fun draw(d: Canvas2D) {
        bg.drawOr(d, "sky_teahouse", Design.W, Design.H,
            Col.rgb(52, 26, 24), Col.rgb(96, 44, 36), Col.rgb(34, 18, 16))

        // 锅体暖光垫底（让"红油锅"成为画面焦点）
        d.glow(POT_CX, POT_CY - 20f, POT_RX * 1.7f, Col.rgb(255, 170, 90, 55))

        // 锅
        d.ellipse(POT_CX, POT_CY, POT_RX, POT_RY, Col.rgb(150, 44, 36))
        d.ellipse(POT_CX, POT_CY, POT_RX - 18f, POT_RY - 14f, Col.rgb(196, 62, 44))
        // 红油高光
        d.ellipse(POT_CX - 80f, POT_CY - 60f, 120f, 60f, Col.rgb(226, 104, 62))
        // 九宫格分隔
        d.line(POT_CX - POT_RX * 0.5f, POT_CY - POT_RY * 0.62f,
            POT_CX - POT_RX * 0.5f, POT_CY + POT_RY * 0.62f, Col.rgb(150, 40, 32), 6f)
        d.line(POT_CX + POT_RX * 0.5f, POT_CY - POT_RY * 0.62f,
            POT_CX + POT_RX * 0.5f, POT_CY + POT_RY * 0.62f, Col.rgb(150, 40, 32), 6f)

        // 食材
        for (f in foods) {
            val bobY = f.y + kotlin.math.sin(f.bob) * 8f
            val wanted = f.kind == targetKind
            if (wanted) {
                d.circle(f.x, bobY, 40f, Col.rgb(255, 226, 140, 90))
            }
            d.ellipse(f.x, bobY, 30f, 22f, FOOD_COL[f.kind])
            d.ellipse(f.x, bobY, 30f, 22f, Col.shade(FOOD_COL[f.kind], 0.6f), 3f)
        }

        // 筷子
        val cy = chopY
        for (s in intArrayOf(-1, 1)) {
            d.line(chopX + s * 14f, cy - 260f, chopX + s * 4f, cy, Col.rgb(214, 178, 120), 12f)
        }

        // 锅沿高光
        d.arc(POT_CX, POT_CY, POT_RX - 6f, 180f, 180f, Col.rgb(255, 220, 170, 55), 4f)

        // 蒸汽：几缕白汽沿锅面升腾、摆动、渐隐（火锅氛围的核心）
        for (i in 0 until 7) {
            val cycle = (t * 0.42f + i * 0.149f) % 1f
            val sx = POT_CX + (i - 3) * 46f + kotlin.math.sin(cycle * 7f + i * 1.7f) * 16f
            val sy = POT_CY - 30f - cycle * 330f
            val a = ((1f - cycle) * (cycle * 5f).coerceAtMost(1f) * 115f).toInt()
            d.circle(sx, sy, 16f + cycle * 26f, Col.rgb(246, 242, 236, a))
        }

        particles.draw(d)

        // 目标提示
        d.text("目标：${FOOD_NAME[targetKind]}", Design.W / 2, Design.TOP + 96f, 40f,
            Col.rgb(255, 226, 150), align = "center", bold = true)
        if (lastMsg.isNotEmpty()) {
            d.text(lastMsg, Design.W / 2, Design.TOP + 160f, 34f, Col.rgb(255, 255, 255),
                align = "center", bold = true)
        }
    }

    override fun hudItems(): List<HudItem> = listOf(
        HudItem("已捞", "$got / $TARGET_GOALS", Col.rgb(255, 226, 140)),
        HudItem("生命", "$lives", Col.rgb(255, 140, 120), icon = "heart"),
        HudItem("时间", "${maxOf(0f, left).toInt()}", Col.rgb(226, 232, 240)),
        HudItem("得分", "$mScore", accent),
    )
}
