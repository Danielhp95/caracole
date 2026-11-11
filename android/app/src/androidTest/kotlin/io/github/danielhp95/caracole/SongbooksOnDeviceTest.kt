package io.github.danielhp95.caracole

import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.evaluate
import io.github.danielhp95.caracole.Pages.url
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.core.songbooks.Songbook
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.testing.replays.SongbookTabReplay
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * The Songbooks tab on a device or an emulator, with no computer, the page's own scripts posting to the phone's own
 * server in the WebView:
 *
 *     android/scripts/device-test.sh io.github.danielhp95.caracole.SongbooksOnDeviceTest
 *
 * The songbook tab corpus's library (vectors/songbook/fixtures/entries-library.jsonl: sheets the computer kept and
 * rendered, in keys major and minor, with a capo) is put in the app's library. Then, as a hand would: + New songbook
 * turns Select on, two songs are picked in turn, the bar's name typed and Make songbook sent; the phone's queue runs
 * `caracole songbook make` (SongbookRunner), the songbook is made in that order (phone_songbooks) and the tab opens on
 * it. A song's chip sets the key the songbook plays it in (`songbook set`), which the set list then says; and the
 * songbook's Phone page, the songbook.html the phone made of it, opens in the WebView.
 */
@RunWith(AndroidJUnit4::class)
class SongbooksOnDeviceTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext

    @Test fun aSongbookMadeFromTheSelectBarPlaysASongInTheKeyItsChipSetsAndOpensItsPage() {
        Corpus.open = { name -> runCatching { instrumentation.context.assets.open("conformance/$name") }.getOrNull() }
        Corpus.openFixture = { name -> runCatching { instrumentation.context.assets.open("fixtures/$name") }.getOrNull() }
        val phone = Caracole.phone(context)
        val database = phone.parts.database
        val library = phone.parts.store.libraryDir
        val (soda, oasis) = database.writeBlocking { db ->
            fun id() = db.one("SELECT id FROM songs WHERE artist = ? AND title = ?", "Oasis", "Wonderwall") { it.long(0) }
            if (id() == null) Fixtures.load(db, SongbookTabReplay.LIBRARY, library)
            db.one("SELECT id FROM songs WHERE artist = ? AND title = ?", "Soda Stereo", "De Música Ligera") { it.long(0) }!! to id()!!
        }
        val before = database.read(Songbooks::all).map { it.name }

        ActivityScenario.launch(MainActivity::class.java).use { main ->
            fun js(script: String): Any? = evaluate(main, script)
            fun click(selector: String) {
                val clicked = js("""(() => { const e = document.querySelector(${JSONObject.quote(selector)});
                    if (!e) return false; e.scrollIntoView({block: 'center'}); e.click(); return true; })()""")
                assertEquals("nothing to click: $selector", true, clicked)
            }
            fun shown(selector: String): Boolean = js("""(() => { const e = document.querySelector(${JSONObject.quote(selector)});
                return Boolean(e && e.checkVisibility()); })()""") == true
            waitUntil("the library page") {
                url(main).startsWith("${Pages.origin()}/") && js("document.readyState") == "complete" &&
                    js("Boolean(document.getElementById('tab-songbooks'))") == true
            }

            // + New songbook: Select on, on the library; two songs picked, in this order; the bar's name; Make songbook.
            click("#tab-songbooks")
            waitUntil("the Songbooks tab") { shown("#songbooks .new-book") || shown("#songbooks .book-back") }
            if (!shown("#songbooks .new-book")) click("#songbooks .book-back")
            click("#songbooks .new-book")
            waitUntil("Select") { js("document.body.classList.contains('selecting')") == true }
            for (id in listOf(oasis, soda)) {
                waitUntil("song $id's box") { js("Boolean(document.querySelector('#list [data-id=\"$id\"] .pick input'))") == true }
                click("#list [data-id=\"$id\"] .pick input")
            }
            assertEquals("2 selected", js("document.querySelector('.pick-count').textContent"))
            js("""(() => { const name = document.querySelector('.pick-name'); name.value = 'Beach nights';
                name.dispatchEvent(new Event('input', {bubbles: true})); })()""")
            click(".pickbar-form button[type=submit]")

            // The phone's queue makes it, in the order picked, and the tab opens on it.
            waitUntil("the songbook made", timeoutMs = 60_000) {
                database.read(Songbooks::all).any { it.name == "Beach nights" } &&
                    phone.queue.snapshot().none { it.active }
            }
            val made = database.read(Songbooks::all).first { it.name == "Beach nights" }
            assertEquals(listOf("Oasis - Wonderwall", "Soda Stereo - De Música Ligera"), made.texts)
            assertEquals(before + "Beach nights", database.read(Songbooks::all).map(Songbook::name))
            val job = phone.queue.snapshot().filter { it.spec.kind == "songbook" }.maxBy { it.id }
            assertEquals(job.asJson().toString(), Job.DONE, job.state)
            waitUntil("the tab on the songbook") {
                js("(document.querySelector('#songbooks .book h2') || {}).textContent") == "Beach nights"
            }
            assertTrue("the songbook's page", File(library, "_songbooks/Beach nights/songbook.html").isFile)

            // Its chip: the key it plays Wonderwall in here.
            val line = "#songbooks .book .set-line[data-entry=\"Oasis - Wonderwall\"]"
            waitUntil("Wonderwall's chip") { js("(() => { const c = document.querySelector('$line button.plays'); return Boolean(c && !c.disabled); })()") == true }
            val was = js("document.querySelector('$line .plays').textContent") as String
            click("$line button.plays")
            waitUntil("its menus") { js("Boolean(document.querySelector('$line .set-edit'))") == true }
            js("""(() => { const form = document.querySelector('$line .set-edit');
                form.elements.key.value = 'A'; form.elements.key.dispatchEvent(new Event('change', {bubbles: true})); })()""")
            click("$line .set-edit button[type=submit]")
            waitUntil("the key set", timeoutMs = 60_000) {
                database.read(Songbooks::all).first { it.name == "Beach nights" }.songs.first().setting?.key == "A" &&
                    phone.queue.snapshot().none { it.active }
            }
            waitUntil("the set list to say it") {
                val now = js("document.querySelector('$line .plays').textContent") as? String
                now != null && now != was && now.startsWith("A ")
            }

            // Its Phone page, the songbook.html the phone made, opened in the WebView.
            waitUntil("its Phone page's link") { js("Boolean(document.querySelector('#songbooks .book-files a[href$=\"songbook.html\"]'))") == true }
            val address = Pages.address("_songbooks/Beach nights/songbook.html")
            click("#songbooks .book-files a[href$=\"songbook.html\"]")
            waitUntil("the songbook's page") {  // the document shown says so itself, by its own location
                val shownAt = js("document.readyState === 'complete' ? location.href : ''") as? String
                url(main).substringBefore('#') == address && shownAt?.substringBefore('#') == address
            }
            waitUntil("its songs") {
                val text = js("document.body ? document.body.textContent : ''") as? String
                text != null && "Wonderwall" in text && "De Música Ligera" in text
            }
        }
    }
}
