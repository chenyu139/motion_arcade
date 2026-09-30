package com.motionarcade.ui

import com.motionarcade.game.BaseGame
import com.motionarcade.game.Design
import com.motionarcade.render.BackgroundManager
import com.motionarcade.render.Canvas2D
import com.motionarcade.render.Col
import com.motionarcade.vision.GameInput
import kotlin.math.abs

/**
 * 游戏大厅。
 *
 * 两种选法都支持：
 *  · **触摸**（手机上最直接）：点卡片即进入；
 *  · **头部**（保持一致的无接触体验）：左右转头移动高亮，点头进入。
 *
 * 之所以保留头部选择：这是体感游戏厅，玩家的手可能正拿着手机/不方便，
 * 而且"用头翻菜单"本身就是这个项目要验证的交互。
 *
 * 网格自适应：游戏少时用 3 列大卡（信息全）；超过 6 款自动切 5 列紧凑卡，
 * 保证任意数量都在两三行内放下。
 */
class Menu(private val bg: BackgroundManager) {

    private var games: List<BaseGame> = emptyList()
    var selected = 0
    private var hoverT = 0f
    private var axisLatch = false

    /** 供外壳判断"玩家确认进入某一款"了。 */
    var onEnter: ((BaseGame) -> Unit)? = null

    /** 高亮移动（换了一款）时通知，用于播"嗒"的音效。 */
    var onMove: (() -> Unit)? = null

    // ---- 自适应网格 ----
    private val dense: Boolean get() = games.size > 6
    private val cols: Int get() = if (dense) 5 else 3
    private val cardW: Float get() = if (dense) 330f else 520f
    private val cardH: Float get() = if (dense) 330f else 300f
    private val gap: Float get() = if (dense) 30f else 40f
    private val gridX: Float get() = (Design.W - (cols * cardW + (cols - 1) * gap)) / 2f
    private val gridY: Float get() = if (dense) 300f else 240f

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
        bg.drawOr(d, "bg_bev_mist", Design.W, Design.H,
            Col.rgb(22, 20, 54), Col.rgb(62, 48, 108), Col.rgb(120, 96, 140))

        d.text("Motion Arcade", Design.W / 2, 90f, 58f, Col.rgb(255, 255, 255),
            align = "center", bold = true)
        d.text("摄像头体感游戏厅　·　用头或手来玩", Design.W / 2, 140f, 28f,
            Col.rgb(200, 206, 226), align = "center")

        val tx = if (dense) 36f else 52f
        val titleSize = if (dense) 30f else 44f
        val subSize = if (dense) 20f else 26f
        val catSize = if (dense) 20f else 26f
        val howSize = if (dense) 17f else 24f

        for (i in games.indices) {
            val g = games[i]
            val r = cardRect(i)
            val sel = i == selected
            val pulse = if (sel) (1f + 0.012f * kotlin.math.sin(hoverT * 3f)) else 1f
            val cx = r[0] + r[2] / 2
            val cy = r[1] + r[3] / 2

            // 卡片底
            d.roundRect(r[0], r[1], r[2], r[3], 26f,
                if (sel) Col.rgb(38, 44, 68) else Col.rgb(28, 32, 50))
            d.roundRect(r[0], r[1], r[2], r[3], 26f,
                if (sel) g.accent else Col.rgb(60, 68, 96), if (sel) 6f else 3f)

            // 强调色条
            d.roundRect(r[0] + 18f, r[1] + 22f, 8f, r[3] - 44f, 4f, g.accent)

            // 标题 / 副标题
            d.text(g.title, r[0] + tx, r[1] + if (dense) 62f else 74f, titleSize,
                Col.rgb(255, 255, 255), bold = true)
            d.text(g.sub, r[0] + tx, r[1] + if (dense) 104f else 124f, subSize,
                Col.rgb(178, 188, 210))

            // 分类 / 难度
            d.text(g.category, r[0] + tx, r[1] + if (dense) 170f else 186f, catSize, g.accent)
            val stars = "★".repeat(g.difficulty) + "☆".repeat(3 - g.difficulty)
            d.text(stars, r[0] + r[2] - tx, r[1] + if (dense) 170f else 186f, catSize,
                Col.rgb(255, 214, 120), align = "right")

            // 玩法一句话（放不下就截断）
            val maxHow = r[2] - tx * 2f
            d.text(fit(d, g.how, maxHow, howSize), r[0] + tx,
                r[1] + if (dense) 240f else 246f, howSize, Col.rgb(150, 160, 184))

            if (sel) {
                d.roundRect(cx - 90f, r[1] + r[3] - 6f, 180f, 12f, 6f, g.accent)
            }
        }

        d.text("点卡片进入　·　或用头左右转选择、点头确认",
            Design.W / 2, Design.BOT + 26f, 26f, Col.rgb(150, 160, 184), align = "center")
    }

    /** 宽度放不下时截断加省略号。 */
    private fun fit(d: Canvas2D, text: String, maxW: Float, size: Float): String {
        if (d.textWidth(text, size) <= maxW) return text
        var t = text
        while (t.isNotEmpty() && d.textWidth("$t…", size) > maxW) t = t.dropLast(1)
        return "$t…"
    }
}
