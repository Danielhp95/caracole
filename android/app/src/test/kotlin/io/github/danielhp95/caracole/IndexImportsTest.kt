package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.mirror.Http
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.core.index.TransferError
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayInputStream
import java.io.File
import java.net.InetAddress
import java.net.ServerSocket
import java.net.SocketException
import kotlin.concurrent.thread
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** The computer's index brought to the phone: fetched from caracole serve, or copied from a file picked, then merged. */
class IndexImportsTest {
    @get:Rule val folder = TemporaryFolder()

    private val export = "SQLite format 3\u0000".toByteArray() + ByteArray(4096) { (it % 251).toByte() }
    /** The computer: a plain HTTP/1.1 server on 127.0.0.1 that answers every request with [answer]. */
    private val server = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
    private val asked = java.util.Collections.synchronizedList(mutableListOf<String>())
    @Volatile private var answer: Pair<Int, ByteArray> = 200 to export

    init {
        thread(isDaemon = true) {
            while (true) {
                val socket = try {
                    server.accept()
                } catch (e: SocketException) {
                    break
                }
                socket.use {
                    val input = it.getInputStream().bufferedReader(Charsets.ISO_8859_1)
                    val line = input.readLine() ?: return@use
                    while (!input.readLine().isNullOrEmpty()) Unit
                    asked.add(line.split(' ')[1])
                    val (status, body) = answer
                    val head = "HTTP/1.1 $status Answer\r\nContent-Type: application/vnd.sqlite3\r\n" +
                        "Content-Length: ${body.size}\r\nConnection: close\r\n\r\n"
                    it.getOutputStream().apply { write(head.toByteArray(Charsets.ISO_8859_1)); write(body); flush() }
                }
            }
        }
    }

    @After fun stop() = server.close()

    private val address get() = ServerAddress.parse("127.0.0.1:${server.localPort}")

    @Test
    fun `the computer's index comes whole from GET api peer index, into a file of its own in the cache`() {
        val cache = File(folder.root, "state/cache")
        val seen = mutableListOf<Pair<Long, Long>>()
        val file = IndexImports.download(Http(), address, cache) { done, total -> seen.add(done to total) }
        assertEquals(listOf("/api/peer/index"), asked)
        assertEquals(cache, file.parentFile)
        assertTrue(file.name.startsWith("index-") && file.name.endsWith(".sqlite"), file.name)
        assertContentEquals(export, file.readBytes())
        assertEquals(listOf(file.name), cache.list()!!.toList(), "nothing else left there")
        assertEquals(export.size.toLong() to export.size.toLong(), seen.last())
    }

    @Test
    fun `a computer with no index to give, or that sends something else, leaves nothing`() {
        val cache = File(folder.root, "cache")
        answer = 404 to "Not found".toByteArray()
        val old = assertFailsWith<IndexImportError> { IndexImports.download(Http(), address, cache) }
        assertTrue("newer caracole" in old.message!!, old.message)
        answer = 503 to ByteArray(0)
        val busy = assertFailsWith<IndexImportError> { IndexImports.download(Http(), address, cache) }
        assertTrue("503" in busy.message!!, busy.message)
        answer = 200 to "<html>Wi-Fi login</html>".toByteArray()
        val other = assertFailsWith<IndexImportError> { IndexImports.download(Http(), address, cache) }
        assertTrue("isn't an index" in other.message!!, other.message)
        assertEquals(emptyList(), cache.list().orEmpty().toList())
    }

    @Test
    fun `a file picked is copied whole into the cache, and only an SQLite file is taken`() {
        val cache = File(folder.root, "cache")
        val file = IndexImports.copy(ByteArrayInputStream(export), cache)
        assertContentEquals(export, file.readBytes())
        assertFailsWith<IndexImportError> { IndexImports.copy(ByteArrayInputStream("PK\u0003\u0004zip".toByteArray()), cache) }
        assertFailsWith<IndexImportError> { IndexImports.copy(ByteArrayInputStream(ByteArray(0)), cache) }
        assertEquals(listOf(file.name), cache.list()!!.toList())
    }

    @Test
    fun `a computer that can't give its index says why, in its own words`() {
        val cache = File(folder.root, "cache")
        answer = 503 to """{"error": "Another copy of the indexes is being sent: try again once it is."}""".toByteArray()
        val busy = assertFailsWith<IndexImportError> { IndexImports.download(Http(), address, cache) }
        assertTrue("503" in busy.message!!, busy.message)
        assertTrue("Another copy of the indexes is being sent: try again once it is." in busy.message!!, busy.message)
        assertEquals(emptyList(), cache.list().orEmpty().toList())
    }

    @Test
    fun `an import stopped while it copies leaves nothing`() {
        val cache = File(folder.root, "cache")
        var reads = 0
        val endless = object : java.io.InputStream() {
            override fun read(): Int = 0
            override fun read(b: ByteArray, off: Int, len: Int): Int {
                reads++
                if (reads == 1) System.arraycopy(export, 0, b, off, minOf(len, export.size))
                return len
            }
        }
        assertFailsWith<CancellationException> { IndexImports.copy(endless, cache) { reads >= 3 } }
        assertEquals(3, reads)
        assertEquals(emptyList(), cache.list().orEmpty().toList())
    }

    /** The phone's job queue, as Phone.importIndex submits to it: an import's job run, and how it ended. */
    private fun imported(run: suspend (JobContext) -> Unit): Job {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        try {
            val queue = JobQueue(scope)
            val (job, _) = queue.submit(JobSpec(title = "Import the index", key = "index", kind = "index",
                                                display = "The computer's index",
                                                stages = listOf("merge" to "Merging the index"), run = run))
            return runBlocking { withTimeout(10_000) { queue.await(job.id) } }
        } finally {
            scope.cancel()
        }
    }

    @Test
    fun `a merge that took something says which sites, and one with nothing newer says so`() {
        val merged = imported { job ->
            job.stage("merge", "running")
            job.stage("merge", "done", "merged")
            job.outcome(JsonObject(mapOf("changed" to JsonPrimitive(true),
                                         "sites" to JsonArray(listOf(JsonPrimitive("lacuerda"), JsonPrimitive("ug"))))))
        }
        assertEquals(Outcome(5L, true, "Indexes imported: lacuerda, ug"), IndexImports.describe(merged, at = 5L))
        val same = imported { job ->
            job.stage("merge", "running")
            job.stage("merge", "done", "nothing newer")
            job.outcome(JsonObject(mapOf("changed" to JsonPrimitive(false), "sites" to JsonArray(emptyList()))))
        }
        assertEquals(Outcome(6L, true, "Indexes imported: nothing newer"), IndexImports.describe(same, at = 6L))
        val bare = imported { job -> job.stage("merge", "done") }
        assertEquals(Outcome(7L, true, "Indexes imported"), IndexImports.describe(bare, at = 7L))
    }

    @Test
    fun `a merge refused says the refusal's words, the file named as the file`() {
        val file = File(folder.root, "state/cache/index-1-abcd.sqlite")
        val refused = imported { job ->
            job.stage("merge", "running")
            throw TransferError("$file was exported at schema version 14, and this caracole's is 15")
        }
        assertEquals("failed", refused.state)
        assertEquals(Outcome(8L, false, "The import failed: the file was exported at schema version 14, and this " +
                                        "caracole's is 15"), IndexImports.describe(refused, at = 8L, file = file))
        val unnamed = imported { job ->
            job.stage("merge", "running")
            throw IllegalStateException()
        }
        assertEquals(Outcome(9L, false, "The import failed: IllegalStateException"), IndexImports.describe(unnamed, at = 9L))
    }
}
