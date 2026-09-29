# ---- MediaPipe Tasks Vision：native 与 JNI 桥接必须保留 ----
-keep class com.google.mediapipe.** { *; }
-keepclasseswithmembernames class * { native <methods>; }
-keep class com.google.mediapipe.tasks.vision.** { *; }
-dontwarn com.google.mediapipe.**
-dontwarn com.google.protobuf.**

# ---- CameraX ----
-keep class androidx.camera.** { *; }
-dontwarn androidx.camera.**

# ---- Kotlin ----
-keepclassmembers class **$WhenMappings { <fields>; }
-keepclassmembers class kotlin.Metadata { public <methods>; }
-dontwarn kotlinx.coroutines.**

# ---- 移除日志（release）----
-assumenosideeffects class android.util.Log {
    public static boolean isLoggable(java.lang.String, int);
    public static int v(...);
    public static int d(...);
    public static int i(...);
}
