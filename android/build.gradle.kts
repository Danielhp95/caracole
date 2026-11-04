// The versions every module builds with. The SDK's (compileSdk, build tools) are flake.nix's too.
plugins {
    id("com.android.application") version "8.13.2" apply false
    id("org.jetbrains.kotlin.android") version "2.2.21" apply false
    id("org.jetbrains.kotlin.jvm") version "2.2.21" apply false
    id("org.jetbrains.kotlin.plugin.serialization") version "2.2.21" apply false
}

// What every module's tests share:
// - no test reaches the network: caracole.network=loopback, under which core.http.RealTransport refuses any host but
//   loopback and the emulator's 10.0.2.2 (AGENTS.md, "How work is done here");
// - caracole.fixtures, tests/fixtures/, which a corpus record names in place of a fixture's bytes (Corpus.fixture);
// - a class named *Bench is a benchmark: never in `test`, only in the gated `bench` task of each JVM module (a 3 GiB
//   heap, one fork): `nix develop ./android -c gradle -p android bench`.
val fixtures: File = file("../tests/fixtures")
subprojects {
    tasks.withType<Test>().configureEach {
        systemProperty("caracole.network", "loopback")
        inputs.dir(fixtures).withPropertyName("fixtures").withPathSensitivity(PathSensitivity.RELATIVE)
        systemProperty("caracole.fixtures", fixtures.absolutePath)
        if (name != "bench") exclude("**/*Bench.class", "**/*Bench$*.class")
    }
    plugins.withId("org.jetbrains.kotlin.jvm") {
        val sourceSets = extensions.getByType<SourceSetContainer>()
        tasks.register<Test>("bench") {
            description = "The *Bench classes: benchmarks over big data sets, run only when asked."
            group = "verification"
            testClassesDirs = sourceSets.getByName("test").output.classesDirs
            classpath = sourceSets.getByName("test").runtimeClasspath
            include("**/*Bench.class")
            maxHeapSize = "3g"
            maxParallelForks = 1
            outputs.upToDateWhen { false }
            testLogging { events("passed", "skipped", "failed") }
        }
    }
}
