package com.motionarcade.vision

/**
 * 所有游戏统一接收的输入结构 —— **与 Python 端 `core.inputs.GameInput` 一一对应**。
 *
 * 之所以复用同一个对象而不是每帧 new 一个 data class：
 * 这是 60fps 的实时链路，每帧产生垃圾会直接换来 GC 卡顿（体感游戏里表现为
 * 动作"顿一下"）。所以这里是可变对象 + [beginFrame] 复位边沿量。
 *
 * 坐标系约定
 * ----------
 * · 归一化坐标一律 ∈ [0,1]，原点在左上角；
 * · [axis]/[yaw]/[headY] 是有符号量，0 = 中性位（已减去校准中性值）；
 * · [hx]/[hy] 是**主手**掌心在画面中的归一化位置，游戏里再映射到屏幕光标。
 */
class GameInput {

    // ── 头部 ────────────────────────────────────────────────────────────
    /** 是否检测到头部/人脸。 */
    var found: Boolean = false

    /** 头部水平控制量 -1 ~ +1（以校准中性位为原点）。 */
    var axis: Float = 0f

    /** 抬头幅度 0~1。 */
    var up: Float = 0f

    /** 头部纵向连续量 -1(低头) ~ +1(抬头)。 */
    var headY: Float = 0f

    /** 头部左右转 -1 ~ +1（可以只转头不移动）。 */
    var yaw: Float = 0f

    /** 动作键：抬头超阈值 或 张嘴，持续为 true。 */
    var jump: Boolean = false

    /** 张嘴程度 0~1。 */
    var mouth: Float = 0f

    // ── 识别质量（供 UI 提示与降级；游戏逻辑一般不必关心）──────────────
    var confidence: Float = 1f
    var quality: String = QUALITY_GOOD          // good / far / poor / angle / lost
    var hint: String = ""

    // ── 手部 ────────────────────────────────────────────────────────────
    var handFound: Boolean = false
    var hx: Float = 0.5f
    var hy: Float = 0.5f
    var handOpen: Float = 0f                    // 0=握拳 1=张开
    var fingers: Int = 0
    var hands: List<HandState> = emptyList()
    var handL: HandState? = null
    var handR: HandState? = null
    var pinch: Boolean = false                  // 捏合边沿（仅触发帧为 true）
    var release: Boolean = false                // 张开边沿（握拳→张开那一刻）
    var grabHold: Boolean = false               // "保持收拢"连续状态

    // ── 全身（需要身体入镜）─────────────────────────────────────────────
    var bodyFound: Boolean = false
    var bodyX: Float = 0f                       // 身体横向偏移 -1 ~ +1
    var crouch: Float = 0f                      // 下蹲 0(站直) ~ 1(蹲到底)
    var armL: Float = 0f                        // 左臂举起 0~1
    var armR: Float = 0f
    var armLExt: Float = 0f                     // 左臂伸展 0(弯曲) ~ 1(伸直)
    var armRExt: Float = 0f

    companion object {
        const val QUALITY_GOOD = "good"
        const val QUALITY_FAR = "far"
        const val QUALITY_POOR = "poor"
        const val QUALITY_ANGLE = "angle"
        const val QUALITY_LOST = "lost"
    }

    /**
     * 每帧开头调用：只清**边沿量**（pinch/release），连续量保留，
     * 这样即使这一帧检测器没出结果，控制量也不会突然归零把角色甩回去。
     */
    fun beginFrame() {
        pinch = false
        release = false
    }

    /** 彻底复位（换游戏/重新校准时用）。 */
    fun reset() {
        found = false
        axis = 0f
        up = 0f
        headY = 0f
        yaw = 0f
        jump = false
        mouth = 0f
        confidence = 1f
        quality = QUALITY_GOOD
        hint = ""
        handFound = false
        hx = 0.5f
        hy = 0.5f
        handOpen = 0f
        fingers = 0
        hands = emptyList()
        handL = null
        handR = null
        pinch = false
        release = false
        grabHold = false
        bodyFound = false
        bodyX = 0f
        crouch = 0f
        armL = 0f
        armR = 0f
        armLExt = 0f
        armRExt = 0f
    }
}

/** 游戏声明自己需要哪些输入通道，用来**按需启停检测器**省算力。 */
enum class InputChannel { HEAD, HAND, BODY }
