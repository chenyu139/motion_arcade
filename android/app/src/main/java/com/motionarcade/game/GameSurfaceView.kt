package com.motionarcade.game

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.util.Log
import android.view.MotionEvent
import android.view.SurfaceHolder
import android.view.SurfaceView
import androidx.lifecycle.LifecycleOwner
import com.motionarcade.render.BackgroundManager
import com.motionarcade.render.Canvas2D
import com.motionarcade.audio.Sfx
import com.motionarcade.render.Col
import com.motionarcade.render.SpriteManager
import com.motionarcade.ui.Hud
import com.motionarcade.ui.Menu
import com.motionarcade.vision.GameInput
import com.motionarcade.vision.InputChannel
import com.motionarcade.vision.VisionPipeline
import kotlin.math.min

/**
 * 游戏主视图：SurfaceView + **独立渲染线程**。
 *
 * 为什么不用 Choreographer 跑在主线程：
 * 主线程还要承担 CameraX 回调、权限、输入分发；把 60fps 渲染压上去会互相抢时间。
 * SurfaceView 的 lockCanvas 本来就允许任意线程调用，独立线程是 Android 2D 游戏的标准做法。
 *
 * 设计坐标系
 * ----------
 * 所有游戏仍按 Python 端的 1920×1080（16:9）绘制，这里负责**等比缩放并居中**
 * 到实际屏幕。手机横屏多为 20:9，多出来的部分作为安全边距由背景填满：
 *   · 不变形（等比）；
 *   · 不裁掉关键内容（contain 而非 cover）；
 *   · 触摸坐标能反向映射回设计坐标。
 */
class GameSurfaceView(
    context: Context,
    private val lifecycleOwner: LifecycleOwner,
) : SurfaceView(context), SurfaceHolder.Callback {

    companion object {
        private const val TAG = "GameSurfaceView"
        const val DESIGN_W = 1920
        const val DESIGN_H = 1080
        private const val TARGET_FPS = 60
        private const val MAX_DT = 0.05f
        private val FRAME_NS = 1_000_000_000L / TARGET_FPS
        private const val RESULT_HOLD = 2.6f     // 结算停留时长（秒）
    }

    private val sprites = SpriteManager(context)
    private val bg = BackgroundManager(context)
    private val registry = GameRegistry(sprites, bg)
    private val menu = Menu(bg)
    private val pipeline = VisionPipeline(context, lifecycleOwner)
    private val hud = Hud()

    private var scene = "menu"               // menu | game | result
    private var current: BaseGame? = null
    private var resultT = 0f
    private var resultWin = false

    // ---- 屏幕适配 ----
    private var scale = 1f
    private var offsetX = 0f
    private var offsetY = 0f

    @Volatile
    private var running = false
    private var renderThread: Thread? = null
    private var smoothedFps = 60f

    private val bgPaint = Paint().apply { color = Color.parseColor("#0B0D12") }
    private var hasCameraPermission = false

    init {
        holder.addCallback(this)
        isFocusable = true
        keepScreenOn = true
        registry.preload()
        menu.attach(registry.entries)
        menu.onEnter = { game -> enterGame(game) }
        menu.onMove = { Sfx.play("move") }
        // HUD 数值增加 → 得分音；减少（掉命/扣分）→ 失误音
        hud.onValueChange = { _, grew ->
            if (grew) Sfx.play("hit") else Sfx.play("fail")
        }
    }

    // ------------------------------------------------------------------ 生命周期

    override fun surfaceCreated(holder: SurfaceHolder) { startRenderLoop() }

    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
        scale = min(width / DESIGN_W.toFloat(), height / DESIGN_H.toFloat())
        offsetX = (width - DESIGN_W * scale) * 0.5f
        offsetY = (height - DESIGN_H * scale) * 0.5f
    }

    override fun surfaceDestroyed(holder: SurfaceHolder) { stopRenderLoop() }

    fun onCameraPermissionGranted() {
        hasCameraPermission = true
        // 菜单里也开相机：这样一进游戏就已经校准好了，不用干等。
        pipeline.start(setOf(InputChannel.HEAD, InputChannel.HAND))
        Log.i(TAG, "camera ready")
    }

    fun onResumeOwner() { /* 渲染线程随 surface 走，这里无额外恢复动作 */ }

    fun onPauseOwner() { }

    fun onDestroyOwner() {
        stopRenderLoop()
        pipeline.shutdown()
        sprites.clear()
        bg.clear()
    }

    /** 返回 true 表示消费了返回键。 */
    fun handleBack(): Boolean {
        if (scene != "menu") { toMenu(); return true }
        return false
    }

    // ------------------------------------------------------------------ 场景切换

    private fun enterGame(game: BaseGame) {
        current = game
        game.reset()
        scene = "game"
        resultT = 0f
        hud.reset()
        // 按需启停检测器：头控游戏不必跑手部模型
        pipeline.retune(game.requires)
        pipeline.reset()
        Sfx.play("start")
        Log.i(TAG, "enter ${game.key} requires=${game.requires}")
    }

    private fun toMenu() {
        scene = "menu"
        current = null
        pipeline.retune(setOf(InputChannel.HEAD, InputChannel.HAND))
    }

    // ------------------------------------------------------------------ 渲染循环

    private fun startRenderLoop() {
        if (running) return
        running = true
        renderThread = Thread({ loop() }, "game-render").apply {
            priority = Thread.MAX_PRIORITY
            start()
        }
    }

    private fun stopRenderLoop() {
        running = false
        renderThread?.let { t ->
            try { t.join(600) } catch (e: InterruptedException) {
                Thread.currentThread().interrupt()
            }
        }
        renderThread = null
    }

    private fun loop() {
        var lastNs = System.nanoTime()
        while (running) {
            val frameStart = System.nanoTime()
            var dt = (frameStart - lastNs) / 1_000_000_000f
            lastNs = frameStart
            if (dt > MAX_DT) dt = MAX_DT
            if (dt > 0f) smoothedFps += ((1f / dt) - smoothedFps) * 0.08f

            update(dt)
            drawFrame()

            val elapsed = System.nanoTime() - frameStart
            val sleepMs = (FRAME_NS - elapsed) / 1_000_000L
            if (sleepMs > 1) {
                try { Thread.sleep(sleepMs - 1) } catch (e: InterruptedException) {
                    Thread.currentThread().interrupt(); break
                }
            }
        }
    }

    private fun update(dt: Float) {
        // 视觉管线始终更新（菜单里也要能用头选）
        if (hasCameraPermission) pipeline.update(dt)
        val inp: GameInput = pipeline.input
        hud.update(dt)

        when (scene) {
            "menu" -> menu.update(dt, inp)
            "game" -> {
                val g = current ?: return
                g.tickEffects(dt)
                g.update(dt, inp)
                if (g.state != BaseGame.STATE_PLAY) {
                    scene = "result"
                    resultWin = g.state == BaseGame.STATE_WIN
                    resultT = 0f
                    Sfx.play(if (resultWin) "celebrate" else "fail")
                }
            }
            "result" -> {
                resultT += dt
                current?.tickEffects(dt)
                if (resultT > RESULT_HOLD) toMenu()
            }
        }
    }

    private fun drawFrame() {
        val canvas = holder.lockCanvas() ?: return
        try { render(canvas) } finally { holder.unlockCanvasAndPost(canvas) }
    }

    private fun render(canvas: Canvas) {
        canvas.drawRect(0f, 0f, canvas.width.toFloat(), canvas.height.toFloat(), bgPaint)
        val save = canvas.save()
        canvas.translate(offsetX, offsetY)
        canvas.scale(scale, scale)
        val d = Canvas2D(canvas)

        when (scene) {
            "menu" -> menu.draw(d)
            "game" -> {
                current?.render(d)
                current?.let {
                    hud.draw(d, it, pipeline.input, pipeline.lastFrame,
                        hasCameraPermission, smoothedFps)
                }
            }
            "result" -> {
                current?.render(d)
                current?.let {
                    hud.draw(d, it, pipeline.input, pipeline.lastFrame,
                        hasCameraPermission, smoothedFps)
                }
                drawResult(d)
            }
        }
        canvas.restoreToCount(save)
    }

    private fun drawResult(d: Canvas2D) {
        d.rect(0f, 0f, Design.W, Design.H, Col.rgb(0, 0, 0, 170))
        val g = current ?: return
        val title = if (resultWin) "通关！" else "结束"
        val col = if (resultWin) Col.rgb(255, 214, 96) else Col.rgb(226, 232, 240)
        d.text(title, Design.W / 2, Design.H / 2 - 60f, 84f, col, align = "center", bold = true)
        d.text("${g.title}　得分 ${g.score}", Design.W / 2, Design.H / 2 + 20f, 40f,
            Col.rgb(255, 255, 255), align = "center")
        d.text("点击返回大厅", Design.W / 2, Design.H / 2 + 90f, 30f,
            Col.rgb(180, 190, 210), align = "center")
    }

    // ------------------------------------------------------------------ 输入

    private fun toDesign(x: Float, y: Float): Pair<Float, Float> =
        ((x - offsetX) / scale) to ((y - offsetY) / scale)

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (event.action != MotionEvent.ACTION_UP) return true
        val (dx, dy) = toDesign(event.x, event.y)
        when (scene) {
            "menu" -> menu.onTap(dx, dy)
            "result" -> toMenu()
            "game" -> {
                // 右上角作为"退出"热区，避免游戏中误触
                if (dx > Design.W - 220f && dy < Design.TOP + 40f) toMenu()
            }
        }
        return true
    }
}
