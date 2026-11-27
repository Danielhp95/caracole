// caracole's rules on the phone, in plain Kotlin on the JVM (no Android class): the schema in the bundled SQLite,
// keys, search, canonical JSON, sync. Its runtime data is tests/conformance/data (caracole/… on the classpath), and
// every test reads the conformance vectors from tests/conformance/vectors (the system property caracole.conformance).
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.kotlin.plugin.serialization")
    `java-test-fixtures`
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

val modelsTestData = tasks.register<Sync>("modelsTestData") {
    from("../../tests/conformance/data") {
        include("caracole/autochords/models.json", "caracole/autochords/btc-graph.onnx")
    }
    into(layout.buildDirectory.dir("models-test-data"))
}

sourceSets {
    main {
        resources.srcDir("../../tests/conformance/data")
        // The chord models' graph and pins are :ml's, the debug build's alone until the stage that ships them: never
        // in the release through :core.
        resources.exclude("caracole/autochords/**")
    }
    test {
        // core.models' tests read the pins and BTC's graph as the debug build's :ml puts them on the classpath: a
        // folder of their own, so that the filter is theirs alone (a resources.include would filter every test
        // resource).
        resources.srcDir(modelsTestData)
    }
}

dependencies {
    api("androidx.sqlite:sqlite-bundled:2.7.1")
    api("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")
    api("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.10.2")
    api(project(":mirror"))

    testImplementation("junit:junit:4.13.2")
    testImplementation(kotlin("test-junit"))
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
    testFixturesImplementation("junit:junit:4.13.2")
    testFixturesImplementation(kotlin("test-junit"))
    testFixturesImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
}

val conformance: File = file("../../tests/conformance/vectors")
tasks.withType<Test>().configureEach {
    inputs.dir(conformance).withPropertyName("conformance").withPathSensitivity(PathSensitivity.RELATIVE)
    systemProperty("caracole.conformance", conformance.absolutePath)
}
