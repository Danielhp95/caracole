package io.github.danielhp95.caracole

import android.util.Log
import android.webkit.WebView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.evaluate
import io.github.danielhp95.caracole.Pages.pinch
import io.github.danielhp95.caracole.Pages.url
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.core.http.RoutedTransport
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.server.http.Security
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.viewer.render.WrittenPages
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.security.MessageDigest

/**
 * Milestone 5's pages in the app, on a device or an emulator:
 *
 *     android/scripts/device-test.sh io.github.danielhp95.caracole.PagesOnDeviceTest=DIR
 *     android/scripts/device-test.sh --sites lookups io.github.danielhp95.caracole.PagesOnDeviceTest
 *
 * Each page is opened in the app's WebView, at its address on the phone's own server, and used as a hand would:
 *
 * - a Chinese sheet whose page carries readings plays a chord tapped (a real tap: strum.js sounds only on one, and
 *   writes what it strummed on `<html data-heard>`), shows each character's reading with Pinyin on and its words in
 *   Traditional characters with Traditional on (each reading still over its character), and, fingers apart, its text
 *   grows with every chord still over its syllable and its reading;
 * - a harmonica tab's page draws each hole over its syllable, no wider than the screen, and plays a hole tapped at its
 *   note on the harp it starts on.
 *
 * [theComputersPagesPlayOnThePhone] does it on the pages the copy took from the scenario's computer (`-e server`:
 * tests/helpers/e2e_library.py's 茉莉花, whose made-up words are Chinese, and Oh! Susanna's harmonica tab); without a
 * server it is skipped. [aSongLookedUpOnThePhonePlaysAsOnTheComputer] does it on the pages the phone made itself of
 * the songs it looked up against the fake sites (`-e sites`), each served as the phone wrote it while its record
 * says so (its bytes' SHA-256, at its song unit's digest now).
 */
@RunWith(AndroidJUnit4::class)
class PagesOnDeviceTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val args = InstrumentationRegistry.getArguments()
    private val server: String? = args.getString("server")
    private val sites: String? = args.getString("sites")
    private val hold: Long = args.getString("shots")?.toLongOrNull() ?: 0L
    private val found = JSONObject()

    @After
    fun afterwards() {
        Settings(context).textZoom = TextZoom.DEFAULT
        Caracole.sitesForTests = CaracoleTestRunner.REFUSING
        Log.i(TAG, "RESULT $found")
    }

    @Test
    fun theComputersPagesPlayOnThePhone() {
        assumeTrue("needs -e server http://10.0.2.2:<port> (device-test.sh PagesOnDeviceTest=DIR)", server != null)
        Settings(context).server = server!!
        val outcome = Syncs.run(context, probe = false)!!
        assertTrue(outcome.text, outcome.ok)
        val mirror = Caracole.mirror(context)
        val manifest = mirror.reload()!!
        val chinese = SheetLayout.chineseSheet(mirror, manifest)
        val harmonica = manifest.entries.map { it.path }.firstOrNull { it.endsWith("/harmonica-1.html") }
            ?: throw AssertionError("no harmonica tab's page in the copy: the scenario's computer has one")
        ActivityScenario.launch(MainActivity::class.java).use { main ->
            waitFor(main, Pages.address(""))
            chineseSheet(main, Pages.address(chinese), "mirror")
            harmonicaPage(main, Pages.address(harmonica), "mirror")
        }
    }

    @Test
    fun aSongLookedUpOnThePhonePlaysAsOnTheComputer() {
        assumeTrue("waiting on lookups-e2e: no fake sites server (-e sites, device-test.sh --sites lookups)",
                   sites != null)
        val phone = Caracole.phone(context)
        assumeTrue("waiting on phone-render and written-pages: the phone makes no page of its own yet",
                   phone.render.seam !== SongPages.NONE)
        val document = JSONObject(String(fromSites("/scenario.json"), Charsets.UTF_8))
        val songs = document.getJSONObject("songs")
        assumeTrue("waiting on lookups-e2e: its scenario has no Chinese song and harmonica tab to look up",
                   songs.has(CHINESE) && songs.has(HARMONICA))
        Caracole.sitesForTests = RoutedTransport(sites!!)
        ActivityScenario.launch(MainActivity::class.java).use { main ->
            val index = File(context.cacheDir, "fake-sites-index.sqlite")
            index.writeBytes(fromSites("/index.sqlite"))
            val merged = await(phone.importIndex(index).id)
            assertEquals(merged.asJson().toString(), Job.DONE, merged.state)

            val pages = HashMap<String, String>()
            for ((role, name) in listOf(CHINESE to "sheet.html", HARMONICA to "harmonica-1.html")) {
                val search = songs.getJSONObject(role).getJSONObject("search")
                val job = getIt(search)
                assertEquals(job.asJson().toString(), Job.DONE, job.state)
                pages[role] = ownPage(search.getString("key"), name)
            }
            waitFor(main, Pages.address(""))
            chineseSheet(main, Pages.address(pages.getValue(CHINESE)), "phone")
            harmonicaPage(main, Pages.address(pages.getValue(HARMONICA)), "phone")
        }
    }

    // --- what is checked of each page -------------------------------------------------------------------------------

    /** The Chinese sheet at [address]: a chord tapped sounds; Pinyin and Traditional switch; fingers apart, larger. */
    private fun chineseSheet(main: ActivityScenario<MainActivity>, address: String, from: String) {
        open(main, address)
        Pages.shot("$from-chinese", hold)

        // A chord tapped: its card, and its shape strummed.
        evaluate(main, "delete document.documentElement.dataset.heard")
        tap(main, """#sheet .c[data-c="0"]""")
        waitUntil("the chord heard") { evaluate(main, "document.documentElement.dataset.heard || null") != null }
        record("$from: heard", evaluate(main, "document.documentElement.dataset.heard") as String)
        evaluate(main, "(document.querySelector('#card [data-close]') || {click() {}}).click()")

        // Pinyin on: each character with its reading, each chord over its syllable and its reading.
        assertEquals("no reading before Pinyin", 0, evaluate(main, SheetLayout.READINGS))
        evaluate(main, "document.getElementById('more').click()")
        evaluate(main, "document.getElementById('pinyin-chip').click()")
        waitUntil("the readings") { evaluate(main, SheetLayout.READINGS) as Int > 0 }
        val first = evaluate(main, "document.querySelector('#sheet ruby.py rt').textContent") as String
        record("$from: readings", JSONObject().put("count", evaluate(main, SheetLayout.READINGS)).put("first", first))
        assertEquals("这's reading", "zhè", first)
        laidOut(main, "$from: Pinyin on")
        assertTrue(SheetLayout.SIMPLIFIED in (evaluate(main, SheetLayout.WORDS) as String))

        // Traditional characters: the words in them, each reading kept over its character.
        evaluate(main, "document.getElementById('hanzi-t').click()")
        waitUntil("Traditional characters") { SheetLayout.TRADITIONAL in (evaluate(main, SheetLayout.WORDS) as String) }
        assertEquals("这's reading, over 這", first,
                     evaluate(main, "document.querySelector('#sheet ruby.py rt').textContent"))
        laidOut(main, "$from: Traditional")
        Pages.shot("$from-chinese-traditional", hold)
        evaluate(main, "document.getElementById('hanzi-s').click()")
        waitUntil("Simplified characters") { SheetLayout.SIMPLIFIED in (evaluate(main, SheetLayout.WORDS) as String) }

        // Fingers apart: the text larger, the readings still in place.
        val before = textZoom(main)
        pinch(main, 0.3f, 0.8f)
        waitUntil("a larger size") { textZoom(main) > before }
        record("$from: pinched", JSONObject().put("from", before).put("to", textZoom(main)))
        assertTrue("Pinyin kept", evaluate(main, SheetLayout.READINGS) as Int > 0)
        laidOut(main, "$from: pinched")
        Pages.shot("$from-chinese-pinched", hold)

        // Pinyin off again: no reading.
        evaluate(main, "document.getElementById('pinyin-chip').click()")
        waitUntil("the readings gone") { evaluate(main, SheetLayout.READINGS) == 0 }
        Settings(context).textZoom = TextZoom.DEFAULT
    }

    /** The harmonica tab's page at [address]: its holes drawn over their syllables; a hole tapped heard. */
    private fun harmonicaPage(main: ActivityScenario<MainActivity>, address: String, from: String) {
        open(main, address)
        Pages.shot("$from-harmonica", hold)
        val drawn = JSONObject(evaluate(main, HOLES) as String)
        record("$from: harmonica", drawn)
        assertTrue("holes drawn: $drawn", drawn.getInt("holes") >= 30)
        assertEquals("a hole off its syllable: $drawn", 0, drawn.getJSONArray("off").length())
        assertTrue("wider than the screen: $drawn", drawn.getInt("wider") <= 0)
        assertEquals("the harp it starts on", "C harp", drawn.getString("harp"))

        evaluate(main, "delete document.documentElement.dataset.heard")
        tap(main, """#sheet .h[data-i="0"]""")
        waitUntil("the hole heard") { evaluate(main, "document.documentElement.dataset.heard || null") != null }
        assertEquals("hole 4 blown on a C harp: C5", "523.25", evaluate(main, "document.documentElement.dataset.heard"))
    }

    /** Every chord over its syllable (and its reading), above its line, clear of the next: PinchTest's check. */
    private fun laidOut(main: ActivityScenario<MainActivity>, what: String) {
        var last = ""
        waitUntil("$what: the sheet fitted") {
            val now = evaluate(main, SheetLayout.LAID_OUT) as String
            (now == last).also { last = now }
        }
        val sheet = JSONObject(last)
        assertEquals("$what: ${sheet.getJSONArray("wrong")}", 0, sheet.getInt("count"))
        val wider = evaluate(main, "document.documentElement.scrollWidth - innerWidth") as Int
        assertTrue("$what: wider than the screen by $wider", wider <= 0)
    }

    // --- the pages the phone made ------------------------------------------------------------------------------------

    /**
     * The phone's own page [name] of the song of identity key [key], once its lookup is over: written beside its kept
     * files, recorded (WrittenPages: its bytes' SHA-256 and size, at the song unit's digest now) and served as
     * written. Its path in the library.
     */
    private fun ownPage(key: String, name: String): String {
        val parts = Caracole.phone(context).parts
        val (id, kept) = parts.database.read { db ->
            db.one("SELECT songs.id, files.path FROM files JOIN songs ON songs.id = files.song_id " +
                       "WHERE songs.key = ? AND files.name IN ('sheet.txt', 'harmonica-1.txt') " +
                       "ORDER BY files.name DESC",
                   key) { it.long(0)!! to it.text(1)!! }
        } ?: throw AssertionError("nothing kept of $key")
        val path = kept.substringBeforeLast('/') + "/" + name
        val file = File(parts.store.libraryDir, path)
        assertTrue("$path written", file.isFile)
        val bytes = file.readBytes()
        val written = parts.database.read { db -> WrittenPages.written(db, id, name) }
        assertNotNull("$path recorded", written)
        assertEquals("$path's record", sha256(bytes), written!!.sha256)
        assertEquals("$path's record", bytes.size.toLong(), written.size)
        assertEquals("$path made at its unit's digest now",
                     parts.database.read { db -> Units.digestOf(db, "song/$key") }, written.unitDigest)
        assertTrue("$path served as the phone wrote it", served(Pages.address(path)).contentEquals(bytes))
        record("own $name", JSONObject().put("path", path).put("sha256", written.sha256))
        return path
    }

    /** Get it on /api/search's row of [search]'s song, as the library page posts it: the job, once it is over. */
    private fun getIt(search: JSONObject): Job {
        val (status, body) = PhoneForms.script("/api/search?q=" + URLEncoder.encode(search.getString("query"), "UTF-8"))
        assertEquals(body, 200, status)
        val rows = JSONObject(body).getJSONArray("index")
        val row = (0 until rows.length()).map { rows.getJSONObject(it) }
            .firstOrNull { it.getString("ug") == search.getString("ug") }
            ?: throw AssertionError("/api/search finds no ${search.getString("ug")}: $body")
        val (posted, answer) = PhoneForms.post("/lookup", "artist" to row.getString("artist"),
                                               "title" to row.getString("title"), "ug" to row.getString("ug"))
        assertEquals(answer, 202, posted)
        return await(JSONObject(answer).getInt("job"))
    }

    private fun await(id: Int): Job = runBlocking { withTimeout(300_000) { Caracole.phone(context).queue.await(id) } }

    /** [address]'s bytes as the phone's server answers a page's link (the launch's cookie). */
    private fun served(address: String): ByteArray {
        val connection = URL(address).openConnection() as HttpURLConnection
        try {
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Cookie", "${Security.SECRET_COOKIE}=${Caracole.secret}")
            connection.setRequestProperty("Sec-Fetch-Site", "same-origin")
            assertEquals(address, 200, connection.responseCode)
            return connection.inputStream.use { it.readBytes() }
        } finally {
            connection.disconnect()
        }
    }

    /** The fake sites server's [path], read straight from the host. */
    private fun fromSites(path: String): ByteArray {
        val connection = URL(sites + path).openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = 30_000
            connection.readTimeout = 60_000
            assertEquals(sites + path, 200, connection.responseCode)
            return connection.inputStream.use { it.readBytes() }
        } finally {
            connection.disconnect()
        }
    }

    // --- the WebView ------------------------------------------------------------------------------------------------

    private fun waitFor(main: ActivityScenario<MainActivity>, address: String) = waitUntil("$address loaded") {
        url(main).substringBefore('#') == address && evaluate(main, "document.readyState") == "complete"
    }

    /** The page at [address], once its script ran (`<html data-ready="1">`, a sheet's and a harmonica tab's). */
    private fun open(main: ActivityScenario<MainActivity>, address: String) {
        // The page before marked, so that its own document, which the WebView's url names the new address over
        // until the new one loads, is never taken for the new page's.
        evaluate(main, "window.before = true")
        main.onActivity { it.findViewById<WebView>(R.id.web).loadUrl(address) }
        waitFor(main, address.substringBefore('#'))
        waitUntil("the page's script") {
            evaluate(main, "!window.before && document.documentElement.dataset.ready === '1'") == true
        }
    }

    private fun textZoom(main: ActivityScenario<MainActivity>): Int {
        var zoom = 0
        main.onActivity { zoom = it.findViewById<WebView>(R.id.web).settings.textZoom }
        return zoom
    }

    /** A real tap on the element [selector] names (scrolled to the middle first), as a finger's: `input tap`. */
    private fun tap(main: ActivityScenario<MainActivity>, selector: String) {
        val where = """(() => { const e = document.querySelector(${JSONObject.quote(selector)}); if (!e) return null;
            const r = e.getBoundingClientRect();
            return JSON.stringify({x: r.left + r.width / 2, y: r.top + r.height / 2}); })()"""
        assertNotNull("nothing to tap: $selector",
                      evaluate(main, "(() => { const e = document.querySelector(${JSONObject.quote(selector)}); " +
                                     "if (e) e.scrollIntoView({block: 'center'}); return e ? 1 : null; })()"))
        Thread.sleep(300)  // the scroll settles
        val at = JSONObject(evaluate(main, where) as String)
        val cssWidth = (evaluate(main, "window.innerWidth") as Number).toFloat()
        val origin = IntArray(2)
        var scale = 1f
        main.onActivity {
            val web = it.findViewById<WebView>(R.id.web)
            web.getLocationOnScreen(origin)
            scale = web.width / cssWidth
        }
        val x = origin[0] + at.getDouble("x") * scale
        val y = origin[1] + at.getDouble("y") * scale
        instrumentation.uiAutomation.executeShellCommand("input tap ${x.toInt()} ${y.toInt()}").close()
    }

    private fun record(name: String, value: Any) {
        found.put(name, value)
        Log.i(TAG, "$name: $value")
    }

    private companion object {
        const val TAG = "CaracolePages"

        /** The fake sites' scenario's songs this test looks up: a Chinese sheet, and a song with a harmonica tab. */
        const val CHINESE = "chinese"
        const val HARMONICA = "harmonica"

        /** The harmonica tab's page as drawn: its holes, those not right over their syllable, how much wider than
         * the screen it is, and the harp it shows. */
        const val HOLES = """(() => {
            const off = [];
            document.querySelectorAll('#sheet .s').forEach((s, n) => {
              const g = s.querySelector('.hg'), y = s.querySelector('.y');
              if (!g || !y) return;
              const h = g.getBoundingClientRect(), w = y.getBoundingClientRect();
              if (Math.abs(h.left - w.left) > 0.5 || h.bottom < w.top - 0.5 || h.bottom > w.top + 2) off.push(n);
            });
            return JSON.stringify({holes: document.querySelectorAll('#sheet .h[data-i]').length, off: off.slice(0, 5),
              wider: document.documentElement.scrollWidth - innerWidth,
              harp: (document.getElementById('harp-name') || {}).textContent || ''});
          })()"""

        fun sha256(bytes: ByteArray): String =
            MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    }
}
