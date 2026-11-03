// The phone's local server, in plain Kotlin on the JVM: caracole serve's router and checks, the library page built
// from caracole's own library_assets/ (copied byte for byte at build time), and the routes the page asks.
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("org.jetbrains.kotlin.jvm")
    `java-test-fixtures`
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

// library_assets/ as caracole has it, on the classpath as caracole/library_assets/: no filtering, no line-end change,
// so a page's hashes are those of the very files Python inlines.
val generatedAssets = layout.buildDirectory.dir("generated/assets")
val copyLibraryAssets by tasks.registering(Sync::class) {
    from("../../src/caracole/library_assets") {
        include("*.js", "*.css", "*.html")
    }
    into(generatedAssets.map { it.dir("caracole/library_assets") })
}

sourceSets {
    main {
        resources.srcDir(generatedAssets)
    }
}

tasks.processResources { dependsOn(copyLibraryAssets) }

dependencies {
    api(project(":core"))
    implementation("io.ktor:ktor-server-cio:3.3.3")

    testImplementation(testFixtures(project(":core")))
    testImplementation("junit:junit:4.13.2")
    testImplementation(kotlin("test-junit"))
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
    testFixturesApi(testFixtures(project(":core")))
    testFixturesImplementation("junit:junit:4.13.2")
}

val conformance: File = file("../../tests/conformance/vectors")
tasks.withType<Test>().configureEach {
    inputs.dir(conformance).withPropertyName("conformance").withPathSensitivity(PathSensitivity.RELATIVE)
    systemProperty("caracole.conformance", conformance.absolutePath)
}
