package com.motionarcade

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.WindowManager
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.addCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.motionarcade.game.GameSurfaceView

/**
 * Motion Arcade Android 入口。
 *
 * 职责边界（刻意保持很薄）：
 *  - 权限：只申请摄像头（体感输入必需），震动是普通权限无需申请；
 *  - 窗口：全屏沉浸、常亮、横屏（清单里声明 sensorLandscape）；
 *  - 生命周期：把 resume/pause 转给 [GameSurfaceView]，由它驱动渲染线程与相机；
 *  - 不在这里写任何游戏逻辑 —— 全部在 game/ 与 render/ 包里。
 */
class MainActivity : ComponentActivity() {

    private lateinit var gameView: GameSurfaceView

    private val requestCamera = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            gameView.onCameraPermissionGranted()
        } else {
            Toast.makeText(
                this,
                "需要摄像头权限才能进行体感操控",
                Toast.LENGTH_LONG
            ).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // 全屏 + 内容延伸到系统栏之下（由游戏画面自己留出安全边距）
        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        // GameSurfaceView 需要 LifecycleOwner 来绑定 CameraX（相机随生命周期自动解绑）
        gameView = GameSurfaceView(this, this)
        setContentView(gameView)

        hideSystemBars()
        ensureCameraPermission()

        // 返回键交给游戏层：游戏中先暂停/退回大厅；大厅里再按则退出应用
        onBackPressedDispatcher.addCallback(this) {
            if (!gameView.handleBack()) finish()
        }
    }

    private fun ensureCameraPermission() {
        val granted = ContextCompat.checkSelfPermission(
            this, Manifest.permission.CAMERA
        ) == PackageManager.PERMISSION_GRANTED
        if (granted) {
            gameView.onCameraPermissionGranted()
        } else {
            requestCamera.launch(Manifest.permission.CAMERA)
        }
    }

    private fun hideSystemBars() {
        WindowInsetsControllerCompat(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior =
                WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemBars()
    }

    override fun onResume() {
        super.onResume()
        gameView.onResumeOwner()
    }

    override fun onPause() {
        gameView.onPauseOwner()
        super.onPause()
    }

    override fun onDestroy() {
        gameView.onDestroyOwner()
        super.onDestroy()
    }
}
