package io.github.danielhp95.caracole.server.routes.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverridesStore
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.JobsRoutes
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.server.page.SongCards
import io.github.danielhp95.caracole.server.routes.LibraryRoutes
import io.github.danielhp95.caracole.server.routes.LookupRoutes
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.Commands
import io.github.danielhp95.caracole.server.lookups.GetRunner
import io.github.danielhp95.caracole.server.testing.TestParts
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.json
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** A song added, looked up and removed from the library page on the phone, through TestApp: LibraryRoutes beside
 * LookupRoutes (Get it, Fetch now), each lookup run by the phone's `get` runner with every site refused. */
class LibraryRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private lateinit var queue: JobQueue
    private lateinit var app: TestApp

    private object NoCards : SongCards {
        override fun cards(db: Db, songs: List<SongRow>): Map<Long, JsonObject> = emptyMap()
    }

    /** LibraryRoutes and LookupRoutes over [queue], whose `get` is the phone's runner (Assembly's wiring). */
    private fun modules(dir: java.io.File, queue: JobQueue, commands: MutableMap<String, CommandRunner>,
                        cards: SongCards = NoCards, database: Database): List<RouteModule> {
        val parts = TestParts.of(database, dir, scope, queue)
        commands["get"] = GetRunner(parts)
        return listOf(LibraryRoutes(LibraryStore(java.io.File(dir, "library")), queue, cards, database), LookupRoutes(parts))
    }

    @Before fun up() {
        val commands = HashMap<String, CommandRunner>()
        queue = JobQueue(scope, commands = Commands(commands))
        val dir = tmp.newFolder("phone")
        app = TestApp(dir, modules = { database -> modules(dir, queue, commands, database = database) })
    }

    @After fun down() {
        scope.cancel()
        if (::app.isInitialized) app.close()
    }

    private fun error(answer: io.github.danielhp95.caracole.server.http.Response): String =
        answer.json.jsonObject.getValue("error").jsonPrimitive.content

    private fun waitFor(view: JsonObject): Job = runBlocking {
        withTimeout(20_000) { queue.await(view.getValue("id").jsonPrimitive.int) }
    }

    private fun song(artist: String, title: String): SongRow? =
        app.database.read { Songs.byKey(it, Normalize.identityKey(artist, title)) }

    // --- what is refused before anything is queued -----------------------------------------------------------------

    @Test fun `a request with no artist or title, or a field too long, is refused before anything is queued`() {
        val cases = listOf(
            listOf("artist" to "Soda Stereo", "title" to "  ") to "A song needs an artist and a title.",
            listOf("artist" to "x".repeat(201), "title" to "T") to "The artist is too long: 200 characters at most.",
            listOf("artist" to "A", "title" to "T", "album" to "x".repeat(301)) to "The album is too long: 300 characters at most.",
            listOf("artist" to "A", "title" to "T", "duration" to "4:75") to
                "The length is a bad duration '4:75': write m:ss, h:mm:ss or whole seconds.",
            listOf("artist" to "A", "title" to "T", "duration" to "0:00") to
                "The length is a bad duration '0:00': it must be longer than zero.",
            listOf("artist" to "A", "title" to "T", "duration" to "four minutes") to
                "The length 'four minutes' isn't a duration. Write m:ss, h:mm:ss or seconds.",
            listOf("artist" to "Simon - Garfunkel", "title" to "T") to
                "caracole can't add this song: wanted.txt can't hold an artist name with ' - ' in it: 'Simon - Garfunkel'",
            listOf("q" to "x".repeat(501)) to "The text is too long: 500 characters at most.",
        )
        for ((fields, said) in cases) {
            for (path in listOf("/request", "/lookup")) {
                val answer = app.postScript(path, fields)
                assertEquals(400, answer.status, "$path $fields")
                assertEquals(said, error(answer), "$path $fields")
            }
        }
    }

    @Test fun `a sheet from a YouTube video isn't on the phone yet`() {
        val answer = app.postScript("/request", listOf("artist" to "A", "title" to "T",
                                                       "youtube" to "https://youtu.be/dQw4w9WgXcQ"))
        assertEquals(409, answer.status)
        assertEquals("A sheet from a YouTube video: not on the phone yet.", error(answer))
    }

    @Test fun `a removal of a song the library hasn't got is 404, and one naming none is 400`() {
        assertEquals(404, app.postScript("/remove", listOf("song" to "41")).status)
        assertEquals("That song isn't in the logbook. Removed already?", error(app.postScript("/remove", listOf("song" to "41"))))
        assertEquals(400, app.postScript("/remove", listOf("song" to "")).status)
        assertEquals(404, app.postScript("/lookup", listOf("song" to "41")).status)
    }

    @Test fun `durations read as wanted dot txt reads them`() {
        assertEquals(272_000L, SongForm.parseDuration("4:32"))
        assertEquals(3_723_000L, SongForm.parseDuration("1:02:03"))
        assertEquals(95_000L, SongForm.parseDuration(" 95 "))
        assertEquals(272_000L, SongForm.parseDuration("４:３２"))  // NFKC first
        assertNull(SongForm.parseDuration("4.32"))
        assertNull(SongForm.parseDuration("1:2:3:4"))
    }

    @Test fun `the back address a removal goes to is the library page's own, at the song's card`() {
        assertEquals("/#tab=library&q=creep&song=7", LibraryRoutes.libraryAt(LibraryRoutes.back("#tab=library&song=3&q=creep"), 7))
        assertEquals("/#song=7", LibraryRoutes.libraryAt(LibraryRoutes.back("<script>"), 7))
    }

    // --- with the lanes it stands on -------------------------------------------------------------------------------

    @Test fun `a request adds the song as an add job under its identity key`() {
        val answer = app.postScript("/request", listOf("artist" to " Soda Stereo ", "title" to "De Música Ligera",
                                                       "album" to "Canción Animal", "duration" to "3:31"))
        assertEquals(200, answer.status, answer.json.toString())
        val job = waitFor(answer.json.jsonObject.getValue("job").jsonObject)
        assertEquals("done", job.state)
        assertEquals("add", job.spec.kind)
        assertEquals(Normalize.identityKey("Soda Stereo", "De Música Ligera"), job.spec.key)
        val added = assertNotNull(song("Soda Stereo", "De Música Ligera"))
        assertEquals("Soda Stereo", added.artist)
        assertEquals("Canción Animal", added.album)
        assertEquals(211_000L, added.durationMs)
        // Without the script, the browser goes to the request's line.
        val page = app.post("/request", listOf("artist" to "Soda Stereo", "title" to "Persiana Americana"))
        assertEquals(303, page.status)
        assertNotNull(page.header("Location"))
    }

    @Test fun `Fetch now is a lookup, which adds the song`() {
        val answer = app.postScript("/request", listOf("artist" to "Radiohead", "title" to "Creep", "fetch" to "1"))
        val job = waitFor(answer.json.jsonObject.getValue("job").jsonObject)
        assertEquals("song", job.spec.kind)
        assertEquals(listOf(listOf("get", "--progress", "--", "Radiohead", "Creep")), job.steps.map { it.args })
        assertNotNull(song("Radiohead", "Creep"))
    }

    @Test fun `one text is read as song_names reads it, and one that names no artist is refused`() {
        val answer = app.postScript("/request", listOf("q" to "Soda Stereo - De Música Ligera"))
        assertEquals("done", waitFor(answer.json.jsonObject.getValue("job").jsonObject).state)
        assertNotNull(song("Soda Stereo", "De Música Ligera"))
        val refused = app.postScript("/request", listOf("q" to "música"))
        assertEquals(400, refused.status)
        assertTrue("doesn't say who the artist is" in error(refused))
    }

    @Test fun `Get it adds the song and answers a lookup's shape, which the page follows`() {
        val answer = app.postScript("/lookup", listOf("artist" to "Radiohead", "title" to "Karma Police",
                                                      "ug" to "radiohead/karma-police"))
        assertEquals(202, answer.status)
        val data = answer.json.jsonObject
        val id = data.getValue("job").jsonPrimitive.int
        assertEquals(JsonPrimitive("/api/jobs/$id"), data["url"])
        assertEquals(JsonPrimitive(id), data.getValue("view").jsonObject["id"])
        assertEquals("done", waitFor(data.getValue("view").jsonObject).state)
        assertNotNull(song("Radiohead", "Karma Police"))
        // A song the library has: the same song, never a second.
        val again = app.postScript("/lookup", listOf("song" to song("Radiohead", "Karma Police")!!.id.toString()))
        assertEquals("done", waitFor(again.json.jsonObject.getValue("view").jsonObject).state)
        assertEquals(1, app.database.read { Songs.list(it) }.size)
    }

    @Test fun `add then remove leaves a tombstone, and the song stays removed until asked for again`() {
        waitFor(app.postScript("/request", listOf("artist" to "Oasis", "title" to "Wonderwall")).json.jsonObject.getValue("job").jsonObject)
        val wonderwall = assertNotNull(song("Oasis", "Wonderwall"))

        val question = app.postScript("/remove", listOf("song" to wonderwall.id.toString()))
        assertEquals(200, question.status)
        val removal = question.json.jsonObject.getValue("removal").jsonObject
        assertEquals(listOf("song", "key", "display", "brief", "goes", "stays", "notes"), removal.keys.toList())
        assertEquals(JsonPrimitive(wonderwall.key), removal["key"])
        assertEquals(JsonPrimitive("Deletes its entry."), removal["brief"])
        assertNotNull(song("Oasis", "Wonderwall"), "the question changes nothing")

        val refused = app.postScript("/remove", listOf("song" to wonderwall.id.toString(), "confirm" to "1", "key" to "oasis/other"))
        assertEquals(409, refused.status)

        val confirmed = app.postScript("/remove", listOf("song" to wonderwall.id.toString(), "confirm" to "1",
                                                         "key" to wonderwall.key, "back" to "#tab=library"))
        assertEquals(200, confirmed.status)
        val job = waitFor(confirmed.json.jsonObject.getValue("job").jsonObject)
        assertEquals("done", job.state)
        assertEquals("remove", job.spec.kind)
        assertEquals(wonderwall.id, job.spec.songId)
        assertEquals("remove:${wonderwall.key}", job.spec.key)
        assertNull(song("Oasis", "Wonderwall"))
        assertTrue(app.database.read { Songs.isRemoved(it, wonderwall.key) })

        // Asked for again, it comes back new.
        waitFor(app.postScript("/request", listOf("artist" to "Oasis", "title" to "Wonderwall")).json.jsonObject.getValue("job").jsonObject)
        assertNotNull(song("Oasis", "Wonderwall"))
        assertTrue(!app.database.read { Songs.isRemoved(it, wonderwall.key) })
    }

    @Test fun `a removal confirmed goes back to the library page as it was left, at the song's card`() {
        waitFor(app.postScript("/request", listOf("artist" to "Blur", "title" to "Song 2")).json.jsonObject.getValue("job").jsonObject)
        val song2 = assertNotNull(song("Blur", "Song 2"))
        val page = app.post("/remove", listOf("song" to song2.id.toString(), "confirm" to "1", "key" to song2.key,
                                              "back" to "#tab=library&q=blur"))
        assertEquals(303, page.status)
        assertEquals("/#tab=library&q=blur&song=${song2.id}", page.header("Location"))
    }

    private fun added(fields: List<Pair<String, String>>, path: String = "/request"): Job {
        val data = app.postScript(path, fields).json.jsonObject
        return waitFor((data["job"] as? JsonObject) ?: data.getValue("view").jsonObject)
    }

    private fun unitOf(song: SongRow) = app.database.read { Units.libraryState(it) }.getValue("song/${song.key}")

    @Test fun `a song the library has is never written to by the form, whichever form asks for it again`() {
        added(listOf("artist" to "Radiohead", "title" to "Creep", "album" to "Pablo Honey", "duration" to "3:58"))
        val creep = assertNotNull(song("Radiohead", "Creep"))
        val before = unitOf(creep)
        val asked = listOf(
            "/lookup" to listOf("song" to creep.id.toString()),
            "/lookup" to listOf("artist" to "Radiohead", "title" to "Creep"),
            "/lookup" to listOf("q" to "Radiohead - Creep"),
            "/request" to listOf("artist" to "radiohead", "title" to "CREEP"),
            "/request" to listOf("artist" to "Radiohead", "title" to "Creep", "album" to "Other", "duration" to "1:00",
                                 "fetch" to "1"),
        )
        for ((path, fields) in asked) {
            val job = added(fields, path)
            // every site refused: a lookup ends done all the same (get.py exits 0 on a provider's error)
            assertEquals(Job.DONE, job.state, "$path $fields: ${job.asJson()}")
            assertEquals(creep.key, job.spec.key)
            assertEquals(creep.id, job.songId)
            // An add writes nothing; a lookup looks the song up (what it found, or failed on), never the form's names,
            // album or length.
            if (job.spec.kind == "add") assertEquals(before, unitOf(creep), "$path $fields: its unit as it was")
        }
        val after = assertNotNull(song("Radiohead", "Creep"))
        assertEquals("Pablo Honey", after.album)
        assertEquals(238_000L, after.durationMs)
        assertEquals(creep.sourceIds, after.sourceIds)
        assertEquals(1, app.database.read { Songs.list(it) }.size)
        // Its line names it as the library does, and says it is there already.
        val again = added(listOf("artist" to "radiohead", "title" to "creep"))
        assertEquals("Add Radiohead - Creep", again.spec.title)
        assertEquals("In your book as Radiohead - Creep.", again.stages.single().detail)
    }

    @Test fun `a new song's names are those wanted dot txt's line would hold`() {
        val job = added(listOf("artist" to "Soda  Stereo\u200b", "title" to "De Mu\u0301sica   Ligera",
                               "album" to " Canción\u00a0 Animal "))
        val song = assertNotNull(song("Soda Stereo", "De Música Ligera"))
        assertEquals("Soda Stereo", song.artist)
        assertEquals("De Música Ligera", song.title)
        assertEquals("Canción Animal", song.album)
        assertEquals("Soda Stereo - De Música Ligera", job.display)
        assertEquals(Normalize.identityKey("Soda Stereo", "De Música Ligera"), job.spec.key)
        val refused = app.postScript("/request", listOf("artist" to "\u200b", "title" to "T"))
        assertEquals(400, refused.status)
        assertEquals("Can't add this song: it needs an artist and a title", error(refused))
    }

    @Test fun `a full queue is refused, 503, and nothing is added`() {
        val commands = HashMap<String, CommandRunner>()
        val full = JobQueue(scope, limit = 0, commands = Commands(commands))
        val dir = tmp.newFolder("full")
        TestApp(dir, modules = { database -> modules(dir, full, commands, database = database) }).use { small ->
            for ((path, fetch) in listOf("/request" to "0", "/request" to "1", "/lookup" to "0")) {
                val answer = small.postScript(path, listOf("artist" to "Oasis", "title" to "Wonderwall", "fetch" to fetch))
                assertEquals(503, answer.status, path)
                assertEquals(LibraryRoutes.FULL, error(answer))
            }
            assertEquals(emptyList(), small.database.read { Songs.list(it) })
        }
    }

    @Test fun `once its add is done, the job names its song, whose card the page's requests carry`() {
        val dir = tmp.newFolder("cards")
        val cards = object : SongCards {
            override fun cards(db: Db, songs: List<SongRow>): Map<Long, JsonObject> =
                songs.associate { it.id to JsonObject(mapOf("id" to JsonPrimitive(it.id), "display" to JsonPrimitive(it.display))) }
        }
        TestApp(dir, modules = { database ->
            listOf(JobsRoutes(queue, cards, database), LibraryRoutes(LibraryStore(java.io.File(dir, "library")), queue, cards, database))
        }).use { paged ->
            val view = paged.postScript("/request", listOf("artist" to "Blur", "title" to "Song 2")).json.jsonObject
                .getValue("job").jsonObject
            val job = waitFor(view)
            val song = assertNotNull(paged.database.read { Songs.byKey(it, Normalize.identityKey("Blur", "Song 2")) })
            assertEquals(song.id, job.songId)
            val shown = paged.script("/jobs.json?jobs=${job.id}").json.jsonObject.getValue("jobs").jsonArray.single().jsonObject
            assertEquals(JsonPrimitive(song.id), shown["songId"])
            assertEquals(JsonPrimitive("Blur - Song 2"), shown.getValue("card").jsonObject["display"])
            assertEquals("Added · fetched tonight", shown.getValue("line").jsonObject.getValue("text").jsonPrimitive.content)
        }
    }

    @Test fun `Add with a LaCuerda pick records it for the song, and its line says tonight's run gets it`() {
        val dir = tmp.newFolder("picked")
        TestApp(dir, modules = { database ->
            listOf(JobsRoutes(queue, NoCards, database), LibraryRoutes(LibraryStore(java.io.File(dir, "library")), queue,
                                                                       NoCards, database))
        }).use { paged ->
            val url = "https://acordes.lacuerda.net/estopa/fuego"
            val view = paged.postScript("/request", listOf("artist" to "Estopa", "title" to "Fuego", "lacuerda" to url))
                .json.jsonObject.getValue("job").jsonObject
            val job = waitFor(view)
            assertEquals(Job.DONE, job.state, job.asJson().toString())
            assertEquals("add", job.spec.kind)
            val song = assertNotNull(paged.database.read { Songs.byKey(it, Normalize.identityKey("Estopa", "Fuego")) })
            val entries = paged.database.read { OverridesStore.songEntries(it, song.key) }
            assertTrue("lacuerda" in entries, "$entries")
            assertEquals(OverrideUrls.lacuerdaPickFromUrl(url).url,
                         paged.database.read { Overrides.read(it) }.lacuerda[song.key]?.url)
            val shown = paged.script("/jobs.json?jobs=${job.id}").json.jsonObject.getValue("jobs").jsonArray.single()
                .jsonObject.getValue("line").jsonObject
            assertEquals("Added · your LaCuerda pick comes tonight", shown.getValue("text").jsonPrimitive.content)

            // a song of the library LaCuerda answered for lately: a new pick is asked for at once
            paged.database.writeBlocking { db ->
                db.execute("UPDATE songs SET lacuerda_checked_at = '2026-11-01T00:00:00Z' WHERE id = ?", song.id)
            }
            val other = "https://acordes.lacuerda.net/estopa/fuego-2.shtml"
            val again = waitFor(paged.postScript("/request", listOf("artist" to "estopa", "title" to "fuego",
                                                                     "lacuerda" to other)).json.jsonObject.getValue("job").jsonObject)
            assertEquals(Job.DONE, again.state, again.asJson().toString())
            val after = assertNotNull(paged.database.read { Songs.byId(it, song.id) })
            assertNull(after.lacuerdaCheckedAt)
            assertEquals(OverrideUrls.lacuerdaPickFromUrl(other).url,
                         paged.database.read { Overrides.read(it) }.lacuerda[song.key]?.url)
            assertEquals(1, paged.database.read { Songs.list(it) }.size)
        }
    }

    @Test fun `the question names the files the phone keeps for the song`() {
        waitFor(app.postScript("/request", listOf("artist" to "Estopa", "title" to "Tu Calorro")).json.jsonObject.getValue("job").jsonObject)
        val calorro = assertNotNull(song("Estopa", "Tu Calorro"))
        app.database.writeBlocking { db ->
            db.execute("INSERT INTO versions (provider, tab_id, song_id, slot, kind, url, fetched_at) " +
                       "VALUES ('inbox', 'g', ?, 'guitar', 'guitar', '', '2026-11-03T10:00:00Z')", calorro.id)
            db.execute("INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) VALUES " +
                       "(?, ?, 'guitar-1.gp5', 'Estopa/Tu Calorro/guitar-1.gp5', ?, 0, '2026-11-03T10:00:00Z')",
                       db.lastRowid(), calorro.id, "ab".repeat(32))
        }
        val removal = app.postScript("/remove", listOf("song" to calorro.id.toString())).json.jsonObject.getValue("removal").jsonObject
        assertEquals(JsonPrimitive("Deletes the phone's 1 file for it and its entry."), removal["brief"])
        assertTrue(removal.getValue("goes").jsonArray.first().jsonPrimitive.content.endsWith("guitar-1.gp5"))
    }
}
