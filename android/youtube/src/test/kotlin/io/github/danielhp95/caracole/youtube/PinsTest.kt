package io.github.danielhp95.caracole.youtube

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.security.MessageDigest
import java.util.zip.ZipFile
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

/**
 * android/youtube/pins.json against the wheels android/flake.nix fetched by it (CARACOLE_YTDLP_WHEELS, which
 * youtube/build.gradle.kts hands the test as `caracole.youtube.wheels`): each wheel is the file its URL names, with its
 * SHA-256, of the version pinned; and yt-dlp-ejs's version is the one yt-dlp's own wheel requires (its METADATA's
 * `yt-dlp-ejs==…`), as yt-dlp refuses another (the design's §3.1).
 */
class PinsTest {
    private val pins: JsonObject =
        Json.parseToJsonElement(File(requireNotNull(System.getProperty("caracole.youtube.pins"))).readText()).jsonObject
    private val wheels = File(requireNotNull(System.getProperty("caracole.youtube.wheels")))

    private fun pin(name: String) = pins.getValue(name).jsonObject
    private fun JsonObject.text(key: String) = getValue(key).jsonPrimitive.content
    private fun wheelOf(name: String) = File(wheels, pin(name).text("url").substringAfterLast('/'))

    /** A wheel's METADATA, from its `.dist-info/`. */
    private fun metadata(wheel: File): String = ZipFile(wheel).use { zip ->
        val entry = zip.entries().asSequence().single { it.name.matches(Regex("[^/]+\\.dist-info/METADATA")) }
        zip.getInputStream(entry).readBytes().decodeToString()
    }

    private fun field(metadata: String, name: String): List<String> =
        metadata.lineSequence().takeWhile { it.isNotEmpty() }.filter { it.startsWith("$name: ") }
            .map { it.removePrefix("$name: ") }.toList()

    @Test
    fun `the wheels folder holds the two pinned wheels and nothing else`() {
        assertEquals(
            setOf(wheelOf("ytdlp").name, wheelOf("ejs").name),
            wheels.listFiles().orEmpty().map { it.name }.toSet(),
        )
    }

    @Test
    fun `each wheel has the SHA-256 pinned`() {
        for (name in listOf("ytdlp", "ejs")) {
            val digest = MessageDigest.getInstance("SHA-256").digest(wheelOf(name).readBytes())
                .joinToString("") { "%02x".format(it) }
            assertEquals(pin(name).text("sha256"), digest, name)
        }
    }

    @Test
    fun `each wheel is of the version pinned`() {
        assertEquals(listOf("yt-dlp"), field(metadata(wheelOf("ytdlp")), "Name"))
        assertEquals(listOf(pin("ytdlp").text("version")), field(metadata(wheelOf("ytdlp")), "Version"))
        assertEquals(listOf("yt-dlp-ejs"), field(metadata(wheelOf("ejs")), "Name"))
        assertEquals(listOf(pin("ejs").text("version")), field(metadata(wheelOf("ejs")), "Version"))
    }

    @Test
    fun `yt-dlp-ejs is the version yt-dlp's wheel requires`() {
        val required = field(metadata(wheelOf("ytdlp")), "Requires-Dist")
            .firstNotNullOfOrNull { Regex("""yt-dlp-ejs==([^;\s]+); extra == 'default'""").matchEntire(it) }
        assertNotNull(required, "yt-dlp's METADATA names no yt-dlp-ejs== of its default extra")
        assertEquals(required.groupValues[1], pin("ejs").text("version"))
    }

    @Test
    fun `the Python pinned is a minor version`() {
        assertEquals(true, Regex("""3\.\d+""").matches(pins.text("python")), pins.text("python"))
    }
}
