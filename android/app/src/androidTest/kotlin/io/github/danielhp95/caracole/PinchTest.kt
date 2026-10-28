package io.github.danielhp95.caracole

import android.util.Log
import android.webkit.WebView
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.evaluate
import io.github.danielhp95.caracole.Pages.pinch
import io.github.danielhp95.caracole.Pages.url
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.mirror.Links
import io.github.danielhp95.caracole.mirror.Manifest
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.roundToInt

/**
 * A pinch on the app's pages, on a device or an emulator, with the copy synced from a real caracole serve first:
 *
 *     adb shell am instrument -w -e server http://10.0.2.2:8741 -e class io.github.danielhp95.caracole.PinchTest \
 *         io.github.danielhp95.caracole.test/androidx.test.runner.AndroidJUnitRunner
 *
 * Fingers apart make the text larger, together smaller, in steps of [TextZoom.STEP], of the size Android's font size
 * gives the pages, and the size is kept; Settings' Reset applies when the library screen comes back. A page reflows: never zoomed as a picture, never wider than the
 * screen. On a sheet each chord stays over its syllable, above its line and clear of the next, a row's chords at one
 * height, at a larger size and a smaller one; with Pinyin, over its reading, over its character (a Chinese sheet, when
 * the library has one). The viewer's own Aa multiplies the size. `-e shots <ms>` holds each sheet for a screenshot
 * from the host, as EndToEndTest does. Without `server` it is skipped.
 */
@RunWith(AndroidJUnit4::class)
class PinchTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val args = InstrumentationRegistry.getArguments()
    private val server: String? = args.getString("server")
    private val hold: Long = args.getString("shots")?.toLongOrNull() ?: 0L
    private val found = JSONObject()

    /** The WebView's own text zoom, as Android's font size has it (130 at 130 %): what the pages' own size is. */
    private val own: Int by lazy {
        var zoom = 0
        instrumentation.runOnMainSync {
            val web = WebView(context)
            zoom = web.settings.textZoom
            web.destroy()
        }
        zoom
    }

    @Before
    fun aServerIsGiven() = assumeTrue("needs -e server http://10.0.2.2:<port>", server != null)

    @After
    fun backToThePagesOwnSize() {
        if (server != null) Settings(context).textZoom = TextZoom.DEFAULT
    }

    @Test
    fun aPinchSizesTheTextAndThePagesReflowUnderIt() {
        val manifest = synced()
        val settings = Settings(context)
        settings.textZoom = TextZoom.DEFAULT
        ActivityScenario.launch(MainActivity::class.java).use { main ->
            val library = Links.address(manifest.start)
            waitFor(main, library)
            record("Android's font size", own)
            assertEquals(TextZoom.DEFAULT, zoom(main))

            // The library page: fingers apart, larger text, kept in the settings; the page reflowed.
            pinch(main, 0.3f, 0.8f)
            val larger = zoomAfter(main, TextZoom.DEFAULT)
            record("library: fingers apart", larger)
            assertTrue("larger: $larger", larger > TextZoom.DEFAULT)
            assertEquals(0, larger % TextZoom.STEP)
            assertEquals(larger, settings.textZoom)
            var shown = 0
            main.onActivity { shown = it.findViewById<WebView>(R.id.web).settings.textZoom }
            assertEquals(TextZoom.applied(own, larger), shown)
            reflowed(main, "the library page at $larger")

            // Fingers together: smaller again.
            pinch(main, 0.8f, 0.3f)
            val smaller = zoomAfter(main, larger)
            record("library: fingers together", smaller)
            assertTrue("smaller: $smaller", smaller < larger)
            assertEquals(smaller, settings.textZoom)
            reflowed(main, "the library page at $smaller")

            // Settings' Reset, then back to the library screen: the pages' own size.
            settings.textZoom = TextZoom.DEFAULT
            main.moveToState(Lifecycle.State.STARTED)
            main.moveToState(Lifecycle.State.RESUMED)
            assertEquals(TextZoom.DEFAULT, zoom(main))

            // A sheet viewer, at the pages' own size, then larger, then smaller.
            open(main, evaluate(main, """document.querySelector('a[href$="sheet.html"]').href""") as String)
            val atOwn = sheet(main, "sheet-100")

            pinch(main, 0.3f, 0.8f)
            val big = zoomAfter(main, TextZoom.DEFAULT)
            val bigSheet = sheet(main, "sheet-$big")
            // Only the text grew: a chord's name as many times wider as the size is larger.
            val grew = bigSheet.getDouble("chord") / atOwn.getDouble("chord")
            record("sheet: fingers apart", JSONObject().put("zoom", big).put("chord grew", grew))
            assertEquals(big / 100.0, grew, 0.08)

            pinch(main, 0.8f, 0.3f)
            pinch(main, 0.8f, 0.3f)
            val small = zoomAfter(main, big)
            record("sheet: fingers together twice", small)
            assertTrue("smaller than the pages' own: $small", small < TextZoom.DEFAULT)
            val before = sheet(main, "sheet-$small")

            // The viewer's Aa on top: its size times the pinch's.
            evaluate(main, "document.getElementById('bigger').click()")
            waitUntil("the viewer's Aa") { fitted(main).getString("fs") != before.getString("fs") }
            val after = sheet(main, "sheet-$small-aa")
            val fs = { o: JSONObject -> o.getString("fs").removeSuffix("px").toDouble() }
            val aa = after.getDouble("chord") / before.getDouble("chord")
            record("sheet: Aa", JSONObject().put("fs", "${before.getString("fs")} to ${after.getString("fs")}").put("chord grew", aa))
            assertEquals(fs(after) / fs(before), aa, 0.08)
            assertEquals(small, zoom(main))
            evaluate(main, "document.getElementById('smaller').click()")

            // A sheet in Chinese with its readings, at that size, then larger.
            val chinese = manifest.entries.map { it.path }
                .firstOrNull { path -> path.endsWith("/sheet.html") && path.any { it.code in 0x4E00..0x9FFF } }
            if (chinese != null) {
                open(main, Links.address(chinese) + "#py=1")
                waitUntil("the readings") { evaluate(main, "document.querySelector('#sheet ruby.py') !== null") == true }
                sheet(main, "pinyin-$small")
                pinch(main, 0.3f, 0.8f)
                pinch(main, 0.3f, 0.8f)
                val most = zoomAfter(main, small)
                record("pinyin: fingers apart twice", most)
                sheet(main, "pinyin-$most")
            }
        }
        Log.i(TAG, "RESULT $found")
    }

    /** The copy on the phone, synced from [server]: what changed there since, downloaded. */
    private fun synced(): Manifest {
        Settings(context).server = server!!
        val outcome = Syncs.run(context, probe = false)!!
        assertTrue(outcome.text, outcome.ok)
        return Caracole.mirror(context).reload()!!
    }

    private fun waitFor(main: ActivityScenario<MainActivity>, address: String) = waitUntil("$address loaded") {
        url(main).substringBefore('#') == address && evaluate(main, "document.readyState") == "complete"
    }

    /** A sheet viewer at [address], once its script ran. */
    private fun open(main: ActivityScenario<MainActivity>, address: String) {
        main.onActivity { it.findViewById<WebView>(R.id.web).loadUrl(address) }
        waitFor(main, address.substringBefore('#'))
        waitUntil("the viewer's script") { evaluate(main, "document.documentElement.dataset.ready === '1'") == true }
    }

    /** The text size the WebView shows its pages at, in percent of the size Android's font size gives them. */
    private fun zoom(main: ActivityScenario<MainActivity>): Int {
        var zoom = 0
        main.onActivity { zoom = it.findViewById<WebView>(R.id.web).settings.textZoom }
        return (zoom * 100.0 / own).roundToInt()
    }

    /** The size a pinch came to, once it applied: no longer [was], and the same a moment later. */
    private fun zoomAfter(main: ActivityScenario<MainActivity>, was: Int): Int {
        waitUntil("the size to change from $was") { zoom(main) != was }
        var last = zoom(main)
        waitUntil("the size to settle") {
            val now = zoom(main)
            (now == last).also { last = now }
        }
        return last
    }

    /** The page at its own scale, and no wider than the screen. */
    private fun reflowed(main: ActivityScenario<MainActivity>, what: String) {
        val page = JSONObject(evaluate(main, """JSON.stringify({wider: document.documentElement.scrollWidth - innerWidth,
            scale: window.visualViewport ? visualViewport.scale : 1, scrollX: window.scrollX,
            root: getComputedStyle(document.documentElement).fontSize})""") as String)
        record("$what: page", page)
        assertTrue("$what is wider than the screen: $page", page.getInt("wider") <= 0)
        assertEquals("$what is zoomed as a picture: $page", 1.0, page.getDouble("scale"), 0.001)
        assertEquals("$what is scrolled sideways: $page", 0, page.getInt("scrollX"))
    }

    /**
     * The sheet as the viewer fitted it at the size shown ([fitted]), held for a screenshot named [name], then
     * checked: each chord over its syllable, above its line (and its reading, which is over its character) and clear
     * of the next chord on its row, a row's chords at one height; the page reflowed; and fitted for this size, as
     * the viewer, asked to fit it again, changes nothing.
     */
    private fun sheet(main: ActivityScenario<MainActivity>, name: String): JSONObject {
        val sheet = fitted(main)
        record(name, JSONObject(sheet.toString()).apply { remove("widths") })
        Pages.shot(name, hold)
        assertEquals("$name: ${sheet.getJSONArray("wrong")}", 0, sheet.getInt("count"))
        reflowed(main, name)
        evaluate(main, "window.dispatchEvent(new Event('resize'))")
        Thread.sleep(300)
        assertEquals("$name was fitted for another size", sheet.getString("widths"),
            JSONObject(evaluate(main, LAID_OUT) as String).getString("widths"))
        return sheet
    }

    /** The sheet once the viewer has fitted it (a frame after it hears of a new size): [LAID_OUT], twice the same. */
    private fun fitted(main: ActivityScenario<MainActivity>): JSONObject {
        var last = ""
        waitUntil("the sheet fitted") {
            val now = evaluate(main, LAID_OUT) as String
            (now == last).also { last = now }
        }
        return JSONObject(last)
    }

    private fun record(name: String, value: Any) {
        found.put(name, value)
        Log.i(TAG, "$name: $value")
    }

    private companion object {
        const val TAG = "CaracolePinch"

        /**
         * What went wrong with the sheet's chords (`wrong`, the first few, and `count`), the widths the viewer gave
         * its columns (`widths`), the text size the viewer sets (`fs`, its `--fs`) and its first chord's width.
         */
        const val LAID_OUT = """(() => {
            const wrong = [];
            const glyph = (node) => { const r = document.createRange(); r.selectNodeContents(node); return r.getBoundingClientRect(); };
            document.querySelectorAll('#sheet section.sec > p.l').forEach((line, n) => {
              const rows = new Map();
              let before = null;
              for (const col of line.querySelectorAll(':scope > .s')) {
                const c = col.querySelector(':scope > .c'), y = col.querySelector(':scope > .y');
                if (!c || !y) continue;
                const name = c.textContent, cr = c.getBoundingClientRect(), yr = y.getBoundingClientRect();
                if (Math.abs(cr.left - yr.left) > 1) wrong.push(name + ' is not over its syllable');
                if (cr.bottom > yr.top + 1) wrong.push(name + ' is over its line');
                const ruby = y.querySelector('ruby.py');
                if (ruby) {
                  const rt = ruby.querySelector('rt').getBoundingClientRect();
                  if (cr.bottom > rt.top + 1) wrong.push(name + ' is over its reading');
                  if (rt.bottom > glyph(ruby.firstChild).top + 1) wrong.push(name + "'s reading is over its character");
                }
                if (before && Math.abs(before.top - cr.top) < 2 && before.right > cr.left + 0.5) wrong.push(before.name + ' runs into ' + name);
                before = {top: cr.top, right: cr.right, name: name};
                const row = Math.round(yr.bottom);
                rows.set(row, (rows.get(row) || []).concat([cr.top]));
              }
              for (const tops of rows.values()) if (Math.max(...tops) - Math.min(...tops) > 1) wrong.push('line ' + n + ': chords at several heights');
            });
            return JSON.stringify({wrong: wrong.slice(0, 5), count: wrong.length,
              widths: Array.from(document.querySelectorAll('#sheet .s > .y')).map((y) => y.style.minWidth).join(','),
              fs: getComputedStyle(document.documentElement).getPropertyValue('--fs').trim(),
              chord: document.querySelector('#sheet .c').getBoundingClientRect().width});
          })()"""
    }
}
