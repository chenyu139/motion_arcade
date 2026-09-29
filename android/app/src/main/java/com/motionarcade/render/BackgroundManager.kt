package com.motionarcade.render

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.LinearGradient
import android.graphics.Shader
import kotlin.math.max

/**
 * 背景图管理（对应 Python 端 `core/scene.sky_img / sky_or`）。
 *
 * **cover 适配**：素材站的卡通视差背景多为 3072×1536（2:1），而画面是 16:9。
 * 直接拉满会变形，所以这里等比放大、居中裁剪 —— 与 Python 端改成 cover 的
 * `sky_img` 行为保持一致，保证两端观感一致。
 *
 * 缺图时回退到三段渐变（[drawOr] 的 fallback* 参数），不会留黑屏。
 */
class BackgroundManager(private val context: Context) {

    private val sourceCache = HashMap<String, Bitmap?>()
    private val fittedCache = HashMap<String, Bitmap?>()

    /** 解码原图（按最长边 2048 降采样，够全屏用且省内存）。 */
    private fun source(name: String): Bitmap? {
        if (sourceCache.containsKey(name)) return sourceCache[name]
        val bmp = try {
            context.assets.open("bg/$name.png").use { s ->
                val bytes = s.readBytes()
                val probe = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size, probe)
                var sample = 1
                val longest = max(probe.outWidth, probe.outHeight)
                while (longest / sample > 2048) sample *= 2
                val opts = BitmapFactory.Options().apply {
                    inSampleSize = sample
                    inPreferredConfig = Bitmap.Config.ARGB_8888
                }
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size, opts)
            }
        } catch (e: Exception) {
            null
        }
        sourceCache[name] = bmp
        return bmp
    }

    /** 取 cover 适配到 (w,h) 的背景；缺图返回 null。 */
    fun fit(name: String, w: Int, h: Int): Bitmap? {
        val key = "${name}_${w}x${h}"
        if (fittedCache.containsKey(key)) return fittedCache[key]
        val src = source(name) ?: run {
            fittedCache[key] = null
            return null
        }
        val fitted = fitCover(src, w, h)
        fittedCache[key] = fitted
        return fitted
    }

    /** 等比放大并居中裁剪，得到正好 w×h 的图。 */
    private fun fitCover(src: Bitmap, w: Int, h: Int): Bitmap {
        val scale = max(w / src.width.toFloat(), h / src.height.toFloat())
        val scaledW = (src.width * scale).toInt()
        val scaledH = (src.height * scale).toInt()
        val scaled = Bitmap.createScaledBitmap(src, scaledW, scaledH, true)
        val out = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val canvas = android.graphics.Canvas(out)
        val left = (w - scaledW) / 2f
        val top = (h - scaledH) / 2f
        canvas.drawBitmap(scaled, left, top, null)
        if (scaled !== src) scaled.recycle()
        return out
    }

    /**
     * 优先画真实背景图，缺图时回退三段竖直渐变。
     * 返回是否用了真实图（false = 走了渐变回退）。
     */
    fun drawOr(d: Canvas2D, name: String, w: Float, h: Float,
               fallbackTop: Int, fallbackMid: Int, fallbackBottom: Int): Boolean {
        val bmp = fit(name, w.toInt(), h.toInt())
        if (bmp != null) {
            d.raw.drawBitmap(bmp, 0f, 0f, null)
            return true
        }
        drawVerticalGradient(d, w, h, fallbackTop, fallbackMid, fallbackBottom)
        return false
    }

    /** 三段竖直渐变（上→中→下）。 */
    fun drawVerticalGradient(d: Canvas2D, w: Float, h: Float,
                             top: Int, mid: Int, bottom: Int) {
        val shader = LinearGradient(
            0f, 0f, 0f, h,
            intArrayOf(top, mid, bottom),
            floatArrayOf(0f, 0.5f, 1f),
            Shader.TileMode.CLAMP
        )
        val p = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG)
        p.shader = shader
        d.raw.drawRect(0f, 0f, w, h, p)
    }

    fun clear() {
        fittedCache.values.filterNotNull().forEach { if (!it.isRecycled) it.recycle() }
        sourceCache.values.filterNotNull().forEach { if (!it.isRecycled) it.recycle() }
        fittedCache.clear()
        sourceCache.clear()
    }
}
