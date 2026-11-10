package io.github.danielhp95.caracole

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.util.Log
import android.webkit.WebView
import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.intent.Intents
import androidx.test.espresso.intent.Intents.intending
import androidx.test.espresso.intent.matcher.IntentMatchers.hasAction
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.evaluate
import io.github.danielhp95.caracole.Pages.url
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.server.guitar.AlphaTabBundle
import kotlinx.serialization.json.JsonObject
import org.hamcrest.Matchers.anyOf
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.net.URLEncoder
import java.security.MessageDigest
import java.util.Base64

/**
 * The Guitar Pro page on the phone, on a device or an emulator, with no computer:
 *
 *     android/scripts/device-test.sh io.github.danielhp95.caracole.GuitarPageTest
 *
 * The APK holds alphaTab's bundle as caracole's web/alphatab.py builds it from nix/alphatab.nix's files, byte for byte
 * (tests/conformance/vectors/web/guitar.jsonl's record of them), beside their MPL-2.0, OFL and Apache-2.0 notices, and
 * the build's resource names it. A song's Guitar Pro file kept in the phone's library opens on the phone's own page
 * (GuitarRoutes) in the library screen's WebView: sandboxed, an opaque origin, its bundle answered from the APK by
 * AlphaTabAssets (the page's request carries no launch cookie) and checked by its integrity, alphaTab drawing the
 * score with the font its policy allows by hash and its synthesizer's worker ready; Play plays and Stop stops; its
 * Download hands the file to another app; and the library page says the phone shows Guitar Pro files
 * (`server.guitar`).
 */
@RunWith(AndroidJUnit4::class)
class GuitarPageTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val found = JSONObject()

    /** guitar.jsonl's record of alphaTab 1.8.4's own bundle (the test APK's assets: conformance/). */
    private val nix: JSONObject by lazy {
        instrumentation.context.assets.open("conformance/web/guitar.jsonl").bufferedReader().useLines { lines ->
            lines.map { JSONObject(it) }.first { it.optString("case") == "nix/alphatab.nix" }
        }
    }

    @Test fun theApkHoldsTheBundleAlphatabBuildsWithItsLicencesAndItsResourceNamesIt() {
        val out = nix.getJSONObject("out")
        val name = out.getString("name")
        val assets = context.assets
        assertEquals(listOf(name, "licenses"), assets.list(AlphaTabAssets.FOLDER)!!.sorted())
        val body = assets.open("${AlphaTabAssets.FOLDER}/$name").use { it.readBytes() }
        assertEquals(out.getInt("length"), body.size)
        assertEquals(out.getString("sha256"), hex(sha256(body)))
        assertEquals(out.getString("integrity"), "sha256-" + Base64.getEncoder().encodeToString(sha256(body)))
        val licences = nix.getJSONObject("licenses")
        assertEquals(licences.keys().asSequence().sorted().toList(), assets.list("${AlphaTabAssets.FOLDER}/licenses")!!.sorted())
        for (licence in licences.keys()) {
            val bytes = assets.open("${AlphaTabAssets.FOLDER}/licenses/$licence").use { it.readBytes() }
            assertEquals(licence, licences.getString(licence), hex(sha256(bytes)))
        }
        val notices = licences.keys().asSequence().joinToString("\n") { licence ->
            assets.open("${AlphaTabAssets.FOLDER}/licenses/$licence").use { it.readBytes().toString(Charsets.UTF_8) }
        }
        for (said in listOf("MPL-2.0", "SIL OPEN FONT LICENSE", "Apache License, Version 2.0")) {
            assertTrue(said, said in notices)
        }
        assertNotNull("the build's resource names the bundle", AlphaTabBundle.installed())
        val installed = AlphaTabBundle.installed()!!
        assertEquals(name, installed.name)
        assertEquals(out.getString("integrity"), installed.integrity)
        assertEquals(out.getString("script_source"), installed.scriptSource)
        assertEquals(out.getString("font_face"), installed.fontFace)
    }

    @Test fun aGuitarProFileOpensOnThePhonesOwnPageDrawnAndPlayedByAlphaTabFromTheApk() {
        // A first start opens Settings when nothing is set up: an address keeps it closed (nothing is asked of it).
        Settings(context).server = "http://10.0.2.2:9"
        val phone = Caracole.phone(context)
        val data = instrumentation.context.assets.open("fixtures/guitar/synthetic.gp").use { it.readBytes() }
        val path = phone.parts.database.writeBlocking { db ->
            val song = phone.parts.store.add(db, "caracole tests", "Synthetic Étude", now = STAMP)
            val version = Versions.upsert(db, "gtptabs", "12", song.id, "guitar", "guitar-pro", 4.0, 0, 1, null,
                                          "https://gtptabs.com/tabs/12.html", JsonObject(emptyMap()), STAMP)
            Kept.keepFile(db, phone.parts.store, song, version, "guitar-1.gp", data, 1, STAMP)
            db.one("SELECT path FROM files WHERE song_id = ? AND name = ?", song.id, "guitar-1.gp") { it.text(0)!! }!!
        }
        val installed = AlphaTabBundle.installed()!!
        val page = Pages.origin() + "/guitar?file=" + URLEncoder.encode(path, "UTF-8")
        ActivityScenario.launch(MainActivity::class.java).use { main ->
            val js = { script: String -> evaluate(main, script) }
            waitUntil("the library page") {
                url(main).substringBefore('#') == Pages.address("") && js("document.readyState") == "complete"
            }
            assertEquals("the phone shows Guitar Pro files", true,
                         js("JSON.parse(document.getElementById('songs').textContent).server.guitar"))

            main.onActivity { it.findViewById<WebView>(R.id.web).loadUrl(page) }
            waitUntil("the Guitar Pro page") { url(main) == page && js("document.readyState") == "complete" }
            waitUntil("alphaTab to draw the score", 90_000) {
                js("Number(document.documentElement.dataset.rendered) >= 1 && !!document.querySelector('#score canvas, #score svg')") == true
            }
            val drawn = JSONObject(js("""JSON.stringify({origin: String(window.origin),
                status: document.getElementById('gp-status').textContent,
                failed: document.getElementById('gp-status').classList.contains('failed'),
                bundle: !!window.caracoleAlphaTab && !!window.alphaTab,
                script: (() => { const s = document.querySelector('script[src]'); return s ? [s.getAttribute('src'), s.integrity] : null; })(),
                tracks: document.querySelectorAll('#tracks .track').length,
                fontFace: [...document.querySelectorAll('style')].map((s) => s.textContent).filter((t) => t.includes('@font-face'))})""") as String)
            record("drawn", drawn)
            assertEquals("the page is sandboxed, an opaque origin", "null", drawn.getString("origin"))
            assertFalse(drawn.toString(), drawn.getBoolean("failed"))
            assertTrue("the bundle ran: answered from the APK, its integrity checked", drawn.getBoolean("bundle"))
            assertEquals(listOf(installed.href, installed.integrity),
                         drawn.getJSONArray("script").let { listOf(it.getString(0), it.getString(1)) })
            assertEquals("the synthetic score's five tracks", 5, drawn.getInt("tracks"))
            // The stylesheet alphaTab added for its font is the one the page's policy allows by its hash.
            val faces = drawn.getJSONArray("fontFace")
            assertEquals(1, faces.length())
            assertEquals(installed.fontFace,
                         "'sha256-" + Base64.getEncoder().encodeToString(sha256(faces.getString(0).toByteArray())) + "'")
            waitUntil("the synthesizer ready", 90_000) { js("document.documentElement.dataset.player") == "ready" }

            // Play plays, by a finger's tap (the page's AudioContext wants a user's gesture); Stop stops.
            tap(main, "#play")
            waitUntil("playing", 30_000) { js("document.documentElement.dataset.player") == "playing" }
            tap(main, "#stop")
            waitUntil("stopped", 30_000) { js("document.documentElement.dataset.player") != "playing" }
            record("player", js("document.documentElement.dataset.player") ?: "none")

            // Its Download link, in a sandbox that allows downloads: the file goes to another app.
            Intents.init()
            try {
                intending(anyOf(hasAction(Intent.ACTION_VIEW), hasAction(Intent.ACTION_CHOOSER)))
                    .respondWith(Instrumentation.ActivityResult(Activity.RESULT_OK, null))
                tap(main, "a.navlink[download]")
                val sent = handedOff()
                val bytes = context.contentResolver.openInputStream(sent.data!!)!!.use { it.readBytes() }
                assertEquals("the file's bytes", hex(sha256(data)), hex(sha256(bytes)))
                record("download", JSONObject().put("uri", sent.data.toString()).put("type", sent.type))
                assertEquals("the page stays", page, url(main))
            } finally {
                Intents.release()
            }
        }
        Log.i(TAG, "RESULT $found")
    }

    /** The page's first element matching [selector], tapped as a finger would (`input tap`: a user's gesture). */
    private fun tap(main: ActivityScenario<MainActivity>, selector: String) {
        val quoted = JSONObject.quote(selector)
        assertNotNull("nothing to tap: $selector", evaluate(main, "(() => { const e = document.querySelector($quoted); " +
            "if (!e) return null; e.scrollIntoView({block: 'center'}); return true; })()"))
        Thread.sleep(300) // the scroll settles
        val at = JSONObject(evaluate(main, "(() => { const r = document.querySelector($quoted).getBoundingClientRect(); " +
            "return JSON.stringify({x: r.left + r.width / 2, y: r.top + r.height / 2}); })()") as String)
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

    /** The ACTION_VIEW the app sent, on its own or in a chooser, waited for. */
    private fun handedOff(): Intent {
        var intent: Intent? = null
        waitUntil("a file handed to another app", 30_000) {
            intent = Intents.getIntents()
                .map { sent ->
                    if (sent.action != Intent.ACTION_CHOOSER) sent
                    else @Suppress("DEPRECATION") sent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                }
                .lastOrNull { it != null && it.action == Intent.ACTION_VIEW }
            intent != null
        }
        return intent!!
    }

    private fun record(name: String, value: Any) {
        found.put(name, value)
        Log.i(TAG, "$name: $value")
    }

    private fun sha256(bytes: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(bytes)

    private fun hex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it) }

    private companion object {
        const val TAG = "CaracoleGuitar"
        const val STAMP = "2026-10-01T00:00:00Z"
    }
}
