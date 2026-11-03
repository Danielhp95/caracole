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

sourceSets {
    main {
        resources.srcDir("../../tests/conformance/data")
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
