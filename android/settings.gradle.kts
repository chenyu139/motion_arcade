pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        // Maven Central 官方域名在本机网络下会被掐断 Java 的 TLS 握手，
        // 这里用阿里云镜像代理 Maven Central / Google，保证插件 marker 可解析。
        maven("https://maven.aliyun.com/repository/public/")
        maven("https://maven.aliyun.com/repository/google/")
        mavenCentral()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        // 同根 build.gradle.kts：Maven Central 官方域名在此网络下 Java 握手会被掐断，
        // 用阿里云镜像（代理 Maven Central + Google）兜底。
        maven("https://maven.aliyun.com/repository/public/")
        maven("https://maven.aliyun.com/repository/google/")
        mavenCentral()
    }
}

rootProject.name = "MotionArcade"
include(":app")
