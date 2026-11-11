package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.mirror.Http
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.After
import org.junit.Test
import java.net.InetAddress
import java.net.ServerSocket
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * Sync on Wi-Fi by itself (the sync redesign's Task 38): the phone's own sync, unattended (SyncRoutes.alone: the three
 * parts, every one-sided change taken or given, each conflict left), once a caracole answers at the address; a
 * notification only for the conflicts it left.
 */
class SyncsTest {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val notified = mutableListOf<Pair<Int, Boolean>>()
    /** How many times a sync that left no conflict took the conflicts' notification back. */
    private var cleared = 0
    private var server: ServerSocket? = null

    @After
    fun stop() {
        server?.close()
        scope.cancel()
        Caracole.status.value = SyncState.Idle
    }

    private fun outcome(text: String): JsonObject = Json.parseToJsonElement(text).jsonObject

    /** An address nothing answers at: a port of loopback just freed. */
    private fun nothingAt(): String = ServerSocket(0, 1, InetAddress.getLoopbackAddress()).use {
        "http://127.0.0.1:${it.localPort}"
    }

    /** Something that isn't a caracole answering on loopback: every request a 200 of [page], an HTML page. */
    private fun answering(page: String): String {
        val socket = ServerSocket(0, 8, InetAddress.getLoopbackAddress()).also { server = it }
        Thread {
            while (!socket.isClosed) {
                val client = try {
                    socket.accept()
                } catch (e: java.io.IOException) {
                    break
                }
                client.use {
                    val input = it.getInputStream().bufferedReader()
                    while (input.readLine()?.isNotEmpty() == true) Unit
                    val body = page.toByteArray()
                    it.getOutputStream().write(("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n" +
                        "Content-Length: ${body.size}\r\nConnection: close\r\n\r\n").toByteArray() + body)
                }
            }
        }.apply { isDaemon = true }.start()
        return "http://127.0.0.1:${socket.localPort}"
    }

    /** A queue whose sync job ends with [outcome] (null: it fails, as a compare that couldn't ask fails it), its
     * [failed] stage said failed and the job going on past it, as the engine goes on past its mirror stage. */
    private fun phone(outcome: JsonObject?, queued: MutableList<String> = mutableListOf(),
                      failed: Pair<String, String>? = null): Syncs.Unattended {
        val queue = JobQueue(scope)
        return Syncs.Unattended(
            alone = { address ->
                queued.add(address)
                queue.submit(JobSpec(title = "Sync with studio", key = "sync:$address", kind = "sync",
                                     stages = SyncEngine.STAGES, display = "Sync with studio", run = { job ->
                    if (outcome == null) {
                        job.stage(SyncEngine.COMPARE, "failed", "No answer from $address (refused).")
                        throw IllegalStateException("No answer from $address (refused).")
                    }
                    for ((stage, _) in SyncEngine.STAGES) {
                        job.stage(stage, if (stage == failed?.first) "failed" else "done", failed?.second.orEmpty())
                    }
                    job.outcome(outcome)
                })).first
            },
            await = { id -> queue.await(id) },
        )
    }

    private fun settings(server: String): Settings = Settings(MemoryPreferences()).also { it.server = server }

    @Test
    fun `the conflicts left are counted from the outcome, and only conflicts count`() {
        val mixed = outcome("""{"taken": ["song/estopa/tu calorro"], "given": [], "left": [
            ["song/eagles/hotel california", "${SyncEngine.UNSETTLED}"],
            ["songbook/campfire", "${SyncEngine.UNSETTLED}"],
            ["song/estopa/como camaron", "changed here since compared"]], "agreed": 3, "indexed": []}""")
        assertEquals(2 to false, Syncs.conflictsLeft(mixed), "a songbook among them: not all songs")
        val songs = outcome("""{"taken": [], "given": [], "left": [
            ["song/a/b", "${SyncEngine.UNSETTLED}"], ["song/c/d", "${SyncEngine.UNSETTLED}"]], "agreed": 0}""")
        assertEquals(2 to true, Syncs.conflictsLeft(songs))
        assertEquals(0 to true, Syncs.conflictsLeft(outcome("""{"taken": [], "given": [], "left": []}""")))
        assertEquals(0 to true, Syncs.conflictsLeft(outcome("""{"taken": []}""")), "no left at all")
        assertEquals(1 to true, Syncs.conflictsLeft(outcome("""{"left": ["song/x", 3, ["song/y"],
            ["song/z", "${SyncEngine.UNSETTLED}"]]}""")), "what can't be read counts for nothing")
    }

    @Test
    fun `the probe of a Wi-Fi sync with nothing answering does nothing and says nothing`() = runBlocking {
        val asked = { error("the phone's caracole was asked") }
        // What an earlier sync left: kept as it was, in the settings and on the screen, by each probe that finds none.
        val earlier = Outcome(1_000L, true, "Up to date · 1 taken")
        val shown = SyncState.Ended(earlier)
        for (server in listOf(nothingAt(), "", answering("<html><body>Sign in to the café's Wi-Fi</body></html>"))) {
            // Nothing answering there; no address; something else answering there, a Wi-Fi login page.
            val settings = settings(server).also { it.lastOutcome = earlier }
            Caracole.status.value = shown
            assertNull(Syncs.run(settings, probe = true, http = Http(), phone = asked, cleared = { cleared++ }) { n, songs ->
                notified.add(n to songs)
            }, server)
            assertEquals(shown, Caracole.status.value, "the screen's line as it was: $server")
            assertEquals(earlier, settings.lastOutcome, "the last outcome as it was: $server")
        }
        assertEquals(emptyList(), notified, "nothing said")
        assertEquals(0, cleared, "no notification taken back either")
    }

    @Test
    fun `asked by hand, nothing answering is said`() = runBlocking {
        val by = settings(nothingAt())
        val outcome = Syncs.run(by, probe = false, http = Http(), phone = { error("asked") }) { _, _ -> error("notified") }!!
        assertFalse(outcome.ok)
        assertTrue(outcome.text.startsWith("No answer from "), outcome.text)
        assertEquals(outcome, by.lastOutcome)
        assertEquals(SyncState.Ended(outcome), Caracole.status.value)
    }

    @Test
    fun `a sync with no conflict left posts no notification`() = runBlocking {
        val queued = mutableListOf<String>()
        val clean = settings("192.168.1.20:8737")
        val done = Syncs.run(clean, probe = true, http = Http(), ask = {}, cleared = { cleared++ },
                             phone = { phone(outcome("""{"taken": ["song/a/b"], "given": ["song/c/d", "song/e/f"],
                                 "left": [], "agreed": 9, "indexed": []}"""), queued) }) { n, songs -> notified.add(n to songs) }!!
        assertEquals(listOf("http://192.168.1.20:8737"), queued, "the address as the sync reads it")
        assertTrue(done.ok)
        assertEquals("Up to date · 1 taken, 2 given", done.text)
        assertEquals(emptyList(), notified)
        assertEquals(1, cleared, "an earlier sync's notification of its conflicts taken back")
        assertEquals(done, clean.lastOutcome)
        assertEquals(SyncState.Ended(done), Caracole.status.value)

        val same = Syncs.run(clean, probe = true, http = Http(), ask = {},
                             phone = { phone(outcome("""{"taken": [], "given": [], "left": [], "agreed": 9}""")) }) { n, songs ->
            notified.add(n to songs)
        }!!
        assertEquals("Up to date", same.text)
        assertEquals(emptyList(), notified)
    }

    @Test
    fun `a sync that left conflicts says so once, in a notification`() = runBlocking {
        val left = JsonArray(listOf("song/eagles/hotel california", "song/estopa/tu calorro").map {
            JsonArray(listOf(JsonPrimitive(it), JsonPrimitive(SyncEngine.UNSETTLED)))
        })
        val done = Syncs.run(settings("http://192.168.1.20:8737"), probe = true, http = Http(), ask = {},
                             phone = { phone(JsonObject(mapOf("taken" to JsonArray(emptyList()), "given" to JsonArray(emptyList()),
                                                              "left" to left))) }) { n, songs -> notified.add(n to songs) }!!
        assertTrue(done.ok)
        assertEquals("2 changed on both sides: tap Sync to choose", done.text, "never \"Up to date\" then")
        assertEquals(listOf(2 to true), notified)
    }

    @Test
    fun `a sync that went on past a stage that failed is no sync up to date`() = runBlocking {
        val mirror = SyncEngine.STAGES.single { it.first == SyncEngine.MIRROR }
        val done = Syncs.run(settings("http://192.168.1.20:8737"), probe = true, http = Http(), ask = {},
                             phone = { phone(outcome("""{"taken": ["song/a/b"], "given": [], "left": []}"""),
                                             failed = SyncEngine.MIRROR to "No answer from http://192.168.1.20:8737.") }) { n, songs ->
            notified.add(n to songs)
        }!!
        assertFalse(done.ok, "the copy of the computer's pages failed")
        assertEquals("${mirror.second} failed: No answer from http://192.168.1.20:8737. (1 taken)", done.text)
    }

    @Test
    fun `a sync that failed is kept as it failed, and posts no notification`() = runBlocking {
        val failed = Syncs.run(settings("http://192.168.1.20:8737"), probe = true, http = Http(), ask = {},
                               phone = { phone(null) }) { n, songs -> notified.add(n to songs) }!!
        assertFalse(failed.ok)
        assertEquals("No answer from http://192.168.1.20:8737 (refused).", failed.text)
        assertEquals(emptyList(), notified)
    }

    @Test
    fun `a sync on its way already is followed by it, and this one says nothing`() = runBlocking {
        val busy = Syncs.Unattended(alone = { null }, await = { error("awaited") })
        assertNull(Syncs.run(settings("http://192.168.1.20:8737"), probe = true, http = Http(), ask = {},
                             phone = { busy }) { n, songs -> notified.add(n to songs) })
        assertEquals(SyncState.Idle, Caracole.status.value)
        assertEquals(emptyList(), notified)
    }
}
