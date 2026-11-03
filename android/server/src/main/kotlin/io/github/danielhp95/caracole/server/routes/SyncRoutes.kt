package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.stub
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.JobQueue
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** The computer's address the Sync tab syncs with, kept by the app. */
interface SyncSettings {
    val address: String?
    fun remember(address: String)
}

/** The Sync tab's routes on the phone (lane phone-sync-routes; until then, no sync). */
class SyncRoutes(val engine: SyncEngine, val queue: JobQueue, val settings: SyncSettings, val database: Database,
                 val afterSync: () -> Unit) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/api/sync", "this phone's sync and its peers", get = GetAnswer {
            stub("lane phone-sync-routes") {
                val state = JsonObject(mapOf("server" to JsonNull, "name" to JsonPrimitive("Phone"), "address" to JsonNull,
                                             "peers" to JsonArray(emptyList())))
                Response(200, Body.Bytes(state.toString().toByteArray()),
                         mutableListOf("Content-Type" to "application/json; charset=utf-8"))
            }
        }),
        Route("POST", "/sync/compare", "compare with the computer", post = PostAnswer { _, _ -> notBuilt() }),
        Route("POST", "/sync/apply", "take and give what a comparison found", limit = 1_048_576,
              post = PostAnswer { _, _ -> notBuilt() }),
    )

    private fun notBuilt(): Response = stub("lane phone-sync-routes") {
        throw Refused(409, "Not on the phone yet", "Sync isn't built yet.")
    }
}
