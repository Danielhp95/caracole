package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.RenderStats
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.PhoneDeps
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.lookups.RenderRunner
import io.github.danielhp95.caracole.server.routes.ExportRoutes.Companion.MAKING
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.TestParts
import io.github.danielhp95.caracole.server.testing.json
import io.github.danielhp95.caracole.server.testing.replays.ExportReplay
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.net.URLEncoder
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * Export PDF on the phone: `GET /export.pdf` as caracole serve answers it (the vectors), the phone whole as the app
 * assembles it (Make this my version a plain link that runs the render runner, the one write with no form token), a
 * viewer of the computer's the mirror holds, and the runner's own refusals.
 */
class ExportRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private lateinit var phone: Phone
    private lateinit var library: File

    private object NoAddress : SyncSettings {
        override val address: String? = null
        override fun remember(address: String) = Unit
    }

    @Before fun up() {
        val database = TestDb.fresh(tmp.newFolder("db"))
        library = tmp.newFolder("library")
        phone = Phone(PhoneDeps(database, library, tmp.newFolder("state"), null, scope, NoAddress, TestApp.SECRET,
                                TestApp.CSRF, transport = { RefusingTransport }, searchesLacuerda = false))
    }

    @After fun down() {
        scope.cancel()
        phone.parts.database.close()
    }

    private val database: Database get() = phone.parts.database

    private fun handle(method: String, target: String, headers: Map<String, String?> = emptyMap(),
                       body: ByteArray = ByteArray(0)): Response =
        phone.app.handle(TestApp.request(method, target, mapOf("sec-fetch-site" to "same-origin") + headers, body,
                                         TestApp.SECRET))

    /** The viewer's link, asked as the app's Printer asks it: JSON back, no token. */
    private fun export(sheet: String, query: String, method: String = "GET"): Response =
        handle(method, "/export.pdf?sheet=" + URLEncoder.encode(sheet, Charsets.UTF_8).replace("+", "%20") + "&" + query,
               mapOf("accept" to "application/json"))

    private fun done(id: Int): Job = runBlocking { withTimeout(60_000) { phone.queue.await(id) } }

    /** A song in G, its UG sheet kept as the fetch keeps one (sheet.txt and sheet.json), its viewer recorded as
     * render.py records one when [recorded]. */
    private fun song(artist: String = "Soda Stereo", title: String = "De Música Ligera", recorded: Boolean = true): SongRow =
        database.writeBlocking { db ->
            val song = LibraryStore(library).add(db, artist, title, now = NOW)
            val raw = buildJsonObject { put("id", 85001); put("tonality_name", "G") }
            val version = Versions.upsert(db, "ug", "85001", song.id, "sheet", "chords", 4.5, 10, 1, null,
                                          "https://tabs.ultimate-guitar.com/tab/x/y-chords-85001", raw, NOW)
            Kept.keepFile(db, LibraryStore(library), song, version, "sheet.txt", "G D\nPalabras\n".toByteArray(), 1, NOW)
            val folder = SafeName.songFolder(artist, title)
            val json = """{"content": "[tab][ch]G[/ch]           [ch]D[/ch]\r\nPalabras de prueba[/tab]\r\n""" +
                """[tab][ch]Em[/ch]          [ch]C[/ch]\r\nsolo para el visor[/tab]\r\n", "meta": []}"""
            File(library, "${folder.first}/${folder.second}/sheet.json").writeText(json)
            if (recorded) db.kvSet("render:files:${song.id}", """{"sheet.html": {"sha256": "${"0".repeat(64)}", "size": 1}}""")
            song
        }

    private fun versionOf(song: SongRow): String? = database.read { db -> Overrides.read(db).version[song.key] }

    @Test fun `each answer is caracole serve's (vectors web export)`() {
        val misses = Misses("export")
        ExportReplay.replay(misses)
        misses.assertNone()
    }

    @Test fun `Export PDF names the version for the print, and asks nothing of the queue`() {
        song()
        val answer = export("Soda Stereo/De Música Ligera/sheet.html", "t=2&capo=0&fs=20")
        assertEquals(200, answer.status)
        assertEquals(JsonObject(linkedMapOf("name" to JsonPrimitive("Soda Stereo - De Música Ligera (A Major, capo 0).pdf"),
                                            "label" to JsonPrimitive("A Major, capo 0"))), answer.json)
        assertTrue(phone.queue.snapshot().isEmpty())
    }

    @Test fun `mine is a plain link with no token, and the render runner makes the version the song's own`() {
        val song = song()
        val answer = export("Soda Stereo/De Música Ligera/sheet.html", "t=2&capo=0&mine=1")
        assertEquals(200, answer.status, answer.json.toString())
        val job = phone.queue.snapshot().single()
        assertEquals("export:${song.key}:t=2&capo=0:mine", job.key)
        assertEquals(listOf(MAKING), job.steps.map { it.label })
        val ended = done(job.id)
        assertEquals(Job.DONE, ended.state, ended.output.toString())
        assertEquals("Your version of Soda Stereo - De Música Ligera: A Major, capo 0", ended.output.first())
        assertEquals("key=A&capo=0", versionOf(song))
        // its line, as the library page shows it: Make this my version's own words
        val jobs = handle("GET", "/jobs.json?jobs=${job.id}", mapOf("accept" to "application/json",
                                                                       TestApp.TOKEN_HEADER to TestApp.CSRF))
        val line = jobs.json.jsonObject.getValue("jobs").jsonArray.single().jsonObject.getValue("line").jsonObject
        assertEquals(JsonPrimitive("Your version now"), line["text"], "$line")
        // back where the song plays as written: the entry goes
        val back = export("Soda Stereo/De Música Ligera/sheet.html", "t=0&mine=1")
        assertEquals(200, back.status)
        done(phone.queue.snapshot().first { it.key.contains(":t=0:") }.id)
        assertNull(versionOf(song))
    }

    @Test fun `a HEAD names the version and queues nothing`() {
        song()
        assertEquals(200, export("Soda Stereo/De Música Ligera/sheet.html", "t=2&mine=1", method = "HEAD").status)
        assertTrue(phone.queue.snapshot().isEmpty())
    }

    @Test fun `mine stays the one write with no form token`() {
        val song = song()
        val modules = phone.modules
        val posts = modules.flatMap { it.routes }.filter { it.method == "POST" }
        assertTrue(posts.size > 10, "${posts.size} POST routes")
        for (route in posts) {
            val path = if (route.under) route.path + "x" else route.path
            val form = TestApp.form(listOf("song" to "${song.id}", "artist" to "A", "title" to "B", "q" to "abcd"))
            val headers = mapOf("origin" to "http://${TestApp.HOST}", "content-type" to "application/x-www-form-urlencoded")
            assertEquals(403, handle("POST", path, headers, form).status, "POST $path without the token")
            val other = mapOf("origin" to "https://example.com", "sec-fetch-site" to "cross-site",
                              "content-type" to "application/x-www-form-urlencoded")
            val tokened = TestApp.form(listOf("csrf" to TestApp.CSRF)) + "&".toByteArray() + form
            assertEquals(403, handle("POST", path, other, tokened).status, "POST $path from another site")
        }
        val gets = modules.flatMap { it.routes }.filter { it.method == "GET" && it.path != "/export.pdf" }
        for (route in gets) {
            val path = if (route.under) route.path + "x" else route.path
            handle("GET", "$path?song=${song.id}&mine=1&sheet=Soda%20Stereo/De%20M%C3%BAsica%20Ligera/sheet.html")
        }
        assertEquals(emptyList(), phone.queue.snapshot().map { it.key }, "a write with no token")
        assertEquals(200, export("Soda Stereo/De Música Ligera/sheet.html", "t=2&mine=1").status)
        assertEquals(listOf("export:${song.key}:t=2:mine"), phone.queue.snapshot().map { it.key })
    }

    @Test fun `a viewer of the computer's the mirror holds for the song is the library's`() {
        val dir = tmp.newFolder("mirror")
        val song = song(recorded = false)
        val parts = TestParts.of(database, tmp.root, scope)
        val sheet = "Soda Stereo/De Música Ligera/sheet.html"
        assertEquals(404, refusedStatus { ExportRoutes(parts) { null }.export(request(sheet)) })
        val mirror = mirrorWith(dir, sheet, "song/${song.key}")
        assertEquals(200, ExportRoutes(parts) { mirror }.export(request(sheet)).status)
        val another = mirrorWith(tmp.newFolder("other"), sheet, "song/somebody/else")
        assertEquals(404, refusedStatus { ExportRoutes(parts) { another }.export(request(sheet)) })
    }

    @Test fun `the render runner refuses what the phone can't do, in caracole's words`() {
        song()
        val runner = RenderRunner(phone.parts)
        val exits = listOf(
            listOf("render", "--version=t=2") to "--version needs --song: the version is one song's.",
            listOf("render", "--song=Soda Stereo - De Música Ligera", "--mine") to
                "--mine needs --version: the version to make the song's own.",
            listOf("render", "--song=Soda Stereo - De Música Ligera", "--version=t=2") to RenderRunner.NO_PDF,
            listOf("render", "--colour") to "No such option: --colour",
        )
        for ((args, said) in exits) {
            val e = assertFailsWith<CommandExit>(args.toString()) { runBlocking { runner.run(args, Context()) } }
            assertEquals(2 to said, e.code to e.message)
        }
    }

    @Test fun `the render runner makes the song's pages again, and fails where one couldn't be made`() {
        val song = song()
        val made = ArrayList<Collection<Long>>()
        val pages = SongPages { _, ids, _ -> made += ids; RenderStats(written = 1) }
        val parts = withPages(pages)
        val context = Context()
        runBlocking { RenderRunner(parts).run(listOf("render", "--song=Soda Stereo - De Música Ligera",
                                                     "--version=t=2", "--mine"), context) }
        assertEquals(listOf(listOf(song.id)), made.map { it.toList() })
        assertEquals(listOf("Your version of Soda Stereo - De Música Ligera: A Major, capo 0",
                            "1 rendered, 0 up to date, 0 failed"), context.said)
        val failing = withPages { _, _, _ -> RenderStats(failed = mapOf(song.id to "Soda Stereo - De Música Ligera: no page")) }
        val e = assertFailsWith<CommandExit> {
            runBlocking { RenderRunner(failing).run(listOf("render", "--song=Soda Stereo - De Música Ligera"), Context()) }
        }
        assertEquals(1 to "Soda Stereo - De Música Ligera: no page", e.code to e.message)
    }

    private fun withPages(pages: SongPages): PhoneParts {
        val p = phone.parts
        return PhoneParts(p.database, p.store, p.stateDir, p.config, p.queue, p.cards, p.clients, pages, p.songbooks,
                          p.alerts, p.pacing, p.searchesLacuerda)
    }

    private class Context : JobContext {
        val said = ArrayList<String>()
        override fun stage(name: String, state: String, detail: String) = Unit
        override fun say(line: String) {
            said += line
        }
        override fun outcome(value: JsonObject) = Unit
        override val isCancelled: Boolean = false
    }

    private fun request(sheet: String): Request =
        TestApp.request("GET", "/export.pdf?sheet=" + URLEncoder.encode(sheet, Charsets.UTF_8) + "&t=2", emptyMap(),
                        ByteArray(0), TestApp.SECRET)

    private fun refusedStatus(block: () -> Unit): Int = try {
        block()
        200
    } catch (e: io.github.danielhp95.caracole.server.http.Refused) {
        e.status
    }

    /** A mirror whose manifest lists [path] under [unit], its blob on disk. */
    private fun mirrorWith(dir: File, path: String, unit: String): Mirror {
        val bytes = "<!doctype html>".toByteArray()
        val sha = io.github.danielhp95.caracole.core.json.Canonical.sha256Hex(bytes)
        File(dir, "blobs").apply { mkdirs() }.resolve(sha).writeBytes(bytes)
        val entry = buildJsonObject {
            put("path", path); put("url", "/" + path.split('/').joinToString("/") { URLEncoder.encode(it, Charsets.UTF_8).replace("+", "%20") })
            put("size", bytes.size); put("sha256", sha)
            put("type", "text/html; charset=utf-8"); put("headers", buildJsonObject {}); put("unit", unit)
            put("digest", "0".repeat(64))
        }
        File(dir, "manifest.json").writeText(buildJsonObject {
            put("format", 1); put("start", path)
            put("files", kotlinx.serialization.json.JsonArray(listOf(entry))); put("skipped", kotlinx.serialization.json.JsonArray(emptyList()))
        }.toString())
        return Mirror(dir)
    }

    private companion object {
        const val NOW = "2026-11-03T10:00:00Z"
    }
}
