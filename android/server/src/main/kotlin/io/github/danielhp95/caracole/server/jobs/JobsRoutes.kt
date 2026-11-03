package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.stub
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.page.SongCards
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** GET /jobs.json, /api/jobs/N; POST /jobs/cancel (lane jobs; until then, no job). */
class JobsRoutes(val queue: JobQueue, val cards: SongCards, val database: Database) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/jobs.json", "the requests that wait or run", scriptOnly = true, get = GetAnswer {
            stub("lane jobs") {
                json(200, JsonObject(mapOf("active" to JsonPrimitive(0), "jobs" to JsonArray(emptyList()))))
            }
        }),
        Route("GET", "/api/jobs/", "one request", under = true, get = GetAnswer {
            stub("lane jobs") { json(404, JsonObject(mapOf("error" to JsonPrimitive("No such request.")))) }
        }),
    )

    private fun json(status: Int, data: JsonObject) = Response(
        status, Body.Bytes(data.toString().toByteArray()), mutableListOf("Content-Type" to "application/json; charset=utf-8"),
    )
}
