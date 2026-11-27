// ml: caracole's chord model (BTC) and beat model (beat_this) on ONNX Runtime 1.27.1 built from its source (the design's
// §3.5, Gate R), an
// Android library linked into the debug app alone (app/build.gradle.kts's debugImplementation), so no release carries a
// runtime before the owner chooses the one that ships. Its device test, ModelParityTest, holds the runtime's logits to
// the computer's (tests/conformance/vectors/autochords/models.jsonl), DecoderTest its Decoder's PCM to the computer's
// decode (decode.jsonl), and PipelineTest the whole hearing in the :ml process (Pipeline, MlService, MlChordModels) to
// the computer's over the committed clips, each run by `android/scripts/device-test.sh --ml`.
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
}

/** ONNX Runtime's Android build, from its source (../nix/onnxruntime-android.nix: its AAR in the Maven folder
 * settings.gradle.kts reads, $CARACOLE_ONNXRUNTIME); [OrtModels.RUNTIME] names it, and ModelParityTest checks the
 * library loaded is this one. */
val onnxRuntime = "1.27.1"

android {
    namespace = "io.github.danielhp95.caracole.ml"
    compileSdk = 36
    buildToolsVersion = "36.0.0"
    // r28c, android/flake.nix's ndkVersion: it builds libcaracole_soxr.so (autochords/native/), 16 KB aligned.
    ndkVersion = "28.2.13676358"

    defaultConfig {
        minSdk = 26
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        // The app's two ABIs (app/build.gradle.kts), the two the runtime is built for.
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
        buildConfigField("String", "ONNX_RUNTIME", "\"$onnxRuntime\"")
    }

    buildFeatures {
        buildConfig = true
    }

    // libsoxr and its JNI (autochords/native/CMakeLists.txt, the one the JVM's tests build for this machine), for the
    // two ABIs, by android/flake.nix's CMake; its reproducibility flags are the CMakeLists' own (the design's §7).
    externalNativeBuild {
        cmake {
            path = file("../autochords/native/CMakeLists.txt")
            version = "3.31.6"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    // The computer's model outputs and their inputs, as the device test's assets (autochords/…), read through the
    // instrumentation's AssetManager as CorpusOnDeviceTest reads the rest of the corpus.
    sourceSets.getByName("androidTest").assets.srcDir(layout.buildDirectory.dir("generated/modelAssets"))
    // The runtime data of the models, caracole/autochords/ on the classpath (BTC's graph, models.json's pins):
    // :ml's, so the debug build's alone, which :core leaves out (core/build.gradle.kts).
    sourceSets.getByName("main").resources.srcDir(layout.buildDirectory.dir("generated/modelData"))
}

val copyModelVectors by tasks.registering(Sync::class) {
    into(layout.buildDirectory.dir("generated/modelAssets"))
    from("../../tests/conformance/vectors/autochords") {
        include("models.jsonl", "frontend.jsonl", "decode.jsonl")
        into("autochords")
    }
    // DecoderTest's files, the computer's decode of which decode.jsonl holds, and PipelineTest's clips, the
    // computer's hearing of which models.jsonl holds.
    from("../../tests/fixtures/autochords") {
        include("decode*.*", "hearing.*", "steady.wav", "tempo-change.wav", "silence.wav", "long.wav")
        into("autochords")
    }
}
tasks.matching { it.name.endsWith("AndroidTestAssets") }.configureEach { dependsOn(copyModelVectors) }

val copyModelData by tasks.registering(Sync::class) {
    into(layout.buildDirectory.dir("generated/modelData"))
    // frontend.json is :autochords' own resource.
    from("../../tests/conformance/data/caracole/autochords") {
        include("btc-graph.onnx", "models.json")
        into("caracole/autochords")
    }
}
tasks.matching { it.name.contains("JavaRes") || it.name.contains("JavaResource") || it.name.startsWith("lint") }
    .configureEach { dependsOn(copyModelData) }

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

// The JVM's tests of the pipeline (PipelineCheckpointsTest) run the CQT, whose resamples are libsoxr's: the host's
// build, :autochords' hostSoxr, as :autochords' own tests load it.
tasks.withType<Test>().configureEach {
    dependsOn(":autochords:hostSoxr")
    systemProperty("java.library.path", project(":autochords").layout.buildDirectory.dir("hostSoxr").get().asFile.path)
}

dependencies {
    // Pcm (a WAV's or an AIFF's PCM, read with no codec), for Decoder.
    implementation(project(":autochords"))
    implementation("io.github.danielhp95.caracole:onnxruntime-android:$onnxRuntime")
    // The Chords bench's report (BenchReport), as the rest of the app writes JSON (:core's, the same version).
    api("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")

    // BenchReportTest, on the JVM: `gradle :ml:testDebugUnitTest`, in `gradle test`.
    testImplementation("junit:junit:4.13.2")
    testImplementation(kotlin("test-junit"))

    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
}
