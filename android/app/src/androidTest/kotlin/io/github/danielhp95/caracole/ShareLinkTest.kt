package io.github.danielhp95.caracole

import android.content.Intent
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.evaluate
import io.github.danielhp95.caracole.Pages.url
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.server.jobs.JobCommands
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * A song's link shared to caracole as text, in the app (no computer; CaracoleTestRunner: every site refused):
 *
 *     android/scripts/device-test.sh ShareLinkTest
 *
 * The phone's database holds the search corpus's `ug` fixture (an index with Eagles - Hotel California). A share, as
 * Android's share sheet sends it to ShareLinkActivity (ACTION_SEND, text/plain), is logged under `caracole-share` as
 * it came, and opens on the library screen the page of what it names: what caracole read, the best match, its sites.
 * Get it posts the library page's own lookup, which lands on its line in the Requests tab and queues `caracole get`
 * with the index's song; Cancel takes the screen back to the library page; a link alone says so and offers Edit,
 * whose names are searched again.
 */
@RunWith(AndroidJUnit4::class)
class ShareLinkTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext

    @Before fun anIndex() {
        Corpus.open = { name -> runCatching { instrumentation.context.assets.open("conformance/$name") }.getOrNull() }
        val phone = Caracole.phone(context)
        // Once a process: the tests of a class share the app's database.
        phone.parts.database.writeBlocking { db ->
            if (db.one("SELECT COUNT(*) FROM ug_index") { it.long(0) } == 0L) Fixtures.load(db, "search/fixtures/ug.jsonl")
        }
        phone.search.invalidate()
    }

    /** What a music app's share sends caracole: ACTION_SEND of text/plain to the share target. */
    private fun shared(text: String, subject: String? = null): Intent =
        Intent(Intent.ACTION_SEND).setClass(context, ShareLinkActivity::class.java).setType("text/plain")
            .putExtra(Intent.EXTRA_TEXT, text)
            .apply { if (subject != null) putExtra(Intent.EXTRA_SUBJECT, subject) }
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

    private fun open(block: (ActivityScenario<MainActivity>) -> Unit) = ActivityScenario.launch(MainActivity::class.java).use {
        waitUntil("the library page") { url(it).startsWith(Pages.origin()) && evaluate(it, "document.readyState") == "complete" }
        block(it)
    }

    private fun shownAt(scenario: ActivityScenario<MainActivity>, what: String, part: String) =
        waitUntil(what) { url(scenario).contains(part) && evaluate(scenario, "document.readyState") == "complete" }

    private fun text(scenario: ActivityScenario<MainActivity>, selector: String): String =
        evaluate(scenario, "(document.querySelector('$selector') || {}).textContent || ''") as String

    @Test fun aSongSharedFromAMusicAppShowsItsBestMatchAndGetItLooksItUp() = open { scenario ->
        context.startActivity(shared("Eagles - Hotel California https://link.example/s/30x", subject = "Hotel California"))
        shownAt(scenario, "the share's page", "/share?")
        assertEquals("caracole read Eagles – Hotel California.", text(scenario, ".lede"))
        val best = text(scenario, ".reading.now")
        assertTrue(best, "Eagles - Hotel California" in best && "Ultimate Guitar" in best)

        evaluate(scenario, "document.querySelector('.reading.now button[type=submit]').click(); true")
        shownAt(scenario, "the lookup's line in the Requests tab", "#tab=requests&job=")
        val id = url(scenario).substringAfterLast("job=").toInt()
        val job = runBlocking { withTimeout(120_000) { Caracole.phone(context).queue.await(id) } }
        assertEquals(JobCommands.lookupSteps("Eagles", "Hotel California", ug = "eagles/hotel-california").map { it.args },
                     job.steps.map { it.args })
    }

    @Test fun cancelTakesTheScreenBackToTheLibraryAndTheAppThatSharedInFront() = open { scenario ->
        context.startActivity(shared("Eagles - Hotel California"))
        shownAt(scenario, "the share's page", "/share?")
        evaluate(scenario, "document.querySelector('a[href=\"/share/cancel\"]').click(); true")
        waitUntil("the library page again") { url(scenario).substringBefore('#').removeSuffix("/") == Pages.origin() }
        // The screen went behind the app that shared (here, the launcher): stopped, never finished.
        waitUntil("the screen behind") { scenario.state == Lifecycle.State.CREATED }
        context.startActivity(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        waitUntil("the screen in front again") { scenario.state == Lifecycle.State.RESUMED }
        assertTrue("the share page left the history", url(scenario).substringBefore('#').removeSuffix("/") == Pages.origin())
    }

    @Test fun aLinkAloneSaysSoAndEditSearchesTheNamesTyped() = open { scenario ->
        context.startActivity(shared("https://open.spotify.com/track/40riOy7x9W7GXjyGp4pjAv?si=1"))
        shownAt(scenario, "the share's page", "/share?")
        assertTrue(text(scenario, ".lede"), "a link alone, which names no song" in text(scenario, ".lede"))
        assertEquals(true, evaluate(scenario, "document.querySelector('details.picker[open] form[action=\"/share\"]') !== null"))
        evaluate(scenario, "(() => { const f = document.querySelector('form[action=\"/share\"]'); " +
            "f.artist.value = 'Eagles'; f.title.value = 'Hotel California'; f.submit(); return true; })()")
        shownAt(scenario, "the names searched", "artist=Eagles")
        assertEquals("caracole searched for Eagles – Hotel California.", text(scenario, ".lede"))
        assertTrue(text(scenario, ".reading.now").contains("Hotel California"))
    }

    @Test fun eachShareIsLoggedAsItCame() = open { scenario ->
        context.startActivity(shared("Listen to “Hotel California” https://x.example/1", subject = "Eagles"))
        shownAt(scenario, "the share's page", "/share?")
        val log = Runtime.getRuntime().exec(arrayOf("logcat", "-d", "-s", "${SharedLink.TAG}:I")).inputStream.use {
            BufferedReader(InputStreamReader(it)).readText()
        }
        assertTrue(log, "text=\"Listen to “Hotel California” https://x.example/1\" subject=\"Eagles\" title=null" in log)
    }
}
