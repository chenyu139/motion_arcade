package com.motionarcade.render

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.ColorMatrix
import android.graphics.ColorMatrixColorFilter
import android.graphics.Paint
import android.util.Log
import kotlin.math.min

/**
 * 精灵层（对应 Python 端 `core/sprites.py`）。
 *
 * 三条硬约束：
 * 1. **缺图不能崩**。任何精灵找不到就返回 null，由调用方回退到矢量画法。
 *    这是这个项目的一贯约定 —— 素材是随时可替换的，代码不能因为少一张图就炸。
 * 2. **内存可控**。原始 PNG 多是 1024×1024，30 张全量解码 ≈ 120MB，
 *    中低端机直接 OOM。这里按 [MAX_EDGE] 降采样后再缓存，实测降到 ~30MB。
 * 3. **不重复解码**。解码是重 IO + CPU，缓存后每帧只是 blit。
 */
class SpriteManager(private val context: Context) {

    companion object {
        private const val TAG = "SpriteManager"
        private const val MAX_EDGE = 512
    }

    private val cache = HashMap<String, Bitmap?>()

    /** 返回 null 表示缺图（调用方应回退矢量画法）。 */
    fun get(name: String): Bitmap? {
        cache[name]?.let { return it }
        if (cache.containsKey(name)) return cache[name]
        val bmp = decodeAsset("sprites/$name.png", MAX_EDGE)
        cache[name] = bmp
        if (bmp == null) Log.d(TAG, "sprite missing: $name (fallback to vector)")
        return bmp
    }

    fun available(name: String): Boolean = get(name) != null

    /** 预热：把一批精灵提前解码，避免第一次用到时卡一帧。 */
    fun preload(names: Collection<String>) {
        names.forEach { get(it) }
    }

    /**
     * 画精灵。返回是否画成功（false = 缺图，调用方需回退）。
     * @param cx,cy 中心点（设计坐标）
     * @param h 目标高度（宽度按原图比例）
     */
    fun draw(d: Canvas2D, name: String, cx: Float, cy: Float, h: Float,
             flipX: Boolean = false, rotateDeg: Float = 0f, alpha: Int = 255): Boolean {
        val bmp = get(name) ?: return false
        val p = paintFor(alpha)
        val scale = h / bmp.height.toFloat()
        val w = bmp.width * scale
        d.save()
        if (rotateDeg != 0f) d.rotate(rotateDeg)
        if (flipX) d.scale(-1f, 1f)
        // flipX 之后坐标系被镜像，x 要按镜像后的位置放
        val left = if (flipX) -(cx + w / 2f) else cx - w / 2f
        val dst = android.graphics.RectF(left, cy - h / 2f, left + w, cy + h / 2f)
        d.raw.drawBitmap(bmp, null, dst, p)
        d.restore()
        return true
    }

    /**
     * 色相派生：一张底图生成同族配色（Python 端 `SP.hued` 的等价物）。
     * 用于"一张灯笼素材派生 6 种颜色"这类需求，省素材也省内存。
     */
    fun drawTinted(d: Canvas2D, name: String, cx: Float, cy: Float, h: Float,
                   hueDeg: Float, alpha: Int = 255): Boolean {
        val bmp = get(name) ?: return false
        val cm = ColorMatrix()
        cm.setRotate(0, hueDeg)   // 第 0 个轴 = R，做色相旋转
        val p = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            colorFilter = ColorMatrixColorFilter(cm)
            if (alpha < 255) this.alpha = alpha
        }
        val scale = h / bmp.height.toFloat()
        val w = bmp.width * scale
        val r = android.graphics.RectF(cx - w / 2f, cy - h / 2f, cx + w / 2f, cy + h / 2f)
        d.raw.drawBitmap(bmp, null, r, p)
        return true
    }

    private var alphaPaint: Paint? = null
    private fun paintFor(alpha: Int): Paint? {
        if (alpha >= 255) return null
        val p = alphaPaint ?: Paint(Paint.ANTI_ALIAS_FLAG).also { alphaPaint = it }
        p.alpha = alpha
        return p
    }

    /** 按最大边降采样解码 assets 下的 PNG。 */
    private fun decodeAsset(path: String, maxEdge: Int): Bitmap? = try {
        context.assets.open(path).use { s0 ->
            val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            val probe = s0.readBytes()
            BitmapFactory.decodeByteArray(probe, 0, probe.size, opts)
            if (opts.outWidth <= 0 || opts.outHeight <= 0) return null
            opts.inSampleSize = computeSample(opts.outWidth, opts.outHeight, maxEdge)
            opts.inJustDecodeBounds = false
            opts.inPreferredConfig = Bitmap.Config.ARGB_8888
            BitmapFactory.decodeByteArray(probe, 0, probe.size, opts)
        }
    } catch (e: Exception) {
        null
    }

    private fun computeSample(w: Int, h: Int, maxEdge: Int): Int {
        var sample = 1
        val longest = maxOf(w, h)
        while (longest / sample > maxEdge) sample *= 2
        return sample
    }

    fun clear() {
        cache.values.filterNotNull().forEach { if (!it.isRecycled) it.recycle() }
        cache.clear()
    }
}
