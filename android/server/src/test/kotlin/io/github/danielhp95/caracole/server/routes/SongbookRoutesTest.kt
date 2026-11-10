package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.lookup.SongbookPages
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
import io.github.danielhp95.caracole.server.testing.replays.SongbookRoutesReplay
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
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
        // waiting on songbook-entries: Get the missing songs reads SongbookEntries.entries and songsToGet, its lane's
        SongbookRoutesReplay.replay(misses, skip = { path -> path == SongbookRoutes.GET_MISSING })
        misses.assertNone()
    }

    @Test fun `Make from the Select bar makes the songbook, in the order picked, its line Made`() {
        val id = jobOf(post("/songbook/make", "name" to "  Beach  ", "songs" to "${id("Hysteria")},${id("Wonderwall")},${id("Hysteria")}"))
        val job = done(id)
        assertEquals(Job.DONE, job.state, job.asJson().toString())
        assertEquals(listOf(Songbook("Beach", listOf(SongbookSong("Muse - Hysteria"), SongbookSong("Oasis - Wonderwall")))),
                     books())
        assertEquals(listOf("Made the songbook \"Beach\": 2 songs."), output(job))
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
        assertEquals(listOf("Added Radiohead - Creep", "Oasis - Wonderwall is in it already"), output(added))
        val moved = done(jobOf(post("/songbook/move", "name" to "Campfire", "song" to "radiohead - creep", "position" to "1")))
        assertEquals(listOf("Moved Radiohead - Creep to 1"), output(moved))
        assertEquals(listOf("Radiohead - Creep", "Oasis - Wonderwall"), books().single().texts)
        val removed = done(jobOf(post("/songbook/remove", "name" to "Campfire", "song" to "Oasis - Wonderwall")))
        assertEquals(listOf("Removed Oasis - Wonderwall"), output(removed))
        assertEquals("Taken out", JobViews.line(removed).text)
        val renamed = done(jobOf(post("/songbook/rename", "name" to "Campfire", "new" to "Fogata")))
        assertEquals(listOf("Renamed the songbook \"Campfire\" to \"Fogata\"."), output(renamed))
        assertEquals(listOf("Fogata"), books().map { it.name })
        val deleted = done(jobOf(post("/songbook/delete", "name" to "fogata")))
        assertEquals(listOf("Deleted the songbook \"Fogata\"."), output(deleted))
        assertEquals("Deleted", JobViews.line(deleted).text)
        assertEquals(emptyList(), books())
    }

    @Test fun `a form refused queues nothing`() {
        done(jobOf(post("/songbook/make", "name" to "Campfire", "songs" to id("Wonderwall"))))
        val refused = post("/songbook/make", "name" to "CAMPFIRE", "songs" to id("Creep"))
        assertEquals(409, refused.status)
        val mirrored = post("/songbook/add", "name" to "Campfire", "songs" to "-3")
        assertEquals(404, mirrored.status)
        assertTrue("isn't in the library any more" in mirrored.json.jsonObject.toString(), mirrored.json.toString())
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
        assertEquals(listOf("Added Earth - Wind - Fire - September"), output(mine))
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

    @Test fun `while the phone makes no songbook pages, a change makes none and says nothing of them`() {
        // waiting on songbook-entries: its SongbookPagesImpl makes the songbook's page, through its seam
        assertSame(SongbookPages.NONE, phone.parts.songbooks)
        val job = done(jobOf(post("/songbook/make", "name" to "Campfire", "songs" to id("Wonderwall"))))
        assertEquals(listOf("Made the songbook \"Campfire\": 1 song."), output(job))
        assertFalse(File(phone.parts.store.libraryDir, Songbooks.FOLDER).exists())
    }
}
