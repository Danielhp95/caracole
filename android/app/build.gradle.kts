import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

/** youtube/pins.json's yt-dlp version, the one place it is pinned. */
val ytdlpVersion: String = ((groovy.json.JsonSlurper().parse(rootProject.file("youtube/pins.json")) as Map<*, *>)["ytdlp"]
    as Map<*, *>)["version"] as String


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

/** Whether :ml is in the build (settings.gradle.kts includes it in flake.nix's ml shell alone): the chord models (both
 * builds) and the debug build's Chords bench come with it, and a release is made with it alone. */
val chordsOnPhone = findProject(":ml") != null

/** The release's ABIs for the chord models' libraries (ONNX Runtime, libsoxr): arm64-v8a alone, the phones that make
 * chords (the design's §7: x86_64 phones are few, and the APK would carry 13.6 MB more), while SQLite's ships for both;
 * a debug build keeps both, for the emulator. MlChordModels.deviceProblem says "no chord models for this phone's
 * processor" on the others (BuildConfig.ML_ABIS). */
val releaseMlAbis = listOf("arm64-v8a")

/** The release's ABIs for the app's yt-dlp (Chaquopy's Python, its libraries and standard library, and :youtube's
 * libqjs.so): arm64-v8a alone, as the chord models', which a sheet from a YouTube video needs (the phone-youtube
 * design's §3.4); a debug build keeps both. PhoneYouTube says "this phone's caracole has no yt-dlp" on the others
 * (BuildConfig.YOUTUBE_ABIS). */
val releaseYoutubeAbis = listOf("arm64-v8a")

/** The app's ABIs (SQLite's library for both, and a debug build's chord models' and yt-dlp's too). */
val appAbis = listOf("arm64-v8a", "x86_64")

/** The largest release APK the self-hosted F-Droid repository takes (its Pages site: no file over 100 MB). */
val apkMost = 100L * 1024 * 1024

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
        ndk { abiFilters += appAbis }
        // The port the phone's own server asks for first (Caracole.PORT).
        buildConfigField("int", "SERVER_PORT", "8738")
        // The yt-dlp :youtube packages (youtube/pins.json's), which Settings' YouTube audio row names (YouTubeRow).
        buildConfigField("String", "YTDLP_VERSION", "\"$ytdlpVersion\"")
        // The ABIs whose Python and qjs the APK carries ([releaseYoutubeAbis]; a debug build's below).
        buildConfigField("String", "YOUTUBE_ABIS", "\"${releaseYoutubeAbis.joinToString(",")}\"")
        // Settings' Chords bench row: a debug build with :ml alone (below).
        buildConfigField("boolean", "CHORDS_BENCH", "false")
        // The ABIs whose chord models' libraries the APK carries ([releaseMlAbis]; a debug build's below).
        buildConfigField("String", "ML_ABIS", "\"${releaseMlAbis.joinToString(",")}\"")
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
            buildConfigField("String", "ML_ABIS", "\"${appAbis.joinToString(",")}\"")
            buildConfigField("String", "YOUTUBE_ABIS", "\"${appAbis.joinToString(",")}\"")
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
    // The chord models, where :ml is (settings.gradle.kts: the ml shell's source-built ONNX Runtime): src/ml's
    // PhoneChords and PhoneExaminer in both builds; the debug build's Chords bench (src/debugMl, its manifest merged
    // below), and src/testDebugMl's and src/androidTestMl's tests. Elsewhere src/noMl's (none: auto-chords isn't on the
    // phone) and no bench, so the other shells build and test the app with no ONNX Runtime ([chordsOnPhone],
    // BuildConfig.CHORDS_BENCH); a release is never made so (below).
    if (chordsOnPhone) {
        sourceSets.getByName("main").java.srcDir("src/ml/kotlin")
        sourceSets.getByName("debug").java.srcDir("src/debugMl/kotlin")
        sourceSets.getByName("androidTest").java.srcDir("src/androidTestMl/kotlin")
        sourceSets.getByName("testDebug").java.srcDir("src/testDebugMl/kotlin")
    } else {
        sourceSets.getByName("main").java.srcDir("src/noMl/kotlin")
    }
    // The Chords bench's committed clips (src/debugMl's ChordsBenchActivity): the computer's features and model outputs
    // of them, autochords/models.jsonl and frontend.jsonl (2.7 MB), the debug build's assets alone. No model file:
    // the owner's folder holds those (android/README.md, "The Chords bench").
    sourceSets.getByName("debug").assets.srcDir(layout.buildDirectory.dir("generated/benchAssets"))
}

// Every build's native libraries extracted at install into the app's native library folder (android:
// extractNativeLibs), the one place Android runs a program of the app's own: :youtube's libqjs.so, QuickJS-NG's qjs,
// which yt-dlp runs for YouTube's player challenges (the phone-youtube design's §3.4). It applies to every library of
// the APK, not qjs alone: ONNX Runtime's, SQLite's, Python's and libsoxr are then compressed in the APK and installed
// a second time, uncompressed, in that folder, which costs the compressed copies the APK keeps: the release's growth
// over E33's, measured with them so, is android/README.md's ("A sheet from a YouTube video").
androidComponents.onVariants(androidComponents.selector().all()) {
    it.packaging.jniLibs.useLegacyPackaging.set(true)
}
androidComponents.onVariants(androidComponents.selector().withBuildType("debug")) {
    // The Chords bench's manifest (src/debugMl), merged over src/debug's (the YouTube bench's) where :ml is.
    if (chordsOnPhone) it.sources.manifests.addStaticManifestFile("src/debugMl/AndroidManifest.xml")
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

// The release's chord models' libraries for [releaseMlAbis] alone: ONNX Runtime's and libsoxr's of every other ABI left
// out of its APK (SQLite's kept); and its yt-dlp's for [releaseYoutubeAbis] alone: Python's libraries (libpython*,
// libchaquopy_java.so, OpenSSL's and SQLite's lib*_python.so and lib*_chaquopy.so) and libqjs.so, and Chaquopy's assets
// of the other ABIs ([DropPythonAbis]), which Chaquopy, reading defaultConfig's abiFilters alone, makes for both.
androidComponents {
    onVariants(selector().withBuildType("release")) { variant ->
        for (abi in appAbis.filter { it !in releaseMlAbis }) {
            variant.packaging.jniLibs.excludes.addAll(
                "**/$abi/libonnxruntime.so", "**/$abi/libonnxruntime4j_jni.so", "**/$abi/libcaracole_soxr.so")
        }
        val dropped = appAbis.filter { it !in releaseYoutubeAbis }
        for (abi in dropped) {
            variant.packaging.jniLibs.excludes.addAll(
                "**/$abi/libpython*.so", "**/$abi/libchaquopy_java.so", "**/$abi/lib*_python.so",
                "**/$abi/lib*_chaquopy.so", "**/$abi/libqjs.so")
        }
        val drop = tasks.register<DropPythonAbis>("drop${variant.name.replaceFirstChar { it.uppercase() }}PythonAbis") {
            abis.set(dropped)
        }
        variant.artifacts.use(drop).wiredWithDirectories(DropPythonAbis::input, DropPythonAbis::output)
            .toTransform(com.android.build.api.artifact.SingleArtifact.ASSETS)
    }
}

// A release carries the chord models: one made without :ml (outside the ml shell) would ship an app that says
// auto-chords isn't on the phone, so it is refused before anything runs, whichever of the release's packaging tasks
// is asked for (assemble, bundle, package, install), so that no app-release.apk is ever written without them. Its
// tests, lint and compiles still run in every shell (`gradle test`).
gradle.taskGraph.whenReady {
    // The tasks that make or install the release's APK or bundle (never its resources' or classes' jars, which
    // `gradle test`'s release unit tests build too).
    val packaging = setOf("assembleRelease", "bundleRelease", "packageRelease", "packageReleaseBundle",
        "signReleaseBundle", "installRelease", "minifyReleaseWithR8")
    val asked = allTasks.filter { it.project == project && it.name in packaging }.map { it.name }
    if (!chordsOnPhone && asked.isNotEmpty()) {
        throw GradleException("a release carries the chord models (asked: ${asked.joinToString()}): build it in " +
            "flake.nix's ml shell (nix develop ./android#ml), whose CARACOLE_ONNXRUNTIME brings :ml")
    }
}

// The release APK's size against [apkMost], after every release build (release-check.sh too): the APK its
// output-metadata.json names, never a stale one beside it.
val checkApkSize by tasks.registering {
    description = "Fails a release APK over 100 MiB, the most the self-hosted F-Droid repository takes."
    group = "verification"
    dependsOn("assembleRelease")
    val folder = layout.buildDirectory.dir("outputs/apk/release")
    doLast {
        val dir = folder.get().asFile
        val name = Regex("\"outputFile\"\\s*:\\s*\"([^\"]+)\"").find(File(dir, "output-metadata.json").readText())
            ?.groupValues?.get(1) ?: throw GradleException("no outputFile in $dir/output-metadata.json")
        val apk = File(dir, name)
        val size = apk.length()
        if (size > apkMost) throw GradleException("$apk is $size bytes, over 100 MiB ($apkMost)")
        logger.lifecycle("checkApkSize: ${apk.name} is $size bytes, under 100 MiB")
    }
}
tasks.matching { it.name == "assembleRelease" }.configureEach { finalizedBy(checkApkSize) }

// ApkScanTest (Gate R's string scan): the runtime built from its source, the AAR in $CARACOLE_ONNXRUNTIME, in every
// unit test run; the release and debug APKs by apkScan alone, which builds them (release-check.sh runs it).
tasks.withType<Test>().configureEach {
    systemProperty("caracole.onnxruntime", System.getenv("CARACOLE_ONNXRUNTIME") ?: "")
    if (name != "apkScan") filter {
        excludeTestsMatching("*.ApkScanTest.theApksHoldNoTelemetry")
        excludeTestsMatching("*.NoticesTest.theApksCarryTheNotices")
    }
    // NoticesTest: :youtube's notices folder (its copyLicences) against their sources.
    dependsOn(":youtube:copyLicences")
    systemProperty("caracole.youtube.licenses",
                   rootProject.file("youtube/build/generated/licenceAssets/licenses/youtube").path)
    systemProperty("caracole.youtube.committed", rootProject.file("youtube/licenses").path)
    systemProperty("caracole.youtube.wheels", System.getenv("CARACOLE_YTDLP_WHEELS") ?: "")
    systemProperty("caracole.youtube.quickjs", System.getenv("CARACOLE_QUICKJS_SRC") ?: "")
}
val apkScan by tasks.registering(Test::class) {
    description = "Scans the release and debug APKs for what made ONNX Runtime's Maven AAR phone home (ApkScanTest), " +
        "and for the notices of their yt-dlp (NoticesTest)."
    group = "verification"
    val unit = tasks.named<Test>("testDebugUnitTest").get()
    dependsOn("assembleRelease", "assembleDebug", "compileDebugUnitTestKotlin")
    testClassesDirs = unit.testClassesDirs
    classpath = unit.classpath
    filter {
        includeTestsMatching("*.ApkScanTest")
        includeTestsMatching("*.NoticesTest")
    }
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
    // The chord and beat models on ONNX Runtime (the design's stage S), both builds, where :ml is (the ml shell), and
    // :autochords' audio lengths (PhoneExaminer) and hearing's types (the Chords bench's whole-pipeline mode); without
    // :ml, :autochords for the debug build's device tests alone (the corpus's autochords area).
    if (chordsOnPhone) {
        implementation(project(":ml"))
        implementation(project(":autochords"))
    } else {
        debugImplementation(project(":autochords"))
    }
    // yt-dlp under Chaquopy's Python (a song's audio from YouTube), both builds (the phone-youtube design's stage Y5),
    // the release's for arm64-v8a alone (above).
    implementation(project(":youtube"))

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

/**
 * A release's merged assets less Chaquopy's of [abis] (its standard library's and requirements' `.imy`, its bootstrap's
 * native modules), and their entries in `chaquopy/build.json` (written again, its assets sorted); Chaquopy's runtime
 * takes the first of the phone's ABIs it finds a `stdlib-<abi>.imy` of. Every other asset copied as it is.
 */
abstract class DropPythonAbis : DefaultTask() {
    @get:Input abstract val abis: ListProperty<String>
    @get:InputDirectory abstract val input: DirectoryProperty
    @get:OutputDirectory abstract val output: DirectoryProperty

    @TaskAction
    fun drop() {
        val from = input.get().asFile
        val into = output.get().asFile.apply { deleteRecursively(); mkdirs() }
        val dropped = abis.get().flatMap { listOf("stdlib-$it.imy", "requirements-$it.imy", "bootstrap-native/$it/") }
        fun gone(path: String) = dropped.any { path == it || path.startsWith(it) }
        from.walkTopDown().filter { it.isFile }.sortedBy { it.path }.forEach { file ->
            val path = file.relativeTo(from).invariantSeparatorsPath
            if (path.startsWith("chaquopy/") && gone(path.removePrefix("chaquopy/"))) return@forEach
            val to = File(into, path).apply { parentFile.mkdirs() }
            if (path == "chaquopy/build.json") {
                @Suppress("UNCHECKED_CAST")
                val json = groovy.json.JsonSlurper().parse(file) as MutableMap<String, Any?>
                @Suppress("UNCHECKED_CAST")
                val assets = json["assets"] as MutableMap<String, Any?>
                json["assets"] = assets.filterKeys { !gone(it) }.toSortedMap()
                to.writeText(groovy.json.JsonOutput.prettyPrint(groovy.json.JsonOutput.toJson(json)) + "\n")
            } else file.copyTo(to)
        }
    }
}
