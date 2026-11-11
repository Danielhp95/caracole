package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.http.TransportError
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.PhoneDeps
import io.github.danielhp95.caracole.server.http.MessagePage
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.text
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.net.URLEncoder
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * The page of a song shared to the app (`GET /share`), over the phone as the app assembles it and the search corpus's
 * `ug` fixture (your Radiohead - Creep, found; the index's Eagles - Hotel California and Radiohead - Karma Police, not
 * yours): what it read, the best match, Get it as the library page's `POST /lookup`, Open, Edit and Cancel; no tab
 * site asked for any of it; and a link alone of Spotify's, Apple Music's or YouTube Music's read by asking its
 * service once (the answers each gave caracole on 2026-11-10, tests/fixtures/spotify/, itunes/, youtube/), its
 * failures said in one line.
 */
class ShareRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val asked = AtomicInteger()
    private var phone: Phone? = null

    private object NoAddress : SyncSettings {
        override val address: String? = null
        override fun remember(address: String) = Unit
    }

    /** The phone over [fixture] (none: an empty database), every request to a site counted, and refused but those
     * [sites] answers ("GET url" to its answer). */
    private fun phone(fixture: String? = "ug", sites: Map<String, HttpAnswer> = emptyMap()): Phone {
        val database = TestDb.fresh(tmp.newFolder())
        if (fixture != null) database.writeBlocking { Fixtures.load(it, "search/fixtures/$fixture.jsonl") }
        val counting = Transport { request ->
            asked.incrementAndGet()
            sites["${request.method} ${request.url}"]
                ?: throw TransportError("refused", "no site in a test: ${request.url}")
        }
        return Phone(PhoneDeps(database, tmp.newFolder(), tmp.newFolder(), null, scope, NoAddress, TestApp.SECRET,
                               TestApp.CSRF, transport = { counting }, searchesLacuerda = false)).also { phone = it }
    }

    @After fun down() {
        scope.cancel()
        phone?.parts?.database?.close()
    }

    private fun Phone.get(target: String): Response =
        app.handle(TestApp.request("GET", target, mapOf("sec-fetch-site" to "none"), ByteArray(0), TestApp.SECRET))

    private fun Phone.post(target: String, fields: List<Pair<String, String>>): Response = app.handle(TestApp.request(
        "POST", target,
        mapOf("sec-fetch-site" to "same-origin", "origin" to "http://${TestApp.HOST}",
              "content-type" to "application/x-www-form-urlencoded"),
        TestApp.form(fields), TestApp.SECRET,
    ))

    private fun share(vararg fields: Pair<String, String>): String =
        "/share?" + fields.joinToString("&") { (k, v) -> k + "=" + URLEncoder.encode(v, Charsets.UTF_8) }

    /** The page's text, its HTML entities read back where the test compares words. */
    private fun page(response: Response): String {
        assertEquals(200, response.status, response.text)
        assertEquals(MessagePage.HTML, response.header("Content-Type"))
        assertEquals(MessagePage.csp, response.header("Content-Security-Policy"), "no script, the style by its hash")
        return response.text
    }

    /** The page under its header, as a failure says it. */
    private fun shown(html: String): String = html.substringAfter("</header>")

    /** The hidden fields of each form posting to [action], in order. */
    private fun forms(html: String, action: String): List<List<Pair<String, String>>> =
        Regex("""<form[^>]*action="$action"[^>]*>(.*?)</form>""", RegexOption.DOT_MATCHES_ALL).findAll(html).map { form ->
            Regex("""<input type="hidden" name="([^"]*)" value="([^"]*)">""").findAll(form.groupValues[1])
                .map { it.groupValues[1] to unescape(it.groupValues[2]) }.toList()
        }.toList()

    private fun unescape(s: String) = s.replace("&quot;", "\"").replace("&#x27;", "'").replace("&lt;", "<")
        .replace("&gt;", ">").replace("&amp;", "&")

    @Test fun `a text naming an index's song shows it the best match, and Get it queues the library page's lookup`() {
        val phone = phone()
        val html = page(phone.get(share("text" to "Eagles - Hotel California https://example.com/x?si=1")))
        assertTrue("We read <strong>Eagles – Hotel California</strong>." in html, shown(html))
        assertTrue("<h2 class=\"sub\">Best match</h2>" in html, shown(html))
        assertTrue("UG: chords ×1" in html, shown(html))
        assertFalse("In your logbook" in html.substringAfter("Best match").substringBefore("</ul>"), "not yours")
        val getIt = forms(html, "/lookup").first()
        assertEquals(listOf("csrf" to TestApp.CSRF, "artist" to "Eagles", "title" to "Hotel California",
                            "ug" to "eagles/hotel-california"), getIt)
        assertEquals(0, asked.get(), "the page asks no site")

        // Get it, as the WebView posts the form: the library page's lookup, its line in the Requests tab.
        val answer = phone.post("/lookup", getIt)
        assertEquals(303, answer.status, answer.text)
        val location = assertNotNull(answer.header("Location"))
        assertTrue(location.startsWith("/#tab=requests&job="), location)
        val job = assertNotNull(phone.queue.job(location.substringAfterLast('=').toInt()))
        assertEquals(JobCommands.lookupSteps("Eagles", "Hotel California", ug = "eagles/hotel-california").map { it.args },
                     job.steps.map { it.args })
    }

    @Test fun `a Deezer share is read by Deezer's words, its app by its link`() {
        val phone = phone()
        val html = page(phone.get(share("text" to "I've found a song for you... Hotel California by Eagles \uD83D\uDD25 Listen now " +
                                                  "on #Deezer https://link.deezer.com/s/34URX4HSZ3LKo4ZRnW3Sm")))
        assertTrue("<h1>Shared from Deezer</h1>" in html, shown(html))
        assertTrue("We read <strong>Eagles – Hotel California</strong>." in html, shown(html))
        val best = html.substringAfter("Best match").substringBefore("</ul>")
        assertEquals("eagles/hotel-california", forms(best, "/lookup").single().toMap()["ug"])
        assertEquals(0, asked.get())
    }

    @Test fun `your song is the best match, in your library, with Open and Get it again by its id`() {
        val phone = phone()
        val html = page(phone.get(share("text" to "Radiohead - Creep", "from" to "org.example.player")))
        assertTrue("A shared song" in html, "an app caracole doesn't know")
        val best = html.substringAfter("Best match").substringBefore("</ul>")
        assertTrue("Radiohead - Creep" in best, best)
        assertTrue("In your logbook" in best, best)
        assertTrue("href=\"/#song=1\"" in best, "its line in the library, with no page on the phone: $best")
        assertTrue(">Fetch again</button>" in best, best)
        assertEquals(listOf("csrf" to TestApp.CSRF, "song" to "1", "ug" to "radiohead/creep"), forms(best, "/lookup").single())
    }

    @Test fun `a link alone of a service caracole doesn't ask names no song, and nothing is searched or asked`() {
        val phone = phone()
        val html = page(phone.get(share("text" to "https://link.deezer.com/s/34URX4HSZ3LKo4ZRnW3Sm", "from" to "deezer.android.app")))
        assertTrue("<h1>Shared from Deezer</h1>" in html, shown(html))
        assertTrue("Deezer shared a bare link, no song named: <code>https://link.deezer.com/s/34URX4HSZ3LKo4ZRnW3Sm" +
                       "</code>. We don't ask Deezer." in html, shown(html))
        assertTrue("<details class=\"picker\" open><summary class=\"btn\">Edit</summary>" in html, "Edit, open")
        assertFalse("Best match" in html)
        assertEquals(emptyList(), forms(html, "/lookup"), "no Get it without names")
        assertTrue("<a class=\"btn\" href=\"/share/cancel\">Cancel</a>" in html)
        assertEquals(0, asked.get())
    }

    private val spotifyTrack = "https://open.spotify.com/track/4u7EnebtmKWzUH433cf5Qv"
    private val spotifyPage = HttpAnswer(200, listOf("content-type" to "text/html; charset=utf-8"),
                                         Corpus.fixture("spotify/track.html"))

    @Test fun `a Spotify link alone is read from its page, asked once, and Get it looks up its names`() {
        val phone = phone(sites = mapOf("GET $spotifyTrack" to spotifyPage))
        val target = share("text" to "$spotifyTrack?si=0f3c1c4d5e6f4a7b", "from" to "com.spotify.music")
        val html = unescape(page(phone.get(target)))
        assertTrue("<h1>Shared from Spotify</h1>" in html, shown(html))
        assertTrue("Read from Spotify's page: <strong>Queen – Bohemian Rhapsody</strong>." in html, shown(html))
        assertTrue("<li>Spotify's page: <code>Queen – Bohemian Rhapsody - Remastered 2011</code></li>" in html, shown(html))
        assertEquals(listOf(listOf("csrf" to TestApp.CSRF, "artist" to "Queen", "title" to "Bohemian Rhapsody")),
                     forms(html, "/lookup"), "Get it by the names the page gave")
        assertTrue("name=\"artist\" value=\"Queen\"" in html && "name=\"title\" value=\"Bohemian Rhapsody\"" in html)
        assertEquals(1, asked.get(), "one request: the track's page")
        val events = phone.parts.database.read { db ->
            db.query("SELECT run, provider, decision FROM events") { r -> Triple(r.text(0), r.text(1), r.text(2)) }
        }
        assertEquals(listOf("spotify" to "ok"), events.map { it.second to it.third })
        assertTrue(events.single().first!!.startsWith("lookup:share:"), "a lookup's run: the hour's lookup_per_hour counts it")
        // The page loaded again, or the link shared again: the cache's answer, no request.
        assertEquals(html, unescape(page(phone.get(target))))
        assertEquals(1, asked.get())
    }

    @Test fun `an album's link names no song, said with no request`() {
        val phone = phone()
        val html = page(phone.get(share("text" to "https://open.spotify.com/album/1GbtB4zTqAsyfZEsm1RZfx?si=1")))
        assertTrue("Spotify shared a link that names no song (<code>https://open.spotify.com/album/1GbtB4zTqAsyfZEsm1RZfx?si=1" +
                       "</code>): a link to an album. Type the artist and the title." in html, shown(html))
        assertTrue("<details class=\"picker\" open><summary class=\"btn\">Edit</summary>" in html, "Edit, open")
        assertEquals(0, asked.get())
    }

    @Test fun `a service that fails is said in one line, Edit open, and nothing read as a miss`() {
        val phone = phone()
        val html = page(phone.get(share("text" to "$spotifyTrack?si=0f3", "from" to "com.spotify.music")))
        assertTrue("Spotify shared a link alone (<code>$spotifyTrack?si=0f3</code>), and caracole couldn't read it: asking " +
                       "Spotify failed (refused: no site in a test: $spotifyTrack). Type the artist and the title, or share " +
                       "it again later." in html, shown(html))
        assertTrue("<details class=\"picker\" open><summary class=\"btn\">Edit</summary>" in html, "Edit, open")
        assertEquals(emptyList(), forms(html, "/lookup"))
        assertEquals(1, asked.get())
        assertFalse("names no song" in html, "an error is no answer")
    }

    @Test fun `a service turned off on the computer is asked nothing`() {
        val phone = phone(sites = mapOf("GET $spotifyTrack" to spotifyPage))
        phone.parts.database.writeBlocking { db ->
            db.kvSet(PhoneConfig.SETTINGS_KV, """{"providers": {"spotify": {"enabled": false}}}""")
        }
        val html = unescape(page(phone.get(share("text" to spotifyTrack))))
        assertTrue("caracole couldn't read it: reading Spotify's links is off ([providers.spotify] enabled = false in the " +
                       "computer's caracole.toml, which the phone took at its last sync)." in html, shown(html))
        assertEquals(0, asked.get())
    }

    @Test fun `an Apple Music link is read from Apple's catalogue, a YouTube Music one from its video's title and channel`() {
        val apple = "https://itunes.apple.com/lookup?id=1440833334&country=us"
        val oembed = "https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DfJ9rUzIMcZQ&format=json"
        val phone = phone(sites = mapOf(
            "GET $apple" to HttpAnswer(200, emptyList(), Corpus.fixture("itunes/lookup-song.json")),
            "GET $oembed" to HttpAnswer(200, emptyList(), Corpus.fixture("youtube/oembed.json")),
        ))
        val am = unescape(page(phone.get(share("text" to "https://music.apple.com/us/album/love-me-do/1440833098?i=1440833334"))))
        assertTrue("<h1>Shared from Apple Music</h1>" in am, shown(am))
        assertTrue("Read from Apple Music's catalogue: <strong>The Beatles – Love Me Do</strong>." in am, shown(am))
        val ytm = unescape(page(phone.get(share("text" to "https://music.youtube.com/watch?v=fJ9rUzIMcZQ&si=Qx1",
                                                "from" to "com.google.android.apps.youtube.music"))))
        assertTrue("Read from the video's title on YouTube Music: <strong>Queen – Bohemian Rhapsody</strong>." in ytm, shown(ytm))
        assertTrue("<li>The video's title on YouTube Music: <code>Queen – Bohemian Rhapsody (Official Video Remastered), " +
                       "by Queen Official</code></li>" in ytm, shown(ytm))
        assertEquals(2, asked.get(), "one request each")
    }

    @Test fun `Edit searches the names as typed, never read again`() {
        val phone = phone()
        val html = page(phone.get(share("artist" to "Radiohead", "title" to "Karma Police", "app" to "Deezer")))
        assertTrue("<h1>Shared from Deezer</h1>" in html, shown(html))
        assertTrue("We searched for <strong>Radiohead – Karma Police</strong>." in html, shown(html))
        val best = html.substringAfter("Best match").substringBefore("</ul>")
        assertEquals("radiohead/karma-police", forms(best, "/lookup").single().toMap()["ug"])
        assertTrue("name=\"artist\" value=\"Radiohead\"" in html && "name=\"title\" value=\"Karma Police\"" in html)
        assertTrue("<input type=\"hidden\" name=\"app\" value=\"Deezer\">" in html, "the app kept for the next Edit")
    }

    @Test fun `a text whose artist read_names can't tell is searched whole, its title filled in`() {
        val phone = phone()
        val html = page(phone.get(share("text" to "hotel california")))
        assertTrue("We read <strong>“hotel california”</strong> but can't tell the artist" in html, shown(html))
        val best = html.substringAfter("Best match").substringBefore("</ul>")
        assertEquals("eagles/hotel-california", forms(best, "/lookup").single().toMap()["ug"], "the search's best")
        assertTrue("name=\"artist\" value=\"\"" in html && "name=\"title\" value=\"hotel california\"" in html, shown(html))
    }

    @Test fun `a song no index has is got by its names`() {
        val phone = phone()
        val html = page(phone.get(share("text" to "Nadie Sabe - Cancion Inventada Zzyzx")))
        assertFalse("Best match" in html)
        assertTrue("Not in the phone's indexes. Fetch looks up <strong>Nadie Sabe – Cancion " +
                       "Inventada Zzyzx</strong>" in html, shown(html))
        assertEquals(listOf(listOf("csrf" to TestApp.CSRF, "artist" to "Nadie Sabe", "title" to "Cancion Inventada Zzyzx")),
                     forms(html, "/lookup"))
    }

    @Test fun `with no index the page says how to bring the computer's`() {
        val phone = phone(fixture = null)
        val html = page(phone.get(share("text" to "Eagles - Hotel California")))
        assertTrue("No UG index on the phone yet. Settings › Import indexes" in html, shown(html))
    }

    @Test fun `what the app sent is shown as it came, escaped`() {
        val phone = phone()
        val html = page(phone.get(share("text" to "<script>alert(1)</script> - \"x\"", "subject" to "a & b")))
        assertFalse("<script>" in html, "escaped")
        assertTrue("<li>Text: <code>&lt;script&gt;alert(1)&lt;/script&gt; - &quot;x&quot;</code></li>" in html, shown(html))
        assertTrue("<li>Subject: <code>a &amp; b</code></li>" in html, shown(html))
    }

    @Test fun `Cancel leads to the library page`() {
        val answer = phone().get("/share/cancel")
        assertEquals(303, answer.status)
        assertEquals("/", answer.header("Location"))
    }
}
