// The mirror: the manifest, the copy on the phone, the sync and the lookups the WebView asks.
// Plain Kotlin on the JVM (no Android class), so its tests run with `gradle :mirror:test`.
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
    testImplementation("junit:junit:4.13.2")
    testImplementation(kotlin("test-junit"))
}
