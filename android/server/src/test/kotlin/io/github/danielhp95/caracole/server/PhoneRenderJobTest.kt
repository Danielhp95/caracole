package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.RenderStats
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Security
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.routes.SyncSettings
import io.github.danielhp95.caracole.viewer.render.PhoneRender
import io.github.danielhp95.caracole.viewer.render.WrittenPages
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.net.URLEncoder
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** The phone's own render job on its real queue, with its real lookups (lane phone-render): what PhoneRenderTest
 * shows with a `between` of its own, through JobContext.yieldToQueued and GetRunner's pdf stage. */
class PhoneRenderJobTest {
    @get:Rule val tmp = TemporaryFolder()

    private object NoAddress : SyncSettings {
        override val address: String? = null
        override fun remember(address: String) = Unit
    }

    /** A case's fixture from vectors/viewer/render.jsonl, in [database] and [library]. */
    private fun load(database: Database, library: File, case: String) {
        val record = Corpus.records("viewer/render.jsonl").first { it.extra["case"] == JsonPrimitive(case) }
        database.writeBlocking { db -> Fixtures.loadRecords(db, record.args[0].jsonArray.map { it.jsonObject }, library) }
    }

    @Test fun aLookupQueuedWhileTheRenderJobRunsRunsBetweenTwoSongsAndMakesItsSongsPagesItself() {
        val scope = CoroutineScope(SupervisorJob())
        try {
            TestDb.fresh(tmp.root).use { database ->
                val library = tmp.newFolder("library")
                load(database, library, "own_versions") // three songs, the render job's order newest first
                val deps = PhoneDeps(database, library, tmp.newFolder("state"), null, scope, NoAddress,
                                     secret = "s".repeat(64), csrf = "tok", transport = { RefusingTransport })
                val said = CopyOnWriteArrayList<String>()
                var phone: Phone? = null
                var lookup: Int? = null
                // The render job's own `between`, the queue's yieldToQueued, with a lookup queued before the first
                // (Hotel California, the oldest: the job's last song), as the library page's Get it would.
                val render = object : PhoneRender(deps.database, deps.libraryDir, deps.mirror, deps.version) {
                    override fun renderStale(between: () -> Unit, progress: (done: Int, total: Int) -> Unit): RenderStats =
                        super.renderStale(between = {
                            val queue = phone!!.queue
                            if (lookup == null) {
                                lookup = queue.submit(JobSpec("Look it up", "eagles/hotel california", "song",
                                                              emptyList(),
                                                              commands = JobCommands.lookupSteps("Eagles", "Hotel California")))
                                    .first.id
                            }
                            between()
                            said += "between: the lookup ${queue.snapshot().first { it.id == lookup }.state}"
                        }) { done, total ->
                            said += "$done of $total"
                            progress(done, total)
                        }
                }
                phone = Phone(deps, render)
                assertTrue(render.stale())
                val job = phone.renderAgain()
                val over = runBlocking { withTimeout(120_000) { phone.queue.await(job.id) } }
                assertEquals(Job.DONE, over.state, "${over.stages.single().detail}")
                assertEquals(listOf("0 of 3", "1 of 3", "between: the lookup ${Job.DONE}", "2 of 3",
                                    "between: the lookup ${Job.DONE}", "3 of 3"), said)
                // the lookup made its song's pages in its pdf stage; the job passed over it, made the other two
                val looked = runBlocking { phone.queue.await(lookup!!) }
                val pdf = looked.stages.first { it.name == "pdf" }
                assertEquals("done" to LookupWords.PAGES_MADE, pdf.state to pdf.detail)
                assertEquals("Pages remade · 2 songs", over.stages.single().detail)
                assertTrue(File(library, "Eagles/Hotel California/sheet.html").isFile)
                val hotel = database.read { db -> db.one("SELECT id FROM songs WHERE title = 'Hotel California'") { it.long(0)!! }!! }
                assertTrue(database.read { db -> WrittenPages.current(db, hotel, "sheet.html") })
                assertTrue(database.read { db -> render.owed(db).isEmpty() })
                assertTrue(!render.stale())
            }
        } finally {
            scope.cancel()
        }
    }

    /**
     * A change on the phone that moves a song's unit and makes no page of it (a review answered "None of these", its
     * `[reject]`; the song asked for again with a LaCuerda pick, its `[lacuerda]`) leaves the phone's own sheet page
     * unserved (LibraryFiles: 409) only until the render job, queued after it, makes the song's pages again.
     */
    @Test fun aSongsOwnPageIsServedAgainAfterAChangeOnThePhoneThatMadeNoPage() {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        val secret = "s".repeat(64)
        val own = mapOf("cookie" to "${Security.SECRET_COOKIE}=$secret", "host" to "127.0.0.1:8738",
                        "sec-fetch-site" to "same-origin")
        fun text(r: Response): String = when (val b = r.body) {
            Body.Empty -> ""
            is Body.Bytes -> b.bytes.toString(Charsets.UTF_8)
            is Body.FromFile -> b.open().use { it.readBytes().toString(Charsets.UTF_8) }
        }
        fun Phone.page(path: String): Int = app.handle(Request(
            "GET", "/" + path.split('/').joinToString("/") { URLEncoder.encode(it, Charsets.UTF_8).replace("+", "%20") },
            own, ByteArray(0))).status
        fun Phone.settle() = runBlocking {
            withTimeout(120_000) { for (job in queue.snapshot().filter { it.active }) queue.await(job.id) }
        }
        fun Phone.post(target: String, vararg fields: Pair<String, String>): Job {
            val form = (listOf("csrf" to "tok") + fields).joinToString("&") { (n, v) ->
                URLEncoder.encode(n, Charsets.UTF_8) + "=" + URLEncoder.encode(v, Charsets.UTF_8)
            }
            val queued = app.handle(Request(
                "POST", target, own + ("content-type" to "application/x-www-form-urlencoded") +
                    ("origin" to "http://127.0.0.1:8738") + ("accept" to "application/json"), form.toByteArray()))
            assertEquals(200, queued.status, text(queued))
            val id = Json.parseToJsonElement(text(queued)).jsonObject.getValue("job").jsonObject.getValue("id")
                .jsonPrimitive.int
            return runBlocking { withTimeout(60_000) { queue.await(id) } }
        }
        try {
            TestDb.fresh(tmp.root).use { database ->
                val library = tmp.newFolder("library")
                load(database, library, "own_versions")
                database.writeBlocking { db ->
                    db.execute("UPDATE songs SET review = 1, match_decision = 'review', match_candidates = ? WHERE id = 1",
                               "[{\"artist_key\":\"eagles\",\"song_key\":\"hotel-california-live\"," +
                                   "\"step\":\"fuzzy_title\",\"score\":88.0}]")
                }
                val phone = Phone(PhoneDeps(database, library, tmp.newFolder("state"), null, scope, NoAddress,
                                            secret = secret, csrf = "tok", transport = { RefusingTransport }))
                phone.start()
                phone.settle()
                val eagles = "Eagles/Hotel California/sheet.html"
                val soda = "Soda Stereo/De Música Ligera/sheet.html"
                assertEquals(listOf(200, 200), listOf(phone.page(eagles), phone.page(soda)))

                val review = phone.post("/review", "song" to "1", "pick" to "none", "shown" to "eagles/hotel-california-live")
                assertEquals(Job.DONE, review.state, review.output.joinToString("\n"))
                phone.settle()
                assertEquals(200, phone.page(eagles), "the review's song's own page, made again")

                val add = phone.post("/request", "artist" to "Soda Stereo", "title" to "De Música Ligera",
                                     "lacuerda" to "https://acordes.lacuerda.net/soda_stereo/de_musica_ligera")
                assertEquals(Job.DONE, add.state, add.output.joinToString("\n"))
                phone.settle()
                assertEquals(200, phone.page(soda), "the picked song's own page, made again")
                assertEquals(emptyList(), database.read { db -> phone.render.owed(db).map { it.display } })
                assertEquals(false, phone.render.stale())
            }
        } finally {
            scope.cancel()
        }
    }
}
