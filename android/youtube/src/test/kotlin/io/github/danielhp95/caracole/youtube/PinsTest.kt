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
 * `yt-dlp-ejs==…`), as yt-dlp refuses another (the design's §3.1). QuickJS-NG is pinned by its tag's tree (the commit
 * and the NAR hash of its files, `fetchFromGitHub`'s), never by GitHub's archive tarball, a generated file whose bytes
 * GitHub has changed before; CARACOLE_QUICKJS_SRC (`caracole.youtube.quickjs`) is that tree, of the tag's version.
 */
class PinsTest {
    private val pins: JsonObject =
        Json.parseToJsonElement(File(requireNotNull(System.getProperty("caracole.youtube.pins"))).readText()).jsonObject
    private val wheels = File(requireNotNull(System.getProperty("caracole.youtube.wheels")))
    private val quickjs = File(requireNotNull(System.getProperty("caracole.youtube.quickjs")))

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

    @Test
    fun `QuickJS-NG is pinned by its tag's commit and the NAR hash of its tree`() {
        val pin = pin("quickjs")
        assertEquals(setOf("tag", "owner", "repo", "rev", "hash"), pin.keys)
        assertEquals("quickjs-ng", pin.text("owner"))
        assertEquals("quickjs", pin.text("repo"))
        assertEquals(true, Regex("""v\d+\.\d+\.\d+""").matches(pin.text("tag")), pin.text("tag"))
        assertEquals(true, Regex("""[0-9a-f]{40}""").matches(pin.text("rev")), pin.text("rev"))
        assertEquals(true, Regex("""sha256-[A-Za-z0-9+/]{43}=""").matches(pin.text("hash")), pin.text("hash"))
    }

    @Test
    fun `CARACOLE_QUICKJS_SRC is QuickJS-NG's source of the version pinned, with its own generated C`() {
        val header = File(quickjs, "quickjs.h").readText()
        val version = listOf("MAJOR", "MINOR", "PATCH").map { part ->
            assertNotNull(Regex("""#define QJS_VERSION_$part (\d+)""").find(header), part).groupValues[1]
        }
        assertEquals(pin("quickjs").text("tag"), "v" + version.joinToString("."))
        // qjs's REPL and standalone code, qjsc's output upstream commits: no host step builds them here.
        for (name in listOf("gen/repl.c", "gen/standalone.c", "qjs.c", "LICENSE")) {
            assertEquals(true, File(quickjs, name).isFile, name)
        }
    }
}
