package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.PhoneDeps
import io.github.danielhp95.caracole.server.lookups.AudioRunner
import io.github.danielhp95.caracole.server.lookups.YouTubeSheetRunner
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.json
import io.github.danielhp95.caracole.server.testing.replays.YouTubeRoutesReplay
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import io.github.danielhp95.caracole.viewer.autochords.Heard
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** YouTube's routes on the phone: caracole serve's answers replayed (vectors/web/youtube_routes.jsonl,
 * YouTubeRoutesReplay), and on the phone whole, as the app assembles it: a form posted without its token or from
 * another site refused, an `/api/` read another site asks refused, and each reason of the design's §5.6 the page and
 * the routes say (a search's suggested video: YouTubeSearchTest). */
class YouTubeRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private lateinit var phone: Phone

    private object NoAddress : SyncSettings {
        override val address: String? = null
        override fun remember(address: String) = Unit
    }

    @Before fun up() {
        val database = TestDb.fresh(tmp.newFolder("db"))
        phone = Phone(PhoneDeps(database, tmp.newFolder("library"), tmp.newFolder("state"), null, scope, NoAddress,
                                TestApp.SECRET, TestApp.CSRF, transport = { RefusingTransport }, searchesLacuerda = false))
        database.writeBlocking { db -> phone.parts.store.add(db, "Nick Cani", "Vikingos veganos", now = Stamps.now()) }
    }

    @After fun down() {
        scope.cancel()
        phone.parts.database.close()
    }

    @Test fun everyAnswerIsCaracoleServes() {
        val misses = Misses("web")
        YouTubeRoutesReplay.replay(misses)
        misses.assertNone()
    }

    private val sameSite = mapOf("sec-fetch-site" to "same-origin", "origin" to "http://${TestApp.HOST}",
                                 "content-type" to "application/x-www-form-urlencoded", "accept" to "application/json")

    private fun post(path: String, fields: List<Pair<String, String>>, headers: Map<String, String?> = sameSite) =
        phone.app.handle(TestApp.request("POST", path, headers, TestApp.form(fields), TestApp.SECRET))

    /** Every form route of YouTube's is App's: without the form token, refused (403, the page's script told to reload),
     * nothing queued; from another site, refused (403). */
    @Test fun aFormWithoutItsTokenOrFromAnotherSiteIsRefused() {
        val video = "https://www.youtube.com/watch?v=lzN7Thn3FV4"
        for ((path, fields) in listOf("/youtube" to listOf("youtube" to video, "song" to "1"),
                                      "/youtube/video" to listOf("id" to "lzN7Thn3FV4"),
                                      "/youtube/search" to listOf("q" to "nick cani"),
                                      "/request" to listOf("youtube" to video, "artist" to "A", "title" to "T"))) {
            assertEquals(403, post(path, fields).status, "$path with no token")
            assertEquals(403, post(path, fields + ("csrf" to "not-the-token")).status, "$path with another token")
            val elsewhere = sameSite + ("sec-fetch-site" to "cross-site") + ("origin" to "https://evil.example")
            assertEquals(403, post(path, fields + ("csrf" to TestApp.CSRF), elsewhere).status, "$path from another site")
        }
        assertEquals(0, phone.queue.snapshot().size)
    }

    /** `GET /api/youtube/video` another site's fetch asks is refused, as every `/api/` read (App's own-page read). */
    @Test fun anApiReadAnotherSiteAsksIsRefused() {
        val asked = phone.app.handle(TestApp.request("GET", "/api/youtube/video?id=lzN7Thn3FV4",
                                                     mapOf("sec-fetch-site" to "cross-site"), ByteArray(0), TestApp.SECRET))
        assertEquals(403, asked.status)
        val own = phone.app.handle(TestApp.request("GET", "/api/youtube/video?id=lzN7Thn3FV4",
                                                   mapOf("sec-fetch-site" to "same-origin"), ByteArray(0), TestApp.SECRET))
        assertEquals(200, own.status)
        // this test's phone has no yt-dlp: the panel says so, nothing asked
        assertEquals("off", own.json.jsonObject.getValue("state").jsonPrimitive.content)
    }

    /** A pasted video's every link read to its id, as youtube_urls.video_id_from_url reads it; anything else 400. */
    @Test fun aPastedVideosEveryLinkIsReadToItsId() {
        fun read(query: String) = phone.app.handle(TestApp.request("GET", "/api/youtube/video$query",
                                                                   mapOf("sec-fetch-site" to "same-origin"), ByteArray(0),
                                                                   TestApp.SECRET))
        for (link in listOf("https://youtu.be/dQw4w9WgXcQ", "www.youtube.com/watch?v=dQw4w9WgXcQ&t=1",
                            "https://m.youtube.com/shorts/dQw4w9WgXcQ/", "https://music.youtube.com/embed/dQw4w9WgXcQ")) {
            val got = read("?url=" + java.net.URLEncoder.encode(link, Charsets.UTF_8))
            assertEquals("dQw4w9WgXcQ", got.json.jsonObject.getValue("id").jsonPrimitive.content, link)
        }
        for (bad in listOf("?id=short", "?url=https%3A%2F%2Fevil.example%2Fwatch%3Fv%3DdQw4w9WgXcQ", "", "?id=")) {
            assertEquals(400, read(bad).status, bad)
        }
    }

    /** The routes refuse where the phone makes no sheet from a video, in Phone.youtubeProblem's words. */
    @Test fun whereNoSheetCanBeMadeTheRoutesSayWhy() {
        val asked = post("/youtube", listOf("csrf" to TestApp.CSRF, "youtube" to "https://youtu.be/lzN7Thn3FV4",
                                            "song" to "1"))
        assertEquals(409, asked.status)
        assertEquals("No sheets from YouTube here: ${phone.youtubeProblem()}.",
                     asked.json.jsonObject.getValue("error").jsonPrimitive.content)
        assertEquals(0, phone.queue.snapshot().size)
    }

    private class Models(val why: String?) : ChordModels {
        override fun ready(): String? = why
        override fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard = error("not heard")
    }

    /** Each `why` of the design's §5.6, in its order: YouTube off in the computer's settings; the chords' reasons; no
     * yt-dlp; then, where nothing else stops it, YouTube cooling down; none at all, ok. */
    @Test fun eachWhyOfTheDesigns5point6() {
        val on = PhoneConfig.DEFAULTS
        val off = on.copy(providers = on.providers + ("youtube" to on.provider("youtube").copy(enabled = false)))
        val engine = object : io.github.danielhp95.caracole.core.youtube.YouTubeEngine {
            override fun ready(): String? = null
            override fun process() = error("no run")
            override fun gate() = error("no gate")
            override val qjs = File("/qjs")
            override val cacheDir = File("/cache")
        }
        assertEquals(YouTubeSheetRunner.OFF, YouTubeSheetRunner.problemOf(off, engine, Models(null), null))
        assertEquals(LibraryPageWords.AUDIO, YouTubeSheetRunner.problemOf(on, engine, null, null))
        assertEquals(AudioRunner.NOT_DOWNLOADED, YouTubeSheetRunner.problemOf(on, engine, Models(null), "not here"))
        assertEquals("chords from audio need Android 13 or later",
                     YouTubeSheetRunner.problemOf(on, engine, Models("chords from audio need Android 13 or later"), null))
        assertEquals(YouTubeSheetRunner.NO_YTDLP, YouTubeSheetRunner.problemOf(on, null, Models(null), null))
        assertNull(YouTubeSheetRunner.problemOf(on, engine, Models(null), null))
        val now = Instant.parse("2026-11-27T12:00:00Z")
        phone.parts.database.writeBlocking { db ->
            assertNull(YouTubeRoutes.offered(null, db, now))
            assertEquals("why", YouTubeRoutes.offered("why", db, now))
            Health.recordBlock(db, "youtube", now.minusSeconds(3600), "blocked")
            assertEquals("YouTube refused caracole; asked again after 2026-11-28 13:00 UTC", YouTubeRoutes.offered(null, db, now))
            assertEquals("why", YouTubeRoutes.offered("why", db, now), "the route's own reason first")
        }
    }

    /** The phone as built here offers no sheet from a video (no yt-dlp, no chords): its page says why and draws no
     * field; its member says YouTube is on in the computer's settings. */
    @Test fun thePagesMemberSaysWhatThisPhoneMakes() {
        val page = phone.app.handle(TestApp.request("GET", "/", mapOf("sec-fetch-site" to "same-origin"), ByteArray(0),
                                                    TestApp.SECRET))
        val html = page.bytes().toString(Charsets.UTF_8)
        val form = html.substringAfter("<form class=\"request-form\"").substringBefore("</form>")
        assertTrue("No sheets from YouTube here: ${phone.youtubeProblem()!!.replace("'", "&#x27;")}." in form, form)
        assertTrue("youtube-field" !in form, form)
    }

    /** A song whose audio is a file of its own given caracole (an upload: AudioStore's kept file, its `audio_path`) is
     * refused a sheet from a video, in `caracole youtube --sheet`'s words, nothing queued: an upload always wins. */
    @Test fun aSongWithAnUploadOfItsOwnIsRefusedASheetFromAVideo() {
        val store = io.github.danielhp95.caracole.core.library.AudioStore(phone.parts.stateDir,
                                                                           PhoneDeps.NO_EXAMINER)
        val kept = File(File(phone.parts.stateDir, "audio").apply { mkdirs() }, "1-0123456789abcdef.m4a")
        kept.writeBytes(ByteArray(64))
        phone.parts.database.writeBlocking { db ->
            io.github.danielhp95.caracole.core.library.Versions.updateSong(db, 1, mapOf("audio_path" to kept.path))
        }
        val song = phone.parts.database.read { db -> io.github.danielhp95.caracole.core.library.Songs.byId(db, 1)!! }
        assertEquals(kept.path, store.uploaded(song)?.path, "the store knows it as an upload")
        val routes = YouTubeRoutes(phone.parts, store, problem = { null })
        val refused = kotlin.runCatching {
            routes.sheetFromYoutube(mapOf("youtube" to "https://youtu.be/lzN7Thn3FV4", "song" to "1"))
        }.exceptionOrNull() as io.github.danielhp95.caracole.server.http.Refused
        assertEquals(409, refused.status)
        assertEquals("Nick Cani - Vikingos veganos has its own audio (bought or given); auto-chords uses that.", refused.message)
        assertEquals(0, phone.queue.snapshot().size)
    }

    /** The page's `server.youtube` as the phone assembles it: here no yt-dlp and no chords, so `ok` false with
     * Phone.youtubeProblem's why and YouTube on; the computer's settings turning YouTube off (a sync's) make it
     * "off", in the design's §5.6 words. */
    @Test fun thePhonesPageSaysServerYoutubeAndOffAsAssembled() {
        fun member(): Any? {
            val page = phone.app.handle(TestApp.request("GET", "/", mapOf("sec-fetch-site" to "same-origin"), ByteArray(0),
                                                        TestApp.SECRET)).bytes().toString(Charsets.UTF_8)
            val block = page.substringAfter("<script type=\"application/json\" id=\"songs\">").substringBefore("</script>")
            return kotlinx.serialization.json.Json.parseToJsonElement(block).jsonObject.getValue("server").jsonObject
                .getValue("youtube")
        }
        val why = phone.youtubeProblem()!!
        assertEquals(kotlinx.serialization.json.Json.parseToJsonElement(
            """{"ok": false, "why": ${kotlinx.serialization.json.JsonPrimitive(why)}, "off": false}"""), member())
        phone.parts.database.writeBlocking { db ->
            db.kvSet(PhoneConfig.SETTINGS_KV, """{"providers": {"youtube": {"enabled": false}}}""")
        }
        assertEquals(kotlinx.serialization.json.Json.parseToJsonElement(
            """{"ok": false, "why": ${kotlinx.serialization.json.JsonPrimitive(YouTubeSheetRunner.OFF)}, "off": true}"""),
            member())
    }

    private object LibraryPageWords {
        const val AUDIO = io.github.danielhp95.caracole.server.page.LibraryPage.AUDIO_PROBLEM
    }

    private fun io.github.danielhp95.caracole.server.http.Response.bytes(): ByteArray =
        (body as io.github.danielhp95.caracole.server.http.Body.Bytes).bytes
}
