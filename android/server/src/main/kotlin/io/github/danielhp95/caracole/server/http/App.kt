package io.github.danielhp95.caracole.server.http

import io.github.danielhp95.caracole.server.files.LibraryFiles
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

/** The launch's secrets and who the server answers to. */
data class AppConfig(val csrf: String, val secret: String, val allowed: Set<String> = setOf("127.0.0.1", "localhost"),
                     val libraryName: String = "Phone")

/**
 * caracole serve's WebApp on the phone (lane server-shell): the launch's secret cookie first, then caracole serve's
 * checks in its order, then a route of [modules], else a route of [stubs] (one answers only where no module does;
 * two modules answering one method and path refuse to construct), else a library file.
 */
class App(val config: AppConfig, modules: List<RouteModule>, stubs: RouteModule, val files: LibraryFiles) {
    /** Secret cookie → host → path → (GET own_page_read, route, scriptOnly token, else file) | (POST form ≤ route.limit). */
    fun handle(request: Request): Response = TODO("lane server-shell")

    /** WebApp.finish's headers. */
    fun finish(response: Response): Response = TODO("lane server-shell")

    fun json(data: JsonElement, status: Int = 200): Response = TODO("lane server-shell")

    /** A job queued: 303 with data {job: view}; JSON 200 to Accept: application/json. */
    fun queued(view: JsonObject): Response = TODO("lane server-shell")
}
