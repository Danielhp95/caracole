package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.MessagePage
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.page.PhonePageData
import io.github.danielhp95.caracole.server.routes.share.AudioSharePage
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.text
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * An audio file shared to the app (the chords-on-the-phone design's §8.2), as ShareActivity hands it to the server:
 * staged through AudioRoutes.stageShared (a stream read once, never held whole), then ShareRoutes' `GET /share/audio`:
 * the file, the guess its tags give, the library's song of it and its sheet, the note where its sheet has words heard
 * on the computer, Make sheet (the library page's `POST /audio`, which queues `caracole audio --upload=ID`) and Cancel
 * (`POST /share/audio/cancel`: the upload dropped, the share left); where the phone makes no sheet, why, naming
 * Settings, and nothing staged.
 */
class AudioSharePageTest {
    @get:Rule val tmp = TemporaryFolder()

    private val queue = JobQueue(CoroutineScope(Job().apply { cancel() }))
    private var problem: String? = null
    private lateinit var app: TestApp
    private lateinit var audio: AudioRoutes
    private lateinit var store: LibraryStore

    /** Every file read as an MP3 of 3:18 tagged Calla Lake - River Road (the app's examiner reads Android's tags). */
    private val examiner = AudioStore.Examiner { _, format ->
        AudioStore.Audio(format, 198.4, mapOf("artist" to listOf("Calla Lake"), "title" to listOf("River Road"),
                                              "album" to listOf("Shores")))
    }

    private fun phone(): TestApp {
        val dir = tmp.newFolder()
        val state = File(dir, "state")
        app = TestApp(dir, modules = { database ->
            store = LibraryStore(File(dir, "library"), File(state, AudioStore.FOLDER))
            val config = { database.read { PhoneConfig.read(it) } }
            val cards = PhonePageData(MirrorPageData(null), store)
            val parts = PhoneParts(database, store, state, config, queue, cards,
                                   { Clients(config(), File(state, "cache"), { RefusingTransport }, Pacing.REAL) },
                                   SongPages.NONE, SongbookPages.NONE, Alerts.NONE, Pacing.REAL, searchesLacuerda = false)
            audio = AudioRoutes(parts, AudioStore(state, examiner), { problem })
            listOf(audio, ShareRoutes(database, SearchRoutes(database, cards), TestApp.CSRF, audio = audio))
        })
        return app
    }

    @After fun down() {
        if (::app.isInitialized) app.close()
    }

    private val mp3 = "ID3".toByteArray() + ByteArray(4096)

    private fun shared(name: String = "River Road.mp3"): AudioStore.Staged = audio.stageShared(mp3.inputStream(), name)

    private fun staged(): List<String> =
        File(File(app.libraryDir.parentFile, "state"), AudioStore.FOLDER).list().orEmpty().filter { it.startsWith(".upload-") }
            .filter { !it.endsWith(".json") }

    private fun page(response: Response): String {
        assertEquals(200, response.status, response.text)
        assertEquals(MessagePage.HTML, response.header("Content-Type"))
        assertEquals(MessagePage.csp, response.header("Content-Security-Policy"), "no script, the style by its hash")
        return response.text.substringAfter("</header>")
    }

    /** The fields of the form posting to [action], hidden or typed, in order. */
    private fun form(html: String, action: String): List<Pair<String, String>> {
        val form = Regex("""<form[^>]*action="$action"[^>]*>(.*?)</form>""", RegexOption.DOT_MATCHES_ALL).find(html)
            ?: throw AssertionError("no form to $action: $html")
        return Regex("""<input (?:type="hidden" )?name="([^"]*)" value="([^"]*)"""").findAll(form.groupValues[1])
            .map { it.groupValues[1] to it.groupValues[2].replace("&amp;", "&") }.toList()
    }

    private fun song(artist: String, title: String): SongRow =
        app.database.writeBlocking { db -> store.add(db, artist, title, now = "2026-11-27T00:00:00Z") }

    @Test fun `a shared MP3 gives the page with its guess, and Make sheet queues the audio job`() {
        val app = phone()
        val up = shared()
        val html = page(app.get("/share/audio?upload=${up.id}"))
        assertTrue("<p class=\"lede\"><strong>River Road.mp3</strong> · MP3 · 3:18</p>" in html, html)
        val make = form(html, "/audio")
        assertEquals(listOf("csrf" to TestApp.CSRF, "upload" to up.id, "artist" to "Calla Lake", "title" to "River Road"),
                     make)
        assertTrue(">Make sheet</button>" in html, html)
        assertFalse("In your library" in html, "a song the library hasn't got")
        assertEquals(listOf("csrf" to TestApp.CSRF, "upload" to up.id), form(html, AudioSharePage.CANCEL))

        // Make sheet, as the WebView posts the form: the job queued, its line on the Journal.
        val answer = app.post("/audio", make.drop(1))
        assertEquals(303, answer.status, answer.text)
        val location = assertNotNull(answer.header("Location"))
        assertTrue(location.startsWith("/#tab=requests&job="), location)
        val job = assertNotNull(queue.job(location.substringAfterLast('=').toInt()))
        assertEquals(listOf("audio", "--progress", "--upload=${up.id}", "--song=Calla Lake - River Road"),
                     job.steps.single().args)
        assertEquals(setOf(up.id), JobCommands.uploadsNamed(queue.snapshot()))
    }

    @Test fun `Cancel drops the file and leaves the share, but never a file its sheet is queued from`() {
        val app = phone()
        val up = shared()
        val answer = app.post(AudioSharePage.CANCEL, listOf("upload" to up.id))
        assertEquals(303, answer.status, answer.text)
        assertEquals("/share/cancel", answer.header("Location"))
        assertEquals(emptyList<String>(), staged())
        // Cancel again (a page reloaded): the share is left all the same.
        assertEquals(303, app.post(AudioSharePage.CANCEL, listOf("upload" to up.id)).status)

        val queued = shared()
        assertEquals(303, app.post("/audio", listOf("upload" to queued.id, "artist" to "Calla Lake",
                                                    "title" to "River Road")).status)
        val refused = app.post(AudioSharePage.CANCEL, listOf("upload" to queued.id))
        assertEquals(409, refused.status, refused.text)
        assertTrue(AudioRoutes.WAITS in refused.text, refused.text)
        assertEquals(1, staged().size)
        assertEquals(403, app.post(AudioSharePage.CANCEL, listOf("upload" to queued.id), token = "forged").status)
    }

    @Test fun `the library's song of the guess is named with its sheet, and words heard on the computer are said`() {
        val app = phone()
        val song = song("Calla Lake", "River Road")
        var html = page(app.get("/share/audio?upload=${shared().id}"))
        assertTrue("In your library: <strong>Calla Lake - River Road</strong> · no sheet yet." in html, html)
        assertFalse(AudioSharePage.HEARD in html)

        // An auto sheet the computer made over a transcript: made again here, with no words heard.
        app.database.writeBlocking { db ->
            val raw = JsonObject(mapOf("lyrics" to JsonPrimitive("synced"), "lyrics_source" to JsonPrimitive("transcript")))
            val v = Versions.upsert(db, "auto", song.id.toString(), song.id, "sheet", "auto", 0.0, 0, 1, null,
                                    "file:///x.mp3", raw, "2026-11-27T00:00:00Z")
            Kept.keepFile(db, store, song, v, "sheet (auto).txt", "[Am]la".toByteArray(), 1, "2026-11-27T00:00:00Z")
        }
        html = page(app.get("/share/audio?upload=${shared().id}"))
        assertTrue("In your library: <strong>Calla Lake - River Road</strong> · its auto sheet is made again from " +
                       "this file." in html, html)
        assertTrue("<p class=\"message\">${AudioSharePage.HEARD}</p>" in html, html)
        assertEquals("Its sheet now has words heard on the computer. A sheet made here has words only where a lyrics " +
                         "site has them.", AudioSharePage.HEARD)

        // A sheet of the sites: said, and Make sheet under those names refused as caracole audio refuses it.
        app.database.writeBlocking { db ->
            val v = Versions.upsert(db, "ug", "1", song.id, "sheet", "chords", 4.5, 10, 1, null, "https://x/1",
                                    JsonObject(emptyMap()), "2026-11-27T00:00:00Z")
            Kept.keepFile(db, store, song, v, "sheet.txt", "[C]sites".toByteArray(), 1, "2026-11-27T00:00:00Z")
        }
        val up = shared()
        html = page(app.get("/share/audio?upload=${up.id}"))
        assertTrue("· it has a sheet from the sites: a sheet from an audio file is for a song with none." in html, html)
        val refused = app.post("/audio", form(html, "/audio").drop(1))
        assertEquals(409, refused.status, refused.text)
    }

    @Test fun `where the phone makes no sheet, the page says why and nothing is staged`() {
        val app = phone()
        problem = "the chord models aren't downloaded (Settings › Chords from audio)"
        val refused = assertFailsWith<Refused> { shared() }
        assertEquals(409, refused.status)
        assertEquals(emptyList<String>(), staged())
        val html = page(app.get("/share/audio?name=River%20Road.mp3"))
        assertTrue("<strong>River Road.mp3</strong>" in html, html)
        assertTrue("<p class=\"message\">No sheets from audio files here: the chord models aren&#x27;t downloaded " +
                       "(Settings › Chords from audio).</p>" in html, html)
        assertFalse("action=\"/audio\"" in html, "no Make sheet")
        assertTrue("<a class=\"btn\" href=\"/share/cancel\">Cancel</a>" in html, html)
    }

    @Test fun `an upload no longer staged says so in the store's words`() {
        val app = phone()
        val up = shared()
        shared("Another.mp3")  // a second share lets go of the first, no job naming it
        val html = page(app.get("/share/audio?upload=${up.id}"))
        assertTrue(AudioStore.WORDS.getValue("gone") in html, html)
        assertFalse("action=\"/audio\"" in html)
    }
}
