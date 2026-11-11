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

    private val port = 8738

    private fun at(path: String, method: String = "GET", scheme: String = "http", host: String = "127.0.0.1",
                   port: Int = this.port, bundle: String? = name, server: Int? = this.port) =
        AlphaTabAssets.answerFor(method, scheme, host, port, path, bundle, server)

    @Test
    fun `the bundle at the phone's server's address is the asset, with its headers`() {
        val answer = assertNotNull(at("/assets/alphatab/$name"))
        assertEquals(200, answer.status)
        assertEquals("text/javascript" to "utf-8", answer.mimeType to answer.encoding)
        assertEquals("alphatab/$name", answer.asset)
        // guitar_routes.asset's headers and app.py's, in vectors/web/guitar.jsonl's order, the content type aside.
        assertEquals(listOf("Access-Control-Allow-Origin" to "*", "Cross-Origin-Resource-Policy" to "cross-origin",
                            "Cache-Control" to "public, max-age=31536000, immutable",
                            "Content-Security-Policy" to "default-src 'none'; frame-ancestors 'none'",
                            "X-Content-Type-Options" to "nosniff", "X-Frame-Options" to "DENY",
                            "Referrer-Policy" to "same-origin", "Cross-Origin-Opener-Policy" to "same-origin"),
                     answer.headers.toList())
        // Unquoted first, as caracole serve reads the address.
        assertEquals(200, at("/assets/alphatab/%61" + name.drop(1))?.status)
        // A server that listens on 80 is asked with no port.
        assertEquals(200, at("/assets/alphatab/$name", port = -1, server = 80)?.status)
    }

    @Test
    fun `any other name there is not found, and anything elsewhere is the server's`() {
        for (path in listOf("/assets/alphatab/", "/assets/alphatab/alphaTab.min.js", "/assets/alphatab/$name/",
                            "/assets/alphatab/../$name", "/assets/alphatab/%ff", "/assets/alphatab/${name.uppercase()}")) {
            assertEquals(AlphaTabAssets.NOT_FOUND, at(path), path)
        }
        assertEquals(AlphaTabAssets.NOT_FOUND, at("/assets/alphatab/$name", method = "POST"))
        assertEquals(AlphaTabAssets.NOT_FOUND, at("/assets/alphatab/$name", bundle = null))
        for ((scheme, host, path) in listOf(Triple("http", "127.0.0.1", "/guitar"), Triple("http", "127.0.0.1", "/assets/alphatab"),
                                            Triple("https", "127.0.0.1", "/assets/alphatab/$name"),
                                            Triple("http", "localhost", "/assets/alphatab/$name"),
                                            Triple("http", "evil.example", "/assets/alphatab/$name"))) {
            assertNull(at(path, scheme = scheme, host = host), "$scheme://$host$path")
        }
    }

    @Test
    fun `only the phone's server's exact origin is answered, and nothing before it listens`() {
        assertNull(at("/assets/alphatab/$name", port = port + 1), "another port of 127.0.0.1")
        assertNull(at("/assets/alphatab/", port = port + 1), "another port's other names")
        assertNull(at("/assets/alphatab/$name", port = -1), "no port, 80")
        assertNull(at("/assets/alphatab/$name", server = null), "a server not listening yet")
    }
}
