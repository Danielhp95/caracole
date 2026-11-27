package io.github.danielhp95.caracole

import android.app.ActivityManager
import android.content.ComponentName
import android.content.Intent
import android.os.Process
import android.view.View
import android.view.ViewGroup
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.Button
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.core.youtube.HostGate
import io.github.danielhp95.caracole.youtube.BenchRun
import io.github.danielhp95.caracole.youtube.DbLedger
import io.github.danielhp95.caracole.youtube.GateService
import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The debug build's YouTube bench on the emulator (the phone-youtube design's §4.2 and §4.5), its screen by intent with
 * `go` and a loopback clip for its query (`-e clip`, served on the host by `android/scripts/device-test.sh --youtube`
 * and reached as `http://10.0.2.2:PORT/clip.m4a`), through the gate of this, the main process, whose mode is the test
 * runner's loopback: a report of §4.3's shape whose runs' hosts name 10.0.2.2 alone, no gate-shaped address in it or
 * on the screen after its `-v` runs, the kill check over the bench's own loopback clip leaving no `:youtube` or qjs,
 * each run an `events` row and a stamp of kv `ytbench:runs`, and no Python in `:ytbench`; an intent asking `observe`
 * runs `enforce`; a public host's query refused before any run; a screen recreated mid-session showing it, a second
 * start refused; a relaunch from Recents starting nothing; Settings' row opening the bench in `:ytbench`.
 */
@RunWith(AndroidJUnit4::class)
class YouTubeBenchTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext
    private val reports = File(context.getExternalFilesDir(YouTubeBenchActivity.FOLDER), "")
    private val proxy = Regex(HostGate.PROXY_PATTERN)
    private val bench = "${context.packageName}${GateService.BENCH_PROCESS}"

    private fun clip(): String = InstrumentationRegistry.getArguments().getString("clip")
        ?: fail("no clip: run it through android/scripts/device-test.sh --youtube") as Nothing

    private val database get() = Caracole.phone(context).parts.database

    @Before
    fun clean() {
        reports.listFiles().orEmpty().forEach { it.delete() }
        database.writeBlocking { db ->
            db.execute("DELETE FROM events WHERE provider = 'youtube'")
            for (key in listOf(DbLedger.RUNS, "http:last_request:youtube", "provider:youtube")) {
                db.execute("DELETE FROM kv WHERE key = ?", key)
            }
        }
    }

    @After
    fun stop() {
        benchPid()?.let { Process.killProcess(it) }
    }

    private fun benchPid(): Int? = context.getSystemService(ActivityManager::class.java).runningAppProcesses.orEmpty()
        .firstOrNull { it.processName == bench }?.pid

    private fun start(queries: String, vararg extra: Pair<String, String>, flags: Int = Intent.FLAG_ACTIVITY_CLEAR_TASK) {
        val intent = Intent(context, YouTubeBenchActivity::class.java)
            .putExtra(YouTubeBenchActivity.QUERIES, queries).putExtra(YouTubeBenchActivity.GO, true)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or flags)
        for ((k, v) in extra) intent.putExtra(k, v)
        context.startActivity(intent)
    }

    /** The bench's screen, its texts as the accessibility tree shows them (it is another process's window). */
    private fun screen(): String {
        val out = StringBuilder()
        fun walk(node: AccessibilityNodeInfo?) {
            if (node == null) return
            node.text?.let { out.append(it).append('\n') }
            for (i in 0 until node.childCount) walk(node.getChild(i))
        }
        walk(instrumentation.uiAutomation.rootInActiveWindow)
        return out.toString()
    }

    private fun waitFor(ms: Long, what: String, done: () -> Boolean) {
        val until = System.currentTimeMillis() + ms
        while (!done()) {
            if (System.currentTimeMillis() > until) {
                fail("$what didn't come in ${ms / 1000} s; the screen:\n${screen()}\nthe log:\n${log()}")
            }
            Thread.sleep(500)
        }
    }

    /** The app's log lines of the bench and of a crash (this uid reads its own processes'). */
    private fun log(): String = ProcessBuilder("logcat", "-d", "-v", "brief").redirectErrorStream(true).start().let {
        val text = it.inputStream.readBytes().decodeToString()
        it.waitFor()
        text.lines().filter { line -> "AndroidRuntime" in line || "ytbench" in line || "caracole-ytdlp" in line }
            .takeLast(80).joinToString("\n")
    }

    private fun count(sql: String, vararg args: Any?): Long = database.read { db -> db.one(sql, *args) { it.long(0) }!! }

    @Test
    fun aSessionByIntentWritesItsReportOfLoopbackHostsAloneAndAnIntentNeverObserves() {
        start(clip(), YouTubeBenchActivity.GATE to BenchRun.OBSERVE)
        waitFor(600_000, "the report") { reports.listFiles().orEmpty().any { it.name.endsWith(".json") } }
        val file = reports.listFiles()!!.single { it.name.endsWith(".json") }
        assertTrue(file.name, Regex("""caracole-ytbench-\d{4}-\d{2}-\d{2}T\d{6}Z\.json""").matches(file.name))
        val text = file.readText()
        assertFalse("a gate-shaped address in the report", proxy.containsMatchIn(text))
        val report = Json.parseToJsonElement(text).jsonObject
        // The report, said in `am instrument`'s output (device-test.sh prints it): a loopback session's, for the record.
        instrumentation.sendStatus(0, android.os.Bundle().apply { putString("stream", "the report:\n$text\n") })
        for (key in listOf("device", "soc", "android", "app", "apk_bytes", "installed_bytes", "abi", "pins",
                           "network", "idle", "budget", "runs", "kill_check", "first_start", "summary")) {
            assertTrue("no $key in the report", key in report)
        }
        assertEquals("an intent never observes", BenchRun.ENFORCE, report["gate"]!!.jsonPrimitive.content)
        assertEquals("LOOPBACK", report["mode"]!!.jsonPrimitive.content)
        val runs = report["runs"]!!.jsonArray.map { it.jsonObject }
        assertEquals("$text\n${log()}", listOf("search", "download"), runs.map { it["kind"]!!.jsonPrimitive.content })
        for (run in runs) {
            assertEquals(run.toString(), "ok", run["outcome"]!!.jsonPrimitive.content)
            assertEquals(run.toString(), setOf("10.0.2.2"), run["hosts"]!!.jsonObject.keys)
            for (key in listOf("song", "cache", "started_at", "process_start_ms", "python_ready_ms", "seconds",
                               "challenge", "sleeps_seconds", "pause_seconds", "clients", "reason", "uid_bytes",
                               "pss_peak_mb", "file", "decoded")) {
                assertTrue("no $key in a run: $run", key in run)
            }
        }
        val download = runs[1]
        assertEquals("cold", download["cache"]!!.jsonPrimitive.content)
        assertTrue(download.toString(), download["file"] !is JsonNull && download["decoded"] !is JsonNull)
        assertTrue(report["pins"]!!.jsonObject["ytdlp"] !is JsonNull)
        val kill = report["kill_check"]!!.jsonObject
        assertTrue(kill.toString(), kill["run"]!!.jsonPrimitive.boolean && kill["killed"]!!.jsonPrimitive.boolean)
        assertTrue(kill.toString(), kill["qjs_seen"]!!.jsonPrimitive.boolean)
        assertEquals(kill.toString(), 0, kill["left"]!!.jsonArray.size)
        assertTrue(kill.toString(), kill["next_run_ok"]!!.jsonPrimitive.boolean)
        assertEquals(kill.toString(), 0, kill["spends"]!!.jsonPrimitive.content.toInt())
        // Nothing of the session's audio stays.
        val left = File(context.cacheDir, YouTubeBenchActivity.FOLDER).listFiles().orEmpty()
            .filter { it.name.startsWith("into-") || it.name == "kill" }
        assertEquals("the session's audio left: $left", emptyList<File>(), left)
        assertEquals(0, report["after_block_requests"]!!.jsonPrimitive.content.toInt())
        // Each run an events row of provider youtube, a search's under youtube-search:, and a stamp of the bench's own.
        assertEquals(1L, count("SELECT COUNT(*) FROM events WHERE provider = 'youtube' AND run LIKE ?",
                               "${BenchRun.SEARCH_RUN}%"))
        assertEquals(1L, count("SELECT COUNT(*) FROM events WHERE provider = 'youtube' AND run LIKE ?",
                               "${BenchRun.DOWNLOAD_RUN}%"))
        val stamps = database.read { db -> db.kvGet(DbLedger.RUNS) }
        assertEquals(stamps, 2, Json.parseToJsonElement(stamps!!).jsonArray.size)
        // The screen: what came back from the client, the report's path, no gate-shaped address; and no Python here.
        waitFor(30_000, "the report's line") { YouTubeBenchActivity.DONE in screen() }
        val shown = screen()
        assertTrue(shown, YouTubeBenchActivity.INTENT_NEVER_OBSERVES in shown)
        assertFalse("a gate-shaped address on the screen", proxy.containsMatchIn(shown))
        val pid = checkNotNull(benchPid()) { "no :ytbench process" }
        val maps = File("/proc/$pid/maps").readText()
        assertFalse("Python is loaded in :ytbench", "libpython" in maps || "libchaquopy" in maps)
    }

    /** The day's cap lifted (DbLedger.DAY_CAP_LIFTED, the owner's word of 2026-11-27): with seven runs of the phone's
     * already in the last 24 hours, a session still goes, its runs counted and its report saying the cap lifted. */
    @Test
    fun aSessionGoesPastSixRunsAlreadyCountedWhileTheCapIsLifted() {
        assertTrue(DbLedger.DAY_CAP_LIFTED)
        val hourAgo = io.github.danielhp95.caracole.youtube.utc(java.time.Instant.now().minusSeconds(3_600))
        database.writeBlocking { db ->
            repeat(7) {
                db.execute("INSERT INTO events (run, at, provider, url, status, decision, message) VALUES " +
                           "('youtube-sheet:x', ?, 'youtube', 'u', NULL, 'ok', NULL)", hourAgo)
            }
        }
        start(clip())
        waitFor(600_000, "the report") { reports.listFiles().orEmpty().any { it.name.endsWith(".json") } }
        val report = Json.parseToJsonElement(reports.listFiles()!!.single { it.name.endsWith(".json") }.readText())
            .jsonObject
        val budget = report["budget"]!!.jsonObject
        assertEquals(budget.toString(), 7, budget["before"]!!.jsonPrimitive.content.toInt())
        assertEquals(budget.toString(), 9, budget["after"]!!.jsonPrimitive.content.toInt())
        assertEquals(budget.toString(), 6, budget["of"]!!.jsonPrimitive.content.toInt())
        assertTrue(budget.toString(), budget["lifted"]!!.jsonPrimitive.boolean)
        assertEquals(listOf("ok", "ok"), report["runs"]!!.jsonArray.map { it.jsonObject["outcome"]!!.jsonPrimitive.content })
        assertEquals(9L, count("SELECT COUNT(*) FROM events WHERE provider = 'youtube'"))
        waitFor(30_000, "the count on the screen") { "no daily limit while this is developed" in screen() }
    }

    /** One session a process: the screen made again mid-session (a rotation) shows the running session, and a
     * second start (a new screen on top, `go`) is refused in words; one report, two runs. */
    @Test
    fun aRecreatedScreenShowsTheRunningSessionAndASecondStartIsRefused() {
        start(clip())
        waitFor(120_000, "the session's first run") { "search of" in screen() }
        try {
            instrumentation.uiAutomation.setRotation(android.app.UiAutomation.ROTATION_FREEZE_90)
            waitFor(30_000, "the recreated screen's lines") { "search of" in screen() }
            start(clip(), flags = Intent.FLAG_ACTIVITY_SINGLE_TOP)
            waitFor(60_000, "the second start's refusal") { YouTubeBenchActivity.ALREADY in screen() }
        } finally {
            instrumentation.uiAutomation.setRotation(android.app.UiAutomation.ROTATION_UNFREEZE)
        }
        waitFor(600_000, "the report") { reports.listFiles().orEmpty().any { it.name.endsWith(".json") } }
        Thread.sleep(2_000)
        assertEquals(1, reports.listFiles()!!.count { it.name.endsWith(".json") })
        assertEquals(2L, count("SELECT COUNT(*) FROM events WHERE provider = 'youtube'"))
    }

    /** A relaunch from Recents re-delivers `go`: it starts nothing, and says why. */
    @Test
    fun aRelaunchFromRecentsStartsNothing() {
        val gates = GateService.gatesOpened
        start(clip(), flags = Intent.FLAG_ACTIVITY_CLEAR_TASK or Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY)
        waitFor(60_000, "the words") { YouTubeBenchActivity.GO_FROM_HISTORY in screen() }
        Thread.sleep(3_000)
        assertFalse(screen(), "search of" in screen())
        assertEquals(gates, GateService.gatesOpened)
        assertEquals(0L, count("SELECT COUNT(*) FROM events WHERE provider = 'youtube'"))
    }

    @Test
    fun aPublicHostsQueryIsRefusedBeforeAnyRun() {
        val gates = GateService.gatesOpened
        start("https://www.youtube.com/watch?v=aaaaaaaaaaa")
        waitFor(60_000, "the refusal") { "refused:" in screen() }
        assertTrue(screen(), BenchRun.notLoopback("https://www.youtube.com/watch?v=aaaaaaaaaaa") in screen())
        assertEquals("no gate was opened", gates, GateService.gatesOpened)
        assertEquals(0L, count("SELECT COUNT(*) FROM events WHERE provider = 'youtube'"))
        assertTrue(reports.listFiles().orEmpty().none { it.name.endsWith(".json") })
        Process.killProcess(benchPid()!!)
        // "Artist - Title" is a search of YouTube's: refused alike under the tests' network.
        start("Artist - Title")
        waitFor(60_000, "the refusal") { "refused:" in screen() }
        assertEquals(gates, GateService.gatesOpened)
        assertEquals(0L, count("SELECT COUNT(*) FROM events WHERE provider = 'youtube'"))
    }

    @Test
    fun settingsYouTubeBenchRowOpensTheBenchInItsProcessOfItsOwn() {
        @Suppress("DEPRECATION")
        val info = context.packageManager.getActivityInfo(
            ComponentName(context, YouTubeBenchActivity::class.java), 0)
        assertEquals(bench, info.processName)
        assertTrue(!info.exported)
        ActivityScenario.launch(SettingsActivity::class.java).use { scenario ->
            var row: Button? = null
            scenario.onActivity { settings ->
                row = buttons(settings.window.decorView).firstOrNull { it.text == SettingsActivity.YOUTUBE_BENCH }
            }
            assertTrue("Settings shows the YouTube bench row in a debug build", row != null)
            instrumentation.runOnMainSync { row!!.performClick() }
            waitFor(20_000, "the bench's process") { benchPid() != null }
            assertTrue("never this process", benchPid() != Process.myPid())
        }
    }

    private fun buttons(view: View): List<Button> = when (view) {
        is Button -> listOf(view)
        is ViewGroup -> (0 until view.childCount).flatMap { buttons(view.getChildAt(it)) }
        else -> emptyList()
    }
}
