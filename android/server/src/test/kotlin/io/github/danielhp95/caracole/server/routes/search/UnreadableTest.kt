package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.testing.header
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals

/**
 * A database that can't be read answers 503, as caracole serve's search does (search_routes.api_search and the three
 * `/api/artist` forms catching `sqlite3.Error`): `{query, error}` for a search, `{error}` for an artist, the error
 * SQLite's own words after "The database can't be read: ", as Python's `str(sqlite3.Error)` says them (the bundled
 * driver's "Error code: 1, message: " left out). The bodies below are caracole serve's over the sites fixture with the
 * same tables dropped, one before each request.
 */
class UnreadableTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test
    fun a_table_gone_answers_503_with_sqlites_words_as_caracole_serve_does() {
        SearchApp(tmp.newFolder("sites"), "sites").use { search ->
            for ((table, target, body) in ANSWERS) {
                search.app.database.writeBlocking { it.execute("DROP TABLE $table") }
                val answer = search.app.get(target)
                assertEquals(503, answer.status, target)
                assertEquals("application/json; charset=utf-8", answer.header("Content-Type"), target)
                assertEquals(body, String((answer.body as Body.Bytes).bytes, Charsets.UTF_8), target)
            }
        }
    }

    private companion object {
        /** The table dropped, the request, caracole serve's answer (WebApp.handle over the sites fixture). */
        val ANSWERS = listOf(
            Triple("musescore_index", "/api/search?q=creep&box=t",
                   """{"query":"creep","error":"The database can't be read: no such table: musescore_index"}"""),
            Triple("harptabs_artist_tabs", "/api/artist?harptabs=artist/1178/billy-joel",
                   """{"error":"The database can't be read: no such table: harptabs_artist_tabs"}"""),
            Triple("lacuerda_index", "/api/artist?lacuerda=estopa",
                   """{"error":"The database can't be read: no such table: lacuerda_index"}"""),
            Triple("ug_index", "/api/artist?key=radiohead&offset=0",
                   """{"error":"The database can't be read: no such table: ug_index"}"""),
        )
    }
}
