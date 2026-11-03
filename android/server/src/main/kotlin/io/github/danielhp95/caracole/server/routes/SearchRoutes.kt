package io.github.danielhp95.caracole.server.routes

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
import java.net.URLDecoder

/** /api/search and /api/artist on the phone (lane search-routes; until then, a search that finds nothing). */
class SearchRoutes(val database: Database, val cards: SongCards,
                   val enabled: Set<String> = setOf("gtptabs", "musescore", "harptabs", "gametabs")) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/api/search", "a search of your songs and the indexes", get = GetAnswer { request ->
            stub("lane search-routes") {
                val query = request.target.substringAfter('?', "").split('&')
                    .firstOrNull { it.startsWith("q=") }?.let { URLDecoder.decode(it.substring(2), "UTF-8") } ?: ""
                val found = JsonObject(mapOf("query" to JsonPrimitive(query), "library" to JsonArray(emptyList()),
                                             "index" to JsonArray(emptyList()), "short" to JsonPrimitive(true)))
                Response(200, Body.Bytes(found.toString().toByteArray()),
                         mutableListOf("Content-Type" to "application/json; charset=utf-8"))
            }
        }),
    )

    /** After an index import or a sync: what the routes keep of the indexes is read again. */
    fun invalidate() = stub("lane search-routes") { }
}
