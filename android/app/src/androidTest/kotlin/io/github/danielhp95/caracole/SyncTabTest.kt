package io.github.danielhp95.caracole

import android.util.Log
import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.matcher.RootMatchers.isPlatformPopup
import androidx.test.espresso.matcher.ViewMatchers.withId
import androidx.test.espresso.matcher.ViewMatchers.withText
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

/**
 * The library page's Sync tab on the phone, against a real caracole serve (the computer that
 * `python -m tests.helpers.e2e_library serve DIR PORT` starts):
 *
 *     adb shell am instrument -w -e class io.github.danielhp95.caracole.SyncTabTest -e server http://10.0.2.2:PORT \
 *         io.github.danielhp95.caracole.test/androidx.test.runner.AndroidJUnitRunner
 *
 * The menu's Sync with the computer opens the tab, whose field offers the address Settings keeps. Compare lists what
 * differs; Sync (every conflict, if any, taking there's) queues the sync, whose stages run while the app's foreground
 * service names it, and whose end the tab shows. Then the computer is one the phone synced with (GET /api/sync), the
 * mirror holds its pages, the service has stopped, and a second comparison finds nothing that differs. Without
 * `server` it is skipped.
 */
@RunWith(AndroidJUnit4::class)
class SyncTabTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val server: String? = InstrumentationRegistry.getArguments().getString("server")
    private val found = JSONObject()

    @Before
    fun aServerIsGiven() = assumeTrue("needs -e server http://10.0.2.2:<port>", server != null)

    @Test
    fun theSyncTabComparesWithTheComputerInSettingsThenSyncs() {
        Settings(context).server = server!!
        val origin = Pages.origin()
        ActivityScenario.launch(MainActivity::class.java).use { main ->
            val js = { script: String -> evaluate(main, script) }
            waitUntil("the library page") { url(main).startsWith("$origin/") && js("document.readyState") == "complete" }

            // The menu's Sync with the computer: the library page at its Sync tab, the address Settings keeps in it.
            onView(withId(R.id.more)).perform(click())
            onView(withText(R.string.sync_with_computer)).inRoot(isPlatformPopup()).perform(click())
            waitUntil("the Sync tab") {
                url(main).endsWith("#tab=sync") && js("(() => { const p = document.getElementById('sync'); " +
                    "return !!p && !p.hidden; })()") == true
            }
            waitUntil("the address offered") { js("document.getElementById('sync-address').value") == server }

            compare(main)
            val differences = JSONObject(js("""JSON.stringify({rows: document.querySelectorAll('#sync-groups li').length,
                status: document.getElementById('sync-status').textContent,
                conflicts: !document.getElementById('sync-bulk').hidden})""") as String)
            record("compared", differences)
            if (differences.getBoolean("conflicts")) js("document.getElementById('sync-all-there').click()")
            waitUntil("Sync to be offered") { js("document.getElementById('sync-go').disabled") == false }

            // Sync: the job queued, its stages followed on the tab, the service naming it while it works.
            js("document.getElementById('sync-go').click()")
            val lines = mutableSetOf<String>()
            waitUntil("the sync to end", timeoutMs = 5 * 60_000) {
                Caracole.working()?.line?.value?.let(lines::add)
                js("!document.getElementById('sync-reload').hidden") == true
            }
            record("service lines", JSONArray(lines.toList()))
            val ended = JSONObject(js("""JSON.stringify({name: document.getElementById('sync-job-name').textContent,
                tone: document.getElementById('sync-job-line').dataset.tone,
                line: document.getElementById('sync-job-line').textContent,
                steps: Array.from(document.querySelectorAll('#sync-steps .step-chip')).map(c => c.className + ' ' + c.textContent),
                outcome: document.getElementById('sync-outcome').textContent})""") as String)
            record("synced", ended)
            assertTrue(ended.toString(), ended.getString("name").startsWith("Sync with "))
            assertFalse("the sync failed: $ended", ended.getString("tone") == "failed")
            val steps = ended.getJSONArray("steps")
            for (i in 0 until steps.length()) {
                val chip = steps.getString(i)
                assertTrue("every stage done or skipped: $chip", " done " in "$chip " || " plain " in "$chip ")
            }
            waitUntil("the service to stop") { Caracole.working()?.line?.value == null }

            // The computer is one the phone synced with, at the address the tab remembered for both syncs.
            js("""window.synced = null; fetch('/api/sync').then(r => r.json()).then(d => { window.synced = JSON.stringify(d); })""")
            waitUntil("GET /api/sync") { js("window.synced") != null }
            val sync = JSONObject(js("window.synced") as String)
            record("api sync", sync)
            val peers = sync.getJSONArray("peers")
            assertTrue("the computer synced with: $sync", peers.length() > 0)
            assertEquals(peers.getJSONObject(0).getString("address"), Settings(context).server)
            assertTrue("the mirror holds the computer's pages", Caracole.mirror(context).reload()?.entries?.isNotEmpty() == true)

            // Compared again: nothing differs.
            js("window.before = 1; document.getElementById('sync-reload').click()")
            waitUntil("the page again, at its Sync tab") {
                js("typeof window.before === 'undefined' && document.readyState === 'complete'") == true &&
                    js("(() => { const p = document.getElementById('sync'); " +
                       "return !!p && !p.hidden && document.getElementById('sync-address').value !== ''; })()") == true
            }
            compare(main)
            val again = js("document.getElementById('sync-status').textContent") as String
            record("compared again", again)
            assertTrue(again, again.startsWith("Nothing differs"))
        }
        Log.i(TAG, "RESULT $found")
    }

    /** Compare pressed, and its answer drawn (a failure said is a failed test). */
    private fun compare(main: ActivityScenario<MainActivity>) {
        evaluate(main, "document.getElementById('sync-compare').click()")
        waitUntil("the comparison", timeoutMs = 2 * 60_000) {
            evaluate(main, "(() => { const s = document.getElementById('sync-status'); " +
                "return s.dataset.tone === 'failed' || !document.getElementById('sync-found').hidden; })()") == true
        }
        val tone = evaluate(main, "document.getElementById('sync-status').dataset.tone")
        assertFalse("the comparison failed: " + evaluate(main, "document.getElementById('sync-status').textContent"),
                    tone == "failed")
    }

    private fun record(what: String, value: Any) {
        found.put(what, value)
        Log.i(TAG, "$what: $value")
    }

    private companion object {
        const val TAG = "CaracoleSyncTab"
    }
}
