package io.github.danielhp95.caracole.server.http

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.server.files.LibraryFiles
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive

/** The launch's secrets, who the server answers to, and [libraryName], the library's name its pages give now, read
 * for each page (the computer's, as the last sync gave it: PhoneConfig.libraryName; empty before the first), which
 * every page names with the phone's badge (LibraryName.phone). */
data class AppConfig(val csrf: String, val secret: String, val allowed: Set<String> = setOf("127.0.0.1", "localhost"),
                     val libraryName: () -> String = { "" }) {
    companion object {
        /** What the phone calls its own library where it names itself to a computer (the Sync tab's GET /api/sync). */
        const val PHONE = "Phone"
    }
}

/**
 * caracole serve's WebApp on the phone (web/app.py): a request in, its answer out, as `WebApp.handle` answers it
 * (vectors/web/routing.jsonl), behind the launch's secret.
 *
 * - **The secret first**: a request without the launch's cookie ([Security.hasSecret]) is 403, "Not this app's
 *   caracole.", before anything else is read.
 * - **Then caracole serve's order** (`_route`): the host (421); the path, unquoted strictly (400); a GET or HEAD:
 *   an `/api/` read another site's fetch asks is refused (403, JSON), else a route ([modules] first, by its path,
 *   then `under` one; then [stubs] alike: a stub answers only where no module does), a script-only one checked as a
 *   write and for the token header (403), else a library file ([files]; 404); a POST: its route (404), the
 *   cross-origin check (403), a form (415), no longer than the route's limit (413), at most 20 fields, UTF-8 (400),
 *   the form token (403, which tells the page's script to reload); a `json` or `bytes` route's body (Route.body) its
 *   kind's ([document]: the token in its header, 403; its content type, 415; its limit, 413; JSON, 400); any other
 *   method 405.
 * - A route's [Refused] is the message page, whose data, `{"error": …}` (and `"reload": true`), a page's script
 *   gets instead (Accept: application/json), with its status; a job queued ([queued]) is a 303 to the browser and
 *   its view to the script, as 200.
 * - Every answer gets [finish]'s headers. A HEAD is answered as its GET, body and all: the socket sends none
 *   (LocalServer, as server.py).
 *
 * Two modules answering one method and path refuse to construct, as two route modules do in caracole serve.
 */
class App(val config: AppConfig, modules: List<RouteModule>, stubs: RouteModule, val files: LibraryFiles) {
    private class Table(routes: List<Route>, what: String) {
        val exact: Map<Pair<String, String>, Route>
        val under: List<Route> = routes.filter { it.under }

        init {
            val found = LinkedHashMap<Pair<String, String>, Route>()
            for (route in routes) {
                require(route.method == "GET" || route.method == "POST") { "${route.method} ${route.path}: GET or POST" }
                require(route.body in Route.BODY_TYPES) { "${route.method} ${route.path}: a body of form, json or bytes" }
                require(when {
                    route.method == "GET" -> route.get != null
                    route.body == Route.FORM -> route.post != null
                    else -> route.document != null
                }) { "${route.method} ${route.path} has no answer" }
                require(found.put(route.method to route.path, route) == null) {
                    "${route.method} ${route.path} is answered twice ($what)"
                }
            }
            exact = found
        }

        fun find(method: String, path: String): Route? =
            exact[method to path] ?: under.firstOrNull { it.method == method && path.startsWith(it.path) }
    }

    private val routes = Table(modules.flatMap { it.routes }, "by the modules")
    private val stubbed = Table(stubs.routes, "by the stubs")
    /** The library as the pages name it now. */
    private fun name(): LibraryName = LibraryName.phone(config.libraryName())

    init {
        files.name = ::name  // the files' message pages name the library as the App's do
    }

    /** The route that answers [method] at [path]: a module's, else a stub's. */
    fun routeFor(method: String, path: String): Route? = routes.find(method, path) ?: stubbed.find(method, path)

    /** How many bytes of a request's body the server reads: its route's limit, else the default (16 KiB). */
    fun bodyLimit(method: String, target: String): Int {
        val path = try {
            PyUrl.unquote(PyUrl.urlsplit(target).path, strict = true)
        } catch (e: PyUrl.Invalid) {
            return MAX_BODY
        }
        return routeFor(method, path)?.limit ?: MAX_BODY
    }

    /** Secret cookie → host → path → (GET own_page_read, route, scriptOnly token, else file) | (POST form ≤ route.limit). */
    fun handle(request: Request): Response {
        var response = try {
            if (Security.hasSecret(request.headers, config.secret)) route(request) else notThisApp()
        } catch (e: Refused) {
            message(e.status, e.title, e.message ?: "").also { refused ->
                if (e.reload) refused.data = JsonObject(refused.data.orEmpty() + ("reload" to JsonPrimitive(true)))
            }
        }
        val data = response.data
        if (data != null && wantsJson(request)) response = json(data, if (response.status == 303) 200 else response.status)
        return finish(response)
    }

    /** WebApp.finish's headers: no framing, no sniffing, no referrer to another site, no cache; each unless the
     * answer has its own (a mirrored page's policy, with its sandbox). */
    fun finish(response: Response): Response {
        if (response.headers.none { it.first == "Content-Security-Policy" }) {
            response.headers.add("Content-Security-Policy" to FRAMES)
        }
        val own = response.headers.map { Py.asciiLower(it.first) }.toSet()
        for ((name, value) in COMMON_HEADERS) if (Py.asciiLower(name) !in own) response.headers.add(name to value)
        return response
    }

    /** JSON as caracole serve writes it (app.py's json_response: `json.dumps(ensure_ascii=False)`, compact), in UTF-8.
     * A float in [data] is Python's only when it came of a text Python wrote or of PyJson.float, never of
     * JsonPrimitive(Double). */
    fun json(data: JsonElement, status: Int = 200): Response =
        Response(status, Body.Bytes(PyJson.dumps(data, compact = true).toByteArray()), mutableListOf("Content-Type" to JSON))

    /** A job queued: 303 to its line ([view]'s `details`, else the Requests tab's), data {job: view}; JSON 200 to
     * Accept: application/json. */
    fun queued(view: JsonObject): Response {
        val details = (view["details"] as? JsonPrimitive)?.contentOrNull
            ?: "#tab=requests&job=${view["id"]?.jsonPrimitive?.contentOrNull ?: ""}"
        return Response(303, Body.Empty, mutableListOf("Location" to "/$details"), JsonObject(mapOf("job" to view)))
    }

    /** The message page, naming the phone's library. */
    fun message(status: Int, title: String, message: String, link: Pair<String, String>? = null): Response =
        MessagePage.page(status, title, message, link, name())

    // --- routing --------------------------------------------------------------------------------------------------

    private fun notThisApp(): Response = Response(403, Body.Bytes("Not this app's scribe.\n".toByteArray()),
                                                  mutableListOf("Content-Type" to TEXT))

    private fun route(request: Request): Response {
        if (!Security.answersTo(Security.hostName(request.headers["host"]), config.allowed)) {
            return Response(421, Body.Bytes(MISDIRECTED.toByteArray()), mutableListOf("Content-Type" to TEXT))
        }
        val path = try {
            PyUrl.unquote(PyUrl.urlsplit(request.target).path, strict = true)
        } catch (e: PyUrl.Invalid) {
            return message(400, "Not an address", "Can't read that address.")
        }
        return when (request.method) {
            "GET", "HEAD" -> {
                if (path.startsWith("/api/") && !Security.ownPageRead(request.headers)) {
                    return json(JsonObject(mapOf("error" to JsonPrimitive(ANOTHER_SITE))), 403)
                }
                val route = routeFor("GET", path) ?: return file(path)
                if (route.scriptOnly) scriptReadRefused(request)?.let { return it }
                route.get!!.answer(request)
            }
            "POST" -> {
                val route = routeFor("POST", path)
                    ?: return message(404, "Not here", "Nothing to send to here.")
                if (route.body != Route.FORM) {
                    return when (val document = document(request, route)) {
                        is Response -> document
                        else -> route.document!!.answer(request, document)
                    }
                }
                when (val form = form(request, route)) {
                    is Response -> form
                    else -> {
                        @Suppress("UNCHECKED_CAST")
                        route.post!!.answer(request, form as Map<String, String>)
                    }
                }
            }
            else -> Response(405, Body.Empty, mutableListOf("Allow" to "GET, HEAD, POST"))
        }
    }

    /** Why a read only the page's script makes is refused to anything else, as a write would be; null for it. */
    private fun scriptReadRefused(request: Request): Response? {
        if (!Security.crossOriginOk("POST", request.headers, request.headers["host"])) {
            return message(403, "Refused", ANOTHER_SITE)
        }
        if (!Security.sameToken(request.headers[TOKEN_HEADER], config.csrf)) {
            return message(403, "Refused", "caracole serve restarted since this page opened. Reload it.")
        }
        return null
    }

    /** The fields of a POSTed form (each name's first value), or why it is refused. */
    private fun form(request: Request, route: Route): Any {
        val headers = request.headers
        if (!Security.crossOriginOk("POST", headers, headers["host"])) return message(403, "Refused", ANOTHER_SITE)
        val kind = PyText.lower(PyText.strip((headers["content-type"] ?: "").substringBefore(';')))
        if (kind != "application/x-www-form-urlencoded") {
            return message(415, "Not a form", "We read only forms from our own pages.")
        }
        if (request.body.size > route.limit) return message(413, "Too long", "That form is too long.")
        val text = PyText.utf8(request.body) ?: return message(400, "Not a form", "Can't read that form.")
        val fields = try {
            PyUrl.parseQs(text, keepBlank = true, maxFields = MAX_FIELDS)
        } catch (e: PyUrl.Invalid) {
            return message(400, "Not a form", "Can't read that form.")
        }
        val form = LinkedHashMap<String, String>()
        for ((name, values) in fields) form[name] = values.first()
        if (!Security.sameToken(form["csrf"], config.csrf)) {
            val refused = message(403, "Refused", "This form is older than the server, or not from its pages. " +
                                                  "Reload ${route.page} and try again.")
            refused.data = JsonObject(refused.data.orEmpty() + ("reload" to JsonPrimitive(true)))
            return refused
        }
        return form
    }

    /**
     * The body of a POST that isn't a form (web/app.py's `_document`): its bytes, or its JSON (PyJson.loads of its
     * UTF-8, as json.loads reads it), or why it is refused: another site's (403); no form token in its header (403,
     * with `reload`: a token older than the server, which its state gives again); another content type than its
     * kind's (415); too long (413); JSON that can't be read (400).
     */
    private fun document(request: Request, route: Route): Any {
        val headers = request.headers
        if (!Security.crossOriginOk("POST", headers, headers["host"])) return message(403, "Refused", ANOTHER_SITE)
        if (!Security.sameToken(headers[TOKEN_HEADER], config.csrf)) {
            val refused = message(403, "Refused", "This is older than the server, or not from it: read its form token " +
                                                  "again and try again.")
            refused.data = JsonObject(refused.data.orEmpty() + ("reload" to JsonPrimitive(true)))
            return refused
        }
        val type = Route.BODY_TYPES.getValue(route.body)
        if (PyText.lower(PyText.strip((headers["content-type"] ?: "").substringBefore(';'))) != type) {
            return message(415, "Not what it reads", "caracole reads only $type here.")
        }
        if (request.body.size > route.limit) return message(413, "Too long", "That is too long.")
        if (route.body == Route.BYTES) return request.body
        val text = PyText.utf8(request.body) ?: return message(400, "Not JSON", "That can't be read as JSON.")
        return try {
            PyJson.loads(text)
        } catch (e: IllegalArgumentException) {
            message(400, "Not JSON", "That can't be read as JSON.")
        }
    }

    /** A library file (LibraryFiles: the phone's folder, then the mirror), else 404. */
    private fun file(path: String): Response =
        files.serve(path) ?: message(404, "Not found", "No such page or file in the book.")

    private fun wantsJson(request: Request): Boolean =
        "application/json" in PyText.lower(request.headers["accept"] ?: "")

    companion object {
        const val MAX_BODY = 16 * 1024
        const val MAX_FIELDS = 20
        const val TOKEN_HEADER = "x-caracole-form-token"
        const val FRAMES = "frame-ancestors 'none'"
        const val JSON = "application/json; charset=utf-8"
        const val TEXT = "text/plain; charset=utf-8"
        private const val ANOTHER_SITE = "Another site sent this. Refused."
        private const val MISDIRECTED = "This server doesn't answer to this host name. " +
            "Start it with --allow-host NAME to add it.\n"
        val COMMON_HEADERS = listOf(
            "X-Content-Type-Options" to "nosniff",
            "X-Frame-Options" to "DENY",
            // The page's origin to the server alone, never to another site.
            "Referrer-Policy" to "same-origin",
            "Cross-Origin-Resource-Policy" to "same-origin",
            "Cross-Origin-Opener-Policy" to "same-origin",
            "Cache-Control" to "no-store",
        )
    }
}
