// The goal end to end on the JVM: the phone's server against a real caracole serve, which
// tests/test_android_e2e.py starts and names in -Pcaracole.e2e.* properties. Without them every test is skipped.
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

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

dependencies {
    testImplementation(project(":server"))
    testImplementation(testFixtures(project(":core")))
    testImplementation(testFixtures(project(":server")))
    testImplementation("junit:junit:4.13.2")
    testImplementation(kotlin("test-junit"))
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
}

val e2e: Map<String, String> = providers.gradlePropertiesPrefixedBy("caracole.e2e.").get()
val conformance: File = file("../../tests/conformance/vectors")
tasks.test {
    // A real server's state, never a cached result.
    outputs.upToDateWhen { false }
    e2e.forEach { (name, value) -> systemProperty(name, value) }
    systemProperty("caracole.conformance", conformance.absolutePath)
}
