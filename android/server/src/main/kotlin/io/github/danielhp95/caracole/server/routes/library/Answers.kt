package io.github.danielhp95.caracole.server.routes.library

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.server.http.App
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.Response
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit

/** The answers the library's and the Sync tab's routes give, as App gives them (a route module has no App). */
internal object Answers {
    /** App.json: `json.dumps(ensure_ascii=False)`, compact, in UTF-8. */
    fun json(data: JsonElement, status: Int = 200): Response =
        Response(status, Body.Bytes(PyJson.dumps(data, compact = true).toByteArray()), mutableListOf("Content-Type" to App.JSON))

    /** App.queued: a job queued, 303 to [location] (else its line: the view's `details`, else the Requests tab's),
     * with data {job: view}, which App answers a page's script with as JSON, 200. */
    fun queued(view: JsonObject, location: String? = null): Response {
        val details = (view["details"] as? JsonPrimitive)?.contentOrNull
            ?: "#tab=requests&job=${(view["id"] as? JsonPrimitive)?.contentOrNull ?: ""}"
        return Response(303, Body.Empty, mutableListOf("Location" to (location ?: "/$details")),
                        JsonObject(mapOf("job" to view)))
    }

    private val STAMP = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'").withZone(ZoneOffset.UTC)

    /** stamps.stamp of now: the phone's clock, as caracole stores a time. */
    fun now(): String = STAMP.format(Instant.now().truncatedTo(ChronoUnit.SECONDS))
}
