package com.motionarcade.ui

import com.motionarcade.game.BaseGame
import com.motionarcade.game.Design
import com.motionarcade.render.Canvas2D
import com.motionarcade.render.Col
import com.motionarcade.vision.GameInput
import kotlin.math.abs
import kotlin.math.sin
import kotlin.random.Random

/**
 * 游戏大厅。
 *
 * 两种选法都支持：
 *  · **触摸**（手机上最直接）：点卡片即进入；
 *  · **头部**（无接触体验）：左右转头移动高亮，点头进入。
 *
 * 视觉：黄昏戏台 —— 暮色渐变天空、星野、落日、双层山影、地面光带；
 * 卡片是"强调色染色的竖向渐变面板 + 投影 + 选中辉光"。
 * 整套背景程序绘制，不依赖任何图片素材。
 */
class Menu {

    private companion object {
        // 暮色世界
        val SKY_TOP = Col.rgb(20, 26, 62)
        val SKY_MID = Col.rgb(62, 47, 99)
        val SKY_LOW = Col.rgb(180, 106, 106)
        val SUN = Col.rgb(255, 190, 134)
        val RIDGE_FAR = Col.rgb(56, 40, 84)
        val RIDGE_NEAR = Col.rgb(38, 28, 62)
        val GROUND_TOP = Col.rgb(46, 34, 80)
        val GROUND_BOT = Col.rgb(22, 16, 44)

        // 卡面
        val SURFACE_HI = Col.rgb(58, 64, 96)
        val SURFACE_LO = Col.rgb(30, 34, 54)
        val PAPER_DIM = Col.rgb(178, 188, 210)
        val HOW_DIM = Col.rgb(150, 160, 184)
        val GOLD = Col.rgb(255, 214, 120)
    }

    private var games: List<BaseGame> = emptyList()
    var selected = 0
    private var hoverT = 0f
    private var axisLatch = false

    // ---- 星野（确定性伪随机：位置固定、亮度按相位闪烁）----
    private val starX = FloatArray(90)
    private val starY = FloatArray(90)
    private val starR = FloatArray(90)
    private val starPhase = FloatArray(90)

    init {
        val rng = Random(5)
        for (i in starX.indices) {
            starX[i] = rng.nextFloat() * Design.W
            starY[i] = rng.nextFloat() * 540f
            starR[i] = 1.2f + rng.nextFloat() * 1.8f
            starPhase[i] = rng.nextFloat() * 6.28f
        }
    }

    /** 供外壳判断"玩家确认进入某一款"了。 */
    var onEnter: ((BaseGame) -> Unit)? = null

    /** 高亮移动（换了一款）时通知，用于播"嗒"的音效。 */
    var onMove: (() -> Unit)? = null

    // ---- 自适应网格：≤4 款 3 列大卡，其余 4 列紧凑卡 ----
    private val dense: Boolean get() = games.size > 4
    private val cols: Int get() = if (dense) 4 else 3
    private val cardW: Float get() = if (dense) 420f else 520f
    private val cardH: Float get() = if (dense) 330f else 300f
    private val gap: Float get() = if (dense) 30f else 40f
    private val gridX: Float get() = (Design.W - (cols * cardW + (cols - 1) * gap)) / 2f
    private val gridY: Float get() = if (dense) 300f else 250f

    fun attach(list: List<BaseGame>) {
        games = list
        selected = 0
    }

    fun cardRect(i: Int): FloatArray {
        val c = i % cols
        val r = i / cols
        return floatArrayOf(
            gridX + c * (cardW + gap),
            gridY + r * (cardH + gap),
            cardW, cardH
        )
    }

    /** 触摸（设计坐标）→ 命中卡片则返回索引。 */
    fun hitTest(x: Float, y: Float): Int {
        for (i in games.indices) {
            val r = cardRect(i)
            if (x >= r[0] && x <= r[0] + r[2] && y >= r[1] && y <= r[1] + r[3]) return i
        }
        return -1
    }

    fun onTap(x: Float, y: Float) {
        val i = hitTest(x, y)
        if (i >= 0) {
            selected = i
            onEnter?.invoke(games[i])
        }
    }

    fun update(dt: Float, inp: GameInput) {
        if (games.isEmpty()) return
        hoverT += dt

        // 头部：左右转头换选中（用"闩锁"避免一直偏头就连续翻页）
        val axis = inp.axis
        if (abs(axis) > 0.42f) {
            if (!axisLatch) {
                axisLatch = true
                selected = if (axis > 0) {
                    (selected + 1) % games.size
                } else {
                    (selected - 1 + games.size) % games.size
                }
                onMove?.invoke()
            }
        } else if (abs(axis) < 0.18f) {
            axisLatch = false
        }

        if (inp.jump) onEnter?.invoke(games[selected])
    }

    fun draw(d: Canvas2D) {
        drawBackdrop(d)
        drawTitleBar(d)

        val tx = if (dense) 38f else 52f
        val titleSize = if (dense) 32f else 44f
        val subSize = if (dense) 21f else 26f
        val catSize = if (dense) 21f else 26f
        val howSize = if (dense) 18f else 24f

        for (i in games.indices) {
            val g = games[i]
            val r = cardRect(i)
            drawCard(d, g, r, i == selected, tx, titleSize, subSize, catSize, howSize)
        }

        d.shadowText("点卡片进入　·　或用头左右转选择、点头确认",
            Design.W / 2, Design.BOT + 28f, 26f, PAPER_DIM, align = "center")
    }

    // ------------------------------------------------------------------ 背景

    private fun drawBackdrop(d: Canvas2D) {
        // 暮色天空
        d.vGradient(0f, 0f, Design.W, 820f, SKY_TOP, SKY_MID, SKY_LOW)
        // 星野（只在天上半区）
        for (i in starX.indices) {
            val a = (0.30f + 0.35f * (0.5f + 0.5f * sin(hoverT * 1.3f + starPhase[i])))
            d.circle(starX[i], starY[i], starR[i], Col.alpha(Col.rgb(236, 232, 252),
                (a * 255).toInt()))
        }
        // 落日 + 光晕
        d.glow(Design.W * 0.74f, 660f, 260f, Col.rgb(255, 190, 134, 80))
        d.circle(Design.W * 0.74f, 660f, 84f, SUN)
        // 双层山影
        drawRidge(d, baseY = 640f, amp = 95f, seg = 340f, seed = 1.7f, color = RIDGE_FAR)
        drawRidge(d, baseY = 700f, amp = 70f, seg = 240f, seed = 4.3f, color = RIDGE_NEAR)
        // 地面光带
        d.vGradient(0f, 790f, Design.W, Design.H - 790f, GROUND_TOP, GROUND_BOT)
        d.rect(0f, 788f, Design.W, 3f, Col.rgb(255, 190, 134, 70))
    }

    /** 山脊剪影：两条正弦叠加生成确定性轮廓。 */
    private fun drawRidge(d: Canvas2D, baseY: Float, amp: Float, seg: Float,
                          seed: Float, color: Int) {
        val pts = ArrayList<Float>((Design.W / seg + 3).toInt() * 2)
        var x = -seg
        while (x <= Design.W + seg) {
            val y = baseY - amp * (0.6f * sin(seed + x / 620f) + 0.4f * sin(seed * 2.1f + x / 240f))
            pts.add(x); pts.add(y)
            x += seg
        }
        pts.add(Design.W.toFloat()); pts.add(baseY + 320f)
        pts.add(0f); pts.add(baseY + 320f)
        d.polygon(pts.toFloatArray(), color)
    }

    private fun drawTitleBar(d: Canvas2D) {
        d.shadowText("体感游戏厅", 56f, 86f, 58f, Col.rgb(255, 250, 240),
            offset = 4f, bold = true)
        d.text("MOTION ARCADE · 四川文旅", 60f, 130f, 22f, Col.rgb(208, 198, 238), bold = true)
        val n = games.size
        d.text("精选 $n 款", Design.W - 60f, 86f, 30f, GOLD, align = "right", bold = true)
    }

    // ------------------------------------------------------------------ 卡片

    private fun drawCard(d: Canvas2D, g: BaseGame, r: FloatArray, sel: Boolean,
                         tx: Float, titleSize: Float, subSize: Float,
                         catSize: Float, howSize: Float) {
        val pulse = if (sel) 1f + 0.012f * sin(hoverT * 3f) else 1f
        val cx = r[0] + r[2] / 2
        val cy = r[1] + r[3] / 2
        // 选中辉光垫底
        if (sel) d.glow(cx, cy, r[2] * 0.8f, Col.alpha(g.accent, 70))

        // 投影
        d.roundRect(r[0] + 5f, r[1] + 10f, r[2], r[3], 26f, Col.rgb(8, 6, 20, 150))
        // 卡面：强调色染色的竖向渐变
        val hi = Col.mix(SURFACE_HI, g.accent, 0.16f)
        val lo = Col.mix(SURFACE_LO, g.accent, 0.05f)
        d.vGradient(r[0], r[1], r[2], r[3], hi, lo)
        d.roundRect(r[0], r[1], r[2], r[3], 26f,
            if (sel) g.accent else Col.rgb(70, 78, 106), if (sel) 5f else 2f)

        // 强调色条
        d.roundRect(r[0] + 18f, r[1] + 22f, 8f, r[3] - 44f, 4f, g.accent)

        // 标题 / 副标题
        d.shadowText(g.title, r[0] + tx, r[1] + if (dense) 64f else 76f, titleSize,
            Col.rgb(255, 250, 240), offset = 2f, bold = true)
        d.text(g.sub, r[0] + tx, r[1] + if (dense) 106f else 126f, subSize, PAPER_DIM)

        // 分类 / 难度
        d.text(g.category, r[0] + tx, r[1] + if (dense) 172f else 188f, catSize, g.accent)
        val stars = "★".repeat(g.difficulty) + "☆".repeat(3 - g.difficulty)
        d.text(stars, r[0] + r[2] - tx, r[1] + if (dense) 172f else 188f, catSize,
            GOLD, align = "right")

        // 玩法一句话（放不下就截断）
        val maxHow = r[2] - tx * 2f
        d.text(fit(d, g.how, maxHow, howSize), r[0] + tx,
            r[1] + if (dense) 244f else 250f, howSize, HOW_DIM)

        if (sel) {
            val w = 180f * pulse
            d.roundRect(cx - w / 2, r[1] + r[3] - 8f, w, 12f, 6f, g.accent)
        }
    }

    /** 宽度放不下时截断加省略号。 */
    private fun fit(d: Canvas2D, text: String, maxW: Float, size: Float): String {
        if (d.textWidth(text, size) <= maxW) return text
        var t = text
        while (t.isNotEmpty() && d.textWidth("$t…", size) > maxW) t = t.dropLast(1)
        return "$t…"
    }
}
