package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.server.page.SongCards
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.json
import io.github.danielhp95.caracole.server.testing.text
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** jobs_routes.py on the phone, through the App: /jobs.json for the page's script alone, a job's view with its song's
 * card once over, /api/jobs/N, and Cancel. */
// The worker runs in the test's backgroundScope, whose tasks runCurrent runs (advanceUntilIdle leaves them be).
@OptIn(ExperimentalCoroutinesApi::class)
class JobsRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    /** Each song's card: its id and title, as a test can tell them apart. */
    private object Cards : SongCards {
        override fun cards(db: Db, songs: List<SongRow>): Map<Long, JsonObject> =
            songs.associate { it.id to JsonObject(mapOf("id" to JsonPrimitive(it.id), "title" to JsonPrimitive(it.title))) }
    }

    private val books = JsonObject(mapOf("books" to JsonPrimitive("as the Songbooks tab has them now")))

    private fun TestScope.app(): Pair<TestApp, JobQueue> {
        val queue = JobQueue(backgroundScope)
        return TestApp(tmp.root, { database -> listOf(JobsRoutes(queue, Cards, database) { books }) }) to queue
    }

    private fun insert(db: Db, artist: String, title: String, key: String): Long {
        db.execute("INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at) " +
                   "VALUES (?, ?, ?, ?, '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z')",
                   key, artist, title, "[\"$artist\"]")
        return db.lastRowid()
    }

    private fun song(database: Database, artist: String, title: String, key: String): Long =
        database.writeBlocking { db -> insert(db, artist, title, key) }

    private fun add(database: Database, artist: String, title: String, key: String) = JobSpec(
        "Add $artist - $title", key, "add", listOf("add" to "Adding to the library"), display = "$artist - $title",
    ) { context ->
        context.stage("add", "running")
        database.write { db -> insert(db, artist, title, key) }  // the job's write, as every write on the phone
        context.stage("add", "done")
    }

    @Test fun jobsJsonIsThePagesScriptsAloneAndSaysToReloadToAnythingElse() = runTest {
        val (test, _) = app()
        test.use {
            val page = test.get("/jobs.json")
            assertEquals(403, page.status)
            assertTrue("reload it" in page.text, page.text)
            val script = test.get("/jobs.json", "accept" to "application/json")
            assertEquals(403, script.status)
            assertEquals("""{"error":"caracole serve has restarted since this page was opened: reload it."}""", script.text)
            assertEquals(403, test.script("/jobs.json", TestApp.TOKEN_HEADER to "an old token").status)
            val fine = test.script("/jobs.json")
            assertEquals(200, fine.status)
            assertEquals("""{"active":0,"jobs":[]}""", fine.text)
            assertEquals("application/json; charset=utf-8", fine.header("Content-Type"))
        }
    }

    @Test fun eachJobsViewAndOnceOverTheCardOfItsSongWhenThePageAsksForIt() = runTest {
        val (test, queue) = app()
        test.use {
            val gate = CompletableDeferred<Unit>()
            val first = queue.submit(add(test.database, "Radiohead", "Creep", "radiohead/creep")).first
            val held = queue.submit(JobSpec("Sync with Laptop", "sync:http://laptop:8737", "sync",
                                            listOf("compare" to "Compare")) { gate.await() }).first
            val third = queue.submit(add(test.database, "Muse", "Hysteria", "muse/hysteria")).first
            runCurrent()
            val all = test.script("/jobs.json").json.jsonObject
            assertEquals(JsonPrimitive(2), all["active"])
            assertEquals(listOf(third.id, held.id, first.id),
                         all["jobs"]!!.jsonArray.map { it.jsonObject["id"]!!.jsonPrimitive.content.toInt() })  // newest first
            val radiohead = all["jobs"]!!.jsonArray.last().jsonObject
            assertNull(radiohead["card"])  // none asked for: a line alone
            // Asked for by its id, over: its song's card as the page draws it, by its key.
            val asked = test.script("/jobs.json?jobs=${first.id},x,${held.id}").json.jsonObject["jobs"]!!.jsonArray
            assertEquals(listOf(held.id, first.id), asked.map { it.jsonObject["id"]!!.jsonPrimitive.content.toInt() })
            val over = asked.last().jsonObject
            val id = test.database.read { db -> db.one("SELECT id FROM songs WHERE key = 'radiohead/creep'") { it.long(0) } }
            assertEquals(Json.parseToJsonElement("""{"id":$id,"title":"Creep","fetchable":true}"""), over["card"])
            assertEquals(books, over["songbooks"])
            assertEquals(listOf("songbooks", "card"), over.keys.toList().takeLast(2))  // jobs_routes.views' order
            assertEquals(JsonPrimitive(id), over["songId"])
            assertEquals(JsonPrimitive("radiohead/creep"), over["identity"])
            assertEquals("Added: the nightly run looks for it", over["line"]!!.jsonObject["text"]!!.jsonPrimitive.content)
            assertNull(asked.first().jsonObject["card"])  // the sync runs still
            assertEquals(JsonPrimitive("running"), asked.first().jsonObject["state"])
            gate.complete(Unit)
            runCurrent()
            assertEquals(JsonPrimitive(0), test.script("/jobs.json?jobs=").json.jsonObject["active"])
        }
    }

    @Test fun anAddOfASongTheLibraryHasNamesItAtOnceWhileItWaits() = runTest {
        val (test, queue) = app()
        test.use {
            val id = song(test.database, "Radiohead", "Creep", "radiohead/creep")
            val gate = CompletableDeferred<Unit>()
            queue.submit(JobSpec("Hold", "hold", "add", emptyList()) { gate.await() })
            val again = queue.submit(add(test.database, "Radiohead", "Creep", "radiohead/creep")).first
            val fresh = queue.submit(add(test.database, "Muse", "Hysteria", "muse/hysteria")).first
            runCurrent()
            val views = test.script("/jobs.json?jobs=${again.id},${fresh.id}").json.jsonObject["jobs"]!!.jsonArray
                .associateBy { it.jsonObject["id"]!!.jsonPrimitive.content.toInt() }
            val waiting = views.getValue(again.id).jsonObject
            assertEquals(JsonPrimitive(id), waiting["songId"])  // jobs_routes.song_of: by its key, queued or not
            assertEquals(JsonPrimitive("radiohead/creep"), waiting["identity"])
            assertEquals("Queued behind 1 request…", waiting["line"]!!.jsonObject["text"]!!.jsonPrimitive.content)
            assertNull(waiting["card"])  // not over: no card, no songbooks
            assertNull(waiting["songbooks"])
            val new = views.getValue(fresh.id).jsonObject
            assertEquals(kotlinx.serialization.json.JsonNull, new["songId"])  // not in the library yet
            assertNull(new["identity"])
            gate.complete(Unit)
            runCurrent()
        }
    }

    @Test fun aRemovalOverHasNoCardOnceItsSongIsGone() = runTest {
        val (test, queue) = app()
        test.use {
            val id = song(test.database, "Oasis", "Wonderwall", "oasis/wonderwall")
            val removal = queue.submit(JobSpec("Remove Oasis - Wonderwall", "remove:oasis/wonderwall", "remove",
                                               emptyList(), display = "Oasis - Wonderwall", songId = id, join = false) {
                test.database.write { db -> db.execute("DELETE FROM songs WHERE id = ?", id) }
            }).first
            runCurrent()
            val view = test.script("/jobs.json?jobs=${removal.id}").json.jsonObject["jobs"]!!.jsonArray.single().jsonObject
            assertNull(view["card"])
            assertEquals(JsonPrimitive(id), view["songId"])
            assertEquals(JsonPrimitive("remove"), view["kind"])
            assertEquals(JsonPrimitive("oasis/wonderwall"), view["identity"])
            assertEquals("Removed", view["line"]!!.jsonObject["text"]!!.jsonPrimitive.content)
        }
    }

    @Test fun theIdsAskedForArePlainDigitsFiftyAtMost() {
        assertNull(JobsRoutes.jobIds(null))
        assertEquals(emptySet(), JobsRoutes.jobIds(""))
        assertEquals(setOf(1, 2, 3), JobsRoutes.jobIds("1, 2,x,,3,-4,٣,99999999999999999999"))
        assertEquals((1..50).toSet(), JobsRoutes.jobIds((1..60).joinToString(",")))
    }

    @Test fun oneJobAsDataOrNone() = runTest {
        val (test, queue) = app()
        test.use {
            val job = queue.submit(add(test.database, "Blur", "Song 2", "blur/song 2")).first
            runCurrent()
            val answer = test.script("/api/jobs/${job.id}")
            assertEquals(200, answer.status)
            assertEquals(queue.job(job.id)!!.asJson(), answer.json)
            for (other in listOf("/api/jobs/99", "/api/jobs/abc", "/api/jobs/", "/api/jobs/99999999999999")) {
                val none = test.script(other)
                assertEquals(404, none.status, other)
                assertEquals("""{"error":"no such request"}""", none.text)
            }
            // A read of /api/ another site's page makes is refused, as every one is.
            assertEquals(403, test.get("/api/jobs/${job.id}", "sec-fetch-site" to "cross-site").status)
        }
    }

    @Test fun cancelTakesAWaitingJobOutAndRefusesInCaracoleServesWords() = runTest {
        val (test, queue) = app()
        test.use {
            val gate = CompletableDeferred<Unit>()
            val running = queue.submit(JobSpec("a", "a", "add", emptyList()) { gate.await() }).first
            val waiting = queue.submit(JobSpec("b", "b", "add", emptyList()) {}).first
            val other = queue.submit(JobSpec("c", "c", "add", emptyList()) {}).first
            runCurrent()
            val script = test.postScript("/jobs/cancel", listOf("job" to "${waiting.id}"))
            assertEquals(200, script.status)
            assertEquals("""{"cancelled":${waiting.id}}""", script.text)
            assertEquals(Job.CANCELLED, queue.job(waiting.id)!!.state)
            val page = test.post("/jobs/cancel", listOf("job" to " ${other.id} "))
            assertEquals(303, page.status)
            assertEquals("/#tab=requests", page.header("Location"))
            fun refused(job: String) = test.postScript("/jobs/cancel", listOf("job" to job)).let {
                it.status to it.json.jsonObject["error"]!!.jsonPrimitive.content
            }
            assertEquals(409 to "That request has started, and caracole never stops a command halfway: it runs to its end.",
                         refused("${running.id}"))
            assertEquals(404 to "That request isn't queued any more.", refused("${waiting.id}"))  // cancelled already
            assertEquals(404 to "That request isn't queued any more.", refused("77"))
            assertEquals(400 to "Which request? The form names none.", refused("two"))
            assertEquals(400 to "Which request? The form names none.", refused("1234567890123"))
            assertEquals(400, test.postScript("/jobs/cancel").status)
            gate.complete(Unit)
            runCurrent()
            assertEquals(409 to "That request is over: there's nothing left to cancel.", refused("${running.id}"))
            assertEquals(403, test.postScript("/jobs/cancel", listOf("job" to "1"), token = "old").status)
        }
    }

    // --- what a job's line reads of its song (SongFacts.songOf) ------------------------------------------------

    /** Each song's card with its files: a sheet's viewer (the one its line opens) for a song with a kept sheet. */
    private object Filed : SongCards {
        override fun cards(db: Db, songs: List<SongRow>): Map<Long, JsonObject> = songs.associate { song ->
            val kept = db.one("SELECT 1 FROM files WHERE song_id = ? AND name = 'sheet.txt'", song.id) { true } == true
            val files = if (kept) """[{"name":"sheet.txt","href":"Radiohead/Creep/sheet.txt","primary":false},
                {"name":"sheet.html","href":"Radiohead/Creep/sheet.html","primary":true}]""" else "[]"
            song.id to Json.parseToJsonElement("""{"id":${song.id},"files":$files}""").jsonObject
        }
    }

    /** caracole get on the phone, as a lookup reports it: its stages one after another, [then] last. */
    private fun lookups(then: suspend (JobContext) -> Unit = {}) = Commands(mapOf("get" to CommandRunner { _, context ->
        for (stage in listOf("song", "match", "sheet")) context.stage(stage, "done")
        then(context)
    }, "lacuerda" to CommandRunner { _, context ->
        context.say("GET https://acordes.lacuerda.net/soda_stereo/ → 200")
        context.say("Read: LaCuerda's page of Soda Stereo lists 42 songs, in the index now (1 request).")
    }, "songbook" to CommandRunner { _, _ -> }))

    private fun TestScope.served(commands: Commands): Pair<TestApp, JobQueue> {
        val queue = JobQueue(backgroundScope, commands = commands)
        return TestApp(tmp.root, { database -> listOf(JobsRoutes(queue, Filed, database) { books }) }) to queue
    }

    private fun lookup(key: String = "radiohead/creep") = JobSpec(
        "Fetch Radiohead - Creep", key, "song", emptyList(), display = "Radiohead - Creep", fetching = true,
        commands = JobCommands.lookupSteps("Radiohead", "Creep"),
    )

    private fun view(test: TestApp, id: Int): JsonObject =
        test.script("/jobs.json?jobs=$id").json.jsonObject["jobs"]!!.jsonArray.single().jsonObject

    private fun line(view: JsonObject): List<String?> = view["line"]!!.jsonObject.let { line ->
        listOf("tone", "text", "link", "details").map { name ->
            when (val value = line[name]) {
                null, is kotlinx.serialization.json.JsonNull -> null
                is JsonPrimitive -> value.content
                else -> value.toString()
            }
        }
    }

    @Test fun aLookupOverWithItsSheetIsReadyItsSheetTheLinkItsLineOpens() = runTest {
        val (test, queue) = served(lookups())
        test.use {
            val id = song(test.database, "Radiohead", "Creep", "radiohead/creep")
            test.database.writeBlocking { db ->
                db.execute("INSERT INTO versions (song_id, provider, tab_id, slot, kind, url, fetched_at) VALUES " +
                           "(?, 'lacuerda', 'radiohead/creep', 'sheet', 'chords', 'https://acordes.lacuerda.net/x', " +
                           "'2026-11-01T00:00:00Z')", id)
                db.execute("INSERT INTO files (song_id, version_id, name, path, sha256, kept_rank, created_at) VALUES " +
                           "(?, ?, 'sheet.txt', 'Radiohead/Creep/sheet.txt', 'x', 0, '2026-11-01T00:00:00Z')", id,
                           db.lastRowid())
            }
            val job = queue.submit(lookup()).first
            runCurrent()
            val seen = view(test, job.id)
            assertEquals(listOf("ready", "Ready", null, null), line(seen))  // Ready alone: the song's line opens it
            assertEquals(JsonPrimitive("Radiohead/Creep/sheet.html"), seen["sheet"])
            assertEquals(JsonPrimitive(true), seen["fetching"])
            assertNull(seen["steps"])  // its steps fold away once Ready
            val facts = test.database.read { db -> SongFacts.songOf(db, queue.job(job.id)!!, Filed, java.time.Instant.now()) }
            assertEquals(id to SongFacts(sheet = "Radiohead/Creep/sheet.html", sheetFrom = "LaCuerda"), facts)
        }
    }

    @Test fun aLookupThatLeftNoSheetIsNotFoundOnlyOnceUltimateGuitarWasAskedSinceItStarted() = runTest {
        var asked = false
        lateinit var database: Database
        val (test, queue) = served(lookups { context ->
            if (asked) database.write { db -> db.execute("UPDATE songs SET ug_checked_at = '2999-01-01T00:00:00Z'") }
            context.stage("pdf", "skipped", "no PDF on the phone")
        })
        test.use {
            database = test.database
            song(test.database, "Radiohead", "Creep", "radiohead/creep")
            val waited = queue.submit(lookup()).first
            runCurrent()
            val first = view(test, waited.id)
            assertEquals(listOf("waiting", "Not fetched yet", null, "#tab=requests&job=${waited.id}"), line(first))
            assertEquals(listOf("Song", "Match", "Sheet"),  // a pdf stage skipped is none, as those the queue skipped
                         first["steps"]!!.jsonArray.map { it.jsonObject["name"]!!.jsonPrimitive.content })
            asked = true
            val found = queue.submit(lookup()).first
            runCurrent()
            // Not found, with no link: the phone has no to-do page.
            assertEquals(listOf("missing", "Not found", null, null), line(view(test, found.id)))
            assertEquals(listOf("waiting", "Not fetched yet", null, "#tab=requests&job=${waited.id}"),
                         line(view(test, waited.id)))  // a job over keeps what it came to
        }
    }

    @Test fun aSongInReviewWithCandidatesLinksItsPickerAndAnIgnoredOneSaysSo() = runTest {
        val (test, queue) = served(lookups())
        test.use {
            val id = song(test.database, "Radiohead", "Creep", "radiohead/creep")
            test.database.writeBlocking { db ->
                db.execute("UPDATE songs SET review = 1, match_candidates = ? WHERE id = ?",
                           """[{"artist_key":"radiohead","song_key":"creep","score":88}]""", id)
            }
            val job = queue.submit(lookup()).first
            runCurrent()
            assertEquals(listOf("review", "Needs review", """{"label":"Pick the match","href":"review?song=$id"}""", null),
                         line(view(test, job.id)))
            song(test.database, "Muse", "Hysteria", "muse/hysteria")
            test.database.writeBlocking { db ->
                db.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES " +
                           "('ignore', 'muse/hysteria', 'Muse - Hysteria', 'true')")
            }
            val ignored = queue.submit(lookup("muse/hysteria")).first
            runCurrent()
            assertEquals("Ignored in overrides.toml", line(view(test, ignored.id))[1])
        }
    }

    @Test fun aSitesIndexReadSaysWhatTheSiteAnsweredItsDataTooAndChangesNoSongbook() = runTest {
        val (test, queue) = served(lookups())
        test.use {
            val read = queue.submit(JobSpec("Read the page of Soda Stereo on LaCuerda", "lacuerda-artist:soda_stereo",
                                            "lacuerda-artist", emptyList(),
                                            commands = JobCommands.lacuerdaArtistSteps("soda_stereo", "Soda Stereo"))).first
            runCurrent()
            val seen = view(test, read.id)
            assertEquals(listOf("added", "Read: LaCuerda's page of Soda Stereo lists 42 songs, in the index now.", null,
                                null), line(seen))
            assertNull(seen["songbooks"])
            assertEquals(JsonPrimitive("song"), seen["kind"])  // caracole serve's kind of it
            val data = test.script("/api/jobs/${read.id}").json.jsonObject
            assertEquals(seen["line"], data["line"])
        }
    }

    @Test fun aSongbookMadeLinksItsPageWhileThePhoneHasWrittenOne() = runTest {
        val (test, queue) = served(lookups())
        test.use {
            val command = listOf("songbook", "make", "--", "Campfire", "Radiohead - Creep")
            fun make() = queue.submit(JobSpec("Make the songbook", "songbook\u001f" + command.joinToString("\u001f"),
                                              "songbook", emptyList(),
                                              commands = listOf(Command("Making the songbook", command)))).first
            val none = make()
            runCurrent()
            assertEquals(listOf("ready", "Made", null, null), line(view(test, none.id)))
            test.database.writeBlocking { db ->
                db.kvSet("songbook:Campfire", """{"inputs":{},"files":{"songbook.html":{"sha256":"ab","size":12}}}""")
            }
            val made = make()
            runCurrent()
            val seen = view(test, made.id)
            assertEquals("""{"label":"Open songbook","href":"_songbooks/Campfire/songbook.html"}""", line(seen)[2])
            assertEquals(Json.parseToJsonElement("""{"action":"make","name":"Campfire","after":"Campfire"}"""),
                         seen["songbook"])
            assertEquals(JsonPrimitive("songbook"), seen["kind"])
        }
    }
}
