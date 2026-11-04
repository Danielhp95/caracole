// The page builder, viewer/ in plain Kotlin on the JVM (milestone 5): a song's pages built as render.py and viewer/
// build them, with viewer/'s own scripts, stylesheets and voicings copied byte for byte at build time, as
// caracole/viewer/ on the classpath.
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

// viewer/'s assets as caracole has them: no filtering, no line-end change, so a page's hashes are those of the very
// files Python inlines.
val generatedAssets = layout.buildDirectory.dir("generated/assets")
val copyViewerAssets by tasks.registering(Sync::class) {
    from("../../src/caracole/viewer") {
        include("*.js", "*.css", "voicings*.json", "LICENSE-chords-db")
    }
    into(generatedAssets.map { it.dir("caracole/viewer") })
}

sourceSets {
    main {
        resources.srcDir(generatedAssets)
    }
}

tasks.processResources { dependsOn(copyViewerAssets) }

dependencies {
    api(project(":core"))

    testImplementation(testFixtures(project(":core")))
    testImplementation("junit:junit:4.13.2")
    testImplementation(kotlin("test-junit"))
    testFixturesApi(testFixtures(project(":core")))
    testFixturesImplementation("junit:junit:4.13.2")
}

val conformance: File = file("../../tests/conformance/vectors")
tasks.withType<Test>().configureEach {
    inputs.dir(conformance).withPropertyName("conformance").withPathSensitivity(PathSensitivity.RELATIVE)
    systemProperty("caracole.conformance", conformance.absolutePath)
}
