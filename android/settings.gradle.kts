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

/** The source-built ONNX Runtime's Maven folder, set by flake.nix's `ml` shell alone (its one-off build, about 20 min a
 * machine): without it there is no :ml, and the app's debug build carries no chord models, so the other shells build
 * and test everything else with no ONNX Runtime. */
val onnxRuntime: String? = System.getenv("CARACOLE_ONNXRUNTIME")?.takeIf { it.isNotBlank() }

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        // ONNX Runtime built from its source (../nix/onnxruntime-android.nix), :ml's runtime in Maven Central's place:
        // its group comes from this folder alone, which flake.nix's ml shell names (below).
        onnxRuntime?.let { folder ->
            exclusiveContent {
                forRepository { maven { name = "onnxruntime-from-source"; url = uri(folder) } }
                filter { includeGroup("io.github.danielhp95.caracole") }
            }
        }
        google()
        mavenCentral()
    }
}

rootProject.name = "caracole-android"
// mirror: the computer's pages on the phone; core: caracole's rules in Kotlin; viewer: the page builder (viewer/ in
// Kotlin); server: the phone's local server; app: the Android app; e2e: the end-to-end phases against a real caracole
// serve; ml: the chord and beat models on ONNX Runtime, in the release (an arm64 phone's) as in debug builds, in the ml
// shell alone ($CARACOLE_ONNXRUNTIME); autochords: the front ends of the chords from audio (libsoxr over JNI), on the JVM;
// youtube: yt-dlp under Chaquopy's Python, the debug build's alone for now.
include(":mirror", ":core", ":viewer", ":server", ":app", ":e2e", ":autochords", ":youtube")
if (onnxRuntime != null) include(":ml")
