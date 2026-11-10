package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.server.guitar.AlphaTabBundle
import io.github.danielhp95.caracole.server.routes.GuitarRoutes
import org.junit.Test
import java.io.File
import java.security.MessageDigest
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * alphaTab's bundle in the APK: the build's resource (app/alphatab.gradle.kts) names the bundle the Kotlin port makes
 * of the same files (server.guitar.AlphaTabBundle, held to Python's by GuitarReplay), and the WebView's interceptor
 * answers it at the phone's server's address alone. The APK's bytes themselves are GuitarPageTest's, on the device.
 */
class AlphaTabAssetsTest {
    private val name = "alphatab-1.8.4-0123456789abcdef.js"

    @Test
    fun `the build names the bundle the port makes of CARACOLE_ALPHATAB_DIR's files`() {
        val installed = assertNotNull(AlphaTabBundle.installed(), "no caracole/web/alphatab.json on the classpath")
        val dir = File(assertNotNull(System.getenv("CARACOLE_ALPHATAB_DIR"), "run the tests in nix develop ./android"))
        val made = AlphaTabBundle.load(dir)
        assertEquals(made.name, installed.name)
        assertEquals(made.integrity, installed.integrity)
        assertEquals(made.scriptSource, installed.scriptSource)
        assertEquals(made.fontFace, installed.fontFace)
        val record = AlphaTabBundle::class.java.classLoader!!.getResourceAsStream(AlphaTabBundle.INSTALLED)!!
            .use { it.readBytes().toString(Charsets.UTF_8) }
        val sha = MessageDigest.getInstance("SHA-256").digest(made.body).joinToString("") { "%02x".format(it) }
        assertTrue("\"sha256\": \"$sha\", \"length\": ${made.body.size}," in record, record)
        for (licence in File(dir, "licenses").listFiles()!!.map { it.name }) assertTrue("\"$licence\"" in record, licence)
        assertTrue(GuitarRoutes.available())
    }

    @Test
    fun `the bundle at the phone's server's address is the asset, with its headers`() {
        val answer = assertNotNull(AlphaTabAssets.answerFor("GET", "http", "127.0.0.1", "/assets/alphatab/$name", name))
        assertEquals(200, answer.status)
        assertEquals("text/javascript" to "utf-8", answer.mimeType to answer.encoding)
        assertEquals("alphatab/$name", answer.asset)
        assertEquals("*", answer.headers["Access-Control-Allow-Origin"])
        assertEquals("public, max-age=31536000, immutable", answer.headers["Cache-Control"])
        // Unquoted first, as caracole serve reads the address; any port of 127.0.0.1's.
        assertEquals(200, AlphaTabAssets.answerFor("GET", "http", "127.0.0.1", "/assets/alphatab/%61" + name.drop(1), name)?.status)
    }

    @Test
    fun `any other name there is not found, and anything elsewhere is the server's`() {
        for (path in listOf("/assets/alphatab/", "/assets/alphatab/alphaTab.min.js", "/assets/alphatab/$name/",
                            "/assets/alphatab/../$name", "/assets/alphatab/%ff", "/assets/alphatab/${name.uppercase()}")) {
            assertEquals(AlphaTabAssets.NOT_FOUND, AlphaTabAssets.answerFor("GET", "http", "127.0.0.1", path, name), path)
        }
        assertEquals(AlphaTabAssets.NOT_FOUND, AlphaTabAssets.answerFor("POST", "http", "127.0.0.1", "/assets/alphatab/$name", name))
        assertEquals(AlphaTabAssets.NOT_FOUND, AlphaTabAssets.answerFor("GET", "http", "127.0.0.1", "/assets/alphatab/$name", null))
        for ((scheme, host, path) in listOf(Triple("http", "127.0.0.1", "/guitar"), Triple("http", "127.0.0.1", "/assets/alphatab"),
                                            Triple("https", "127.0.0.1", "/assets/alphatab/$name"),
                                            Triple("http", "localhost", "/assets/alphatab/$name"),
                                            Triple("http", "evil.example", "/assets/alphatab/$name"))) {
            assertNull(AlphaTabAssets.answerFor("GET", scheme, host, path, name), "$scheme://$host$path")
        }
    }
}
