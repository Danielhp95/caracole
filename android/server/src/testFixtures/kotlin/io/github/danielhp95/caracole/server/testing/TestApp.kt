package io.github.danielhp95.caracole.server.testing

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.mirror.UnitGate
import io.github.danielhp95.caracole.server.files.LibraryFiles
import io.github.danielhp95.caracole.server.files.PhoneGate
import io.github.danielhp95.caracole.server.http.App
import io.github.danielhp95.caracole.server.http.AppConfig
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.http.Security
import io.github.danielhp95.caracole.server.routes.Stubs
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import java.io.File
import java.net.URLEncoder

/**
 * The phone's App as every :server test builds it: over a fresh database in [dir] (TestDb), the library folder
 * `dir/library`, the [modules] a test chooses (given the database), the out-of-round [stubs] last, and the library's
 * files behind them ([mirror], checked by [gate], PhoneGate by default).
 *
 * Its requests come as the WebView sends them: the launch's cookie, the Host, and for a form the urlencoded body with
 * its token, from the page's own origin; [script] reads as the page's script does, JSON with the token in its header.
 * Each builder takes headers to add or to change (a value of null leaves a header out).
 */
class TestApp(
    dir: File,
    modules: (Database) -> List<RouteModule> = { emptyList() },
    stubs: RouteModule = Stubs(),
    mirror: Mirror? = null,
    gate: ((Database) -> UnitGate)? = null,
    val csrf: String = CSRF,
    val secret: String = SECRET,
    allowed: Set<String> = AppConfig(CSRF, SECRET).allowed,
    libraryName: String = AppConfig(CSRF, SECRET).libraryName,
) : AutoCloseable {
    val database: Database = TestDb.fresh(dir)
    val libraryDir: File = File(dir, "library").apply { mkdirs() }
    val files: LibraryFiles = LibraryFiles(libraryDir, mirror, gate?.invoke(database) ?: PhoneGate(database), database)
    val app: App = App(AppConfig(csrf, secret, allowed, libraryName), modules(database), stubs, files)

    fun handle(request: Request): Response = app.handle(request)

    /** A GET as the WebView makes it: a page's link, or its address typed. */
    fun get(target: String, vararg headers: Pair<String, String?>): Response =
        handle(request("GET", target, mapOf("sec-fetch-site" to "same-origin", *headers)))

    /** A read by the page's own script: JSON, the form token in its header. */
    fun script(target: String, vararg headers: Pair<String, String?>): Response = handle(request(
        "GET", target,
        mapOf("sec-fetch-site" to "same-origin", "accept" to "application/json", TOKEN_HEADER to csrf, *headers),
    ))

    /** A form posted from the page: its [fields] after the token ([token], this app's unless a test says), urlencoded. */
    fun post(target: String, fields: List<Pair<String, String>> = emptyList(), vararg headers: Pair<String, String?>,
             token: String? = csrf): Response = handle(request(
        "POST", target,
        mapOf("sec-fetch-site" to "same-origin", "origin" to "http://$HOST",
              "content-type" to "application/x-www-form-urlencoded", *headers),
        form((if (token != null) listOf("csrf" to token) else emptyList()) + fields),
    ))

    /** [post], as the page's script sends it: JSON back. */
    fun postScript(target: String, fields: List<Pair<String, String>> = emptyList(), vararg headers: Pair<String, String?>,
                   token: String? = csrf): Response =
        post(target, fields, "accept" to "application/json", *headers, token = token)

    /** A request with the launch's cookie (this app's secret) and the Host, then [headers] (null: left out). */
    fun request(method: String, target: String, headers: Map<String, String?> = emptyMap(),
                body: ByteArray = ByteArray(0)): Request = request(method, target, headers, body, secret)

    override fun close() = database.close()

    companion object {
        const val CSRF = "test-csrf-token"
        val SECRET = "5ec7e7".repeat(10) + "abcd"
        const val HOST = "127.0.0.1:8738"
        const val TOKEN_HEADER = "x-caracole-form-token"

        /** A request with `cookie: caracole-launch=<secret>` and `host: HOST`, then [headers] (null: left out). */
        fun request(method: String, target: String, headers: Map<String, String?>, body: ByteArray,
                    secret: String?): Request {
            val all = LinkedHashMap<String, String?>()
            if (secret != null) all["cookie"] = "${Security.SECRET_COOKIE}=$secret"
            all["host"] = HOST
            for ((name, value) in headers) all[name.lowercase()] = value
            @Suppress("UNCHECKED_CAST")
            return Request(method, target, all.filterValues { it != null } as Map<String, String>, body)
        }

        /** The fields as a browser's form sends them: urlencoded, a space a '+'. */
        fun form(fields: List<Pair<String, String>>): ByteArray = fields.joinToString("&") { (name, value) ->
            URLEncoder.encode(name, Charsets.UTF_8) + "=" + URLEncoder.encode(value, Charsets.UTF_8)
        }.toByteArray(Charsets.UTF_8)
    }
}

/** The body's bytes: a file's read whole. */
val Response.bytes: ByteArray
    get() = when (val b = body) {
        Body.Empty -> ByteArray(0)
        is Body.Bytes -> b.bytes
        is Body.FromFile -> b.file.readBytes()
    }

val Response.text: String get() = bytes.toString(Charsets.UTF_8)

val Response.json: JsonElement get() = Json.parseToJsonElement(text)

/** The first header of that name, in any case. */
fun Response.header(name: String): String? = headers.firstOrNull { it.first.equals(name, ignoreCase = true) }?.second
