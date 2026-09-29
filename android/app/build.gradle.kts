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

        // 只打真机主流 ABI + 模拟器 x86_64，避免 MediaPipe 的 .so 把 APK 撑到几百 MB。
        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a", "x86_64")
        }

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        // 设计坐标系与 Python 端一致：1920x1080（横屏）
        buildConfigField("int", "DESIGN_W", "1920")
        buildConfigField("int", "DESIGN_H", "1080")
        buildConfigField("int", "TARGET_FPS", "60")
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

    buildFeatures {
        buildConfig = true
        viewBinding = false
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
