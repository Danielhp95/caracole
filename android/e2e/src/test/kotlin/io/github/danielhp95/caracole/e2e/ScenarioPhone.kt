package io.github.danielhp95.caracole.e2e

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.http.RoutedTransport
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.SyncUnit
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.PhoneDeps
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.routes.SyncSettings
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.text
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import java.io.File
import kotlin.time.Duration.Companion.minutes

/**
 * The phone of the scenario: server.Phone over [home] (DIR/phone/), as the app assembles it (§5.4: its database, its
 * library folder, its state, the mirror), so that what one phase leaves the next finds; the computer it syncs with
 * at [server]. It is driven through its App as the WebView's requests come, made by TestApp's request builder: the
 * launch's cookie and the Host, then a page's link ([get]), its script's read ([script]: JSON, the form token in its
 * header) or its form ([post]: the token in the body, from the page's own origin). Its sites are the fake sites server
 * at [sites] (RoutedTransport: tests/helpers/fake_sites.py), or, with none, a transport that refuses every one.
 */
class ScenarioPhone(val home: File, val server: String, val sites: String? = null) : AutoCloseable {
    val database: Database = Database(File(home.apply { mkdirs() }, "caracole.sqlite"))
    val libraryDir: File = File(home, "library").apply { mkdirs() }
    val stateDir: File = File(home, "state").apply { mkdirs() }
    val mirror: Mirror = Mirror(File(home, "mirror"))
    val address: ServerAddress = ServerAddress.parse(server)

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    /** The computer's address the Sync tab remembers, kept in a file of the phone's as the app keeps it. */
    private val settings = object : SyncSettings {
        private val file = File(home, "sync-address.txt")
        override val address: String? get() = file.takeIf { it.isFile }?.readText()?.trim()?.ifEmpty { null }
        override fun remember(address: String) = file.writeText(address)
    }

    /** The fake sites, every request to one of them sent there; else every site refuses, and nothing is sent. */
    private val transport: Transport = sites?.let(::RoutedTransport) ?: RefusingTransport

    val phone: Phone = Phone(PhoneDeps(database, libraryDir, stateDir, mirror, scope, settings, TestApp.SECRET,
                                       TestApp.CSRF, transport = { transport }))

    /** A GET as the WebView makes it: a page's link, or its address typed. */
    fun get(target: String): Response = handle("GET", target, mapOf("sec-fetch-site" to "same-origin"))

    /** A read by the page's own script: JSON, the form token in its header. */
    fun script(target: String): Response = handle("GET", target, mapOf(
        "sec-fetch-site" to "same-origin", "accept" to "application/json", TestApp.TOKEN_HEADER to TestApp.CSRF,
    ))

    /** A form posted from the page: its [fields] after the token, urlencoded; with [json], as its script posts it. */
    fun post(target: String, vararg fields: Pair<String, String>, json: Boolean = true): Response = handle(
        "POST", target,
        mapOf("sec-fetch-site" to "same-origin", "origin" to "http://${TestApp.HOST}",
              "content-type" to "application/x-www-form-urlencoded") +
            (if (json) mapOf("accept" to "application/json") else emptyMap()),
        TestApp.form(listOf("csrf" to TestApp.CSRF) + fields),
    )

    private fun handle(method: String, target: String, headers: Map<String, String>, body: ByteArray = ByteArray(0)) =
        phone.app.handle(TestApp.request(method, target, headers, body, TestApp.SECRET))

    /** What an answer says: its data, else its JSON body. */
    fun answer(response: Response): JsonObject = response.data
        ?: try {
            Json.parseToJsonElement(response.text).jsonObject
        } catch (e: Exception) {
            throw AssertionError("HTTP ${response.status}, no JSON: ${response.text.take(2000)}", e)
        }

    /** The job an answer queued: `{job: view}` (a form's), or `{job: N, url, view}` (a lookup's). */
    fun jobOf(response: Response): Int {
        val job = answer(response)["job"] ?: throw AssertionError("HTTP ${response.status} queued no job: ${response.text.take(2000)}")
        return if (job is JsonPrimitive) job.int else job.jsonObject.getValue("id").let { (it as JsonPrimitive).int }
    }

    /** The job, once it is over. */
    fun await(id: Int): Job = runBlocking { withTimeout(10.minutes) { phone.queue.await(id) } }

    fun units(): Map<String, SyncUnit> = database.read { Units.libraryState(it) }

    fun ownId(): String = database.read { Compare.ownId(it) }

    /** The computer's peer routes, as the phone's sync reads them. */
    fun peer(): PeerClient = PeerClient(address)

    override fun close() {
        scope.cancel()
        database.close()
    }
}

/** A path's parts percent-encoded as a link writes them, each byte of their UTF-8 outside A–Z, a–z, 0–9 and -._~. */
fun quotePath(path: String): String = path.split('/').joinToString("/") { quote(it) }

fun quote(text: String): String = buildString {
    for (b in text.toByteArray(Charsets.UTF_8)) {
        val c = b.toInt() and 0xff
        if (c in 'A'.code..'Z'.code || c in 'a'.code..'z'.code || c in '0'.code..'9'.code || c.toChar() in "-._~") {
            append(c.toChar())
        } else {
            append('%').append("%02X".format(c))
        }
    }
}
