// 根构建脚本：只声明插件版本，不在这里写模块逻辑。
//
// 用 plugins DSL（而不是 buildscript + apply(plugin=)）的原因：
// Kotlin DSL 的类型安全访问器（android { }、dependencies { implementation() }）
// 只有在 plugins { } 块里声明插件时才会生成；用 apply(plugin=) 会退化成
// 一堆字符串调用，可读性和安全性都差很多。
plugins {
    id("com.android.application") version "8.13.2" apply false
    id("org.jetbrains.kotlin.android") version "2.2.21" apply false
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
