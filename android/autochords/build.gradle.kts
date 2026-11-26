// The front ends of the chords from audio (the chords-on-the-phone design's §3.1, §3.6), in plain Kotlin on the JVM:
// for now libsoxr, the resampler python-soxr runs, over JNI (Soxr). Its C, native/ (libsoxr 0.1.3 vendored, and
// soxr_jni.c), is built here by the host's CMake and gcc for the JVM's tests (hostSoxr, its library on the tests'
// java.library.path), and by the NDK for the phone's ABIs in :ml (ml/build.gradle.kts's externalNativeBuild).
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

/** native/CMakeLists.txt configured and built by the host's cmake and gcc (android/flake.nix's shell), Release as
 * nixpkgs builds the libsoxr python-soxr links: `libcaracole_soxr.so` in [build]. */
abstract class HostSoxr @Inject constructor(private val exec: ExecOperations) : DefaultTask() {
    @get:InputDirectory
    @get:PathSensitive(PathSensitivity.RELATIVE)
    abstract val source: DirectoryProperty

    @get:OutputDirectory
    abstract val build: DirectoryProperty

    @TaskAction
    fun run() {
        val out = build.get().asFile
        val cmake = onPath("cmake")
        exec.exec {
            commandLine(cmake, "-S", source.get().asFile.path, "-B", out.path, "-DCMAKE_BUILD_TYPE=Release",
                        "-DCMAKE_C_COMPILER=${onPath("gcc")}")
        }
        exec.exec { commandLine(cmake, "--build", out.path, "--parallel") }
    }

    /** [name] on this build's PATH, the shell's: a Gradle daemon started in another shell looks a bare name up in its
     * own. */
    private fun onPath(name: String): String =
        System.getenv("PATH").orEmpty().split(File.pathSeparator).map { File(it, name) }.firstOrNull { it.canExecute() }
            ?.path ?: throw GradleException("no $name on PATH: build in `nix develop ./android`")
}

val hostSoxr by tasks.registering(HostSoxr::class) {
    description = "libsoxr and its JNI built for this machine, for the JVM's tests."
    source.set(layout.projectDirectory.dir("native"))
    build.set(layout.buildDirectory.dir("hostSoxr"))
}

dependencies {
    testImplementation(testFixtures(project(":core")))
    testImplementation("junit:junit:4.13.2")
    testImplementation(kotlin("test-junit"))
}

val conformance: File = file("../../tests/conformance/vectors")
tasks.withType<Test>().configureEach {
    dependsOn(hostSoxr)
    systemProperty("java.library.path", hostSoxr.get().build.get().asFile.absolutePath)
    inputs.dir(conformance).withPropertyName("conformance").withPathSensitivity(PathSensitivity.RELATIVE)
    systemProperty("caracole.conformance", conformance.absolutePath)
}
