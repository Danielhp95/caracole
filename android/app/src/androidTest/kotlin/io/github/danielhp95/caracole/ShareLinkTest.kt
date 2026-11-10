package io.github.danielhp95.caracole

import android.content.Intent
import android.webkit.WebView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.http.TransportError
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.server.jobs.JobCommands
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.BufferedReader
import java.io.InputStreamReader
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * A song's link shared to caracole as text, in the app (no computer; CaracoleTestRunner: every site refused):
 *
 *     android/scripts/device-test.sh ShareLinkTest
 *
 * The phone's database holds the search corpus's `ug` fixture (an index with Eagles - Hotel California). A share, as
 * Android's share sheet sends it to ShareLinkActivity (ACTION_SEND, text/plain), is logged under `caracole-share` as
 * it came, and opens on the library screen, already open (a single-task activity: its new intent), the page of what
 * it names: what caracole read, the best match, its sites. Get it posts the library page's own lookup, which lands on
 * the Requests tab and queues `caracole get` with the index's song; Cancel takes the screen back to the library page
 * and behind the app that shared; a link alone of Spotify's is read from its track page, asked once (a fake site's
 * answer: tests/fixtures/spotify/track.html), and one Spotify won't answer (every site refused) says so in one line
 * and offers Edit, whose names are searched again.
 *
 * The library screen is reached through the lifecycle monitor, never ActivityScenario, which loses track of a
 * single-task activity that gets a new intent.
 */
@RunWith(AndroidJUnit4::class)
class ShareLinkTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext

    @Before fun anIndexAndTheLibraryScreen() {
        Corpus.open = { name -> runCatching { instrumentation.context.assets.open("conformance/$name") }.getOrNull() }
        Corpus.openFixture = { name -> runCatching { instrumentation.context.assets.open("fixtures/$name") }.getOrNull() }
        val phone = Caracole.phone(context)
        // Once a process: the tests of a class share the app's database.
        phone.parts.database.writeBlocking { db ->
            if (db.one("SELECT COUNT(*) FROM ug_index") { it.long(0) } == 0L) Fixtures.load(db, "search/fixtures/ug.jsonl")
        }
        phone.search.invalidate()
        context.startActivity(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        // A first start with no address opens Settings over it; a share brings the screen back in front.
        waitUntil("the library page") { found() != null && library() }
    }

    @After fun leave() {
        Caracole.sitesForTests = CaracoleTestRunner.REFUSING
        instrumentation.runOnMainSync { (at(Stage.RESUMED) ?: at(Stage.STOPPED) ?: at(Stage.PAUSED))?.finish() }
        waitUntil("the library screen gone") { listOf(Stage.RESUMED, Stage.PAUSED, Stage.STOPPED).all { at(it) == null } }
    }

    /** The library screen in [stage], else null. */
    private fun at(stage: Stage): MainActivity? {
        var found: MainActivity? = null
        val look = { found = ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(stage)
            .filterIsInstance<MainActivity>().firstOrNull() }
        if (android.os.Looper.myLooper() == android.os.Looper.getMainLooper()) look() else instrumentation.runOnMainSync(look)
        return found
    }

    private fun found(): MainActivity? = at(Stage.RESUMED) ?: at(Stage.PAUSED) ?: at(Stage.STOPPED)

    private fun screen(): MainActivity = found() ?: throw AssertionError("no library screen")

    /** A finger's tap on the page's first [selector], as the owner taps it (a gesture the WebView hears as one). */
    private fun tap(selector: String) {
        val where = evaluate("""(() => { const e = document.querySelector(${JSONObject.quote(selector)});
            if (!e) return null; e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect();
            return JSON.stringify({x: r.left + r.width / 2, y: r.top + r.height / 2, w: window.innerWidth}); })()""")
            ?: throw AssertionError("nothing to tap: $selector")
        val at = JSONObject(where as String)
        val origin = IntArray(2)
        var scale = 1f
        instrumentation.runOnMainSync {
            val web = screen().findViewById<WebView>(R.id.web)
            web.getLocationOnScreen(origin)
            scale = web.width / at.getDouble("w").toFloat()
        }
        val x = origin[0] + at.getDouble("x") * scale
        val y = origin[1] + at.getDouble("y") * scale
        instrumentation.uiAutomation.executeShellCommand("input tap ${x.toInt()} ${y.toInt()}").close()
    }

    /** [script]'s value in the screen's page. */
    private fun evaluate(script: String): Any? {
        var raw: String? = null
        val latch = CountDownLatch(1)
        instrumentation.runOnMainSync {
            screen().findViewById<WebView>(R.id.web).evaluateJavascript(script) { raw = it; latch.countDown() }
        }
        check(latch.await(10, TimeUnit.SECONDS)) { "no answer from the page to: $script" }
        val value = (JSONTokener("[${raw ?: "null"}]").nextValue() as JSONArray).get(0)
        return if (value == JSONObject.NULL) null else value
    }

    /** The address of the document the page shows, once it has loaded whole; null before. The WebView's own url is
     * the next page's as soon as it is asked for, while the document is still the last one. */
    private fun loaded(): String? = evaluate("document.readyState === 'complete' ? location.href : null") as String?

    private fun library(): Boolean = loaded()?.substringBefore('#')?.removeSuffix("/") == Pages.origin()

    private fun shownAt(what: String, part: String) = waitUntil(what) { loaded()?.contains(part) == true }

    private fun text(selector: String): String =
        evaluate("(document.querySelector('$selector') || {}).textContent || ''") as String

    /** What a music app's share sends caracole: ACTION_SEND of text/plain to the share target. */
    private fun share(text: String, subject: String? = null) = context.startActivity(
        Intent(Intent.ACTION_SEND).setClass(context, ShareLinkActivity::class.java).setType("text/plain")
            .putExtra(Intent.EXTRA_TEXT, text)
            .apply { if (subject != null) putExtra(Intent.EXTRA_SUBJECT, subject) }
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
    )

    @Test fun aSongSharedFromAMusicAppShowsItsBestMatchAndGetItLooksItUp() {
        share("Eagles - Hotel California https://link.example/s/30x", subject = "Hotel California")
        shownAt("the share's page", "/share?")
        assertEquals("caracole read Eagles – Hotel California.", text(".lede"))
        val best = text(".reading.now")
        assertTrue(best, "Eagles - Hotel California" in best && "Ultimate Guitar" in best)

        val queue = Caracole.phone(context).queue
        val before = queue.snapshot().map { it.id }.toSet()
        evaluate("document.querySelector('.reading.now button[type=submit]').click(); true")
        waitUntil("the lookup queued") { queue.snapshot().any { it.id !in before } }
        val id = queue.snapshot().first { it.id !in before }.id
        shownAt("the Requests tab", "#tab=requests")
        val job = runBlocking { withTimeout(120_000) { queue.await(id) } }
        assertEquals(JobCommands.lookupSteps("Eagles", "Hotel California", ug = "eagles/hotel-california").map { it.args },
                     job.steps.map { it.args })
    }

    @Test fun cancelTakesTheScreenBackToTheLibraryAndTheAppThatSharedInFront() {
        share("Eagles - Hotel California")
        shownAt("the share's page", "/share?")
        waitUntil("the screen in front") { at(Stage.RESUMED) != null }
        tap("a[href=\"/share/cancel\"]")
        waitUntil("the library page again, the share left") { library() }
        // The screen went behind the app that shared (here, the launcher): stopped, never finished.
        waitUntil("the screen behind, now ${listOf(Stage.RESUMED, Stage.PAUSED, Stage.STOPPED).firstOrNull { at(it) != null }}") {
            at(Stage.STOPPED) != null
        }
    }

    @Test fun aSpotifyLinkAloneIsReadFromItsPageAskedOnce() {
        val track = "https://open.spotify.com/track/4u7EnebtmKWzUH433cf5Qv"
        val asked = AtomicInteger()
        Caracole.sitesForTests = Transport { request ->
            asked.incrementAndGet()
            if (request.url != track) throw TransportError("refused", request.url)
            HttpAnswer(200, listOf("content-type" to "text/html"), Corpus.fixture("spotify/track.html"))
        }
        share("$track?si=0f3c1c4d5e6f4a7b")
        shownAt("the share's page", "/share?")
        assertEquals("Read from Spotify's page: Queen – Bohemian Rhapsody.", text(".lede"))
        assertEquals(1, asked.get())
        assertEquals(true, evaluate("document.querySelector('form[action=\"/lookup\"] input[name=title][value=\"Bohemian Rhapsody\"]') !== null"))
    }

    @Test fun aLinkAloneSaysSoAndEditSearchesTheNamesTyped() {
        share("https://open.spotify.com/track/40riOy7x9W7GXjyGp4pjAv?si=1")
        shownAt("the share's page", "/share?")
        assertTrue(text(".lede"), "caracole couldn't read it: asking Spotify failed (refused" in text(".lede"))
        assertEquals(true, evaluate("document.querySelector('details.picker[open] form[action=\"/share\"]') !== null"))
        evaluate("(() => { const f = document.querySelector('form[action=\"/share\"]'); " +
            "f.artist.value = 'Eagles'; f.title.value = 'Hotel California'; f.submit(); return true; })()")
        shownAt("the names searched", "artist=Eagles")
        assertEquals("caracole searched for Eagles – Hotel California.", text(".lede"))
        assertTrue(text(".reading.now").contains("Hotel California"))
    }

    @Test fun eachShareIsLoggedAsItCame() {
        share("Listen to “Hotel California” https://x.example/1", subject = "Eagles")
        shownAt("the share's page", "/share?")
        val log = Runtime.getRuntime().exec(arrayOf("logcat", "-d", "-s", "${SharedLink.TAG}:I")).inputStream.use {
            BufferedReader(InputStreamReader(it)).readText()
        }
        assertTrue(log, "text=\"Listen to “Hotel California” https://x.example/1\" subject=\"Eagles\" title=null" in log)
    }
}
