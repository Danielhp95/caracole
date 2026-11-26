// youtube: yt-dlp under Chaquopy's Python (the phone-youtube design's §3.1 and §3.5), an Android library linked into
// the debug app alone (app/build.gradle.kts's debugImplementation), so no release carries Python before the owner's
// gate (stage Y5). Every piece is youtube/pins.json's: Chaquopy's plugin (settings.gradle.kts) and its Python, and the
// two pure wheels, yt-dlp and yt-dlp-ejs, which android/flake.nix fetches by URL and SHA-256 into
// CARACOLE_YTDLP_WHEELS and pip installs from there alone, `--no-index --no-deps`. Its device test, YtDlpVersionTest,
// is run by `android/scripts/device-test.sh --youtube`; PinsTest, on the JVM, is in `gradle test`.
import groovy.json.JsonSlurper
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

val pinsFile: File = file("pins.json")
val pins = JsonSlurper().parse(pinsFile) as Map<*, *>
fun pin(name: String): Map<*, *> = pins[name] as Map<*, *>

/** What this module's tasks need from android/flake.nix's shell and is missing, each in words naming it; checked by
 * [checkEngine], which every task of this module runs first, so a build without them fails there, naming them, and
 * a build of another module (`gradle :core:test`) configures and runs without them. */
val missing = mutableListOf<String>()

/** The folder of the two wheels, android/flake.nix's CARACOLE_YTDLP_WHEELS. */
val wheels: File = System.getenv("CARACOLE_YTDLP_WHEELS")?.takeIf { it.isNotBlank() }?.let(::File)
    ?: File("CARACOLE_YTDLP_WHEELS-unset").also {
        missing += "CARACOLE_YTDLP_WHEELS is unset: run Gradle in android/flake.nix's shell " +
            "(`nix develop ./android -c gradle …`), which fetches youtube/pins.json's wheels into it"
    }
/** A pinned wheel's file in [wheels], by its URL's name. */
fun wheel(name: String): File = File(wheels, (pin(name)["url"] as String).substringAfterLast('/'))

/** Chaquopy's buildPython, which must be the app's Python's minor version (pins.json's `python`): `python3.13` on PATH,
 * android/flake.nix's, never another Python found by chance. */
val pythonVersion = pins["python"] as String
val buildPythonPath: String = System.getenv("PATH").orEmpty().split(File.pathSeparator)
    .map { File(it, "python$pythonVersion") }.firstOrNull { it.canExecute() }?.absolutePath
    ?: "python$pythonVersion".also {
        missing += "python$pythonVersion is not on PATH: Chaquopy's buildPython must be Python $pythonVersion, " +
            "android/flake.nix's shell's (`nix develop ./android -c gradle …`)"
    }

val checkEngine by tasks.registering {
    description = "Fails, naming it, when android/flake.nix's shell's wheels or python3.13 are missing."
    val said = missing.toList()
    doLast { if (said.isNotEmpty()) throw GradleException(said.joinToString("\n")) }
}
tasks.configureEach { if (name != checkEngine.name) dependsOn(checkEngine) }

android {
    namespace = "io.github.danielhp95.caracole.youtube"
    compileSdk = 36
    buildToolsVersion = "36.0.0"
    // r28c, android/flake.nix's ndkVersion: its llvm-strip strips the native libraries this module's test APK packages.
    ndkVersion = "28.2.13676358"

    defaultConfig {
        minSdk = 26
        testInstrumentationRunner = "io.github.danielhp95.caracole.youtube.YoutubeTestRunner"
        // The app's two ABIs (app/build.gradle.kts): Chaquopy's Python 3.12 and later is 64-bit alone.
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

}

// pins.json, as the device test's asset (youtube/pins.json), so YtDlpVersionTest holds the running Python to it: the
// task provider as the folder, which carries the dependency.
val copyPins by tasks.registering(Sync::class) {
    into(layout.buildDirectory.dir("generated/pinsAssets"))
    from(pinsFile) { into("youtube") }
}
android.sourceSets.getByName("androidTest").assets.srcDir(copyPins)

chaquopy {
    defaultConfig {
        version = pythonVersion
        buildPython(buildPythonPath)
        pip {
            // The two wheels alone, from the Nix folder: no index, no dependency (yt-dlp[default]'s brotli,
            // pycryptodomex, websockets and curl_cffi are native packages the phone doesn't need: §3.1).
            options("--no-index", "--no-deps")
            install(wheel("ytdlp").absolutePath)
            install(wheel("ejs").absolutePath)
        }
        // Our own code as source; the wheels and the standard library compiled (§3.4's trimming). The standard
        // library's other trimming, the modules yt-dlp never imports (tkinter, idlelib, test, ensurepip, lib2to3,
        // pydoc_data), is Chaquopy's own: it packages none of them (and 3.13 has no lib2to3), which YtDlpVersionTest
        // checks; Chaquopy has no setting to leave out more.
        pyc {
            src = false
        }
    }
}

// PinsTest reads pins.json and the wheels' folder; GlueTest runs the glue with buildPython over the wheels.
val glue: File = file("src/main/python")
tasks.withType<Test>().configureEach {
    inputs.file(pinsFile).withPropertyName("pins")
    inputs.files(wheels).withPropertyName("wheels")
    inputs.dir(glue).withPropertyName("glue")
    systemProperty("caracole.youtube.pins", pinsFile.absolutePath)
    systemProperty("caracole.youtube.wheels", wheels.absolutePath)
    systemProperty("caracole.youtube.python", buildPythonPath)
    systemProperty("caracole.youtube.glue", glue.absolutePath)
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

dependencies {
    // PinsTest, on the JVM: `gradle :youtube:testDebugUnitTest`, in `gradle test`.
    testImplementation("junit:junit:4.13.2")
    testImplementation(kotlin("test-junit"))
    testImplementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")

    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
}
