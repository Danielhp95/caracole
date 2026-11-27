pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        // ONNX Runtime built from its source (../nix/onnxruntime-android.nix), :ml's runtime in Maven Central's place:
        // its group comes from this folder alone, every shell of flake.nix naming it.
        val onnxRuntime = System.getenv("CARACOLE_ONNXRUNTIME")
            ?: error("CARACOLE_ONNXRUNTIME is unset: run Gradle in a shell of android/flake.nix (nix develop ./android)")
        exclusiveContent {
            forRepository { maven { name = "onnxruntime-from-source"; url = uri(onnxRuntime) } }
            filter { includeGroup("io.github.danielhp95.caracole") }
        }
        google()
        mavenCentral()
    }
}

rootProject.name = "caracole-android"
// mirror: the computer's pages on the phone; core: caracole's rules in Kotlin; viewer: the page builder (viewer/ in
// Kotlin); server: the phone's local server; app: the Android app; e2e: the end-to-end phases against a real caracole
// serve; ml: the chord and beat models on ONNX Runtime, the debug build's alone for now; autochords: the front ends of
// the chords from audio (libsoxr over JNI), on the JVM.
include(":mirror", ":core", ":viewer", ":server", ":app", ":e2e", ":ml", ":autochords")
