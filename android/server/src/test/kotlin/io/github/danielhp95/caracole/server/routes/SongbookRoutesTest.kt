package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.Versions as LibraryVersions
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.mirror.Mirror
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import io.github.danielhp95.caracole.core.songbooks.Setting
import io.github.danielhp95.caracole.core.songbooks.Songbook
import io.github.danielhp95.caracole.core.songbooks.SongbookSong
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.PhoneDeps
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.Command
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.routes.lookup.LookupForms
import io.github.danielhp95.caracole.server.songbooks.SongbookRunner
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.json
import io.github.danielhp95.caracole.server.testing.text
import io.github.danielhp95.caracole.server.testing.replays.SongbookRoutesReplay
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertSame
import kotlin.test.assertTrue

/** The Songbooks tab's forms on the phone: each form as caracole serve answers it (vectors/songbook/routes.jsonl),
 * and the phone whole, as the app assembles it, running each `caracole songbook` command its forms queue. */
class SongbookRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private lateinit var phone: Phone
    private lateinit var songs: Map<String, SongRow>

    private object NoAddress : SyncSettings {
        override val address: String? = null
        override fun remember(address: String) = Unit
    }

    @Before fun up() {
        val database = TestDb.fresh(tmp.newFolder("db"))
        phone = Phone(PhoneDeps(database, tmp.newFolder("library"), tmp.newFolder("state"), null, scope, NoAddress,
                                TestApp.SECRET, TestApp.CSRF, transport = { RefusingTransport },
                                searchesLacuerda = false))
        songs = database.writeBlocking { db ->
            listOf("Oasis" to "Wonderwall", "Muse" to "Hysteria", "Radiohead" to "Creep", "Earth - Wind - Fire" to "September")
                .associate { (artist, title) -> title to phone.parts.store.add(db, artist, title, now = "2026-11-03T10:00:00Z") }
        }
    }

    @After fun down() {
        scope.cancel()
        phone.parts.database.close()
    }

    private fun post(target: String, vararg fields: Pair<String, String>, json: Boolean = true): Response = phone.app.handle(
        TestApp.request(
            "POST", target,
            mapOf("sec-fetch-site" to "same-origin", "origin" to "http://${TestApp.HOST}",
                  "content-type" to "application/x-www-form-urlencoded") +
                (if (json) mapOf("accept" to "application/json") else emptyMap()),
            TestApp.form(listOf("csrf" to TestApp.CSRF) + fields), TestApp.SECRET,
        ),
    )

    /** The songbook job a form queued: its view's id. */
    private fun jobOf(answer: Response): Int {
        assertEquals(200, answer.status, answer.json.toString())
        return answer.json.jsonObject.getValue("job").jsonObject.getValue("id").jsonPrimitive.int
    }

    private fun done(id: Int): Job = runBlocking { withTimeout(60_000) { phone.queue.await(id) } }

    private fun books(): List<Songbook> = phone.parts.database.read(Songbooks::all)

    private fun id(title: String): String = songs.getValue(title).id.toString()

    private fun output(job: Job): List<String> = job.steps.flatMap { it.output }

    @Test fun `each form answers as caracole serve's (vectors songbook routes)`() {
        val misses = Misses("songbook-routes")
        SongbookRoutesReplay.replay(misses)
        misses.assertNone()
    }

    @Test fun `each command a form queues says and does what caracole songbook does (vectors songbook routes_runner)`() {
        val misses = Misses("songbook-runner")
        SongbookRoutesReplay.runner(misses)
        misses.assertNone()
    }

    /** What the phone's songbooks' pages say once they made [name]'s songbook.html, where its songs have no sheet. */
    private fun wrote(name: String, vararg sheetless: String): List<String> =
        sheetless.map { "$it has no sheet yet: it is named missing until it has one" } +
            "Wrote ${File(File(phone.parts.store.libraryDir, Songbooks.FOLDER), name).path}: songbook.html"

    private fun page(name: String): File = File(File(File(phone.parts.store.libraryDir, Songbooks.FOLDER), name), "songbook.html")

    @Test fun `Make from the Select bar makes the songbook, in the order picked, its line Made`() {
        val id = jobOf(post("/songbook/make", "name" to "  Beach  ", "songs" to "${id("Hysteria")},${id("Wonderwall")},${id("Hysteria")}"))
        val job = done(id)
        assertEquals(Job.DONE, job.state, job.asJson().toString())
        assertEquals(listOf(Songbook("Beach", listOf(SongbookSong("Muse - Hysteria"), SongbookSong("Oasis - Wonderwall")))),
                     books())
        assertEquals(listOf("Made the songbook \"Beach\": 2 songs.") + wrote("Beach", "Muse - Hysteria", "Oasis - Wonderwall"),
                     output(job))
        assertTrue(page("Beach").isFile)
        assertEquals("Made", JobViews.line(job).text)
        assertEquals("songbook", job.spec.kind)
    }

    @Test fun `a form a page didn't post goes to its line in the Requests tab`() {
        val answer = post("/songbook/make", "name" to "Beach", "songs" to id("Creep"), json = false)
        assertEquals(303, answer.status)
        val id = phone.queue.snapshot().single().id
        assertEquals("/#tab=requests&job=$id", answer.header("location"))
        done(id)
    }

    @Test fun `add, move, remove, rename and delete each change the songbook as caracole songbook does`() {
        done(jobOf(post("/songbook/make", "name" to "Campfire", "songs" to id("Wonderwall"))))
        val added = done(jobOf(post("/songbook/add", "name" to "campfire", "songs" to "${id("Creep")},${id("Wonderwall")}")))
        assertEquals(listOf("Added Radiohead - Creep", "Oasis - Wonderwall is in it already") +
                         wrote("Campfire", "Oasis - Wonderwall", "Radiohead - Creep"), output(added))
        val moved = done(jobOf(post("/songbook/move", "name" to "Campfire", "song" to "radiohead - creep", "position" to "1")))
        assertEquals(listOf("Moved Radiohead - Creep to 1") + wrote("Campfire", "Radiohead - Creep", "Oasis - Wonderwall"),
                     output(moved))
        assertEquals(listOf("Radiohead - Creep", "Oasis - Wonderwall"), books().single().texts)
        val removed = done(jobOf(post("/songbook/remove", "name" to "Campfire", "song" to "Oasis - Wonderwall")))
        assertEquals(listOf("Removed Oasis - Wonderwall") + wrote("Campfire", "Radiohead - Creep"), output(removed))
        assertEquals("Taken out", JobViews.line(removed).text)
        val renamed = done(jobOf(post("/songbook/rename", "name" to "Campfire", "new" to "Fogata")))
        assertEquals(listOf("Renamed the songbook \"Campfire\" to \"Fogata\".") + wrote("Fogata", "Radiohead - Creep"),
                     output(renamed))
        assertEquals(listOf("Fogata"), books().map { it.name })
        // its page went to the folder of its new name, the old one's taken away
        assertTrue(page("Fogata").isFile)
        assertFalse(page("Campfire").exists())
        val deleted = done(jobOf(post("/songbook/delete", "name" to "fogata")))
        assertEquals(listOf("Deleted the songbook \"Fogata\"."), output(deleted))  // a songbook gone: nothing more
        assertEquals("Deleted", JobViews.line(deleted).text)
        assertEquals(emptyList(), books())
        assertFalse(page("Fogata").exists())
    }

    @Test fun `a form refused queues nothing`() {
        done(jobOf(post("/songbook/make", "name" to "Campfire", "songs" to id("Wonderwall"))))
        val refused = post("/songbook/make", "name" to "CAMPFIRE", "songs" to id("Creep"))
        assertEquals(409, refused.status)
        val mirrored = post("/songbook/add", "name" to "Campfire", "songs" to "-3")
        assertEquals(404, mirrored.status)
        assertTrue("left the logbook" in mirrored.json.jsonObject.toString(), mirrored.json.toString())
        assertEquals(1, phone.queue.snapshot().size)
    }

    @Test fun `a song gone from the library between the form and its job fails the job in caracole songbook's words`() {
        done(jobOf(post("/songbook/make", "name" to "Campfire", "songs" to id("Wonderwall"))))
        val queued = phone.queue.submit(LookupForms.spec(
            "Add", "songbook\u001fsongbook\u001fadd\u001f--\u001fCampfire\u001fNobody - Nothing",
            listOf(Command("Adding to the songbook",
                                                                     listOf("songbook", "add", "--", "Campfire", "Nobody - Nothing"))),
        )).first
        val job = done(queued.id)
        assertEquals(Job.FAILED, job.state)
        assertEquals(1, job.steps.single().code)
        assertEquals("error: No song \"Nobody - Nothing\" in the library.", output(job).first())
        assertEquals(listOf("Oasis - Wonderwall"), books().single().texts)
    }

    @Test fun `Add a song puts a song of the library in the songbook, and looks a new one up first, both or neither`() {
        done(jobOf(post("/songbook/make", "name" to "Campfire", "songs" to id("Wonderwall"))))
        val mine = done(jobOf(post("/songbook/add-song", "name" to "Campfire", "song" to id("September"))))
        assertEquals(listOf("Added Earth - Wind - Fire - September") +
                         wrote("Campfire", "Oasis - Wonderwall", "Earth - Wind - Fire - September"), output(mine))
        val answer = post("/songbook/add-song", "name" to "Campfire", "artist" to "Fito Páez", "title" to "Mariposa Tecknicolor")
        val body = answer.json.jsonObject
        val lookup = body.getValue("jobs").jsonArray.single().jsonObject.getValue("id").jsonPrimitive.int
        val add = done(jobOf(answer))
        val looked = done(lookup)
        assertEquals(listOf(lookup, add.id), looked.together)
        assertEquals(listOf("get", "--progress", "--", "Fito Páez", "Mariposa Tecknicolor"), looked.steps.single().args)
        // the lookup added the song (every site refused), and the add put it in the songbook after it
        assertEquals(Job.DONE, add.state, add.asJson().toString())
        assertEquals(listOf("Oasis - Wonderwall", "Earth - Wind - Fire - September", "Fito Páez - Mariposa Tecknicolor"),
                     books().single().texts)
    }

    @Test fun `the runner's words for a setting are caracole songbook's`() {
        assertEquals("key G, dorian, capo 2", SongbookRunner.settingLine(Setting("G", "dorian", 2)))
        assertEquals("no capo, on the piano", SongbookRunner.settingLine(Setting(capo = 0, instrument = "piano")))
        assertEquals("on the low-G ukulele", SongbookRunner.settingLine(Setting(instrument = "ukulele-low-g")))
        assertEquals("the sheet's own setting", SongbookRunner.settingLine(Setting()))
    }

    @Test fun `a usage error exits 2 as typer does, and nothing is changed`() {
        done(jobOf(post("/songbook/make", "name" to "Campfire", "songs" to id("Wonderwall"))))
        for ((args, said) in listOf(
            listOf("songbook", "move", "--", "Campfire", "Oasis - Wonderwall", "0") to
                "error: Invalid value for 'POSITION': 0 is not in the range x>=1.",
            listOf("songbook", "set", "--", "Campfire", "Oasis - Wonderwall") to
                "error: Give --key, --mode, --capo or --instrument to set, or --clear to take the setting off.",
            listOf("songbook", "set", "--capo", "12", "--", "Campfire", "Oasis - Wonderwall") to
                "error: Invalid value for '--capo': 12 is not in the range 0<=x<=11.",
            listOf("songbook", "add", "--", "Campfire") to "error: Missing argument '\"ARTIST - TITLE\"...'.",
            listOf("songbook", "make", "--force", "--", "X", "A - B") to "error: No such option: --force",
        )) {
            val job = done(phone.queue.submit(LookupForms.spec(
                "t", "songbook\u001f" + args.joinToString("\u001f"),
                listOf(Command("l", args)))).first.id)
            assertEquals(2, job.steps.single().code, "$args")
            assertEquals(said, output(job).last(), "$args")
        }
        assertEquals(listOf(Songbook("Campfire", listOf(SongbookSong("Oasis - Wonderwall")))), books())
    }

    @Test fun `a song's chip sets where the songbook plays it, and back to its own`() {
        done(jobOf(post("/songbook/make", "name" to "Campfire", "songs" to "${id("Wonderwall")},${id("Creep")}")))
        val set = done(jobOf(post("/songbook/set", "name" to "Campfire", "song" to "Oasis - Wonderwall", "key" to "g",
                                  "mode" to "Dorian", "capo" to "2")))
        assertEquals(Job.DONE, set.state, set.asJson().toString())
        assertEquals(listOf("Oasis - Wonderwall: key G, dorian, capo 2") + wrote("Campfire", "Oasis - Wonderwall", "Radiohead - Creep"),
                     output(set))
        assertEquals(Setting("G", "dorian", 2), books().single().songs.first().setting)
        val piano = done(jobOf(post("/songbook/set", "name" to "Campfire", "song" to "Oasis - Wonderwall",
                                    "instrument" to "piano")))
        assertEquals(Job.DONE, piano.state, piano.asJson().toString())
        assertEquals("piano", books().single().songs.first().setting?.instrument)
        val own = done(jobOf(post("/songbook/set", "name" to "Campfire", "song" to "Oasis - Wonderwall", "clear" to "1")))
        assertEquals("Oasis - Wonderwall: the sheet's own setting", output(own).first())
        assertEquals(null, books().single().songs.first().setting)
        assertEquals("Changed", JobViews.line(own).text)
    }

    @Test fun `the library page's Songbooks tab is the phone's own songbooks, and jobs json gives them again`() {
        val made = done(jobOf(post("/songbook/make", "name" to "Campfire", "songs" to id("Wonderwall"))))
        val page = phone.app.handle(TestApp.request("GET", "/", emptyMap(), ByteArray(0), TestApp.SECRET))
        assertEquals(200, page.status)
        val block = Regex("""<script type="application/json" id="songs">(.*?)</script>""", RegexOption.DOT_MATCHES_ALL)
            .find(page.text)?.groupValues?.get(1) ?: throw AssertionError("no data on the library page")
        val books = Json.parseToJsonElement(block).jsonObject.getValue("songbooks").jsonObject.getValue("books").jsonArray
        assertEquals(listOf("Campfire"), books.map { it.jsonObject.getValue("name").jsonPrimitive.content })
        val jobs = phone.app.handle(TestApp.request("GET", "/jobs.json?jobs=${made.id}",
                                                    mapOf("sec-fetch-site" to "same-origin", "accept" to "application/json",
                                                          TestApp.TOKEN_HEADER to TestApp.CSRF),
                                                    ByteArray(0), TestApp.SECRET))
        assertEquals(200, jobs.status, jobs.text)
        assertTrue("\"Campfire\"" in jobs.text, jobs.text)
    }

    @Test fun `Get the missing songs asks for none whose sheet the computer's pages keep`() {
        val mirror = Mirror(tmp.newFolder("mirror"))
        val synced = Phone(PhoneDeps(TestDb.fresh(tmp.newFolder("db2")), tmp.newFolder("library2"), tmp.newFolder("state2"),
                                     mirror, scope, NoAddress, TestApp.SECRET, TestApp.CSRF,
                                     transport = { RefusingTransport }, searchesLacuerda = false))
        try {
            val cho = "{title: Creep}\n{artist: Radiohead}\n[G]Words [B]here\n".toByteArray()
            val (creep, wonderwall) = synced.parts.database.writeBlocking { db ->
                // two songs a sync took, each with its sheet.txt, no page of the phone's
                val taken = listOf("Radiohead" to "Creep", "Oasis" to "Wonderwall").map { (artist, title) ->
                    val song = synced.parts.store.add(db, artist, title, now = "2026-11-03T10:00:00Z")
                    val version = LibraryVersions.upsert(db, provider = "ug", tabId = "1${song.id}", songId = song.id,
                                                         slot = "sheet", kind = "chords", rating = 4.5, votes = 3,
                                                         version = 1, label = null, url = "", raw = JsonObject(emptyMap()),
                                                         now = "2026-11-03T10:00:00Z")
                    Kept.keepFile(db, synced.parts.store, song, version, "sheet.txt", "words".toByteArray(), 1,
                                  "2026-11-03T10:00:00Z")
                    song
                }
                Songbooks.make(db, "Gig", taken.map { it.display })
                taken[0] to taken[1]
            }
            // the computer's pages: Creep's sheet.cho, of the song as the phone holds it
            val unit = "song/${creep.key}"
            val digest = synced.parts.database.read { db -> Units.digestOf(db, unit)!! }
            mirror.blobs.mkdirs()
            val files = listOf("Radiohead/Creep/sheet.cho" to cho, "index.html" to "<!doctype html>start".toByteArray())
            val entries = files.map { (path, bytes) ->
                File(mirror.blobs, Canonical.sha256Hex(bytes)).writeBytes(bytes)
                JsonObject(buildMap {
                    put("path", JsonPrimitive(path)); put("url", JsonPrimitive("/" + PyUrl.quote(path)))
                    put("size", JsonPrimitive(bytes.size)); put("sha256", JsonPrimitive(Canonical.sha256Hex(bytes)))
                    put("type", JsonPrimitive("text/plain; charset=utf-8")); put("headers", JsonObject(emptyMap()))
                    if (path.endsWith(".cho")) { put("unit", JsonPrimitive(unit)); put("digest", JsonPrimitive(digest)) }
                })
            }
            mirror.manifestFile.writeText(JsonObject(mapOf("format" to JsonPrimitive(1), "start" to JsonPrimitive("index.html"),
                                                           "files" to JsonArray(entries))).toString())
            assertTrue(mirror.reload() != null)
            fun get(vararg fields: Pair<String, String>): Response = synced.app.handle(TestApp.request(
                "POST", "/songbook/get",
                mapOf("sec-fetch-site" to "same-origin", "origin" to "http://${TestApp.HOST}",
                      "content-type" to "application/x-www-form-urlencoded", "accept" to "application/json"),
                TestApp.form(listOf("csrf" to TestApp.CSRF, "name" to "Gig") + fields), TestApp.SECRET))
            // Creep plays from the computer's sheet: asked for by itself, nothing to get
            val one = get("song" to creep.id.toString())
            assertEquals(409, one.status, one.text)
            // the songbook's: Wonderwall alone, then the songbook made again
            val answer = get()
            assertEquals(200, answer.status, answer.text)
            val lookups = answer.json.jsonObject.getValue("jobs").jsonArray.map { it.jsonObject.getValue("display").jsonPrimitive.content }
            assertEquals(listOf(wonderwall.display), lookups)
        } finally {
            synced.parts.database.close()
        }
    }

    @Test fun `a change makes the songbook's page through the phone's songbooks' pages`() {
        assertSame(phone.songbookPages, phone.parts.songbooks)
        val job = done(jobOf(post("/songbook/make", "name" to "Campfire", "songs" to id("Wonderwall"))))
        assertEquals(listOf("Made the songbook \"Campfire\": 1 song.") + wrote("Campfire", "Oasis - Wonderwall"), output(job))
        assertTrue("Wonderwall" in page("Campfire").readText())
        val again = done(phone.queue.submit(LookupForms.spec(
            "Make it", "songbook\u001fsongbook\u001frender\u001f--\u001fCampfire",
            listOf(Command("Making the songbook", listOf("songbook", "render", "--", "Campfire"))))).first.id)
        assertEquals(listOf("0 rendered, 1 up to date, 0 failed"), output(again))
    }

    @Test fun `a songbook whose page can't be made fails its job as caracole serve's says it, its change made`() {
        // a file where its folder would be: its page can't be written
        val folder = File(phone.parts.store.libraryDir, Songbooks.FOLDER).apply { mkdirs() }
        File(folder, "Campfire").writeText("not a folder")
        val job = done(jobOf(post("/songbook/make", "name" to "Campfire", "songs" to id("Wonderwall"))))
        assertEquals(Job.FAILED, job.state, job.asJson().toString())
        assertEquals(1, job.steps.single().code)
        assertEquals(listOf("Made the songbook \"Campfire\": 1 song.", "warning: songbook Campfire: its page couldn't be made",
                            "Oasis - Wonderwall has no sheet yet: it is named missing until it has one",
                            "Nothing written in ${File(folder, "Campfire").path}",
                            "Some of its files couldn't be made: the warning above says why."), output(job))
        // no error line: typer.Exit(1)'s, so the line is caracole serve's
        assertEquals("Making the songbook failed.", JobViews.line(job).text)
        assertEquals(listOf("Oasis - Wonderwall"), books().single().texts)
        val render = done(phone.queue.submit(LookupForms.spec(
            "Make them", "songbook\u001fsongbook\u001frender",
            listOf(Command("Making the songbooks", listOf("songbook", "render"))))).first.id)
        assertEquals(1, render.steps.single().code)
        assertEquals(listOf("warning: songbook Campfire: its page couldn't be made", "0 rendered, 0 up to date, 1 failed"),
                     output(render))
    }
}
