package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Test
import java.security.MessageDigest
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** The phone's library page is caracole serve's for the same data and controls, its Requests tab counted and its
 * sync the sheet alone (the vector's "sheet" cases; its "tab" cases are caracole serve's alone), byte for byte
 * (tests/conformance/vectors/web/library_page.json, vectors/web/requests.jsonl's tabs). */
class LibraryPageTest {
    private val vector = Corpus.json("web/library_page.json")
    private val page = LibraryPage(LibraryAssets.load())
    private val name = vector.getValue("library_name").jsonPrimitive.content

    /** A case's sync as the phone serves it: "sheet" the sheet, null none; null for "tab", which it never serves. */
    private fun sheet(of: JsonObject): Boolean? = when (val sync = of.getValue("sync")) {
        is JsonNull -> false
        else -> if (sync.jsonPrimitive.content == "sheet") true else null
    }

    private fun controls(of: JsonObject) = ServerControls(
        csrf = of.getValue("csrf").jsonPrimitive.content,
        badge = of.getValue("badge").let { if (it is JsonNull) null else it.jsonPrimitive.content },
        sync = sheet(of) ?: throw AssertionError("the phone never serves the Sync tab"),
        active = of.getValue("active").jsonPrimitive.int,
        inApp = of.getValue("in_app").jsonPrimitive.boolean,
    )

    private fun sha256(text: String) =
        MessageDigest.getInstance("SHA-256").digest(text.toByteArray()).joinToString("") { "%02x".format(it) }

    private val cases get() = vector.getValue("cases").jsonArray.map { it.jsonObject }

    /** The cases the phone serves: every one but caracole serve's Sync tab. */
    private val phones get() = cases.filter { sheet(it.getValue("controls").jsonObject) != null }

    @Test fun `the app's page has no library-name row and keeps its title`() {
        val made = page.served(mirroredData(emptyList()), ServerControls("tok", inApp = true), "Tabs")
        assertFalse("class=\"libname\"" in made)
        assertTrue("<title>Phone · caracole · Tabs</title>" in made)
    }

    @Test
    fun `the request form's reason for no sheet from YouTube is the vector's`() {
        assertEquals(vector.getValue("youtube_problem").jsonPrimitive.content, LibraryPage.YOUTUBE_PROBLEM)
    }

    @Test
    fun `the server's member is build_library_page's for the same controls`() {
        val server = vector.getValue("server").jsonObject
        val of = server.getValue("controls").jsonObject
        fun ids(name: String) = of.getValue(name).jsonArray.map { it.jsonPrimitive.long }.toSet()
        val controls = ServerControls(
            csrf = of.getValue("csrf").jsonPrimitive.content, busy = ids("busy"), active = of.getValue("active").jsonPrimitive.int,
            held = ids("held"), removing = ids("removing"), jobs = of.getValue("jobs").jsonArray.map { it.jsonObject },
        )
        val member = page.withServer(mirroredData(emptyList()), controls).getValue("server").jsonObject
        assertEquals(server.getValue("member"), member)
        assertEquals(listOf("csrf", "busy", "active", "removing", "jobs", "guitar", "youtube", "transcribe", "audio",
                            "lyricsSearch"),
                     member.keys.toList())
        assertEquals(JsonPrimitive(true), member.getValue("lyricsSearch"))  // lyrics searched under a name: LyricsRoutes
        assertEquals(listOf("ok", "why", "off"), member.getValue("youtube").jsonObject.keys.toList())
        assertEquals(listOf("ok", "why", "songs", "nothing", "unsung", "transcribed", "time"),
                     member.getValue("transcribe").jsonObject.keys.toList())
        assertEquals(obj("ok" to false, "why" to LibraryPage.AUDIO_PROBLEM, "limit" to 0, "too_big" to ""),
                     member.getValue("audio"))
    }

    @Test
    fun `where the phone makes sheets from audio files its server's audio is caracole serve's that does`() {
        val python = io.github.danielhp95.caracole.core.testing.Corpus.records("web/audio_routes.jsonl")
            .single { it.fn == "caracole.library_page.audio_member" }.out
        val member = page.withServer(mirroredData(emptyList()), ServerControls("tok", audio = null))
            .getValue("server").jsonObject.getValue("audio")
        assertEquals(python, member)
        assertEquals(listOf("ok", "why", "limit", "too_big"), member.jsonObject.keys.toList())
    }

    @Test
    fun `where it doesn't its server's audio says why, each of the design's reasons`() {
        for (why in listOf("the chord models aren't downloaded (Settings › Chords from audio)",
                           "chords from audio need Android 13 or later", "no chord models for this phone's processor",
                           "chords from audio need 6 GB of memory or more", LibraryPage.AUDIO_PROBLEM)) {
            val member = page.withServer(mirroredData(emptyList()), ServerControls("tok", audio = why))
                .getValue("server").jsonObject.getValue("audio")
            assertEquals(obj("ok" to false, "why" to why, "limit" to 0, "too_big" to ""), member, why)
        }
    }

    @Test
    fun `the served page gives its script the audio member the "+" is drawn from`() {
        val made = page.served(page.withServer(mirroredData(emptyList()), ServerControls("tok", audio = null)),
                               ServerControls("tok", audio = null), "Tabs")
        val data = Regex("""<script type="application/json" id="songs">(.*?)</script>""", RegexOption.DOT_MATCHES_ALL)
            .find(made)!!.groupValues[1]
        val audio = kotlinx.serialization.json.Json.parseToJsonElement(data).jsonObject.getValue("server").jsonObject
            .getValue("audio").jsonObject
        assertEquals(JsonPrimitive(true), audio.getValue("ok"))
        // library.js draws the bar's "+" (#add-audio) where server.audio.ok is true: its script is the page's own
        assertTrue("server.audio.ok === true" in made && "plus.id = \"add-audio\"" in made)
    }

    @Test
    fun `the server's part goes where caracole serve puts it, before the songbooks`() {
        val data = mirroredData(listOf(mirroredCard(3, "a/x", "A", "X"), mirroredCard(-1, "b/y", "B", "Y")))
        val controls = ServerControls("tok", busy = setOf(9L, 3L), active = 2, held = setOf(3L), removing = setOf(5L),
                                      jobs = listOf(obj("id" to 1, "kind" to "sync")))
        val served = page.withServer(data, controls)
        assertEquals(listOf("generated", "fold", "songs", "icons", "catalogue", "server", "songbooks", "sites"), served.keys.toList())
        assertEquals(obj("csrf" to "tok", "busy" to listOf(3, 9), "active" to 2, "removing" to listOf(5),
                         "jobs" to listOf(obj("id" to 1, "kind" to "sync")), "guitar" to false,
                         "youtube" to obj("ok" to false, "why" to LibraryPage.YOUTUBE_PROBLEM, "off" to true),
                         "transcribe" to obj("ok" to false, "why" to LibraryPage.TRANSCRIBE_PROBLEM,
                                             "songs" to emptyList<Int>(), "nothing" to emptyList<Int>(),
                                             "unsung" to emptyList<Int>(), "transcribed" to emptyList<Int>(),
                                             "time" to ""),
                         "audio" to obj("ok" to false, "why" to LibraryPage.AUDIO_PROBLEM, "limit" to 0,
                                        "too_big" to ""),
                         "lyricsSearch" to true),
                     served.getValue("server"))
        for (name in data.keys - "songs") assertEquals(data.getValue(name), served.getValue(name), name)
    }

    @Test
    fun `a song is fetchable unless a review comes first or the phone hasn't got it, its fields as they were`() {
        val cards = listOf(mirroredCard(3, "a/x", "A", "X"), mirroredCard(4, "c/z", "C", "Z", "fetchable" to true),
                           mirroredCard(-1, "b/y", "B", "Y"))
        val served = page.withServer(mirroredData(cards), ServerControls("tok", held = setOf(4L)))
        val songs = served.getValue("songs").jsonArray.map { it.jsonObject }
        assertEquals(listOf(true, false, false), songs.map { it.getValue("fetchable").jsonPrimitive.boolean })
        assertEquals(cards[0].keys.toList() + "fetchable", songs[0].keys.toList(), "added at its end")
        assertEquals(cards[1].keys.toList(), songs[1].keys.toList(), "set in its place")
        assertEquals(cards[0], JsonObject(songs[0] - "fetchable"))
    }

    @Test
    fun `the tests' timers go to the page, and none otherwise`() {
        val data = mirroredData(emptyList())
        val timed = page.withServer(data, ServerControls("tok", timers = linkedMapOf("poll" to 50, "undo" to 200)))
        assertEquals(obj("poll" to 50, "undo" to 200), timed.getValue("server").jsonObject.getValue("timers"))
        assertFalse("timers" in page.withServer(data, ServerControls("tok")).getValue("server").jsonObject)
        val noBooks = page.withServer(JsonObject(data - "songbooks" - "sites"), ServerControls("tok"))
        assertEquals("server", noBooks.keys.last(), "last, with nothing for it to go before")
    }

    @Test
    fun `the page's policy is caracole serve's served page's`() {
        assertEquals(vector.getValue("csp").jsonPrimitive.content, page.csp)
    }

    @Test
    fun `the phone's page is the sheet case byte for byte`() {
        val case = cases.first()
        assertEquals(JsonPrimitive("sheet"), case.getValue("controls").jsonObject.getValue("sync"))
        val made = page.served(case.getValue("data").jsonObject, controls(case.getValue("controls").jsonObject), name)
        val expected = case.getValue("page").jsonPrimitive.content
        if (made != expected) {
            val at = made.indices.firstOrNull { it >= expected.length || made[it] != expected[it] } ?: expected.length
            throw AssertionError("the page differs from Python's at $at: …${made.substring(maxOf(0, at - 80), minOf(made.length, at + 80))}…")
        }
        assertEquals(case.getValue("sha256").jsonPrimitive.content, sha256(made))
    }

    @Test
    fun `every case the phone serves has Python's SHA-256`() {
        assertTrue(phones.size >= 4 && phones.size < cases.size, "caracole serve's Sync tab is a case of its own")
        for (case in phones) {
            val made = page.served(case.getValue("data").jsonObject, controls(case.getValue("controls").jsonObject), name)
            assertEquals(case.getValue("sha256").jsonPrimitive.content, sha256(made), case.getValue("name").jsonPrimitive.content)
        }
    }

    @Test
    fun `the sync is its sheet as it is, where the controls have it, never the Sync tab, and the Requests tab always`() {
        val assets = page.assets
        val data = cases.first().getValue("data").jsonObject
        val on = page.served(data, ServerControls("tok", sync = true), name)
        val off = page.served(data, ServerControls("tok", sync = false), name)
        val markup = { text: String -> text.substringBefore("<script type=\"application/json\"") }
        assertEquals(1, markup(on).split(assets.template("sync-sheet.html")).size - 1)
        assertFalse(assets.template("sync-sheet.html") in off)
        for (made in listOf(on, off)) {
            assertFalse(assets.template("sync-tab.html") in made || assets.template("sync-panel.html") in made)
            assertFalse("id=\"tab-sync\"" in markup(made))
            assertEquals(1, markup(made).split("id=\"tab-requests\"").size - 1)
            assertEquals(1, markup(made).split(page.requests.panel).size - 1)
        }
        assertFalse("__" + "SYNC__" in markup(off) || "__" + "REQUESTS__" in markup(on), "no blank left")
    }

    @Test
    fun `the Requests tab counts the requests that wait or run as library_page's tab does, none for none`() {
        val tabs = Corpus.records("web/requests.jsonl").filter { it.fn == "caracole.library_page._requests_tab" }
        assertTrue(tabs.size >= 5)
        for (r in tabs) {
            val active = r.extra.getValue("active").jsonPrimitive.int
            assertEquals(r.out!!.jsonPrimitive.content, page.requests.tab(active), "$active")
            val made = page.served(cases.first().getValue("data").jsonObject, ServerControls("tok", active = active), name)
            assertTrue(r.out!!.jsonPrimitive.content in made, "$active")
        }
        assertTrue("Journal <span class=\"n\"></span>" in page.requests.tab(0))
    }
}
