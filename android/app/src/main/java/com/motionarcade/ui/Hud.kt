package com.motionarcade.ui

import android.graphics.Bitmap
import com.motionarcade.game.BaseGame
import com.motionarcade.game.Design
import com.motionarcade.render.Canvas2D
import com.motionarcade.render.Col
import com.motionarcade.vision.GameInput
import com.motionarcade.vision.InputChannel
import kotlin.math.abs
import kotlin.math.exp

/**
 * 游戏内 HUD（对应 Python 端 `core/shell._draw_hud`）。
 *
 * 设计取向：**浮层，不是状态栏**。
 * 不用贯穿全宽的深色条平铺 label/value（那是后台管理系统的语言），而是浮在画面上的
 * 独立卡片：小标签 + 大数值，靠强层级让 2~4 米外先读到数值。
 *
 * 同时**不给玩家看 FPS 与快捷键**：那是调试信息，不是游戏信息。
 */
class Hud {

    private companion object {
        val INK = Col.rgb(10, 12, 20)
        val PAPER = Col.rgb(250, 250, 252)
        val PAPER_DIM = Col.rgb(198, 206, 226)
        val WARN = Col.rgb(255, 184, 84)
        val DANGER = Col.rgb(255, 104, 92)
        val OK = Col.rgb(126, 231, 135)

        /** 倒计时类数值每秒都在变，不能当"得分"去弹（否则每秒弹一次）。 */
        val QUIET = setOf("时间", "剩余", "倒计时", "Time")
    }

    // 数值变化 → 弹一下
    private val prev = HashMap<String, String>()
    private val popT = HashMap<String, Float>()

    /**
     * 数值变化回调：`(label, 是否变大)`。
     * 外壳用它触发音效 —— "我的操作有反馈"里最便宜也最有效的一环。
     */
    var onValueChange: ((String, Boolean) -> Unit)? = null

    /** 场景切换/重开时清掉，避免新一局开头就"弹"一下。 */
    fun reset() {
        prev.clear()
        popT.clear()
    }

    fun update(dt: Float) {
        val it = popT.entries.iterator()
        while (it.hasNext()) {
            val e = it.next()
            val v = e.value - dt * 3.6f
            if (v <= 0f) it.remove() else e.setValue(v)
        }
    }

    // ------------------------------------------------------------------ 主入口

    fun draw(d: Canvas2D, game: BaseGame, inp: GameInput,
             preview: Bitmap?, hasCamera: Boolean, fps: Float) {
        drawTitle(d, game)
        drawCards(d, game)
        drawStatusPill(d, game, inp, hasCamera)
        drawHint(d, game)
        drawPreview(d, preview, inp, hasCamera, fps)
    }

    // ---- 左：标题 ----
    private fun drawTitle(d: Canvas2D, game: BaseGame) {
        d.shadowText(game.title, 42f, 34f, 36f, PAPER, offset = 3f, bold = true)
        if (game.sub.isNotEmpty()) {
            d.text(game.sub, 46f, 80f, 22f, PAPER_DIM, bold = true)
        }
    }

    // ---- 中：状态卡 ----
    private fun drawCards(d: Canvas2D, game: BaseGame) {
        val items = game.hudItems()
        if (items.isEmpty()) return

        val gap = 16f
        val cw = minOf(260f, (1040f - gap * (items.size - 1)) / items.size)
        val rowW = items.size * cw + (items.size - 1) * gap
        val x0 = (Design.W - rowW) / 2f
        val ch = 88f
        val y = (Design.HUD_H - ch) / 2f

        for (i in items.indices) {
            val it = items[i]
            // 数值变了就弹 + 通知（QUIET 类除外）
            if (prev[it.label] != it.value) {
                val old = prev[it.label]
                if (old != null && it.label !in QUIET) {
                    popT[it.label] = 1f
                    val grew = (it.value.toIntOrNull() ?: 0) > (old.toIntOrNull() ?: 0)
                    onValueChange?.invoke(it.label, grew)
                }
                prev[it.label] = it.value
            }
            val amt = popT[it.label] ?: 0f
            val card = android.graphics.RectF(x0 + i * (cw + gap), y, 0f, 0f).apply {
                right = left + cw; bottom = top + ch
            }

            // 弹动：整体轻微放大
            val s = 1f + 0.07f * amt
            d.save()
            d.scale(s, s)
            val cx = card.centerX() / s
            val cy = card.centerY() / s
            val w = cw / s
            val h = ch / s

            d.roundRect(cx - w / 2, cy - h / 2, w, h, 16f, Col.rgb(16, 20, 32, 215))
            d.roundRect(cx - w / 2, cy - h / 2, w, h, 16f, it.color, if (amt > 0.02f) 4f else 2f)

            if (it.icon == "heart") {
                drawHearts(d, cx - w / 2 + 22f, cy, it.value, it.color)
            } else {
                d.text(it.label, cx - w / 2 + 20f, cy - h / 2 + 30f, 22f, PAPER_DIM)
                d.text(it.value, cx - w / 2 + 20f, cy + 16f, 38f, it.color, bold = true)
            }
            d.restore()
        }
    }

    private fun drawHearts(d: Canvas2D, x: Float, cy: Float, value: String, color: Int) {
        val n = value.toIntOrNull() ?: 0
        for (i in 0 until n.coerceAtMost(6)) {
            val hx = x + i * 34f
            val hy = cy - 2f
            // 心形：两个圆 + 一个三角
            d.circle(hx - 6f, hy, 9f, color)
            d.circle(hx + 6f, hy, 9f, color)
            d.polygon(floatArrayOf(hx - 14f, hy + 2f, hx + 14f, hy + 2f, hx, hy + 20f), color)
        }
    }

    // ---- 右：识别状态 ----
    private fun drawStatusPill(d: Canvas2D, game: BaseGame, inp: GameInput, hasCamera: Boolean) {
        val needHand = InputChannel.HAND in game.requires
        val needHead = InputChannel.HEAD in game.requires

        val (text, col) = when {
            !hasCamera -> "等待摄像头权限" to WARN
            needHand && !inp.handFound -> "未看到手 · 已暂停" to DANGER
            needHead && !inp.found -> "未识别到头 · 已暂停" to DANGER
            inp.quality != GameInput.QUALITY_GOOD && inp.quality != "" ->
                (inp.hint.ifEmpty { "识别质量不佳" }) to WARN
            needHand && needHead -> "头 + 手 已锁定" to OK
            needHand -> "手部已锁定" to OK
            else -> "头部已锁定" to OK
        }

        // 右对齐摆放（居中会因文字变长而整体抖动）
        val size = 22f
        val w = d.textWidth(text, size) + 44f
        val h = 52f
        val x1 = Design.W - 42f
        val y1 = 30f
        d.roundRect(x1 - w, y1, w, h, h / 2, Col.rgb(16, 20, 32, 225))
        d.roundRect(x1 - w, y1, w, h, h / 2, col, 2f)
        d.circle(x1 - w + 20f, y1 + h / 2, 6f, col)
        d.text(text, x1 - 20f, y1 + h / 2, size, col, align = "right", bold = true)
    }

    // ---- 底部提示条 ----
    private fun drawHint(d: Canvas2D, game: BaseGame) {
        if (game.hint.isEmpty()) return
        val y = Design.BOT + Design.HINT_H / 2
        d.text(game.hint, Design.W / 2, y, 26f, PAPER_DIM, align = "center", bold = true)
    }

    // ---- 左下角：摄像头预览面板 ----
    private fun drawPreview(d: Canvas2D, preview: Bitmap?, inp: GameInput,
                            hasCamera: Boolean, fps: Float) {
        val x = Design.PX
        val y = Design.PY
        val w = Design.PW
        val h = Design.PH

        d.roundRect(x, y, w, h, 14f, Col.rgb(12, 14, 22, 200))
        if (preview != null) {
            // 缩略图已按预览尺寸生成，直接贴
            d.raw.save()
            d.raw.clipPath(roundRectPath(x, y, w, h, 14f))
            d.raw.drawBitmap(preview, null,
                android.graphics.RectF(x, y, x + w, y + h), null)
            d.raw.restore()
        }
        d.roundRect(x, y, w, h, 14f, Col.rgb(70, 78, 96), 2f)

        // 角标：检测到的通道
        val tag = when {
            !hasCamera -> "无摄像头"
            inp.handFound && inp.found -> "头 + 手"
            inp.handFound -> "手"
            inp.found -> "头"
            else -> "未识别"
        }
        val tagCol = if (inp.found || inp.handFound) OK else WARN
        d.roundRect(x + 10f, y + 10f, d.textWidth(tag, 20f) + 24f, 30f, 15f,
            Col.rgb(10, 12, 20, 220))
        d.text(tag, x + 22f, y + 25f, 20f, tagCol, bold = true)
    }

    private fun roundRectPath(x: Float, y: Float, w: Float, h: Float, r: Float) =
        android.graphics.Path().apply {
            addRoundRect(x, y, x + w, y + h, r, r, android.graphics.Path.Direction.CW)
        }
}
