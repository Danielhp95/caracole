package io.github.danielhp95.caracole

import android.Manifest
import android.app.Activity
import android.app.Notification
import android.app.NotificationManager
import android.net.Uri
import android.os.Build
import android.util.Log
import android.webkit.WebView
import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.matcher.ViewMatchers.withId
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.server.http.Security
import io.github.danielhp95.caracole.server.jobs.Job
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.FixMethodOrder
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.MethodSorters
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * The bar's sync button and the library page's sync sheet on the phone, against a real caracole serve (the computer
 * `python -m tests.helpers.e2e_library serve DIR PORT` starts), as android/scripts/device-test.sh runs it:
 *
 *     android/scripts/device-test.sh --computer "$(mktemp -d)" io.github.danielhp95.caracole.SyncSheetTest
 *
 * Each test agrees with the computer first (Sync on Wi-Fi's sync, [Syncs.run]), then changes one song on both sides
 * so that the next sync finds it changed on both: Make this my version of its sheet on the phone (the phone's own
 * `GET /export.pdf?…&mine=1`) and on the computer (caracole serve's, which renders the PDF there and asks no site),
 * each in another key. The button opens the sheet, which compares; Sync shows the conflict's card, its two sides
 * Phone and Computer; the computer's kept, the summary says so, and the two then agree. A sync on Wi-Fi leaves such a
 * conflict as it is and says so in a notification, whose tap opens the sheet, Sync its card. The computer's song keeps
 * the last key it was given (this class changes one song's [version] on the computer it shares with the classes after
 * it). Without `server` it is skipped.
 */
@RunWith(AndroidJUnit4::class)
@FixMethodOrder(MethodSorters.NAME_ASCENDING)
class SyncSheetTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val server: String? = InstrumentationRegistry.getArguments().getString("server")
    private val found = JSONObject()

    @Before
    fun setUp() {
        assumeTrue("needs -e server http://10.0.2.2:<port>", server != null)
        SyncDevice.mayNotify()
    }

    @Test
    fun theBarsButtonOpensTheSheetAConflictsCardNamesPhoneAndComputerAndTheSummaryShowsWhatItDid() {
        val song = SyncDevice.conflicted(server!!, phoneMove = 1, computerMove = 2) { what, value -> record(what, value) }
        ActivityScenario.launch(MainActivity::class.java).use { main ->
            val sheet = SyncSheet { script -> Pages.evaluate(main, script) }
            sheet.libraryLoaded()

            // The bar's sync button: the sheet, which compares with the computer Settings names.
            onView(withId(R.id.sync)).perform(click())
            val compared = sheet.compared()
            record("compared", compared)
            assertTrue(compared.toString(), compared.getString("title").startsWith("Sync with "))
            assertEquals("the song changed on both sides: $compared", 1, compared.getInt("both"))

            // Sync: its card first, this phone on the left, the computer on the right.
            sheet.click("sync-go")
            val card = sheet.card()
            record("card", card)
            assertEquals("Phone", card.getString("here"))
            assertEquals("Computer", card.getString("there"))
            assertEquals("On the phone", card.getString("hereOn"))
            assertEquals("On the computer", card.getString("thereOn"))
            assertEquals("1 of 1", card.getString("at"))
            assertTrue(card.toString(), song.title in card.getString("name"))
            waitUntil("both versions read") { sheet.card().getString("lines") == "" }
            record("card read", sheet.card())

            // The computer's kept: the sync runs, and its summary says what it did.
            sheet.click("sync-keep-there")
            val done = sheet.done()
            record("done", done)
            assertEquals("Synced with: Computer", done.getString("title"))
            val conflicts = done.getJSONArray("sections").objects().single { it.getString("kind") == "conflicts" }
            assertEquals("1 conflict · computer's kept", conflicts.getString("said"))
            assertTrue(conflicts.toString(), conflicts.getJSONArray("rows").getString(0).startsWith(song.title))
            assertFalse("no given arrow from a file: this is the computer", done.getBoolean("fileNote"))

            // Done; then the button again: the two agree on everything the sheet syncs.
            sheet.click("sync-go")
            waitUntil("the sheet closed") { !sheet.state().getBoolean("open") }
            onView(withId(R.id.sync)).perform(click())
            val again = sheet.compared()
            record("compared again", again)
            assertEquals(again.toString(), listOf(0, 0, 0), listOf(again.getInt("take"), again.getInt("give"), again.getInt("both")))
            sheet.click("sync-cancel")
        }
        Log.i(TAG, "RESULT $found")
    }

    @Test
    fun theNotificationOfASyncThatLeftAConflictOpensTheSheetAtItsCard() {
        val song = SyncDevice.conflicted(server!!, phoneMove = 3, computerMove = 4) { what, value -> record(what, value) }
        val notifications = context.getSystemService(NotificationManager::class.java)
        notifications.cancel(Notifications.CONFLICTS)

        // Sync on Wi-Fi's sync: the conflict left as it is on both sides, and said in a notification.
        val outcome = runBlocking { Syncs.run(context, probe = false) }!!
        record("unattended", outcome.text)
        assertTrue(outcome.text, outcome.ok)
        assertTrue(outcome.text, outcome.text.endsWith("1 changed on both sides: tap Sync to choose"))
        val posted = notifications.activeNotifications.single { it.id == Notifications.CONFLICTS }.notification
        val text = posted.extras.getCharSequence(Notification.EXTRA_TEXT).toString()
        record("notification", text)
        assertEquals("1 song changed on both sides: tap to choose", text)
        assertEquals(Notifications.SYNCS, posted.channelId)

        // Its tap: the library screen, the app not on the screen, at the sheet, which compares; Sync, its card.
        posted.contentIntent.send()
        val main = resumedMain()
        try {
            val sheet = SyncSheet { script -> evaluate(main, script) }
            val compared = sheet.compared()
            record("compared", compared)
            assertEquals(compared.toString(), 1, compared.getInt("both"))
            sheet.click("sync-go")
            val card = sheet.card()
            record("card", card)
            assertTrue(card.toString(), song.title in card.getString("name"))
            assertEquals("Phone", card.getString("here"))
            assertEquals("Computer", card.getString("there"))
            // Cancel: nothing taken or given, the conflict left for another time.
            sheet.click("sync-cancel")
            waitUntil("the sheet closed") { !sheet.state().getBoolean("open") }
        } finally {
            instrumentation.runOnMainSync { main.finish() }
        }
        Log.i(TAG, "RESULT $found")
    }

    /** The library screen a notification's tap opened (no scenario of the test's). */
    private fun resumedMain(): MainActivity {
        var shown: MainActivity? = null
        waitUntil("the library screen, opened by the notification") {
            instrumentation.runOnMainSync {
                shown = ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED)
                    .filterIsInstance<MainActivity>().firstOrNull()
            }
            shown != null
        }
        return shown!!
    }

    private fun evaluate(activity: Activity, script: String): Any? {
        var raw: String? = null
        val latch = CountDownLatch(1)
        instrumentation.runOnMainSync {
            activity.findViewById<WebView>(R.id.web).evaluateJavascript(script) { raw = it; latch.countDown() }
        }
        check(latch.await(10, TimeUnit.SECONDS)) { "no answer from the page to: $script" }
        val value = (JSONTokener("[${raw ?: "null"}]").nextValue() as JSONArray).get(0)
        return if (value == JSONObject.NULL) null else value
    }

    private fun record(what: String, value: Any) {
        found.put(what, value)
        Log.i(TAG, "$what: $value")
    }

    private companion object {
        const val TAG = "CaracoleSyncSheet"
    }
}

/** A JSON array's objects. */
internal fun JSONArray.objects(): List<JSONObject> = (0 until length()).map { getJSONObject(it) }

/**
 * The library page's sync sheet (library_assets/sync-sheet.html, sync.js) as the device tests read and press it,
 * through [js], a script's value in the page shown.
 */
internal class SyncSheet(private val js: (String) -> Any?) {
    /** The library page, its document loaded and its sync sheet's script there. */
    fun libraryLoaded() = waitUntil("the library page") {
        js("document.readyState === 'complete' && !!document.getElementById('sync-sheet')") == true
    }

    /** Where the sheet is: open, its view and flow, its title, status, buttons and counts. */
    fun state(): JSONObject = JSONObject(js("""(() => {
        const s = document.getElementById('sync-sheet'), go = document.getElementById('sync-go');
        const cancel = document.getElementById('sync-cancel'), st = document.getElementById('sync-status');
        const n = (k) => Number(((document.querySelector('#sync-counts .' + k + ' .n') || {}).textContent) || 0);
        return JSON.stringify({open: !!(s && s.open), view: s ? s.dataset.view || '' : '', flow: s ? s.dataset.flow || '' : '',
          title: document.getElementById('sync-title').textContent, sub: document.getElementById('sync-sub').textContent,
          go: go.textContent, goDisabled: go.disabled, goHidden: go.hidden, cancelHidden: cancel.hidden,
          status: st.textContent, tone: st.dataset.tone || '', countsHidden: document.getElementById('sync-counts').hidden,
          take: n('take'), give: n('give'), both: n('both'),
          parts: Array.from(document.querySelectorAll('#sync-parts .sync-part')).map((p) =>
            p.dataset.part + (p.querySelector('input').checked ? '+' : '-') + (p.querySelector('input').disabled ? ' off' : '') + ': '
            + p.querySelector('.sync-part-said').textContent)});
      })()""") as String)

    /** The comparison drawn, the sheet open at what to sync with Sync offered: a comparison that failed fails. */
    fun compared(timeoutMs: Long = 3 * 60_000): JSONObject {
        var last = JSONObject()
        waitUntil("the comparison", timeoutMs) {
            last = state()
            last.getBoolean("open") && last.getString("view") == "what" && !last.getBoolean("goDisabled") &&
                !last.getBoolean("countsHidden") || last.getString("tone") == "failed"
        }
        assertFalse("the comparison failed: $last", last.getString("tone") == "failed")
        assertEquals(last.toString(), "Sync", last.getString("go"))
        return last
    }

    /** The conflict's card shown: its unit's name, "1 of N", each side's button and heading, and its lines' state
     * ("reading" until both versions are read, "" then). */
    fun card(): JSONObject {
        waitUntil("a conflict's card") { state().getString("view") == "conflict" }
        return JSONObject(js("""(() => {
            const t = (id) => document.getElementById(id).textContent;
            const head = (id) => document.querySelector('#' + id + ' .sync-side-head').textContent;
            const lines = Array.from(document.querySelectorAll('#sync-conflict .sync-lines'));
            return JSON.stringify({name: t('sync-card-name'), at: t('sync-card-at'), here: t('sync-keep-here'),
              there: t('sync-keep-there'), hereOn: head('sync-card-here'), thereOn: head('sync-card-there'),
              same: !document.getElementById('sync-same-row').hidden,
              lines: lines.map((l) => l.dataset.state || '').filter(Boolean).join(' '),
              shown: lines.map((l) => l.textContent).join(' | ')});
          })()""") as String)
    }

    /** The sync over, its summary shown ("Synced with: …", a section for each kind of change), within [timeoutMs]. */
    fun done(timeoutMs: Long = 5 * 60_000): JSONObject {
        waitUntil("the sync's summary", timeoutMs) { state().getString("view") == "done" }
        return JSONObject(js("""(() => {
            const sections = Array.from(document.querySelectorAll('#sync-sections .sync-section')).map((s) => ({
              kind: s.dataset.kind, said: s.querySelector('.sync-lane-said').textContent,
              rows: Array.from(s.querySelectorAll('.sync-rows li')).map((li) => li.textContent)}));
            const st = document.getElementById('sync-status');
            return JSON.stringify({title: document.getElementById('sync-title').textContent,
              sub: document.getElementById('sync-sub').textContent, sections,
              note: (document.querySelector('#sync-sections .sync-note') || {}).textContent || '',
              fileNote: !document.getElementById('sync-file-note').hidden, status: st.textContent,
              tone: st.dataset.tone || '', go: document.getElementById('sync-go').textContent});
          })()""") as String)
    }

    /** A button of the sheet pressed by its script (one that needs a user's gesture is tapped: [SyncDevice.tap]). */
    fun click(id: String) {
        js("document.getElementById(${JSONObject.quote(id)}).click()")
    }
}

/** What the sync device tests do outside the page: agree with the computer, and change a song on both sides. */
internal object SyncDevice {
    private const val TAG = "CaracoleSyncDevice"
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext

    /** The app may notify (Android 13 and later ask first): the sheet asks as it opens, and its dialog over the
     * library screen would pause it. */
    fun mayNotify() {
        if (Build.VERSION.SDK_INT >= 33) {
            instrumentation.uiAutomation.grantRuntimePermission(context.packageName, Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    /** A song of the library: its sheet viewer's path ("Traditional/She Moved Through the Fair/sheet.html"). */
    data class Song(val sheet: String) {
        val title: String get() = sheet.split('/').let { it[it.size - 2] }
    }

    /**
     * The phone agreed with the computer at [server] (Sync on Wi-Fi's sync: every one-sided change taken or given),
     * then one song changed on both sides since: its own version made on the phone [phoneMove] semitones up, and on
     * the computer [computerMove] up (each Make this my version, in another key), so that the next comparison finds it
     * changed on both. [record] hears what each step said.
     */
    fun conflicted(server: String, phoneMove: Int, computerMove: Int, record: (String, Any) -> Unit): Song {
        Settings(context).server = server
        val agreed = runBlocking { Syncs.run(context, probe = false) }!!
        record("agreed", agreed.text)
        assertTrue(agreed.text, agreed.ok)
        val song = song()
        record("song", song.sheet)
        mineOnThePhone(song, phoneMove)
        mineOnTheComputer(server, song, computerMove)
        return song
    }

    /** The song both sides change: She Moved Through the Fair (no [version] of the e2e library's own, in no
     * songbook), else the last sheet the copy of the computer's pages lists. */
    private fun song(): Song {
        val sheets = Caracole.mirror(context).manifest()!!.entries.map { it.path }
            .filter { it.endsWith("/sheet.html") && it.count { c -> c == '/' } == 2 }.sorted()
        return Song(sheets.firstOrNull { "/She Moved Through the Fair/" in it } ?: sheets.last())
    }

    private fun versionQuery(song: Song, move: Int) =
        "/export.pdf?sheet=${Uri.encode(song.sheet, "/")}&t=$move&mine=1"

    /** Make this my version on the phone (ExportRoutes: its job queued, then awaited). */
    private fun mineOnThePhone(song: Song, move: Int) {
        val phone = Caracole.phone(context)
        val (status, body) = get(phone.server.origin + versionQuery(song, move), phone = true)
        Log.i(TAG, "phone's export.pdf: $status $body")
        assertEquals(body, 200, status)
        val job = phone.queue.snapshot().filter { it.spec.key.endsWith(":mine") }.maxBy { it.id }
        val done = runBlocking { phone.queue.await(job.id) }
        assertEquals("the phone's Make this my version: ${done.output}", Job.DONE, done.state)
    }

    /** Make this my version on the computer (caracole serve's export.pdf, tokenless), its job awaited. */
    private fun mineOnTheComputer(server: String, song: Song, move: Int) {
        val (status, body) = get(server + versionQuery(song, move), phone = false)
        assertEquals(body.take(300), 200, status)
        var jobs = JSONArray()
        waitUntil("the computer's Make this my version", 2 * 60_000) {
            jobs = JSONObject(get("$server/api/jobs", phone = false).second).getJSONArray("jobs")
            jobs.objects().none { it.optBoolean("active") }
        }
        val mine = jobs.objects().filter { it.getString("title").startsWith("Make ") }.maxBy { it.getInt("id") }
        Log.i(TAG, "computer's job: $mine")
        assertEquals(mine.toString(), "done", mine.getString("state"))
    }

    /** [url] asked: its status and body (the phone's with the launch's cookie). */
    private fun get(url: String, phone: Boolean): Pair<Int, String> {
        val connection = URL(url).openConnection() as HttpURLConnection
        try {
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 10_000
            connection.readTimeout = 120_000
            if (phone) connection.setRequestProperty("Cookie", "${Security.SECRET_COOKIE}=${Caracole.secret}")
            val status = connection.responseCode
            val body = (if (status >= 400) connection.errorStream else connection.inputStream)?.use { it.readBytes() }
                ?: ByteArray(0)
            val type = connection.contentType.orEmpty()
            return status to if (type.startsWith("application/pdf")) "PDF, ${body.size} bytes" else body.toString(Charsets.UTF_8)
        } finally {
            connection.disconnect()
        }
    }

    /**
     * Taps the page's element [id] as a finger would (`input tap`, so the page sees a user's gesture: a file input's
     * chooser opens only on one), scrolled into view first, in the WebView of [activity].
     */
    fun tap(activity: Activity, js: (String) -> Any?, id: String) {
        val quoted = JSONObject.quote(id)
        js("document.getElementById($quoted).scrollIntoView({block: 'center'})")
        Thread.sleep(300) // the scroll settles
        val at = JSONObject(js("""(() => { const r = document.getElementById($quoted).getBoundingClientRect();
            return JSON.stringify({x: r.left + r.width / 2, y: r.top + r.height / 2, w: window.innerWidth}); })()""") as String)
        val origin = IntArray(2)
        var scale = 1f
        instrumentation.runOnMainSync {
            val web = activity.findViewById<WebView>(R.id.web)
            web.getLocationOnScreen(origin)
            scale = web.width / at.getDouble("w").toFloat()
        }
        val x = origin[0] + at.getDouble("x") * scale
        val y = origin[1] + at.getDouble("y") * scale
        instrumentation.uiAutomation.executeShellCommand("input tap ${x.toInt()} ${y.toInt()}").close()
    }
}
