import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

/** The short hash of the commit the checkout is at (`git rev-parse --short HEAD`, read as Gradle configures the
 * build), for the debug build's version; none outside a git checkout or with no git (a source tarball, a sandbox). */
val commit: String? = try {
    providers.exec {
        commandLine("git", "rev-parse", "--short", "HEAD")
        workingDir = rootDir
        isIgnoreExitValue = true
    }.standardOutput.asText.get().trim().takeIf { Regex("[0-9a-f]{4,40}").matches(it) }
} catch (e: Exception) {
    null
}

/** Whether :ml is in the build (settings.gradle.kts includes it in flake.nix's ml shell alone): the debug build's chord
 * models and Chords bench come with it. */
val chordsOnPhone = findProject(":ml") != null

android {
    namespace = "io.github.danielhp95.caracole"
    // flake.nix's platformVersion and buildToolsVersion: the SDK the shell provides.
    compileSdk = 36
    buildToolsVersion = "36.0.0"
    // r28c, flake.nix's ndkVersion: the NDK whose llvm-strip strips the native libraries the app packages (:ml's
    // libcaracole_soxr.so among them); without it the plugin looks for its own default, finds none, and packages
    // them unstripped.
    ndkVersion = "28.2.13676358"

    defaultConfig {
        applicationId = "io.github.danielhp95.caracole"
        minSdk = 26
        // 36, not 37: an app targeting Android 17 must ask for ACCESS_LOCAL_NETWORK to reach a LAN address.
        targetSdk = 36
        versionCode = 4
        versionName = "0.4.0"
        // Sends no site a request: caracole.network=loopback and a refusing Caracole.sitesForTests, before the app starts.
        testInstrumentationRunner = "io.github.danielhp95.caracole.CaracoleTestRunner"
        // The bundled SQLite's native library, for phones and for the emulator.
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
        // The port the phone's own server asks for first (Caracole.PORT).
        buildConfigField("int", "SERVER_PORT", "8738")
        // Settings' Chords bench row: a debug build with :ml alone (below).
        buildConfigField("boolean", "CHORDS_BENCH", "false")
    }

    // The release key, from outside the repo: ~/.gradle/gradle.properties (or -P / ORG_GRADLE_PROJECT_*) names the
    // keystore and its passwords. Without them assembleRelease still builds, unsigned.
    val releaseStore = providers.gradleProperty("caracole.release.storeFile").orNull
    val releaseSigning = releaseStore?.let {
        signingConfigs.create("release") {
            storeFile = file(it)
            storePassword = providers.gradleProperty("caracole.release.storePassword").get()
            keyAlias = providers.gradleProperty("caracole.release.keyAlias").getOrElse("caracole")
            keyPassword = providers.gradleProperty("caracole.release.keyPassword")
                .orElse(providers.gradleProperty("caracole.release.storePassword")).get()
        }
    }

    buildTypes {
        // A debug build installs beside F-Droid's release, never over it: a package of its own (so its own data and
        // library), named "Debug caracole" with an icon of its own (src/debug/res), and a port of its own, so both
        // keep their origin when they run at once. The test APK is io.github.danielhp95.caracole.debug.test. Its
        // version names the commit it was built from, "0.3.0-debug+abc1234" ([commit]), so the phone tells which.
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug" + (commit?.let { "+$it" } ?: "")
            buildConfigField("int", "SERVER_PORT", "8739")
            buildConfigField("boolean", "CHORDS_BENCH", chordsOnPhone.toString())
        }
        release {
            signingConfig = releaseSigning
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
    }

    // No dependency metadata in the APK: nothing a store could read about the build that isn't in it.
    dependenciesInfo {
        includeInApk = false
        includeInBundle = false
    }

    packaging {
        resources.excludes += setOf(
            "META-INF/*.version", "META-INF/*.kotlin_module", "DebugProbesKt.bin",
            "META-INF/INDEX.LIST", "META-INF/io.netty.versions.properties",
            // jansi's desktop libraries, which Ktor brings and Android never loads.
            "org/fusesource/jansi/internal/native/**",
        )
    }

    // The conformance vectors, as the device tests' assets (conformance/…): CorpusOnDeviceTest reads them through
    // the instrumentation's AssetManager.
    sourceSets.getByName("androidTest").assets.srcDir(layout.buildDirectory.dir("generated/conformanceAssets"))
    // The chord models in the debug build, where :ml is (settings.gradle.kts: the ml shell's source-built ONNX Runtime):
    // src/debugMl's PhoneChords, the Chords bench and its manifest, src/testDebugMl's and src/androidTestMl's tests of
    // them.
    // Elsewhere the debug build has the release's PhoneChords (none) and no bench, so the other shells build and test
    // the app with no ONNX Runtime ([chordsOnPhone], BuildConfig.CHORDS_BENCH).
    if (chordsOnPhone) {
        sourceSets.getByName("debug").java.srcDir("src/debugMl/kotlin")
        sourceSets.getByName("debug").manifest.srcFile("src/debugMl/AndroidManifest.xml")
        sourceSets.getByName("androidTest").java.srcDir("src/androidTestMl/kotlin")
        sourceSets.getByName("testDebug").java.srcDir("src/testDebugMl/kotlin")
    } else {
        sourceSets.getByName("debug").java.srcDir("src/release/kotlin")
    }
    // The Chords bench's committed clips (src/debugMl's ChordsBenchActivity): the computer's features and model outputs
    // of them, autochords/models.jsonl and frontend.jsonl (2.7 MB), the debug build's assets alone. No model file:
    // the owner's folder holds those (android/README.md, "The Chords bench").
    sourceSets.getByName("debug").assets.srcDir(layout.buildDirectory.dir("generated/benchAssets"))
}

val copyConformanceVectors by tasks.registering(Sync::class) {
    // The vectors, and the fixtures a record names (Corpus.fixture: `fixtures/`).
    into(layout.buildDirectory.dir("generated/conformanceAssets"))
    from("../../tests/conformance/vectors") { into("conformance") }
    from("../../tests/fixtures") { into("fixtures") }
}
tasks.matching { it.name.endsWith("AndroidTestAssets") }.configureEach { dependsOn(copyConformanceVectors) }

val copyBenchClips by tasks.registering(Sync::class) {
    into(layout.buildDirectory.dir("generated/benchAssets"))
    from("../../tests/conformance/vectors/autochords") {
        include("models.jsonl", "frontend.jsonl")
        into("autochords")
    }
}
tasks.matching { it.name.matches(Regex("(generate|merge|package)Debug\\w*Assets|lint\\w*Debug\\w*")) }
    .configureEach { dependsOn(copyBenchClips) }

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

// ApkScanTest (Gate R's string scan): the runtime built from its source, the AAR in $CARACOLE_ONNXRUNTIME, in every
// unit test run; the release and debug APKs by apkScan alone, which builds them (release-check.sh runs it).
tasks.withType<Test>().configureEach {
    systemProperty("caracole.onnxruntime", System.getenv("CARACOLE_ONNXRUNTIME") ?: "")
    if (name != "apkScan") filter { excludeTestsMatching("*.ApkScanTest.theApksHoldNoTelemetry") }
}
val apkScan by tasks.registering(Test::class) {
    description = "Scans the release and debug APKs for what made ONNX Runtime's Maven AAR phone home (ApkScanTest)."
    group = "verification"
    val unit = tasks.named<Test>("testDebugUnitTest").get()
    dependsOn("assembleRelease", "assembleDebug", "compileDebugUnitTestKotlin")
    testClassesDirs = unit.testClassesDirs
    classpath = unit.classpath
    filter { includeTestsMatching("*.ApkScanTest") }
    systemProperty("caracole.apks", listOf("release", "debug").joinToString(File.pathSeparator) {
        layout.buildDirectory.dir("outputs/apk/$it").get().asFile.path
    })
    outputs.upToDateWhen { false }
}

dependencies {
    implementation(project(":mirror"))
    implementation(project(":server"))
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.work:work-runtime-ktx:2.10.5")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    // The chord and beat models on ONNX Runtime, the debug build's alone until the release takes them (the design's
    // stage S, E33): no release carries it, and a debug build only where :ml is (the ml shell).
    if (chordsOnPhone) debugImplementation(project(":ml"))
    // Its hearing's types (Heard, Checkpoints), which the Chords bench's whole-pipeline mode reads: :ml's own, the
    // debug build's alone too.
    debugImplementation(project(":autochords"))

    // The app's own logic that needs no device (the text size, Settings over its preferences, a file read from the
    // phone's server and copied for another app, an index fetched): `gradle :app:test`.
    testImplementation("junit:junit:4.13.2")
    testImplementation(kotlin("test-junit"))

    androidTestImplementation(testFixtures(project(":core")))
    androidTestImplementation(testFixtures(project(":viewer")))
    androidTestImplementation(testFixtures(project(":server")))
    // The corpus's autochords area (its front ends over the committed clips), whose libsoxr is :ml's, the debug
    // build's.
    androidTestImplementation(testFixtures(project(":autochords")))
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test:core-ktx:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test.espresso:espresso-intents:3.7.0")
}

// alphaTab's bundle as the APK's assets, for the Guitar Pro page (lane guitar-alphatab's).
apply(from = "alphatab.gradle.kts")
