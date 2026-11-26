// The front ends of the chords from audio (the chords-on-the-phone design's §3.1, §3.6), in plain Kotlin on the JVM:
// for now libsoxr, the resampler python-soxr runs, over JNI (Soxr). Its C, native/ (libsoxr 0.1.3 vendored, and
// soxr_jni.c), is built here by the host's CMake and gcc for the JVM's tests (hostSoxr, its library on the tests'
// java.library.path) and by the NDK as a static arm64 program for SoxrArm64Test (arm64SoxrDriver, run under
// qemu-aarch64), and by the NDK for the phone's ABIs in :ml (ml/build.gradle.kts's externalNativeBuild).
import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import javax.inject.Inject

plugins {
    id("org.jetbrains.kotlin.jvm")
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

/** native/CMakeLists.txt configured with [cmakeArgs] and built, Release as nixpkgs builds the libsoxr python-soxr links,
 * into [build]: by the host's gcc where [hostGcc] (android/flake.nix's shell), else by the toolchain [cmakeArgs] name. */
abstract class CmakeBuild @Inject constructor(private val exec: ExecOperations) : DefaultTask() {
    @get:InputDirectory
    @get:PathSensitive(PathSensitivity.RELATIVE)
    abstract val source: DirectoryProperty

    @get:Input
    abstract val cmakeArgs: ListProperty<String>

    @get:Input
    abstract val hostGcc: Property<Boolean>

    @get:OutputDirectory
    abstract val build: DirectoryProperty

    @TaskAction
    fun run() {
        val out = build.get().asFile
        val cmake = onPath("cmake")
        val compiler = if (hostGcc.get()) listOf("-DCMAKE_C_COMPILER=${onPath("gcc")}") else emptyList()
        exec.exec {
            commandLine(listOf(cmake, "-S", source.get().asFile.path, "-B", out.path, "-DCMAKE_BUILD_TYPE=Release") +
                        compiler + cmakeArgs.get())
        }
        exec.exec { commandLine(cmake, "--build", out.path, "--parallel") }
    }

    /** [name] on this build's PATH, the shell's: a Gradle daemon started in another shell looks a bare name up in its
     * own. */
    private fun onPath(name: String): String =
        System.getenv("PATH").orEmpty().split(File.pathSeparator).map { File(it, name) }.firstOrNull { it.canExecute() }
            ?.path ?: throw GradleException("no $name on PATH: build in `nix develop ./android`")
}

val hostSoxr by tasks.registering(CmakeBuild::class) {
    description = "libsoxr and its JNI built for this machine, for the JVM's tests."
    source.set(layout.projectDirectory.dir("native"))
    hostGcc.set(true)
    cmakeArgs.set(emptyList())
    build.set(layout.buildDirectory.dir("hostSoxr"))
}

// r28c, android/flake.nix's ndkVersion and ml/build.gradle.kts's: they change together.
val ndkVersion = "28.2.13676358"
val ndkToolchain: File? = System.getenv("ANDROID_HOME")
    ?.let { File(it, "ndk/$ndkVersion/build/cmake/android.toolchain.cmake") }?.takeIf { it.isFile }

/** The static arm64 program SoxrArm64Test runs under qemu-aarch64: the phone's sources and flags, by the NDK. */
val arm64SoxrDriver by tasks.registering(CmakeBuild::class) {
    description = "caracole_soxr_driver, static for arm64-v8a, for SoxrArm64Test under qemu-aarch64."
    source.set(layout.projectDirectory.dir("native"))
    hostGcc.set(false)
    cmakeArgs.set(listOf("-DCMAKE_TOOLCHAIN_FILE=${ndkToolchain?.path}", "-DANDROID_ABI=arm64-v8a",
                    "-DANDROID_PLATFORM=android-26", "-DCARACOLE_SOXR_DRIVER=ON"))
    build.set(layout.buildDirectory.dir("arm64Soxr"))
    onlyIf("the NDK r28c is under ANDROID_HOME") { ndkToolchain != null }
}

dependencies {
    testImplementation(testFixtures(project(":core")))
    testImplementation("junit:junit:4.13.2")
    testImplementation(kotlin("test-junit"))
}

val conformance: File = file("../../tests/conformance/vectors")
tasks.withType<Test>().configureEach {
    dependsOn(hostSoxr, arm64SoxrDriver)
    systemProperty("java.library.path", hostSoxr.get().build.get().asFile.absolutePath)
    // Only where the NDK is: a driver an earlier build left is no build of this tree's.
    if (ndkToolchain != null) {
        systemProperty("caracole.soxr.arm64", arm64SoxrDriver.get().build.get().file("caracole_soxr_driver").asFile.path)
    }
    inputs.dir(conformance).withPropertyName("conformance").withPathSensitivity(PathSensitivity.RELATIVE)
    systemProperty("caracole.conformance", conformance.absolutePath)
}
