package com.motionarcade.game

import android.content.Context

/**
 * 极轻量的设备参数持久化（如鼓点的音频延迟校准值）。
 * 只存"这台设备上才有的东西"，不存进度——结算统计是另一回事。
 */
object GamePrefs {
    private lateinit var app: Context

    fun attach(context: Context) {
        app = context.applicationContext
    }

    fun getFloat(key: String, def: Float): Float = try {
        prefs().getFloat(key, def)
    } catch (_: Exception) {
        def
    }

    fun putFloat(key: String, value: Float) {
        try {
            prefs().edit().putFloat(key, value).apply()
        } catch (_: Exception) {
        }
    }

    private fun prefs() = app.getSharedPreferences("motion_arcade", Context.MODE_PRIVATE)
}
