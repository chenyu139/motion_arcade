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
import kotlin.math.abs
import kotlin.math.sign

/**
 * 超级马里奥（横版平台跳跃）—— 头控代表游戏。
 *
 * 操作：头部左右平移 → 跑动；抬头 → 跳跃（有冷却，连抬不会连跳）。
 *
 * 物理常量与判定**逐项对齐 Python 端**（core/config.py + games/mario.py）：
 * GRAVITY 2600 / MAX_FALL 1500 / MOVE_ACCEL 3000 / GROUND_DECEL 3200 /
 * AIR_DECEL 1100 / JUMP_VELOCITY -920 / MAX_RUN 430 / COYOTE 0.10 /
 * JUMP_COOLDOWN 0.18。手感必须与桌面端一致，否则"验证手感"就没意义了。
 */
class MarioGame(
    private val sprites: SpriteManager,
    private val bg: BackgroundManager,
) : BaseGame() {

    override val key = "mario"
    override val title = "超级马里奥"
    override val sub = "川味横版"
    override val category = "头部控制"
    override val hint = "左右转头跑动　抬头跳跃"
    override val how = "用头部控制跑动与跳跃，吃金币、踩敌人，跑到终点旗杆"
    override val accent = Col.rgb(232, 96, 72)
    override val requires = setOf(InputChannel.HEAD)

    // ---- 常量（与 Python 端一致）----
    private companion object {
        const val GROUND = 900f
        const val LEVEL_W = 6200f
        const val DEATH_Y = 1260f
        const val PLAYER_W = 54f
        const val PLAYER_H = 74f
        const val GRAVITY = 2600f
        const val MAX_FALL = 1500f
        const val MOVE_ACCEL = 3000f
        const val GROUND_DECEL = 3200f
        const val AIR_DECEL = 1100f
        const val JUMP_VELOCITY = -920f
        const val MAX_RUN = 430f
        const val COYOTE_TIME = 0.10f
        const val JUMP_COOLDOWN = 0.18f
        const val GOAL_X = 6020f
        const val TIME_LIMIT = 100f
    }

    private data class Plat(val x: Float, val y: Float, val w: Float, val kind: String) {
        val h: Float get() = if (kind == "ground") 60f else 34f
    }

    // ---- 关卡数据（与 Python 端 PLATFORMS/COINS/FOES 一致）----
    private val platforms = listOf(
        Plat(0f, GROUND, 1180f, "ground"), Plat(1300f, GROUND, 700f, "ground"),
        Plat(2160f, GROUND, 520f, "ground"), Plat(2860f, GROUND, 900f, "ground"),
        Plat(3960f, GROUND, 620f, "ground"), Plat(4740f, GROUND, 1460f, "ground"),
        Plat(620f, 720f, 190f, "brick"), Plat(880f, 596f, 150f, "q"),
        Plat(1330f, 700f, 240f, "brick"), Plat(1640f, 560f, 150f, "q"),
        Plat(1820f, 700f, 180f, "brick"), Plat(2200f, 660f, 200f, "cloud"),
        Plat(2520f, 520f, 200f, "cloud"), Plat(2900f, 700f, 190f, "brick"),
        Plat(3120f, 560f, 150f, "q"), Plat(3320f, 690f, 220f, "brick"),
        Plat(3560f, 500f, 200f, "cloud"), Plat(4020f, 660f, 210f, "brick"),
        Plat(4300f, 520f, 170f, "q"), Plat(4560f, 700f, 160f, "brick"),
        Plat(4980f, 690f, 220f, "cloud"), Plat(5300f, 540f, 220f, "cloud"),
        Plat(5620f, 690f, 200f, "brick"),
    )

    private val coinX = floatArrayOf(660f, 700f, 740f, 910f, 950f, 1370f, 1420f, 1470f,
        1670f, 1710f, 1890f, 2250f, 2300f, 2350f, 2570f, 2610f, 2960f, 3160f,
        3200f, 3380f, 3600f, 3640f, 4070f, 4120f, 4340f, 4610f, 5030f, 5080f,
        5350f, 5390f, 5670f, 5720f, 5770f)
    private val coinY = floatArrayOf(660f, 660f, 660f, 530f, 530f, 640f, 640f, 640f,
        490f, 490f, 640f, 600f, 600f, 600f, 460f, 460f, 640f, 490f, 490f, 630f,
        440f, 440f, 600f, 600f, 460f, 640f, 620f, 620f, 480f, 480f, 630f, 630f, 630f)

    // 敌人：(x, 巡逻左, 巡逻右)
    private val foeX = floatArrayOf(700f, 1000f, 1420f, 1750f, 2260f, 2450f, 2990f,
        3200f, 3450f, 4120f, 4350f, 4900f, 5150f, 5380f, 5700f)
    private val foeL = floatArrayOf(600f, 900f, 1310f, 1310f, 2170f, 2170f, 2870f,
        2870f, 2870f, 3970f, 3970f, 4750f, 4750f, 4750f, 5560f)
    private val foeR = floatArrayOf(1150f, 1150f, 1950f, 1950f, 2650f, 2650f, 3700f,
        3700f, 3700f, 4540f, 4540f, 5500f, 5500f, 5500f, 6150f)

    // ---- 运行时状态 ----
    private var px = 140f
    private var py = GROUND - PLAYER_H
    private var vx = 0f
    private var vy = 0f
    private var onGround = true
    private var coyote = COYOTE_TIME
    private var jumpCd = 0f
    private var jumpHeld = false
    private var face = 1
    private var camX = 0f
    private var timeLeft = TIME_LIMIT
    private var coinCount = 0
    private val coinGot = BooleanArray(coinX.size)
    private val foeAlive = BooleanArray(foeX.size) { true }
    private val foeDir = FloatArray(foeX.size) { -1f }
    private val broken = HashSet<Int>()
    private val usedQ = HashSet<Int>()
    private var deathT = 0f
    private var winT = 0f

    override val score: Int get() = coinCount * 100

    override fun reset() {
        px = 140f; py = GROUND - PLAYER_H
        vx = 0f; vy = 0f
        onGround = true; coyote = COYOTE_TIME
        jumpCd = 0f; jumpHeld = false; face = 1
        camX = 0f; timeLeft = TIME_LIMIT; coinCount = 0
        coinGot.fill(false); foeAlive.fill(true); foeDir.fill(-1f)
        broken.clear(); usedQ.clear()
        deathT = 0f; winT = 0f
        state = STATE_PLAY
        particles.clear()
    }

    override fun update(dt: Float, inp: GameInput) {
        if (state != STATE_PLAY) {
            if (state == STATE_WIN) {
                winT += dt
                if (winT > 2.4f) { /* 由外壳切结算 */ }
            } else {
                deathT += dt
                if (deathT > 1.4f) respawn()
            }
            return
        }

        timeLeft -= dt
        if (timeLeft <= 0f) { die(); return }

        // ---- 输入 ----
        val axis = inp.axis.coerceIn(-1f, 1f) * 1.15f
        val jump = inp.jump
        if (abs(axis) > 0.08f) face = if (axis > 0) 1 else -1

        // ---- 水平加速/减速 ----
        val target = axis * MAX_RUN
        if (abs(target) > abs(vx)) {
            vx += sign(target - vx) * (if (onGround) MOVE_ACCEL else AIR_DECEL * 1.6f) * dt
        } else {
            val dec = if (onGround) GROUND_DECEL else AIR_DECEL
            vx = if (vx > 0) maxOf(target, vx - dec * dt) else minOf(target, vx + dec * dt)
        }

        // ---- 跳跃 ----
        jumpCd = maxOf(0f, jumpCd - dt)
        coyote = if (!onGround) maxOf(0f, coyote - dt) else COYOTE_TIME
        if (jump && !jumpHeld && jumpCd <= 0f && (onGround || coyote > 0f)) {
            vy = JUMP_VELOCITY
            onGround = false
            coyote = 0f
            jumpCd = JUMP_COOLDOWN
            jumpHeld = true
            addShake(4f)
            particles.burst(px + PLAYER_W / 2, py + PLAYER_H, 8,
                Col.rgb(236, 240, 250), speed = 180f, spread = 90f, dirDeg = 270f, sizeRange = 3.4f)
        }
        if (!jump) jumpHeld = false

        // ---- 重力 ----
        vy = minOf(MAX_FALL, vy + GRAVITY * dt)

        // ---- 水平移动 + 碰撞 ----
        px += vx * dt
        for (i in platforms.indices) {
            val p = platforms[i]
            if (p.kind == "cloud" || (p.kind == "brick" && i in broken)) continue
            if (!overlap(px, py, PLAYER_W, PLAYER_H, p.x, p.y, p.w, p.h)) continue
            px = if (vx > 0) p.x - PLAYER_W else p.x + p.w
            vx = 0f
        }

        // ---- 垂直移动 + 碰撞 ----
        py += vy * dt
        val wasAir = !onGround
        onGround = false
        for (i in platforms.indices) {
            val p = platforms[i]
            if (p.kind == "brick" && i in broken) continue
            if (p.kind == "cloud" && vy <= 0f) continue
            if (!overlap(px, py, PLAYER_W, PLAYER_H, p.x, p.y, p.w, p.h)) continue
            if (vy > 0) {
                py = p.y - PLAYER_H
                vy = 0f
                onGround = true
            } else {
                py = p.y + p.h
                vy = 120f
                when (p.kind) {
                    "q" -> if (i !in usedQ) { usedQ.add(i); popCoin(p.x + p.w / 2, p.y - 40f) }
                    "brick" -> {
                        broken.add(i); addShake(7f)
                        particles.burst(p.x + p.w / 2, p.y + p.h / 2, 16,
                            Col.rgb(196, 108, 64), speed = 300f, spread = 260f, dirDeg = 270f)
                    }
                    else -> addShake(5f)
                }
            }
        }

        // ---- 掉出世界 ----
        if (py > DEATH_Y) { die(); return }

        // ---- 金币 ----
        for (i in coinX.indices) {
            if (coinGot[i]) continue
            if (abs(px + PLAYER_W / 2 - coinX[i]) < 42f && abs(py + PLAYER_H / 2 - coinY[i]) < 46f) {
                coinGot[i] = true
                coinCount++
                particles.burst(coinX[i], coinY[i], 10, Col.rgb(255, 214, 96),
                    speed = 240f, spread = 360f, sizeRange = 5f)
            }
        }

        // ---- 敌人巡逻与踩踏 ----
        for (i in foeX.indices) {
            if (!foeAlive[i]) continue
            val fx = foeX[i]
            if (fx < foeL[i] || fx > foeR[i]) foeDir[i] = -foeDir[i]
            foeX[i] = (fx + foeDir[i] * 90f * dt).coerceIn(foeL[i], foeR[i])
            val ex = foeX[i]
            val ey = GROUND - 58f
            if (overlap(px, py, PLAYER_W, PLAYER_H, ex - 26f, ey, 52f, 58f)) {
                if (vy > 0 && py + PLAYER_H - vy * dt <= ey + 12f) {
                    foeAlive[i] = false
                    vy = -620f
                    addShake(6f)
                    particles.burst(ex, ey, 14, Col.rgb(150, 200, 120),
                        speed = 300f, spread = 360f)
                } else {
                    die(); return
                }
            }
        }

        // ---- 终点 ----
        if (px > GOAL_X) {
            state = STATE_WIN
            winT = 0f
            particles.burst(px, py, 40, Col.rgb(255, 214, 96), speed = 420f, spread = 360f)
        }

        // ---- 相机：玩家保持在画面偏左 700 处 ----
        val want = (px - 700f).coerceIn(0f, LEVEL_W - Design.W)
        camX += (want - camX) * (1f - kotlin.math.exp(-8f * dt))
    }

    private fun overlap(ax: Float, ay: Float, aw: Float, ah: Float,
                        bx: Float, by: Float, bw: Float, bh: Float): Boolean =
        ax < bx + bw && ax + aw > bx && ay < by + bh && ay + ah > by

    private fun popCoin(cx: Float, cy: Float) {
        coinCount++
        particles.burst(cx, cy, 12, Col.rgb(255, 214, 96), speed = 260f, spread = 360f)
        addShake(3f)
    }

    private fun die() {
        state = STATE_OVER
        deathT = 0f
        addShake(12f)
        particles.burst(px + PLAYER_W / 2, py + PLAYER_H / 2, 26,
            Col.rgb(236, 96, 72), speed = 380f, spread = 360f)
    }

    private fun respawn() {
        px = 140f; py = GROUND - PLAYER_H
        vx = 0f; vy = 0f
        state = STATE_PLAY
        timeLeft = TIME_LIMIT
    }

    // ------------------------------------------------------------------ 绘制

    override fun draw(d: Canvas2D) {
        // 背景（视差 + 渐变兜底）
        bg.drawOr(d, "bg_bev_game", Design.W, Design.H,
            Col.rgb(58, 122, 206), Col.rgb(120, 170, 220), Col.rgb(150, 202, 244))

        drawHills(d)

        // ---- 世界物体（减去相机偏移）----
        val ox = -camX
        for (i in platforms.indices) {
            val p = platforms[i]
            if (p.kind == "brick" && i in broken) continue
            val sx = p.x + ox
            if (sx + p.w < -60f || sx > Design.W + 60f) continue
            drawPlatform(d, sx, p)
        }

        // 金币
        for (i in coinX.indices) {
            if (coinGot[i]) continue
            val sx = coinX[i] + ox
            if (sx < -40f || sx > Design.W + 40f) continue
            if (!sprites.draw(d, "coin", sx, coinY[i], 46f)) {
                d.circle(sx, coinY[i], 22f, Col.rgb(255, 214, 96))
                d.circle(sx, coinY[i], 22f, Col.rgb(210, 150, 40), 3f)
            }
        }

        // 敌人
        for (i in foeX.indices) {
            if (!foeAlive[i]) continue
            val sx = foeX[i] + ox
            if (sx < -60f || sx > Design.W + 60f) continue
            val sy = GROUND - 58f + 29f
            if (!sprites.draw(d, "enemy", sx, sy, 58f, flipX = foeDir[i] > 0)) {
                d.ellipse(sx, sy, 26f, 29f, Col.rgb(168, 116, 74))
            }
        }

        // 终点旗杆
        val gx = GOAL_X + ox
        if (gx in -80f..Design.W + 80f) {
            d.rect(gx - 4f, GROUND - 320f, 8f, 320f, Col.rgb(220, 226, 236))
            d.polygon(floatArrayOf(gx + 4f, GROUND - 320f, gx + 120f, GROUND - 280f,
                gx + 4f, GROUND - 240f), Col.rgb(232, 96, 72))
        }

        // 玩家
        val psx = px + ox
        val psy = py
        if (!sprites.draw(d, "panda_hero", psx + PLAYER_W / 2, psy + PLAYER_H / 2,
                PLAYER_H * 1.25f, flipX = face < 0)) {
            // 缺图回退：矢量小人
            d.roundRect(psx, psy + 14f, PLAYER_W, PLAYER_H - 14f, 16f, accent)
            d.circle(psx + PLAYER_W / 2, psy + 16f, 20f, Col.rgb(250, 240, 226))
            d.circle(psx + PLAYER_W / 2 + face * 7f, psy + 14f, 4f, Col.rgb(40, 36, 44))
        }

        particles.draw(d)
        // 顶部 HUD 由外壳统一绘制（见 Hud.kt），这里不再自己画，避免与浮层重叠。
    }

    override fun hudItems(): List<HudItem> = listOf(
        HudItem("金币", "$coinCount", Col.rgb(255, 226, 140)),
        HudItem("进度", "${((px / GOAL_X) * 100).toInt().coerceIn(0, 100)}%", Col.rgb(126, 231, 135)),
        HudItem("时间", "${maxOf(0f, timeLeft).toInt()}", Col.rgb(226, 232, 240)),
    )

    private fun drawHills(d: Canvas2D) {
        val shift = (camX * 0.25f) % 900f
        for (k in -1..3) {
            val cx = k * 900f - shift
            d.ellipse(cx, GROUND + 40f, 300f, 180f, Col.rgb(74, 152, 88))
            d.ellipse(cx + 420f, GROUND + 60f, 230f, 130f, Col.rgb(86, 168, 96))
        }
        d.rect(0f, GROUND, Design.W, Design.H - GROUND, Col.rgb(120, 84, 56))
        d.rect(0f, GROUND, Design.W, 14f, Col.rgb(96, 176, 92))
    }

    private fun drawPlatform(d: Canvas2D, sx: Float, p: Plat) {
        when (p.kind) {
            "ground" -> {
                d.rect(sx, p.y, p.w, p.h, Col.rgb(150, 100, 62))
                d.rect(sx, p.y, p.w, 12f, Col.rgb(96, 176, 92))
            }
            "brick" -> {
                d.rect(sx, p.y, p.w, p.h, Col.rgb(196, 108, 64))
                for (i in 0 until (p.w / 34f).toInt()) {
                    d.line(sx + i * 34f, p.y, sx + i * 34f, p.y + p.h,
                        Col.rgb(150, 76, 44), 2f)
                }
            }
            "q" -> {
                val used = platforms.indexOf(p) in usedQ
                d.rect(sx, p.y, p.w, p.h, if (used) Col.rgb(150, 110, 70) else Col.rgb(240, 180, 60))
                d.text("?", sx + p.w / 2, p.y + p.h / 2, 30f,
                    if (used) Col.rgb(90, 80, 70) else Col.rgb(90, 60, 20),
                    align = "center", bold = true)
            }
            "cloud" -> {
                d.roundRect(sx, p.y, p.w, p.h, p.h / 2, Col.rgb(238, 246, 252))
                d.roundRect(sx, p.y, p.w, p.h, p.h / 2, Col.rgb(200, 214, 232), 3f)
            }
        }
    }
}
