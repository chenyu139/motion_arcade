package com.motionarcade.audio

import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.util.Log
import java.util.concurrent.Executors
import kotlin.math.pow
import kotlin.math.sin
import kotlin.random.Random

/**
 * **纯程序化音效** —— 不引入任何音频素材文件（与 Python 端 `core/sfx.py` 同一套思路）。
 *
 * 为什么自己合成而不是打包音频文件：
 *   · 零体积、零版权；
 *   · 时长和音高可精确控制，能和 Combo 等级联动（连击越高音越高）；
 *   · 项目里本来也没有音频素材。
 *
 * 三条硬约束：
 * 1. **首次播放时合成一次并缓存**。合成要算几万个采样点，放在帧内会掉帧。
 * 2. **播放走后台线程**。AudioTrack 的 write/play 会阻塞，放在渲染线程会让操作卡顿。
 * 3. **音频不可用时全部退化为空操作，绝不抛异常**。无头环境/模拟器/静音设备
 *    都可能拿不到音频输出，游戏不能因此崩。
 */
object Sfx {

    private const val TAG = "Sfx"
    private const val RATE = 44100

    @Volatile
    private var muted = false

    /** 音频输出是否可用（拿不到就整体静默，不反复尝试）。 */
    @Volatile
    private var dead = false

    private val cache = HashMap<String, ShortArray>()
    private val pool = Executors.newSingleThreadExecutor { r ->
        Thread(r, "sfx").apply { isDaemon = true }
    }

    // ------------------------------------------------------------------ 对外接口

    fun play(name: String, vol: Float = 1f) {
        if (muted || dead) return
        pool.execute { playNow(name, vol) }
    }

    /** 连击音：等级越高音越高（对应 Python 端 play_combo）。 */
    fun playCombo(level: Int) {
        if (muted || dead) return
        val semis = (level.coerceIn(0, 12) * 1.5f)
        val freq = 523.25f * 2f.pow(semis / 12f)
        pool.execute { playNow("combo", 1f, freqOverride = freq) }
    }

    fun toggleMute(): Boolean {
        muted = !muted
        return muted
    }

    val isMuted: Boolean get() = muted

    // ------------------------------------------------------------------ 播放

    private fun playNow(name: String, vol: Float, freqOverride: Float = 0f) {
        val pcm = try {
            if (freqOverride > 0f) buildCombo(freqOverride) else cache.getOrPut(name) { build(name) }
        } catch (e: Exception) {
            Log.w(TAG, "build failed: $name", e); return
        }
        if (pcm.isEmpty()) return

        var track: AudioTrack? = null
        try {
            val minBuf = AudioTrack.getMinBufferSize(
                RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT
            )
            track = AudioTrack(
                AudioManager.STREAM_MUSIC, RATE,
                AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT,
                maxOf(minBuf, pcm.size * 2), AudioTrack.MODE_STATIC
            )
            if (track.state != AudioTrack.STATE_INITIALIZED) { dead = true; return }
            track.write(pcm, 0, pcm.size)
            track.play()
            // 后台线程，等它播完再释放（MODE_STATIC 不会自动回调结束）
            val ms = (pcm.size * 1000L) / RATE + 60
            Thread.sleep(ms)
        } catch (e: Exception) {
            dead = true
            Log.w(TAG, "audio unavailable, sfx disabled", e)
        } finally {
            try { track?.stop(); track?.release() } catch (_: Exception) {}
        }
    }

    // ------------------------------------------------------------------ 合成

    /** 音量包络：极短起音 + 幂函数衰减（卡通音效"脆"的来源）。 */
    private fun env(n: Int, attack: Float, decay: Float, power: Float): FloatArray {
        val out = FloatArray(n)
        val atk = (attack * RATE).toInt().coerceAtLeast(1)
        val dec = (decay * RATE).toInt().coerceAtLeast(1)
        for (i in 0 until n) {
            val a = (i.toFloat() / atk).coerceIn(0f, 1f)
            val d = (1f - i.toFloat() / dec).coerceIn(0f, 1f).toDouble().pow(power.toDouble()).toFloat()
            out[i] = a * d
        }
        return out
    }

    /**
     * 单音合成。
     * @param harm 二次谐波比例（避免纯正弦的"电子玩具"感）
     * @param slide 频率滑动 Hz/秒（上升=得分，下降=失败）
     * @param noise 噪声比例
     */
    private fun tone(freq: Float, dur: Float, vol: Float = 0.5f, harm: Float = 0.28f,
                     noise: Float = 0f, slide: Float = 0f,
                     attack: Float = 0.008f, power: Float = 2f): FloatArray {
        val n = (dur * RATE).toInt()
        val e = env(n, attack, dur, power)
        val out = FloatArray(n)
        var phase = 0.0
        var phase2 = 0.0
        for (i in 0 until n) {
            val t = i.toFloat() / RATE
            val f = freq + slide * t
            phase += 2.0 * Math.PI * f / RATE
            phase2 += 2.0 * Math.PI * f * 2.0 / RATE
            var s = sin(phase).toFloat() + harm * sin(phase2).toFloat()
            if (noise > 0f) s += noise * (Random.nextFloat() * 2f - 1f)
            out[i] = s * e[i] * vol
        }
        return out
    }

    private fun mix(vararg parts: FloatArray): FloatArray {
        val n = parts.maxOf { it.size }
        val out = FloatArray(n)
        for (p in parts) for (i in p.indices) out[i] += p[i]
        // 防削波
        var peak = 0f
        for (v in out) peak = maxOf(peak, kotlin.math.abs(v))
        if (peak > 0.95f) {
            val k = 0.95f / peak
            for (i in out.indices) out[i] *= k
        }
        return out
    }

    private fun chord(freqs: List<Float>, dur: Float, vol: Float = 0.4f): FloatArray =
        mix(*freqs.map { tone(it, dur, vol = vol / freqs.size * 1.6f) }.toTypedArray())

    /** 上行琶音（过关用）。 */
    private fun arpeggio(freqs: List<Float>, step: Float): FloatArray {
        val parts = ArrayList<FloatArray>()
        var t = 0
        for (f in freqs) {
            val p = tone(f, 0.34f, vol = 0.42f)
            val out = FloatArray(t + p.size)
            p.copyInto(out, t)
            parts.add(out)
            t += (step * RATE).toInt()
        }
        return mix(*parts.toTypedArray())
    }

    private fun toPcm(f: FloatArray): ShortArray {
        val out = ShortArray(f.size)
        for (i in f.indices) {
            val v = (f[i] * 32767f).toInt().coerceIn(-32768, 32767)
            out[i] = v.toShort()
        }
        return out
    }

    private fun buildCombo(freq: Float): ShortArray =
        toPcm(tone(freq, 0.16f, vol = 0.5f, harm = 0.30f, slide = 220f))

    /** 音效表：与 Python 端 `core/sfx._build` 的音效名一一对应。 */
    private fun build(name: String): ShortArray = when (name) {
        "move" ->       // 大厅移动选择：轻微一声"嗒"
            toPcm(tone(620f, 0.055f, vol = 0.30f, harm = 0.12f, attack = 0.004f, power = 3f))
        "confirm" ->    // 确认进入：上行两音
            toPcm(mix(
                tone(523.25f, 0.10f, vol = 0.42f),
                FloatArray((0.09f * RATE).toInt()).let { pad ->
                    val p = tone(783.99f, 0.16f, vol = 0.42f)
                    val out = FloatArray(pad.size + p.size); p.copyInto(out, pad.size); out
                }
            ))
        "hit" ->        // 得分：短促上滑
            toPcm(tone(660f, 0.13f, vol = 0.46f, harm = 0.30f, slide = 420f))
        "hit_big" ->    // 大额得分：更厚
            toPcm(mix(
                tone(392f, 0.22f, vol = 0.30f, harm = 0.34f),
                tone(587.33f, 0.22f, vol = 0.26f, harm = 0.30f, slide = 260f)
            ))
        "combo" ->
            buildCombo(523.25f)
        "fail" ->       // 失误：下行 + 噪声
            toPcm(tone(300f, 0.30f, vol = 0.40f, harm = 0.16f, noise = 0.10f,
                slide = -320f, power = 1.6f))
        "celebrate" ->  // 过关：上行琶音
            toPcm(arpeggio(listOf(523.25f, 659.25f, 783.99f, 1046.5f), 0.09f))
        "start" ->      // 开始：厚和弦
            toPcm(chord(listOf(261.63f, 329.63f, 392f), 0.42f, vol = 0.46f))
        else -> ShortArray(0)     // "pause" 等：不发声
    }
}
