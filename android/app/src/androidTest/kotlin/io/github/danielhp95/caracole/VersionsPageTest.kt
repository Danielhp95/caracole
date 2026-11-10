package io.github.danielhp95.caracole

import android.webkit.WebView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.evaluate
import io.github.danielhp95.caracole.Pages.url
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.testing.replays.ChoicesReplay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The versions page in the app (CaracoleTestRunner: every site refused):
 *
 *     android/scripts/device-test.sh VersionsPageTest          # the page, its form
 *     android/scripts/device-test.sh VersionsPageTest=DIR      # and from a sandboxed viewer, a computer's copy synced
 *
 * The phone's database holds the choices vectors' base library (De Música Ligera, its sheet the phone's viewer by its
 * record). A top-level navigation to `/versions?…` carries the launch's cookie, the page is the server's own with its
 * one form, and the form posts with the form token: the request queued under the song's key, the page following it
 * until it is over, its words read from the song's state. With `-e server`, a sheet viewer of the computer's copy,
 * in its sandbox (an opaque origin), reaches the page by a plain GET of its own, as its versions' links do: the
 * cookie, Lax, goes with a top-level navigation from any page. Without `server` that part is skipped.
 */
@RunWith(AndroidJUnit4::class)
class VersionsPageTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val server: String? = InstrumentationRegistry.getArguments().getString("server")

    @Before fun theLibrary() {
        Corpus.open = { name -> runCatching { instrumentation.context.assets.open("conformance/$name") }.getOrNull() }
        Corpus.openFixture = { name -> runCatching { instrumentation.context.assets.open("fixtures/$name") }.getOrNull() }
        // No Settings over the library screen: an address no computer answers, unless the test was given one.
        if (server == null && Settings(context).server.isBlank()) Settings(context).server = "http://127.0.0.1:9"
        // The vectors' base library in the phone's database, once a process (the tests of a class share it).
        val phone = Caracole.phone(context)
        phone.parts.database.writeBlocking { db ->
            if (Songs.byKey(db, Normalize.identityKey("Soda Stereo", "De Música Ligera")) == null) {
                Fixtures.loadRecords(db, ChoicesReplay.scene(ChoicesReplay.VERSIONS, "base"), phone.parts.store.libraryDir)
            }
        }
    }

    private fun versions(tab: String, doing: String): String =
        Pages.origin() + "/versions?" + PyUrl.urlencode(listOf("sheet" to SHEET, "tab" to tab, "do" to doing))

    private fun loaded(main: ActivityScenario<MainActivity>, starts: String) = waitUntil("$starts loaded") {
        url(main).startsWith(starts) && evaluate(main, "document.readyState") == "complete"
    }

    /** The library screen, once its start has shown the library page: nothing loads over a page opened after. */
    private fun started(body: (ActivityScenario<MainActivity>) -> Unit) =
        ActivityScenario.launch(MainActivity::class.java).use { main ->
            val library = Pages.address("")
            waitUntil("the library page") {
                url(main).substringBefore('#') == library && evaluate(main, "document.readyState") == "complete"
            }
            body(main)
        }

    private fun open(main: ActivityScenario<MainActivity>, address: String) =
        main.onActivity { it.findViewById<WebView>(R.id.web).loadUrl(address) }

    private fun text(main: ActivityScenario<MainActivity>): String = evaluate(main, "document.body.innerText") as String

    @Test fun aTopLevelGetReachesThePageAndItsFormPostsWithTheToken() = started { main ->
        val address = versions(OTHER, "keep")
        open(main, address)
        loaded(main, address)
        val title = evaluate(main, "document.title") as String
        assertTrue(title, "Keep a version · Soda Stereo - De Música Ligera" in title)
        val form = JSONObject(evaluate(main, """JSON.stringify({action: document.querySelector('form.confirm').action,
            token: document.querySelector('form.confirm input[name=csrf]').value})""") as String)
        assertEquals(Pages.origin() + "/versions/keep", form.getString("action"))
        assertTrue("the form carries the server's token", form.getString("token").length >= 32)

        evaluate(main, "document.querySelector('form.confirm button').click()")
        loaded(main, "$address&job=")
        val id = url(main).substringAfterLast("job=").toInt()
        val job = runBlocking { withTimeout(120_000) { Caracole.phone(context).queue.await(id) } }
        assertEquals(listOf("versions", "--keep=$OTHER", "--progress", "--", "Soda Stereo", "De Música Ligera"),
                     job.steps.single().args)
        // the page reloads while the request waits or runs, then says what it came to (every site refused: nothing
        // kept), from the song's state
        val said = if (job.state == Job.DONE) "Done, but it wasn't kept" else "Failed"
        waitUntil("the page to say \"$said\"", 60_000) {
            main.onActivity { it.findViewById<WebView>(R.id.web).reload() }
            Thread.sleep(500)
            said in text(main)
        }
    }

    @Test fun aSandboxedViewerReachesThePageByAPlainGet() {
        assumeTrue("needs -e server http://10.0.2.2:<port>", server != null)
        Settings(context).server = server!!
        val outcome = Syncs.run(context, probe = false)!!
        assertTrue(outcome.text, outcome.ok)
        val manifest = Caracole.mirror(context).reload()!!
        val sheet = manifest.entries.first { it.name == "sheet.html" }.path
        started { main ->
            val viewer = Pages.address(sheet)
            open(main, viewer)
            loaded(main, viewer)
            waitUntil("the viewer's script") { evaluate(main, "document.documentElement.dataset.ready === '1'") == true }
            assertEquals("the viewer runs in its sandbox", "null", evaluate(main, "String(window.origin)"))
            val address = versions(OTHER, "choose")
            evaluate(main, "location.assign(${JSONObject.quote(address.removePrefix(Pages.origin()))})")
            loaded(main, address)
            assertTrue(text(main), "Make this the one" in text(main))
            assertTrue("a page of the server's own", evaluate(main, "document.querySelector('form.confirm') !== null") == true)
        }
    }

    private companion object {
        const val SHEET = "Soda Stereo/De Música Ligera/sheet.html"
        const val OTHER = "1064463"
    }
}
