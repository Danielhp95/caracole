pluginManagement {
    repositories {
        google()
        // Chaquopy's plugin and its Python runtime (:youtube) come from here.
        mavenCentral()
        gradlePluginPortal()
    }
    // Chaquopy's version is youtube/pins.json's, the one place :youtube's pieces are pinned.
    val pins = groovy.json.JsonSlurper().parse(file("youtube/pins.json")) as Map<*, *>
    plugins {
        id("com.chaquo.python") version pins["chaquopy"] as String
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "caracole-android"
// mirror: the computer's pages on the phone; core: caracole's rules in Kotlin; viewer: the page builder (viewer/ in
// Kotlin); server: the phone's local server; app: the Android app; e2e: the end-to-end phases against a real caracole
// serve; ml: the chord and beat models on ONNX Runtime, the debug build's alone for now; autochords: the front ends of
// the chords from audio (libsoxr over JNI), on the JVM; youtube: yt-dlp under Chaquopy's Python, the debug build's alone
// for now.
include(":mirror", ":core", ":viewer", ":server", ":app", ":e2e", ":ml", ":autochords", ":youtube")
