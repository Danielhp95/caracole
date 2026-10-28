package io.github.danielhp95.caracole

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.util.Log
import android.webkit.WebView
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.intent.Intents
import androidx.test.espresso.intent.Intents.intending
import androidx.test.espresso.intent.matcher.IntentMatchers.hasAction
import org.hamcrest.Matchers.anyOf
import androidx.test.espresso.matcher.ViewMatchers.withId
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.evaluate
import io.github.danielhp95.caracole.Pages.url
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.mirror.Links
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.security.MessageDigest

/**
 * The app against a real caracole serve, on a device or an emulator:
 *
 *     adb shell am instrument -w -e server http://10.0.2.2:8741 \
 *         io.github.danielhp95.caracole.test/androidx.test.runner.AndroidJUnitRunner
 *
 * (`-e shots 6000` holds each screen 6 s after logging "CARACOLE-SHOT <name>", for screenshots taken from the
 * host.) It syncs a fresh copy, runs Settings' Test, opens the library page and a sheet viewer from it, and
 * records what the viewer's sandbox does, that its script transposes, and that a PDF (a link) and a Guitar Pro
 * file (a download link) go to another app. Every ACTION_VIEW is stubbed: nothing outside the app opens. Without
 * `server` it is skipped.
 */
@RunWith(AndroidJUnit4::class)
class EndToEndTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val args = InstrumentationRegistry.getArguments()
    private val server: String? = args.getString("server")
    private val hold: Long = args.getString("shots")?.toLongOrNull() ?: 0L
    private val found = JSONObject()

    @Before
    fun aServerIsGiven() = assumeTrue("needs -e server http://10.0.2.2:<port>", server != null)

    @Test
    fun syncsThenShowsTheLibraryAndAViewerOfflineAndHandsFilesOff() {
        // A fresh copy, synced as Sync now does.
        val mirror = Caracole.mirror(context)
        File(context.filesDir, "blobs").deleteRecursively()
        File(context.filesDir, "manifest.json").delete()
        mirror.reload()
        Settings(context).server = server!!
        val outcome = Syncs.run(context, probe = false)!!
        record("sync", outcome.text)
        assertTrue(outcome.text, outcome.ok)
        val manifest = mirror.reload()!!
        record("files", manifest.entries.size)
        assertTrue(manifest.entries.all { mirror.blob(it.sha256).isFile })

        ActivityScenario.launch(SettingsActivity::class.java).use { settings ->
            onView(withId(R.id.test)).perform(click())
            var said = ""
            waitUntil("Test's answer") {
                settings.onActivity { said = it.findViewById<TextView>(R.id.test_result).text.toString() }
                said.startsWith("caracole answered")
            }
            record("test", said)
            shot("settings")
        }

        ActivityScenario.launch(MainActivity::class.java).use { main ->
            val js = { script: String -> evaluate(main, script) }
            val loaded = { suffix: String ->
                waitUntil("$suffix loaded") {
                    val at = url(main)
                    val state = js("document.readyState")
                    Log.d(TAG, "at $at, $state")
                    at.substringBefore('#').substringBefore('?').endsWith(suffix) && state == "complete"
                }
            }

            loaded(Links.address(manifest.start).substringAfterLast('/'))
            assertEquals(Links.address(manifest.start), url(main).substringBefore('#'))
            val library = JSONObject(js("""JSON.stringify({origin: window.origin,
                sheets: document.querySelectorAll('a[href$="sheet.html"]').length,
                downloads: Array.from(document.querySelectorAll('a[download]')).map(a => a.getAttribute('href'))})""") as String)
            record("library", library)
            assertEquals("https://${Links.HOST}", library.getString("origin"))
            assertTrue("the library page lists sheets", library.getInt("sheets") > 0)
            shot("library")

            // A sheet viewer, opened by a tap on the library page's link.
            val sheetHref = js("""document.querySelector('a[href$="sheet.html"]').href""") as String
            tap(main, """a[href$="sheet.html"]""")
            loaded("sheet.html")
            assertEquals(sheetHref.substringBefore('#'), url(main).substringBefore('#'))
            waitUntil("the viewer's script") { (js("(document.getElementById('key-now') || {}).textContent || ''") as String).isNotEmpty() }
            val sandbox = JSONObject(js("""JSON.stringify({origin: String(window.origin),
                storage: (() => { try { localStorage.length; return 'allowed'; } catch (e) { return 'refused: ' + e.name; } })(),
                cookie: (() => { try { document.cookie; return 'allowed'; } catch (e) { return 'refused: ' + e.name; } })(),
                serverLinks: Array.from(document.querySelectorAll('a[href]')).filter(a => !a.hidden)
                    .map(a => a.getAttribute('href')).filter(h => /^\/(export|versions|guitar)/.test(h)),
                hiddenServerLinks: Array.from(document.querySelectorAll('a[href]')).filter(a => a.hidden)
                    .map(a => a.getAttribute('href')).filter(h => /^\/(export|versions|guitar)/.test(h)),
                exportShown: (() => { const e = document.getElementById('export'); return !!e && !e.hidden; })()})""") as String)
            record("viewer", sandbox)
            assertEquals("no link to caracole serve's own pages", 0, sandbox.getJSONArray("serverLinks").length())
            assertFalse("no Export PDF link", sandbox.getBoolean("exportShown"))
            shot("sheet")

            // Its script runs: one semitone up changes the key and the chords shown, and the address keeps it.
            val shown = "JSON.stringify({key: document.getElementById('key-now').textContent, " +
                "chords: Array.from(document.querySelectorAll('.c')).slice(0, 4).map(c => c.textContent).join(' '), hash: location.hash})"
            val before = JSONObject(js(shown) as String)
            tap(main, "#t-up")
            waitUntil("the transposition") { JSONObject(js(shown) as String).getString("key") != before.getString("key") }
            val after = JSONObject(js(shown) as String)
            record("transpose", JSONObject().put("before", before).put("after", after))
            assertTrue(after.getString("chords") != before.getString("chords"))
            assertTrue(after.getString("hash").contains("t=1"))
            shot("sheet-transposed")

            Intents.init()
            try {
                intending(anyOf(hasAction(Intent.ACTION_VIEW), hasAction(Intent.ACTION_CHOOSER))).respondWith(Instrumentation.ActivityResult(Activity.RESULT_OK, null))

                // The viewer's PDF link: a navigation, which goes to another app; the viewer stays.
                val folder = sheetHref.removePrefix("https://${Links.HOST}/").substringBeforeLast('/')
                val pdfPath = java.net.URLDecoder.decode(folder, "UTF-8") + "/sheet.pdf"
                val pdfLink = js("""(() => { const a = document.querySelector('a[href$=".pdf"]'); return a ? a.getAttribute('href') : null; })()""")
                record("pdfLink", pdfLink ?: "none")
                if (pdfLink != null) tap(main, """a[href$=".pdf"]""") else js("location.href = 'sheet.pdf'")
                val pdf = handedOff("application/pdf")
                checkCopy(pdf, manifest.byPath.getValue(pdfPath).sha256)
                record("pdf", JSONObject().put("uri", pdf.data.toString()).put("type", pdf.type).put("flags", pdf.flags))
                assertTrue(pdf.flags and Intent.FLAG_GRANT_READ_URI_PERMISSION != 0)
                assertFalse("a PDF goes straight to the app that opens PDFs", "application/pdf" in chosen)
                assertTrue(url(main).substringBefore('#').endsWith("sheet.html"))

                // Back goes back in the WebView: to the library page.
                instrumentation.uiAutomation.executeShellCommand("input keyevent KEYCODE_BACK").close()
                loaded(Links.address(manifest.start).substringAfterLast('/'))
                record("back", url(main))

                // The library page's Guitar Pro link, which has `download`: the download listener hands it off.
                val gp = library.getJSONArray("downloads")
                if (gp.length() > 0) {
                    val href = gp.getString(0)
                    val sent = Intents.getIntents().size
                    if (!tap(main, "a[download]", optional = true)) js("document.querySelector('a[download]').click()")
                    val file = handedOff(null, since = sent)
                    val path = java.net.URLDecoder.decode(href, "UTF-8")
                    checkCopy(file, manifest.byPath.getValue(path).sha256)
                    record("download", JSONObject().put("href", href).put("uri", file.data.toString()).put("type", file.type)
                        .put("chooser", file.type in chosen))
                    assertTrue("a file of no known type goes through a chooser", file.type in chosen)

                    // That song's viewer links its Guitar Pro file too, in its settings panel: with `download` now
                    // (as from a file), in a page sandboxed without allow-downloads. Recorded, not asserted.
                    val viewer = Links.address(path.substringBeforeLast('/') + "/sheet.html")
                    main.onActivity { it.findViewById<WebView>(R.id.web).loadUrl(viewer) }
                    loaded("sheet.html")
                    waitUntil("the viewer's script") { (js("(document.getElementById('key-now') || {}).textContent || ''") as String).isNotEmpty() }
                    tap(main, "#more")
                    waitUntil("the settings panel") { js("(() => { const r = document.getElementById('guitar-row'); return !!r && !r.hidden && r.getBoundingClientRect().height > 0; })()") == true }
                    val link = js("""(() => { const a = document.querySelector('#guitar-links a'); return a ? JSON.stringify({href: a.getAttribute('href'), download: a.getAttribute('download'), text: a.textContent}) : null; })()""")
                    val before = Intents.getIntents().size
                    tap(main, "#guitar-links a")
                    val reached = try {
                        handedOff(null, since = before, timeoutMs = 8_000).type
                    } catch (e: AssertionError) {
                        null
                    }
                    record("viewerGuitar", JSONObject().put("link", link ?: "none").put("handedOff", reached ?: "nothing: the tap opened no app"))
                    shot("viewer-guitar")
                    instrumentation.uiAutomation.executeShellCommand("input keyevent KEYCODE_BACK").close()
                    loaded(Links.address(manifest.start).substringAfterLast('/'))
                }
            } finally {
                Intents.release()
            }

            // Back on the library page, with nothing to go back to, leaves.
            instrumentation.uiAutomation.executeShellCommand("input keyevent KEYCODE_BACK").close()
            waitUntil("the app to leave") { main.state == androidx.lifecycle.Lifecycle.State.DESTROYED }
            record("left", main.state.toString())
        }
        Log.i(TAG, "RESULT $found")
        // The research's open question, answered last so that every other check above ran and was recorded.
        assertEquals("the viewer runs in a sandbox, an opaque origin", "null", found.getJSONObject("viewer").getString("origin"))
        assertFalse(found.getJSONObject("viewer").getString("storage") == "allowed")
    }

    /**
     * Taps the page's first element matching [selector] as a finger would (`input tap`, so the page sees a user's
     * gesture), scrolled into view first; with [optional], false when it isn't on the screen to tap.
     */
    private fun tap(main: ActivityScenario<MainActivity>, selector: String, optional: Boolean = false): Boolean {
        val where = evaluate(main, """(() => { const e = document.querySelector(${JSONObject.quote(selector)});
            if (!e) return null; e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect();
            return r.width && r.height ? JSON.stringify({x: r.left + r.width / 2, y: r.top + r.height / 2}) : null; })()""")
        if (where == null) {
            check(optional) { "nothing to tap: $selector" }
            return false
        }
        Thread.sleep(300) // the scroll settles
        val at = JSONObject(evaluate(main, """(() => { const r = document.querySelector(${JSONObject.quote(selector)}).getBoundingClientRect();
            return JSON.stringify({x: r.left + r.width / 2, y: r.top + r.height / 2}); })()""") as String)
        // CSS pixels to the screen's: the WebView's width over the page's.
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
        return true
    }

    /**
     * The ACTION_VIEW the app sent (of [type], when given; after the first [since] intents), on its own or in a
     * chooser, waited for.
     */
    private fun handedOff(type: String?, since: Int = 0, timeoutMs: Long = 30_000): Intent {
        var intent: Intent? = null
        waitUntil("a file handed to another app", timeoutMs) {
            intent = Intents.getIntents().drop(since)
                .map { sent ->
                    if (sent.action != Intent.ACTION_CHOOSER) sent
                    else (@Suppress("DEPRECATION") sent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT))?.also { chosen.add(it.type) }
                }
                .lastOrNull { it != null && it.action == Intent.ACTION_VIEW && (type == null || it.type == type) }
            intent != null
        }
        return intent!!
    }

    /** The types of the files handed over through a chooser. */
    private val chosen = mutableSetOf<String?>()

    /** The bytes another app reads through the intent's URI are the file's, as listed. */
    private fun checkCopy(intent: Intent, sha256: String) {
        val bytes = context.contentResolver.openInputStream(intent.data!!)!!.use { it.readBytes() }
        val got = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
        assertEquals(sha256, got)
    }

    private fun record(name: String, value: Any) {
        found.put(name, value)
        Log.i(TAG, "$name: $value")
    }

    private fun shot(name: String) = Pages.shot(name, hold)

    private companion object {
        const val TAG = "CaracoleE2E"
    }
}
