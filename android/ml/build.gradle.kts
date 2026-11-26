// ml: caracole's chord model (BTC) and beat model (beat_this) on ONNX Runtime (the design's §3.5 prototype), an
// Android library linked into the debug app alone (app/build.gradle.kts's debugImplementation), so no release carries a
// runtime before the owner chooses the one that ships. Its device test, ModelParityTest, holds the runtime's logits to
// the computer's (tests/conformance/vectors/autochords/models.jsonl), run by `android/scripts/device-test.sh --ml`.
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
}

/** ONNX Runtime's Android build, from Maven Central; [OrtModels.RUNTIME] names it, and ModelParityTest checks the
 * library loaded is this one. */
val onnxRuntime = "1.32.0"

android {
    namespace = "io.github.danielhp95.caracole.ml"
    compileSdk = 36
    buildToolsVersion = "36.0.0"

    defaultConfig {
        minSdk = 26
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        // The app's two ABIs (app/build.gradle.kts): ORT's AAR also brings 32-bit ARM and x86, which no APK keeps.
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
        buildConfigField("String", "ONNX_RUNTIME", "\"$onnxRuntime\"")
    }

    buildFeatures {
        buildConfig = true
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
        include("models.jsonl", "frontend.jsonl")
        into("autochords")
    }
}
tasks.matching { it.name.endsWith("AndroidTestAssets") }.configureEach { dependsOn(copyModelVectors) }

val copyModelData by tasks.registering(Sync::class) {
    into(layout.buildDirectory.dir("generated/modelData"))
    from("../../tests/conformance/data/caracole/autochords") { into("caracole/autochords") }
}
tasks.matching { it.name.contains("JavaRes") || it.name.contains("JavaResource") || it.name.startsWith("lint") }
    .configureEach { dependsOn(copyModelData) }

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

dependencies {
    implementation("com.microsoft.onnxruntime:onnxruntime-android:$onnxRuntime")
    // The Chords bench's report (BenchReport), as the rest of the app writes JSON (:core's, the same version).
    api("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")

    // BenchReportTest, on the JVM: `gradle :ml:testDebugUnitTest`, in `gradle test`.
    testImplementation("junit:junit:4.13.2")
    testImplementation(kotlin("test-junit"))

    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
}
