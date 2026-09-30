plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.motionarcade"
    // CameraX 1.6.2 及其传递依赖要求 compileSdk ≥ 36。
    compileSdk = 36

    defaultConfig {
        applicationId = "com.motionarcade"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"

        // 只打 arm64-v8a：目标设备（Android 手机 / Amlogic A311D2 级板卡）与
        // Apple Silicon 上的模拟器全是 arm64。armeabi-v7a / x86_64 各占约 9MB
        // 的 MediaPipe .so，去掉后 APK 从 54MB 降到约 35MB。
        ndk {
            abiFilters += listOf("arm64-v8a")
        }

        // 设计坐标系：1920x1080（横屏），常量见 game/Design.kt
    }

    buildTypes {
        getByName("debug") {
            isMinifyEnabled = false
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
        getByName("release") {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
        freeCompilerArgs += listOf(
            "-opt-in=kotlinx.coroutines.ExperimentalCoroutinesApi"
        )
    }

    // 模型与素材放 assets；MediaPipe 从 assets 加载 .task。
    androidResources {
        noCompress += listOf("task", "onnx")
    }

    packaging {
        resources {
            excludes += setOf(
                "/META-INF/{AL2.0,LGPL2.1}",
                "META-INF/DEPENDENCIES",
                "META-INF/LICENSE.md",
                "META-INF/NOTICE.md"
            )
        }
        jniLibs {
            useLegacyPackaging = true   // 让 .so 不压缩，减少安装后占用与加载耗时
        }
    }

    lint {
        abortOnError = false
        checkReleaseBuilds = false
    }
}

dependencies {
    // ---- AndroidX 基础 ----
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.activity:activity-ktx:1.9.3")

    // ---- CameraX 1.6.2（Google Jetpack 相机，工业标准）----
    // 只引 core / camera2 / lifecycle：画面是 Canvas 自绘的，不需要 camera-view
    // 的 PreviewView（那会多一次 GPU 合成，还会把 compileSdk 要求抬高到 36）。
    val camerax = "1.6.2"
    implementation("androidx.camera:camera-core:$camerax")
    implementation("androidx.camera:camera-camera2:$camerax")
    implementation("androidx.camera:camera-lifecycle:$camerax")

    // ---- MediaPipe Tasks Vision 1.0.0（Google AI Edge，姿态/手/脸）----
    implementation("com.google.mediapipe:tasks-vision:1.0.0")

    // ---- 协程（相机与分析线程编排）----
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
}
