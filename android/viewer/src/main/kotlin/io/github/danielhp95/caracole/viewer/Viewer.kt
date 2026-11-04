package io.github.danielhp95.caracole.viewer

/** The page builder's own files: viewer/'s scripts, stylesheets and voicings, on the classpath as they are in
 * src/caracole/viewer/ (viewer/build.gradle.kts's copyViewerAssets). skeleton-m5m6 declares the rest of :viewer. */
object Viewer {
    const val ASSETS = "caracole/viewer"

    /** An asset's bytes as caracole has them, or null for one viewer/ doesn't have. */
    fun asset(name: String): ByteArray? =
        Viewer::class.java.getResourceAsStream("/$ASSETS/$name")?.use { it.readBytes() }
}
