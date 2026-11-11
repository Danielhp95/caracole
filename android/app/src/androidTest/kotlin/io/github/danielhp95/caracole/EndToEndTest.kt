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
import org.json.JSONArray
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
 * host.) It syncs a fresh copy, runs Settings' Test, opens the library page (the phone's own server's, at its
 * origin, http://127.0.0.1:8738) and a sheet viewer from it, and records what the viewer's sandbox does, that its
 * Export PDF is the phone's own route (here, a copy of pages with no song, its 404) and each other link it shows to
 * caracole serve's own pages is answered by the phone's stub ("… isn't on the phone yet."), that its script transposes, and that a PDF (a link) and a Guitar Pro file (a download link) go to another app, read from
 * the phone's server with the launch's cookie. Every ACTION_VIEW is stubbed: nothing outside the app opens. Without
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

        val origin = Pages.origin()
        val libraryPage = Pages.address("")
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

            loadedAt(main, libraryPage)
            assertEquals(libraryPage, url(main).substringBefore('#'))
            val library = JSONObject(js("""JSON.stringify({origin: window.origin,
                sheets: document.querySelectorAll('a[href$="sheet.html"]').length,
                downloads: Array.from(document.querySelectorAll('a[download]')).map(a => a.getAttribute('href'))})""") as String)
            record("library", library)
            assertEquals("the phone's own server's origin", origin, library.getString("origin"))
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
            // Served from the phone's own server, the viewer links caracole serve's own pages (Export PDF, a version's,
            // the Guitar Pro page) as it does on the computer. Export PDF is the phone's own route (ExportRoutes: the
            // version named, {name, label}, which the app prints, for a song of the phone's library): this sync took
            // the computer's pages alone, no song, so it says the library has no such sheet (404). The Guitar Pro page
            // is the phone's own too (GuitarRoutes): a file only the copy of the computer's pages holds, as this test's
            // sync of the copy alone leaves it, is the file itself (303 to the file's own address), which the app hands
            // to another app; the page itself (200) is GuitarPageTest's. A version's page is the phone's own as well
            // (VersionsRoutes), of a viewer the phone made: a copy's names no sheet of its (404; VersionsPageTest's
            // viewer is the phone's). The phone answers each other with its stub: the message page, 409, "… isn't on
            // the phone yet." (Stubs).
            val serverLinks = sandbox.getJSONArray("serverLinks")
            val answered = JSONObject()
            for (i in 0 until serverLinks.length()) {
                val href = serverLinks.getString(i)
                val (status, text, location) = stubbed(origin + href)
                answered.put(href, status)
                if (href.startsWith("/export.pdf?") || href.startsWith("/versions?")) {
                    assertEquals("$href on the phone: $text", 404, status)
                    assertTrue("$href: $text", "no such sheet in the library" in text)
                    continue
                }
                if (href.startsWith("/guitar")) {
                    assertEquals("$href on the phone", 303, status)
                    val file = android.net.Uri.parse(href).getQueryParameter("file")
                    assertTrue("$href names a file", !file.isNullOrEmpty())
                    assertEquals("$href goes to its file", "/$file", location?.let { android.net.Uri.decode(it) })
                    continue
                }
                assertEquals("$href on the phone", 409, status)
                assertTrue("$href: $text", "on the phone yet" in text)
            }
            record("server links", answered)
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
            // One up from where the sheet was: from its own version's move (a song's [version] opens at its t=), or 0.
            val t = { hash: String -> Regex("(?:^#|&)t=(-?\\d+)").find(hash)?.groupValues?.get(1)?.toInt() ?: 0 }
            assertEquals(after.getString("hash"), t(before.getString("hash")) + 1, t(after.getString("hash")))
            shot("sheet-transposed")

            Intents.init()
            try {
                intending(anyOf(hasAction(Intent.ACTION_VIEW), hasAction(Intent.ACTION_CHOOSER))).respondWith(Instrumentation.ActivityResult(Activity.RESULT_OK, null))

                // The viewer's PDF link: a navigation, which goes to another app; the viewer stays.
                val folder = sheetHref.removePrefix("$origin/").substringBeforeLast('/')
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
                loadedAt(main, libraryPage)
                record("back", url(main))

                // The library page's Guitar Pro link, which has `download`: the download listener hands it off.
                // (Its first such link that is a Guitar Pro file: the page gives its PDFs and texts `download` too.)
                val downloads = library.getJSONArray("downloads")
                val gp = (0 until downloads.length()).map { downloads.getString(it) }
                    .filter { Regex("\\.(gp[345x]?|ptb)$", RegexOption.IGNORE_CASE).containsMatchIn(it) }
                record("guitarPro", JSONArray(gp))
                if (gp.isNotEmpty()) {
                    val href = gp.first()
                    val gpLink = "a[download][href=${JSONObject.quote(href)}]"
                    val sent = Intents.getIntents().size
                    if (!tap(main, gpLink, optional = true)) js("document.querySelector(${JSONObject.quote(gpLink)}).click()")
                    val file = handedOff(null, since = sent)
                    val path = java.net.URLDecoder.decode(href, "UTF-8")
                    checkCopy(file, manifest.byPath.getValue(path).sha256)
                    record("download", JSONObject().put("href", href).put("uri", file.data.toString()).put("type", file.type)
                        .put("chooser", file.type in chosen))
                    assertTrue("a file of no known type goes through a chooser", file.type in chosen)

                    // That song's viewer links its Guitar Pro file too, in its settings panel: with `download` now
                    // (as from a file), in a page sandboxed without allow-downloads. Recorded, not asserted.
                    val viewer = Pages.address(path.substringBeforeLast('/') + "/sheet.html")
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
                    record("viewerGuitar", JSONObject().put("link", link ?: "none").put("handedOff", reached ?: "nothing: the tap opened no app")
                        .put("at", url(main)))
                    shot("viewer-guitar")
                    // Served, the link is the Guitar Pro page's (/guitar): the phone's own page, or, for a file only the
                    // copy holds, the file itself; a page opened is one more to go back from.
                    instrumentation.uiAutomation.executeShellCommand("input keyevent KEYCODE_BACK").close()
                    waitUntil("back from the Guitar Pro link") {
                        val at = url(main).substringBefore('#')
                        (at == libraryPage || at.endsWith("sheet.html")) && js("document.readyState") == "complete"
                    }
                    if (url(main).substringBefore('#').endsWith("sheet.html")) {
                        instrumentation.uiAutomation.executeShellCommand("input keyevent KEYCODE_BACK").close()
                    }
                    loadedAt(main, libraryPage)
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

    /** [url]'s status and text, asked of the phone's server with the launch's cookie, as the WebView asks it. */
    private fun stubbed(url: String): Triple<Int, String, String?> {
        val connection = java.net.URL(url).openConnection() as java.net.HttpURLConnection
        try {
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Cookie", "${io.github.danielhp95.caracole.server.http.Security.SECRET_COOKIE}=${Caracole.secret}")
            val status = connection.responseCode
            val body = (if (status >= 400) connection.errorStream else connection.inputStream)?.use { it.readBytes() } ?: ByteArray(0)
            return Triple(status, body.toString(Charsets.UTF_8), connection.getHeaderField("Location"))
        } finally {
            connection.disconnect()
        }
    }

    /** The page at [address] (its fragment aside) once it has loaded: the document shown says so itself, by its own
     * location. WebView.getUrl names a navigation the app started while it is still pending, and until it commits the
     * document shown is the blank one before it, complete and of origin null (a slow answer read it so: no sheet, origin
     * "null"). */
    private fun loadedAt(main: ActivityScenario<MainActivity>, address: String) = waitUntil("$address loaded") {
        val shown = evaluate(main, "document.readyState === 'complete' ? location.href : ''") as? String
        url(main).substringBefore('#') == address && shown?.substringBefore('#') == address
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
