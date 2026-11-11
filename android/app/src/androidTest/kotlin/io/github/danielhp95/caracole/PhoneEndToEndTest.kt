package io.github.danielhp95.caracole

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.os.Build
import android.os.ParcelFileDescriptor
import android.util.Log
import android.view.WindowInsets
import android.view.inputmethod.InputMethodManager
import android.webkit.CookieManager
import android.webkit.WebView
import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.intent.Intents
import androidx.test.espresso.intent.Intents.intending
import androidx.test.espresso.intent.matcher.IntentMatchers.hasAction
import androidx.test.espresso.matcher.ViewMatchers.withId
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.evaluate
import io.github.danielhp95.caracole.Pages.url
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.server.http.Security
import io.github.danielhp95.caracole.server.jobs.Job
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.ServerSocket
import java.net.SocketException
import java.net.URL
import java.net.URLEncoder
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

/**
 * The phone's caracole end to end in the app, against the scenario's computer (`python -m tests.helpers.e2e_library
 * serve DIR PORT`, a computer of its own: the test changes the phone's library and the computer's):
 *
 *     adb shell pm clear io.github.danielhp95.caracole
 *     adb shell am instrument -w -e class io.github.danielhp95.caracole.PhoneEndToEndTest -e server http://10.0.2.2:PORT \
 *         io.github.danielhp95.caracole.test/androidx.test.runner.AndroidJUnitRunner
 *
 * In this order, each in the WebView the app shows:
 * - the app's server is at http://127.0.0.1:8738/, the launch's cookie is the WebView's for that origin, and a request
 *   without it is refused ("Not this app's scribe.");
 * - another loopback port is never loaded: a link there goes to the browser, a fetch and an image of it are answered
 *   in the app, and that port's server hears nothing;
 * - a sync from the bar's sync button and its sheet (its comparison, Sync, each conflict keeping the computer's),
 *   which brings the computer's library and its indexes;
 * - Sec-Fetch-Site reaches the server from the WebView: the library page's own read of /api/sync is answered, and the
 *   same read from a sandboxed viewer (an opaque origin, so `cross-site`) is refused as another site's;
 * - a query typed into the library page's box shows /api/search's rows: a song of the computer's index the library
 *   hasn't got; /api/search offers no LaCuerda search for it, so the page sends none by itself
 *   (CaracoleTestRunner's `searchesLacuerda` false);
 * - its row's Get it looks it up, `caracole get` under the runner's transport, which refuses every site: the job is
 *   done, its song added, its sites' stages failed or skipped (a lane's port still neutral), never a miss, its line
 *   the library page's (/jobs.json's: "Not fetched yet"), and the reloaded page has its card;
 * - a song removed with its line's Remove is gone from the reloaded page's cards;
 * - a sandboxed viewer's link back to the library (its artist line, index.html#by=…) loads the library page, so the
 *   navigation carried the cookie.
 *
 * Without `server` it is skipped.
 */
@RunWith(AndroidJUnit4::class)
class PhoneEndToEndTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val server: String? = InstrumentationRegistry.getArguments().getString("server")
    private val found = JSONObject()

    /** Another server on 127.0.0.1, on a port of its own: it counts the connections it is asked for. */
    private val other = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
    private val heard = AtomicInteger()

    @Before
    fun setUp() {
        assumeTrue("needs -e server http://10.0.2.2:<port>", server != null)
        thread(isDaemon = true) {
            while (true) {
                val socket = try {
                    other.accept()
                } catch (e: SocketException) {
                    break
                }
                heard.incrementAndGet()
                socket.use { it.getOutputStream().write("HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nno".toByteArray()) }
            }
        }
    }

    @After
    fun stop() = other.close()

    @Test
    fun thePhonesCaracoleInTheAppFromItsOriginToASync() {
        Settings(context).server = server!!
        val origin = Pages.origin()
        val library = "$origin/"
        record("origin", origin)
        assertEquals("the app's server", "http://127.0.0.1:${Caracole.PORT}", origin)

        ActivityScenario.launch(MainActivity::class.java).use { main ->
            val js = { script: String -> evaluate(main, script) }
            loaded(main, library)

            // The cookie: the WebView's for the server's origin, and a request without it refused.
            val cookie = CookieManager.getInstance().getCookie(origin).orEmpty()
            assertTrue("the WebView's cookie for $origin", "${Security.SECRET_COOKIE}=${Caracole.secret}" in cookie.split("; "))
            val page = get(library, "${Security.SECRET_COOKIE}=${Caracole.secret}")
            assertEquals(200, page.first)
            val refused = get(library, null)
            assertEquals(403, refused.first)
            assertEquals("Not this app's scribe.\n", refused.second)
            record("cookie", JSONObject().put("webview", cookie.isNotEmpty()).put("without", refused.first))

            // Another loopback port: never loaded in the WebView.
            val elsewhere = "http://127.0.0.1:${other.localPort}/"
            Intents.init()
            try {
                intending(hasAction(Intent.ACTION_VIEW)).respondWith(Instrumentation.ActivityResult(Activity.RESULT_OK, null))
                js("location.href = ${JSONObject.quote(elsewhere)}")
                waitUntil("the link handed to the browser") {
                    Intents.getIntents().any { it.action == Intent.ACTION_VIEW && it.dataString == elsewhere }
                }
                assertTrue(url(main).startsWith(library))
                js("""(() => { window.probes = {};
                    fetch(${JSONObject.quote(elsewhere + "fetched")}).then((r) => { window.probes.fetch = 'status ' + r.status; },
                                                                          () => { window.probes.fetch = 'refused'; });
                    const image = new Image();
                    image.onload = () => { window.probes.image = 'loaded'; };
                    image.onerror = () => { window.probes.image = 'refused'; };
                    image.src = ${JSONObject.quote(elsewhere + "image.png")}; return 1; })()""")
                waitUntil("the fetch and the image to settle") { js("Object.keys(window.probes || {}).length") == 2 }
                val probes = JSONObject(js("JSON.stringify(window.probes)") as String)
                record("elsewhere", probes)
                assertEquals("refused", probes.getString("image"))
                assertTrue(probes.toString(), probes.getString("fetch") != "status 200")
            } finally {
                Intents.release()
            }
            assertEquals("connections the other port heard", 0, heard.get())

            // A sync from the bar's sync button and its sheet (SyncSheet, sync-app's): the computer's library and
            // indexes come to the phone, each song changed on both sides keeping the computer's.
            SyncDevice.mayNotify()
            val syncSheet = SyncSheet { script -> js(script) }
            syncSheet.libraryLoaded()
            onView(withId(R.id.sync)).perform(click())
            val compared = syncSheet.compared()
            record("compared", compared)
            assertTrue("the first sync takes the computer's songs: $compared", compared.getInt("take") > 0)
            syncSheet.click("sync-go")
            waitUntil("a conflict's card or the sync's summary", timeoutMs = 5 * 60_000) {
                when (syncSheet.state().getString("view")) {
                    "conflict" -> { syncSheet.click("sync-keep-there"); false }
                    "done" -> true
                    else -> false
                }
            }
            val synced = syncSheet.done()
            record("synced", synced)
            assertFalse("the sync failed: $synced", synced.getString("tone") == "failed")
            assertTrue("the summary: $synced", synced.getString("title").startsWith("Synced with: "))
            syncSheet.click("sync-go")
            waitUntil("the sheet closed") { !syncSheet.state().getBoolean("open") }

            // The library page as the sync left it.
            reload(main, library)
            val cards = cards(main)
            record("cards after the sync", cards.length())
            assertTrue("the computer's songs on the phone: ${cards.length()}", cards.length() >= 20)

            // Sec-Fetch-Site: the library page's own read is answered; a sandboxed viewer's is another site's.
            js("location.href = '/api/sync'")
            loaded(main, "$origin/api/sync")
            val own = js("document.body.textContent") as String
            record("own read", own.take(300))
            assertTrue("the page's own read of /api/sync: $own", JSONObject(own).has("peers"))
            val sheet = viewerOf(cards)
            val viewer = Pages.address(sheet)
            main.onActivity { it.findViewById<WebView>(R.id.web).loadUrl(viewer) }
            loaded(main, viewer)
            waitUntil("the viewer's script") { js("document.documentElement.dataset.ready === '1'") == true }
            assertEquals("the viewer's sandbox, an opaque origin", "null", js("String(window.origin)"))
            js("location.href = '/api/sync'")
            loaded(main, "$origin/api/sync")
            val theirs = js("document.body.textContent") as String
            record("sandboxed read", theirs.take(300))
            assertTrue("the sandbox's read is refused as another site's (Sec-Fetch-Site): $theirs",
                       "another site" in theirs && !theirs.startsWith("Not this app's"))

            // A query typed into the box: /api/search's rows, a song of the computer's index the library hasn't got.
            reload(main, library)
            assertFalse("the index's song isn't the phone's yet", cardTitles(cards(main)).any { WANTED.containsMatchIn(it) })
            tap(main, "#q")
            // `input text` types a key at a time: read its output to its end, so the keys are all sent (an `input tap`
            // sent while it still types is lost) before the box is read
            ParcelFileDescriptor.AutoCloseInputStream(
                instrumentation.uiAutomation.executeShellCommand("input text ${QUERY.replace(" ", "%s")}"),
            ).use { it.readBytes() }
            val typed = try {
                waitUntil("the query typed", 10_000) { js("document.getElementById('q').value") == QUERY }
                true
            } catch (e: AssertionError) {
                // The keyboard's events went elsewhere: the box's own input event, as typing fires it.
                js("(() => { const q = document.getElementById('q'); q.value = ${JSONObject.quote(QUERY)}; " +
                   "q.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()")
                false
            }
            record("typed", typed)
            // The keyboard put away, and whatever it shows over the page with it (Gboard's own sheets, such as its
            // stylus tour, which take every tap below them), so that the row's Get it is what a tap reaches.
            main.onActivity { activity ->
                activity.getSystemService(InputMethodManager::class.java)
                    .hideSoftInputFromWindow(activity.findViewById<WebView>(R.id.web).windowToken, 0)
            }
            if (Build.VERSION.SDK_INT >= 30) {
                waitUntil("the keyboard put away") {
                    var shown = true
                    main.onActivity { activity ->
                        shown = activity.window.decorView.rootWindowInsets?.isVisible(WindowInsets.Type.ime()) == true
                    }
                    !shown
                }
            }
            // the page's answer to the whole query drawn (library.js's results, `found`, of that query, no search on
            // its way), so that the row tapped is the one it keeps
            waitUntil("the query's answer drawn") {
                js("(() => { const f = document.getElementById('found'); " +
                   "return f.dataset.query === ${JSONObject.quote(QUERY)} && !f.hasAttribute('aria-busy'); })()") == true
            }
            val getIt = "button[aria-label^=\"Get \"][aria-label*=\"$TITLE_WORD\" i]"
            waitUntil("the index's row and its Get it") { js("document.querySelector(${JSONObject.quote(getIt)}) !== null") == true }
            val row = js("""(() => { const b = document.querySelector(${JSONObject.quote(getIt)});
                const line = b.closest('[data-hit]') || b.parentElement;
                return JSON.stringify({label: b.getAttribute('aria-label'), line: line.textContent.slice(0, 200),
                    hit: line.dataset ? line.dataset.hit || '' : ''}); })()""") as String
            record("row", JSONObject(row))
            // The runner's searchesLacuerda false: /api/search offers no LaCuerda search for the query, so the page
            // (library.js, which sends one only where `lacuerda_search` says so) sends none by itself.
            assertFalse(Caracole.searchesLacuerdaForTests)
            val (searched, said) = PhoneForms.script("/api/search?q=${URLEncoder.encode(QUERY, "UTF-8")}&box=check")
            assertEquals(said.take(500), 200, searched)
            val answer = JSONObject(said)
            record("lacuerda_search", answer.opt("lacuerda_search")?.toString() ?: "absent")
            assertTrue("no LaCuerda search offered: ${answer.opt("lacuerda_search")}", answer.isNull("lacuerda_search"))
            assertTrue("no LaCuerda search queued", Caracole.started()!!.queue.snapshot().none { it.spec.kind == "lacuerda-search" })

            // Its Get it: the song added on the phone.
            val before = Caracole.started()!!.queue.snapshot().map { it.id }.toSet()
            val where = """(() => { const b = document.querySelector(${JSONObject.quote(getIt)}); const r = b.getBoundingClientRect();
                const v = window.visualViewport; return JSON.stringify({top: r.top, left: r.left, h: window.innerHeight,
                vh: v ? v.height : null, focus: document.activeElement ? document.activeElement.id : null,
                disabled: b.disabled}); })()"""
            record("before the tap", JSONObject(js(where) as String))
            tap(main, getIt)
            try {
                waitUntil("the Get it's job queued", 10_000) { Caracole.started()!!.queue.snapshot().any { it.id !in before } }
            } catch (e: AssertionError) {
                record("no job after the tap", JSONObject(js(where) as String))
                throw e
            }
            val added = waitForJob("the Get it's job", before)
            val stages = added.stages.associate { it.name to it.state }
            val line = PhoneForms.line(added.id)  // as the library page shows it: /jobs.json's, its song's facts read
            record("get it", JSONObject().put("kind", added.spec.kind).put("title", added.spec.title).put("state", added.state)
                .put("stages", JSONObject(stages)).put("line", line))
            assertEquals("the Get it's job: ${added.spec.title}", Job.DONE, added.state)
            // A lookup, every site refused: its song added, its sites failed or skipped, never a miss.
            assertEquals("song", added.spec.kind)
            assertEquals("get", added.steps.single().args.first())
            assertEquals("done", stages["song"])
            assertEquals("failed", stages["lyrics"])
            for (site in listOf("ug", "lacuerda", "gtptabs", "harptabs", "gametabs")) {
                assertTrue("$site: $stages", stages[site] in setOf("failed", "skipped"))
            }
            // status.py's line for a lookup that no site answered: not fetched yet, never Not found
            assertEquals(line.toString(), "Not fetched yet", line.getString("text"))
            reload(main, library)
            val withIt = cardTitles(cards(main))
            assertTrue("the added song's card: $withIt", withIt.any { WANTED.containsMatchIn(it) })

            // A song removed with its line's Remove: its card gone once the page is loaded again.
            val gone = cards(main).let { all -> (0 until all.length()).map { all.getJSONObject(it) } }
                .first { it.optString("title") == REMOVED.second && it.optString("artist") == REMOVED.first }
            val remove = "button[aria-label=${JSONObject.quote("Remove ${REMOVED.second} by ${REMOVED.first} from caracole")}]"
            assertTrue("its Remove", js("document.querySelector(${JSONObject.quote(remove)}) !== null") == true)
            val beforeRemoval = Caracole.started()!!.queue.snapshot().map { it.id }.toSet()
            js("document.querySelector(${JSONObject.quote(remove)}).click()")
            val removal = waitForJob("the removal", beforeRemoval, kind = "remove")
            record("removal", JSONObject().put("title", removal.spec.title).put("state", removal.state))
            assertEquals(Job.DONE, removal.state)
            reload(main, library)
            val left = cards(main)
            val identities = (0 until left.length()).map { left.getJSONObject(it).optString("identity") }
            assertFalse("${gone.optString("identity")} still has a card", gone.optString("identity") in identities)
            record("cards after the removal", left.length())

            // A sandboxed viewer's link back to the library: the navigation carries the cookie.
            val back = Pages.address(viewerOf(left))
            main.onActivity { it.findViewById<WebView>(R.id.web).loadUrl(back) }
            loaded(main, back)
            waitUntil("the viewer's script") { js("document.documentElement.dataset.ready === '1'") == true }
            val artistLink = "a[href*=\"index.html#by=\"]"
            val href = js("(() => { const a = document.querySelector(${JSONObject.quote(artistLink)}); return a ? a.href : null; })()")
            record("link back", href ?: "none")
            assertTrue("the viewer's artist line links the library", href is String)
            tap(main, artistLink)
            waitUntil("the library page by the link") {
                url(main).substringBefore('#') == "$origin/index.html" && js("document.readyState") == "complete"
            }
            val came = JSONObject(js("""JSON.stringify({text: document.body ? document.body.textContent.slice(0, 80) : '',
                songs: !!document.getElementById('songs'), origin: window.origin, hash: location.hash})""") as String)
            record("came back", came)
            assertTrue("the library page, the cookie carried: $came", came.getBoolean("songs"))
            assertEquals(origin, came.getString("origin"))
        }
        Log.i(TAG, "RESULT $found")
    }

    /** The cards of the library page's data (its `songs` block). */
    private fun cards(main: ActivityScenario<MainActivity>): JSONArray =
        JSONObject(evaluate(main, "document.getElementById('songs').textContent") as String).getJSONArray("songs")

    private fun cardTitles(cards: JSONArray): List<String> = (0 until cards.length()).map {
        cards.getJSONObject(it).let { c -> c.optString("artist") + " - " + c.optString("title") }
    }

    /** The library path of a mirrored sheet viewer of one of [cards]' songs. */
    private fun viewerOf(cards: JSONArray): String {
        val mirror = Caracole.mirror(context).reload()!!
        val titles = cardTitles(cards).toSet()
        return mirror.entries.map { it.path }.first { path ->
            path.endsWith("/sheet.html") && path.split('/').let { it.size == 3 && "${it[0]} - ${it[1]}" in titles }
        }
    }

    /** The job the phone's queue got since [before] (of [kind], when given), once it has ended. */
    private fun waitForJob(what: String, before: Set<Int>, kind: String? = null): Job {
        var job: Job? = null
        waitUntil(what, timeoutMs = 60_000) {
            job = Caracole.started()!!.queue.snapshot().firstOrNull { it.id !in before && (kind == null || it.spec.kind == kind) }
            job?.state == Job.DONE || job?.state == Job.FAILED
        }
        return job!!
    }


    private fun loaded(main: ActivityScenario<MainActivity>, address: String) = waitUntil("$address loaded") {
        url(main).substringBefore('#') == address && evaluate(main, "document.readyState") == "complete"
    }

    /** The page at [address] loaded again, a new document (`window.before` is the one before). */
    private fun reload(main: ActivityScenario<MainActivity>, address: String) {
        evaluate(main, "window.before = 1")
        main.onActivity { it.findViewById<WebView>(R.id.web).loadUrl(address) }
        waitUntil("$address again") {
            url(main).substringBefore('#') == address &&
                evaluate(main, "typeof window.before === 'undefined' && document.readyState === 'complete'") == true
        }
    }

    /** Taps the page's first element matching [selector] as a finger would (`input tap`), scrolled into view first. */
    private fun tap(main: ActivityScenario<MainActivity>, selector: String) {
        val quoted = JSONObject.quote(selector)
        check(evaluate(main, "(() => { const e = document.querySelector($quoted); if (!e) return false; " +
            "e.scrollIntoView({block: 'center'}); return true; })()") == true) { "nothing to tap: $selector" }
        Thread.sleep(300)
        val at = JSONObject(evaluate(main, "(() => { const r = document.querySelector($quoted).getBoundingClientRect(); " +
            "return JSON.stringify({x: r.left + r.width / 2, y: r.top + r.height / 2}); })()") as String)
        val cssWidth = (evaluate(main, "window.innerWidth") as Number).toFloat()
        val corner = IntArray(2)
        var scale = 1f
        main.onActivity {
            val web = it.findViewById<WebView>(R.id.web)
            web.getLocationOnScreen(corner)
            scale = web.width / cssWidth
        }
        val x = corner[0] + at.getDouble("x") * scale
        val y = corner[1] + at.getDouble("y") * scale
        instrumentation.uiAutomation.executeShellCommand("input tap ${x.toInt()} ${y.toInt()}").close()
    }

    /** [url]'s status and text, asked as another app on the phone would, with [cookie] or none. */
    private fun get(url: String, cookie: String?): Pair<Int, String> {
        val connection = URL(url).openConnection() as HttpURLConnection
        try {
            connection.instanceFollowRedirects = false
            if (cookie != null) connection.setRequestProperty("Cookie", cookie)
            val status = connection.responseCode
            val body = (if (status >= 400) connection.errorStream else connection.inputStream)?.use { it.readBytes() } ?: ByteArray(0)
            return status to body.toString(Charsets.UTF_8)
        } finally {
            connection.disconnect()
        }
    }

    private fun record(what: String, value: Any) {
        found.put(what, value)
        Log.i(TAG, "$what: $value")
    }

    private companion object {
        const val TAG = "CaracolePhoneE2E"

        /** The scenario's song of the computer's index (tests/helpers/e2e_library.py INDEX_SONG): its query. */
        const val QUERY = "jeanie light brown"
        const val TITLE_WORD = "Jeanie"
        val WANTED = Regex("jeanie", RegexOption.IGNORE_CASE)

        /** A computer song the phone removes (e2e_library.py REMOVED's R). */
        val REMOVED = "Traditional" to "Barbara Allen"
    }
}
