package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.HttpRequest
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.youtube.Due
import io.github.danielhp95.caracole.core.youtube.HostGate
import io.github.danielhp95.caracole.core.youtube.YouTubeEngine
import io.github.danielhp95.caracole.core.youtube.YtDlpGate
import io.github.danielhp95.caracole.core.youtube.YtDlpProcess
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.routes.SyncSettings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import io.github.danielhp95.caracole.server.jobs.Outcomes

/** The automatic pass's trigger after a lookup (the design's §5.3; Phone.afterJob): a lookup whose outcome is "Not on
 * the sites" notes that song (kv `youtube-wanted:<id>`) and tells onNoSheet; one of a song that keeps a sheet notes
 * nothing; a build with no yt-dlp notes nothing. Every site answers 404 (none has the song; LRCLIB's search an empty list), UG's index read whole
 * and of another song, so the match settles "not found". */
class NoSheetNoteTest {
    @get:Rule val tmp = TemporaryFolder()

    private object NoAddress : SyncSettings {
        override val address: String? = null
        override fun remember(address: String) = Unit
    }

    private object Missing : Transport {
        override fun send(request: HttpRequest): HttpAnswer =
            if ("lrclib.net/api/search" in request.url) HttpAnswer(200, emptyList(), "[]".toByteArray())
            else HttpAnswer(404, emptyList(), ByteArray(0))
    }

    private object Engine : YouTubeEngine {
        override fun ready(): String? = null
        override fun process(): YtDlpProcess = throw AssertionError("a lookup never runs yt-dlp")
        override fun gate(): YtDlpGate = object : YtDlpGate {
            override val proxyArg = "http://t:s@127.0.0.1:9"
            override fun log(): Map<String, HostGate.HostUse> = emptyMap()
            override fun close() {}
        }
        override val qjs = File("/qjs")
        override val cacheDir = File("/nowhere")
    }

    private fun <T> phone(youtube: YouTubeEngine? = Engine, block: (Phone) -> T): T {
        val scope = CoroutineScope(SupervisorJob())
        try {
            return TestDb.fresh(tmp.newFolder()).use { database ->
                val dir = tmp.newFolder()
                val deps = PhoneDeps(database, File(dir, "library").apply { mkdirs() }, File(dir, "state").apply { mkdirs() },
                                     null, scope, NoAddress, secret = "s".repeat(64), csrf = "tok",
                                     transport = { Missing }, youtube = youtube)
                database.writeBlocking { db ->  // UG's index read whole, of another song alone
                    db.kvSet("ug:index:built_at", "2026-11-01T00:00:00Z")
                    db.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                                   "VALUES (1, 'oasis', 'wonderwall', 'chords', 's1', '2026-11-01T00:00:00Z', 'tab/oasis/wonderwall')")
                }
                block(Phone(deps))
            }
        } finally {
            scope.cancel()
        }
    }

    private fun lookUp(phone: Phone, artist: String, title: String): Job = runBlocking {
        val spec = JobSpec("Get $artist - $title", io.github.danielhp95.caracole.core.keys.Normalize.identityKey(artist, title),
                           "song", emptyList(), commands = JobCommands.lookupSteps(artist, title), fetching = true)
        withTimeout(60_000) { phone.queue.await(phone.queue.submit(spec).first.id) }
    }

    private fun said(phone: Phone, job: Job): String = phone.parts.database.read { db ->
        val (id, facts) = io.github.danielhp95.caracole.server.jobs.SongFacts.ended(phone.queue).songOf(db, job, phone.parts.cards, java.time.Instant.now())
        val line = io.github.danielhp95.caracole.server.jobs.JobViews.line(job, facts = facts)
        "$line / ${io.github.danielhp95.caracole.server.jobs.Outcomes.outcome(job, line, facts, id)} / $facts / " +
            "${Songs.list(db).map { it.matchDecision to it.status }} / ${job.stages.map { it.name to it.state + ":" + it.detail }}"
    }

    private fun noted(phone: Phone, artist: String, title: String): String? = phone.parts.database.read { db ->
        val song = Songs.byKey(db, io.github.danielhp95.caracole.core.keys.Normalize.identityKey(artist, title))!!
        db.kvGet(Due.WANTED_PREFIX + song.id)
    }

    @Test fun aLookupNotOnTheSitesNotesItsSongAndTellsOnNoSheet() = phone { phone ->
        val told = AtomicInteger()
        phone.onNoSheet = { told.incrementAndGet() }
        val job = lookUp(phone, "Calla Lake", "River Road")
        assertEquals(Job.DONE, job.state, "${job.stages.map { it.name to it.detail }}")
        assertNotNull(noted(phone, "Calla Lake", "River Road"), said(phone, job))
        assertEquals(1, told.get())
        // Another song's lookup in between: each its own.
        assertEquals(Job.DONE, lookUp(phone, "Harbour Lights", "Paper Boats").state)
        assertNotNull(noted(phone, "Harbour Lights", "Paper Boats"))
        assertEquals(2, told.get())
        assertEquals(2L, phone.parts.database.read { db ->
            db.one("SELECT COUNT(*) FROM kv WHERE key LIKE 'youtube-wanted:%'") { it.long(0) }
        })
    }

    @Test fun aLookupOfASongThatKeepsASheetNotesNothing() = phone { phone ->
        val told = AtomicInteger()
        phone.onNoSheet = { told.incrementAndGet() }
        phone.parts.database.writeBlocking { db ->
            val song = phone.parts.store.add(db, "Calla Lake", "River Road", now = Stamps.now())
            val v = Versions.upsert(db, "ug", "101", song.id, "sheet", "chords", 4.8, 120, 1, null,
                                    "https://tabs.ultimate-guitar.com/tab/x", kotlinx.serialization.json.JsonObject(emptyMap()),
                                    Stamps.now())
            Kept.keepFile(db, phone.parts.store, song, v, "sheet.txt", "[ch]G[/ch]\nHi".toByteArray(), 1, Stamps.now())
            Versions.updateSong(db, song.id, mapOf("status" to "found", "match_decision" to "pinned"))
        }
        val job = lookUp(phone, "Calla Lake", "River Road")
        assertEquals(Job.DONE, job.state)
        assertTrue(Outcomes.NOT_ON_THE_SITES !in said(phone, job), said(phone, job))
        assertNull(noted(phone, "Calla Lake", "River Road"))
        assertEquals(0, told.get())
    }

    @Test fun aBuildWithNoYtDlpNotesNothing() = phone(youtube = null) { phone ->
        val told = AtomicInteger()
        phone.onNoSheet = { told.incrementAndGet() }
        val job = lookUp(phone, "Calla Lake", "River Road")
        assertEquals(Job.DONE, job.state)
        assertTrue(Outcomes.NOT_ON_THE_SITES in said(phone, job), "the lookup would note it with yt-dlp: ${said(phone, job)}")
        assertNull(noted(phone, "Calla Lake", "River Road"))
        assertEquals(0, told.get())
    }
}
