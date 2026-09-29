package com.motionarcade.render

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Typeface
import kotlin.math.abs

/**
 * 颜色工具（对应 Python 端 `core.theme.U` 的颜色部分）。
 * 用 Int ARGB 表示颜色，和 Android Canvas/Paint 原生一致，避免每帧装箱。
 */
object Col {
    fun rgb(r: Int, g: Int, b: Int, a: Int = 255): Int =
        (a.coerceIn(0, 255) shl 24) or
            (r.coerceIn(0, 255) shl 16) or
            (g.coerceIn(0, 255) shl 8) or
            b.coerceIn(0, 255)

    /** 亮度缩放：k>1 变亮，k<1 变暗（各通道等比，保持色相）。 */
    fun shade(color: Int, k: Float): Int {
        val a = Color.alpha(color)
        val r = (Color.red(color) * k).toInt().coerceIn(0, 255)
        val g = (Color.green(color) * k).toInt().coerceIn(0, 255)
        val b = (Color.blue(color) * k).toInt().coerceIn(0, 255)
        return rgb(r, g, b, a)
    }

    /** 两色插值。 */
    fun mix(a: Int, b: Int, t: Float): Int {
        val k = t.coerceIn(0f, 1f)
        return rgb(
            (Color.red(a) + (Color.red(b) - Color.red(a)) * k).toInt(),
            (Color.green(a) + (Color.green(b) - Color.green(a)) * k).toInt(),
            (Color.blue(a) + (Color.blue(b) - Color.blue(a)) * k).toInt(),
            (Color.alpha(a) + (Color.alpha(b) - Color.alpha(a)) * k).toInt()
        )
    }

    fun alpha(color: Int, a: Int): Int =
        (a.coerceIn(0, 255) shl 24) or (color and 0x00FFFFFF)

    fun alphaF(color: Int, k: Float): Int =
        alpha(color, (Color.alpha(color) * k.coerceIn(0f, 1f)).toInt())
}

/**
 * pygame 绘制 API 在 Android Canvas 上的等价封装。
 *
 * 存在的意义：让 18 款游戏的绘制代码能从 Python **近乎逐行翻译**过来，
 * 而不必在每个游戏里重写一遍 Canvas 样板。
 *
 * 性能约定（60fps 下很重要）
 * ------------------------
 * · 所有 Paint / RectF / Path 都是**复用的字段**，方法内不 new 对象；
 * · 没有隐藏的逐帧分配，避免把 GC 压力转嫁成操作延迟；
 * · 坐标一律是 1920×1080 设计坐标，缩放由外层 Canvas 矩阵统一处理。
 */
class Canvas2D(private val canvas: Canvas) {

    private val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        typeface = Typeface.DEFAULT
    }
    private val tmpRect = RectF()
    private val tmpPath = Path()

    // ------------------------------------------------------------------ 基本图元

    /** width<=0 时为填充，否则为描边。 */
    fun circle(cx: Float, cy: Float, r: Float, color: Int, width: Float = 0f) {
        if (r <= 0f) return
        if (width <= 0f) {
            fill.color = color
            canvas.drawCircle(cx, cy, r, fill)
        } else {
            stroke.color = color
            stroke.strokeWidth = width
            canvas.drawCircle(cx, cy, r - width * 0.5f, stroke)
        }
    }

    fun ellipse(cx: Float, cy: Float, rx: Float, ry: Float, color: Int, width: Float = 0f) {
        tmpRect.set(cx - rx, cy - ry, cx + rx, cy + ry)
        if (width <= 0f) {
            fill.color = color
            canvas.drawOval(tmpRect, fill)
        } else {
            stroke.color = color
            stroke.strokeWidth = width
            canvas.drawOval(tmpRect, stroke)
        }
    }

    fun rect(x: Float, y: Float, w: Float, h: Float, color: Int, width: Float = 0f) {
        tmpRect.set(x, y, x + w, y + h)
        if (width <= 0f) {
            fill.color = color
            canvas.drawRect(tmpRect, fill)
        } else {
            stroke.color = color
            stroke.strokeWidth = width
            canvas.drawRect(tmpRect, stroke)
        }
    }

    fun roundRect(x: Float, y: Float, w: Float, h: Float, r: Float,
                  color: Int, width: Float = 0f) {
        tmpRect.set(x, y, x + w, y + h)
        if (width <= 0f) {
            fill.color = color
            canvas.drawRoundRect(tmpRect, r, r, fill)
        } else {
            stroke.color = color
            stroke.strokeWidth = width
            canvas.drawRoundRect(tmpRect, r, r, stroke)
        }
    }

    fun line(x1: Float, y1: Float, x2: Float, y2: Float, color: Int, width: Float) {
        stroke.color = color
        stroke.strokeWidth = width
        canvas.drawLine(x1, y1, x2, y2, stroke)
    }

    /** pts 为 [x0,y0,x1,y1,...]。close=true 时闭合。 */
    fun polygon(pts: FloatArray, color: Int, width: Float = 0f, close: Boolean = true) {
        if (pts.size < 6) return
        tmpPath.rewind()
        tmpPath.moveTo(pts[0], pts[1])
        var i = 2
        while (i < pts.size) {
            tmpPath.lineTo(pts[i], pts[i + 1])
            i += 2
        }
        if (close) tmpPath.close()
        if (width <= 0f) {
            fill.color = color
            canvas.drawPath(tmpPath, fill)
        } else {
            stroke.color = color
            stroke.strokeWidth = width
            canvas.drawPath(tmpPath, stroke)
        }
    }

    /** 圆弧：angles 单位为度，0° 在 3 点方向，顺时针为正。 */
    fun arc(cx: Float, cy: Float, r: Float, startDeg: Float, sweepDeg: Float,
            color: Int, width: Float) {
        stroke.color = color
        stroke.strokeWidth = width
        tmpRect.set(cx - r, cy - r, cx + r, cy + r)
        canvas.drawArc(tmpRect, startDeg, sweepDeg, false, stroke)
    }

    // ------------------------------------------------------------------ 位图

    /** 以 (x,y) 为左上角贴图。 */
    fun blit(bmp: Bitmap, x: Float, y: Float) {
        canvas.drawBitmap(bmp, x, y, null)
    }

    /** 以 (cx,cy) 为中心、按给定高度缩放贴图（保持宽高比）。 */
    fun blitCentered(bmp: Bitmap, cx: Float, cy: Float, targetH: Float, flipX: Boolean = false) {
        val scale = targetH / bmp.height.toFloat()
        val w = bmp.width * scale
        val h = bmp.height * scale
        val left = cx - w * 0.5f
        val top = cy - h * 0.5f
        if (flipX) {
            canvas.save()
            canvas.scale(-1f, 1f, cx, cy)
            canvas.drawBitmap(bmp, null, RectF(left, top, left + w, top + h), null)
            canvas.restore()
        } else {
            canvas.drawBitmap(bmp, null, RectF(left, top, left + w, top + h), null)
        }
    }

    /** 绕中心旋转贴图。 */
    fun blitRotated(bmp: Bitmap, cx: Float, cy: Float, targetH: Float, deg: Float) {
        val scale = targetH / bmp.height.toFloat()
        canvas.save()
        canvas.rotate(deg, cx, cy)
        val w = bmp.width * scale
        val h = bmp.height * scale
        canvas.drawBitmap(bmp, null, RectF(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), null)
        canvas.restore()
    }

    // ------------------------------------------------------------------ 文字

    /** align: "left" | "center" | "right"（相对 x 的水平对齐）。 */
    fun text(str: String, x: Float, y: Float, size: Float, color: Int,
             align: String = "left", bold: Boolean = false) {
        textPaint.color = color
        textPaint.textSize = size
        textPaint.isFakeBoldText = bold
        textPaint.textAlign = when (align) {
            "center" -> Paint.Align.CENTER
            "right" -> Paint.Align.RIGHT
            else -> Paint.Align.LEFT
        }
        // y 按基线对齐：调用方传的是"这一行的中心"，这里换算到基线
        val fm = textPaint.fontMetrics
        val baseline = y - (fm.ascent + fm.descent) / 2f
        canvas.drawText(str, x, baseline, textPaint)
    }

    fun textWidth(str: String, size: Float): Float {
        textPaint.textSize = size
        return textPaint.measureText(str)
    }

    /** 描边文字（UI 标题常用：外描边 + 内填充）。 */
    fun outlinedText(str: String, x: Float, y: Float, size: Float,
                     fillColor: Int, strokeColor: Int, strokeW: Float,
                     align: String = "left") {
        textPaint.color = strokeColor
        textPaint.textSize = size
        textPaint.isFakeBoldText = true
        textPaint.textAlign = when (align) {
            "center" -> Paint.Align.CENTER
            "right" -> Paint.Align.RIGHT
            else -> Paint.Align.LEFT
        }
        val fm = textPaint.fontMetrics
        val baseline = y - (fm.ascent + fm.descent) / 2f
        stroke.color = strokeColor
        stroke.strokeWidth = strokeW
        stroke.style = Paint.Style.STROKE
        stroke.textSize = size
        stroke.textAlign = textPaint.textAlign
        stroke.isFakeBoldText = true
        canvas.drawText(str, x, baseline, stroke)
        stroke.style = Paint.Style.STROKE
        textPaint.color = fillColor
        canvas.drawText(str, x, baseline, textPaint)
    }

    // ------------------------------------------------------------------ 状态

    fun save(): Int = canvas.save()
    fun restore() = canvas.restore()
    fun saveLayerAlpha(x: Float, y: Float, w: Float, h: Float, alpha: Int): Int =
        canvas.saveLayerAlpha(x, y, x + w, y + h, alpha)

    fun clipRect(x: Float, y: Float, w: Float, h: Float): Boolean =
        canvas.clipRect(x, y, x + w, y + h)

    fun translate(dx: Float, dy: Float) = canvas.translate(dx, dy)
    fun scale(sx: Float, sy: Float) = canvas.scale(sx, sy)
    fun rotate(deg: Float) = canvas.rotate(deg)

    val width: Int get() = canvas.width
    val height: Int get() = canvas.height

    /** 暴露底层 Canvas：需要直接用原生 API（如带 Paint/Shader 的 drawBitmap）时用。 */
    val raw: Canvas get() = canvas
}

/** 数值工具（对应 core/theme.py 里的 clamp/lerp 等）。 */
object Num {
    fun clamp(v: Float, lo: Float, hi: Float): Float =
        if (v < lo) lo else if (v > hi) hi else v

    fun lerp(a: Float, b: Float, t: Float): Float = a + (b - a) * t

    /** 帧率无关的平滑系数：halfLife 以"帧"为单位（60fps 基准）。 */
    fun smoothK(halfLifeFrames: Float, dt: Float): Float {
        val k60 = 1f - kotlin.math.exp(-0.6931f / halfLifeFrames)
        return clamp(k60 * (dt * 60f), 0f, 1f)
    }

    fun approach(cur: Float, target: Float, maxDelta: Float): Float {
        val d = target - cur
        return if (abs(d) <= maxDelta) target else cur + if (d > 0) maxDelta else -maxDelta
    }
}
