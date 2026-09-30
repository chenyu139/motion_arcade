package com.motionarcade.game.games

import android.util.Log
import com.motionarcade.audio.Sfx
import com.motionarcade.game.BaseGame
import com.motionarcade.game.Design
import com.motionarcade.game.GamePrefs
import com.motionarcade.game.HudItem
import com.motionarcade.render.Canvas2D
import com.motionarcade.render.Col
import com.motionarcade.vision.GameInput
import com.motionarcade.vision.InputChannel
import kotlin.math.abs
import kotlin.random.Random

/**
 * 蜀韵鼓点 —— 川剧锣鼓 · 双手击节（手控）。
 *
 * **动词来自文化动作本身**：鼓匠就是握槌下砸。操作：握拳、向下快速一砸 = 击鼓，
 * 左右手皆可（双手交替最舒服）。锣点（短语头一个音）要砸出"锣"的分量。
 *
 * **音频延迟校准**（这是节奏游戏在手机上能"踩得上点"的关键）：
 * 检测到击打要过 相机帧 + 推理 两道延迟，声音发出要过音频输出延迟——三者叠加
 * 会让玩家"明明听点上砸的，却总判晚"。开局先跟 4 拍节拍器，量出本机系统偏移
 * （默认取系统报告的音频输出延迟），存在本机，之后判定窗口整体平移这个偏移。
 */
class DrumGame : BaseGame() {

    override val key = "drum"
    override val title = "蜀韵鼓点"
    override val sub = "川剧锣鼓 · 双手击节"
    override val category = "手控"
    override val hint = "握拳向下快速一砸 = 击鼓 · 锣点更有分量"
    override val how = "跟上川剧锣鼓点，越准分越高；错太多就散场"
    override val accent = Col.rgb(255, 160, 64)
    override val difficulty = 3
    override val requires = setOf(InputChannel.HAND)

    private companion object {
        const val BPM = 96f
        const val BEAT = 60f / BPM
        const val NOTES = 40
        const val CALIB_TICKS = 4          // 校准节拍数
        const val CALIB_TAIL = 0.8f        // 校准结束后的缓冲（秒）
        const val APPROACH = 1.6f          // 音符从顶部落到鼓面的秒数
        const val PERFECT = 0.09f
        const val GOOD = 0.18f
        const val HEARTS = 5
        const val STRIKE_V = 1.7f          // 拳向下速度阈值（/秒）
        const val NOTE_Y0 = 250f
        const val DRUM_Y = 800f
        const val DRUM_X = 960f
        const val PREF_OFFSET = "drum_offset_ms"
        const val WIN_RATE = 0.5f
        private const val TAG = "DrumGame"
        const val LEAD_BEATS = 7f          // 校准 4 拍 + 缓冲，之后音符才登场
    }

    /** 每 2 拍一个短语（落点以拍为单位）：川剧锣鼓的"七字句"感。 */
    private val PHRASES = listOf(
        floatArrayOf(0f, 1f),
        floatArrayOf(0f, 0.5f, 1f, 1.5f),
        floatArrayOf(0f, 0.75f, 1.5f),
        floatArrayOf(0f, 1.5f),
        floatArrayOf(0f, 0.5f, 1f),
    )

    // 谱面
    private var noteBeat = FloatArray(NOTES)
    private var noteIsGong = BooleanArray(NOTES)
    private var noteHit = BooleanArray(NOTES)

    private var songT = 0f              // 本局时间轴（秒）
    private var phase = 0               // 0=校准 1=演奏 2=收尾
    private var offset = 0f             // 检测系统偏移（秒）
    private var ticksDone = 0
    private var tickFlash = 0f
    private val calibDeltas = ArrayList<Float>()
    private var lastTickT = 0f

    private var nextNote = 0
    private var mScore = 0
    private var combo = 0
    private var bestCombo = 0
    private var nPerfect = 0
    private var nGood = 0
    private var nMiss = 0
    private var hearts = HEARTS
    private var drumFlashL = 0f
    private var drumFlashR = 0f
    private var cdL = 0f
    private var cdR = 0f
    private var lastMsg = ""
    private var msgT = 0f

    override val score: Int get() = mScore

    override fun reset() {
        state = STATE_PLAY
        buildScore()
        songT = 0f
        offset = GamePrefs.getFloat(PREF_OFFSET, -1f)
        phase = if (offset >= 0f) 1 else 0
        if (phase == 1) offset /= 1000f else offset = Sfx.outputLatencyMs / 1000f
        ticksDone = 0
        calibDeltas.clear()
        nextNote = 0
        mScore = 0; combo = 0; bestCombo = 0
        nPerfect = 0; nGood = 0; nMiss = 0
        hearts = HEARTS
        drumFlashL = 0f; drumFlashR = 0f
        cdL = 0f; cdR = 0f
        lastMsg = ""; msgT = 0f
        particles.clear()
    }

    /** 生成谱面：短语循环，每短语 2 拍，头一个音是"锣"；从第 7 拍起（校准 4 拍 + 缓冲）。 */
    private fun buildScore() {
        var b = LEAD_BEATS
        var i = 0
        var phraseIdx = Random.nextInt(PHRASES.size)
        while (i < NOTES) {
            val phrase = PHRASES[phraseIdx % PHRASES.size]
            phraseIdx++
            for (o in phrase) {
                if (i >= NOTES) break
                noteBeat[i] = (b + o) * BEAT
                noteIsGong[i] = o == 0f
                i++
            }
            b += 2f
        }
    }

    private fun expectedT(i: Int): Float = noteBeat[i] + offset

    override fun update(dt: Float, inp: GameInput) {
        if (state != STATE_PLAY) return
        songT += dt
        tickFlash = maxOf(0f, tickFlash - dt * 3f)
        drumFlashL = maxOf(0f, drumFlashL - dt * 4f)
        drumFlashR = maxOf(0f, drumFlashR - dt * 4f)
        msgT = maxOf(0f, msgT - dt)
        cdL = maxOf(0f, cdL - dt)
        cdR = maxOf(0f, cdR - dt)

        // ---- 击打检测（左右拳独立，冷却防一次挥动连发）----
        val strikeL = inp.handFound && inp.handOpen < 0.5f &&
            inp.handDipL > STRIKE_V && cdL <= 0f
        val strikeR = inp.handFound && inp.handOpen < 0.5f &&
            inp.handDipR > STRIKE_V && cdR <= 0f
        if (strikeL) { cdL = 0.28f; drumFlashL = 1f }
        if (strikeR) { cdR = 0.28f; drumFlashR = 1f }

        if (phase == 0) {
            // ---- 校准：节拍器 4 拍，跟着砸 ----
            while (ticksDone < CALIB_TICKS && songT >= (ticksDone + 1) * BEAT) {
                ticksDone++
                lastTickT = ticksDone * BEAT
                tickFlash = 1f
                Sfx.play("tick")
            }
            if (strikeL || strikeR) {
                Sfx.play("drum")
                val d = songT - lastTickT
                if (abs(d) < 0.35f) calibDeltas.add(d)
            }
            if (ticksDone >= CALIB_TICKS && songT >= CALIB_TICKS * BEAT + CALIB_TAIL) {
                offset = if (calibDeltas.size >= 2) {
                    val mean = calibDeltas.average().toFloat()
                    mean.coerceIn(-0.15f, 0.15f)
                } else {
                    Sfx.outputLatencyMs / 1000f
                }
                GamePrefs.putFloat(PREF_OFFSET, offset * 1000f)
                phase = 1
                lastMsg = "校准完成 ±${(abs(offset) * 1000).toInt()}ms"
                msgT = 1.6f
                Sfx.play("start")
                Log.i(TAG, "calibrated offset=${offset * 1000}ms from ${calibDeltas.size} strikes")
            }
            return
        }

        // ---- 演奏：先处理 miss（过窗未击）----
        while (nextNote < NOTES &&
            (noteHit[nextNote] || songT > expectedT(nextNote) + GOOD)
        ) {
            if (!noteHit[nextNote]) {
                noteHit[nextNote] = true
                nMiss++
                combo = 0
                hearts--
                addShake(6f)
                flash(Col.rgb(255, 90, 70), 0.22f)
            }
            nextNote++
        }
        if (hearts <= 0) {
            state = STATE_OVER
            Sfx.play("fail")
            return
        }

        // ---- 击打判定：找最近的未击音符 ----
        if (strikeL || strikeR) {
            var bestI = -1
            var bestD = Float.MAX_VALUE
            var i = nextNote
            while (i < NOTES && i <= nextNote + 8) {
                if (!noteHit[i]) {
                    val d = abs(songT - expectedT(i))
                    if (d < bestD) { bestD = d; bestI = i }
                }
                i++
            }
            if (bestI >= 0 && bestD <= GOOD) {
                noteHit[bestI] = true
                val gongHit = noteIsGong[bestI]
                Sfx.play(if (gongHit) "gong" else "drum")
                if (bestD <= PERFECT) {
                    nPerfect++
                    combo++
                    mScore += 150 + combo * 5
                    lastMsg = "好！"
                } else {
                    nGood++
                    combo++
                    mScore += 80
                    lastMsg = "不错"
                }
                bestCombo = maxOf(bestCombo, combo)
                msgT = 0.5f
                particles.burst(DRUM_X, DRUM_Y - 40f, 12,
                    if (noteIsGong[bestI]) Col.rgb(180, 240, 200) else Col.rgb(255, 214, 96),
                    speed = 300f, spread = 200f, dirDeg = 270f)
                addShake(if (gongHit) 8f else 4f)
            } else {
                // 空砸：只有鼓声，不计分不罚
                Sfx.play("drum_side")
            }
        }

        // ---- 收尾 ----
        if (nextNote >= NOTES) {
            val hits = nPerfect + nGood
            val rate = hits.toFloat() / NOTES
            state = if (hearts > 0 && rate >= WIN_RATE) STATE_WIN else STATE_OVER
            Sfx.play(if (state == STATE_WIN) "celebrate" else "fail")
        }
    }

    override fun draw(d: Canvas2D) {
        // ---- 戏台 ----
        d.vGradient(0f, 0f, Design.W, Design.H,
            Col.rgb(30, 18, 12), Col.rgb(22, 14, 10), Col.rgb(12, 8, 6))
        d.polygon(floatArrayOf(
            DRUM_X - 140f, 0f, DRUM_X + 140f, 0f,
            DRUM_X + 360f, Design.H.toFloat(), DRUM_X - 360f, Design.H.toFloat()
        ), Col.rgb(255, 220, 170, 22))
        for (k in 0 until 6) {
            val x = 120f + k * (Design.W - 240f) / 5f
            d.rect(x - 3f, 0f, 6f, 120f, Col.rgb(90, 50, 30))
            d.glow(x, 130f, 66f, Col.rgb(255, 190, 100, 60))
            d.circle(x, 130f, 10f, Col.rgb(255, 200, 120, 190))
        }
        // 舞台地板
        d.vGradient(0f, DRUM_Y + 60f, Design.W, Design.H - DRUM_Y - 60f,
            Col.rgb(56, 34, 24), Col.rgb(24, 14, 10))

        // ---- 判定引导线（音符从这里落向鼓面）----
        d.line(DRUM_X - 320f, DRUM_Y - 300f, DRUM_X + 320f, DRUM_Y - 300f,
            Col.rgb(255, 214, 96, 60), 2f)

        // ---- 音符（近的先判，从上往下落）----
        val t = songT
        for (i in nextNote until NOTES) {
            if (noteHit[i]) continue
            val timeToHit = expectedT(i) - t
            if (timeToHit > APPROACH) break
            if (timeToHit < -GOOD) continue
            val k = (1f - timeToHit / APPROACH).coerceIn(0f, 1f)
            val y = NOTE_Y0 + (DRUM_Y - NOTE_Y0) * k
            val r = 30f + 10f * k
            val near = timeToHit < PERFECT + 0.03f
            val col = if (noteIsGong[i]) Col.rgb(150, 236, 180) else Col.rgb(255, 214, 96)
            val body = if (noteIsGong[i]) Col.rgb(52, 130, 84) else Col.rgb(180, 120, 44)
            if (near) d.circle(DRUM_X, y, r + 8f, Col.alpha(col, 70))
            d.circle(DRUM_X, y, r, body)
            d.circle(DRUM_X, y, r, col, 4f)
            d.text(if (noteIsGong[i]) "锣" else "鼓", DRUM_X, y, 26f,
                Col.rgb(255, 248, 230), align = "center", bold = true)
        }

        // ---- 大鼓 ----
        val flash = maxOf(drumFlashL, drumFlashR)
        val bodyCol = Col.rgb(150, 44, 36)
        d.roundRect(DRUM_X - 250f, DRUM_Y - 60f, 500f, 150f, 40f, bodyCol)
        d.roundRect(DRUM_X - 250f, DRUM_Y - 60f, 500f, 150f, 40f,
            Col.rgb(255, 214, 96, 140), 5f)
        // 鼓面（即判定线）
        d.ellipse(DRUM_X, DRUM_Y - 60f, 250f, 54f, Col.rgb(240, 226, 200))
        d.ellipse(DRUM_X, DRUM_Y - 60f, 250f, 54f, Col.rgb(60, 40, 30), 4f)
        d.circle(DRUM_X, DRUM_Y - 60f, 30f + 10f * flash,
            Col.alpha(Col.rgb(255, 120, 80), (200 * flash).toInt()))
        // 鼓钉
        for (k in 0 until 9) {
            val x = DRUM_X - 210f + k * 52f
            d.circle(x, DRUM_Y + 20f, 6f, Col.rgb(255, 214, 96))
        }
        // 左右击打指示
        for (side in 0..1) {
            val f = if (side == 0) drumFlashL else drumFlashR
            val x = DRUM_X + if (side == 0) -300f else 300f
            d.circle(x, DRUM_Y - 30f, 20f + 8f * f,
                Col.alpha(Col.rgb(255, 214, 96), (90 + 160 * f).toInt()))
            d.text(if (side == 0) "左" else "右", x, DRUM_Y - 28f, 22f,
                Col.rgb(60, 40, 20), align = "center", bold = true)
        }

        // 击打冲击波（左右拳各自扩散一圈）
        for ((f, side) in listOf(drumFlashL to -1f, drumFlashR to 1f)) {
            if (f > 0.02f) {
                d.circle(DRUM_X + side * 300f, DRUM_Y - 30f,
                    20f + (1f - f) * 130f, Col.alpha(Col.rgb(255, 214, 96), (150 * f).toInt()), 4f)
            }
        }

        particles.draw(d)

        // ---- 节拍闪烁 + 文案 ----
        if (tickFlash > 0f && phase == 0) {
            d.circle(DRUM_X, 200f, 14f + 10f * tickFlash,
                Col.alpha(Col.rgb(255, 214, 96), (220 * tickFlash).toInt()))
        }
        if (phase == 0) {
            d.text("跟着节拍 · 握拳下砸", Design.W / 2, 130f, 40f,
                Col.rgb(255, 226, 140), align = "center", bold = true)
            d.text("校准 ${ticksDone.coerceAtMost(CALIB_TICKS)} / $CALIB_TICKS",
                Design.W / 2, 180f, 28f, Col.rgb(220, 226, 240), align = "center")
        }
        if (combo >= 2) {
            d.text("连击 ×$combo", 150f, Design.TOP + 40f, 34f,
                Col.rgb(255, 214, 96), bold = true)
        }
        if (msgT > 0f && lastMsg.isNotEmpty()) {
            d.text(lastMsg, Design.W / 2, 160f, 44f,
                if (lastMsg == "好！") Col.rgb(255, 226, 140) else Col.rgb(200, 226, 250),
                align = "center", bold = true)
        }
    }

    override fun hudItems(): List<HudItem> = listOf(
        HudItem("得分", "$mScore", accent),
        HudItem("连击", "$combo", Col.rgb(255, 226, 140)),
        HudItem("命中", "${nPerfect + nGood}/$NOTES", Col.rgb(126, 231, 135)),
        HudItem("生命", "$hearts", Col.rgb(255, 140, 120), icon = "heart"),
    )
}
