package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.DatabaseTooNew
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.page.SongCards
import io.github.danielhp95.caracole.server.routes.search.AnswerCache
import io.github.danielhp95.caracole.server.routes.search.Answered
import io.github.danielhp95.caracole.server.routes.search.Artists
import io.github.danielhp95.caracole.server.routes.search.Found
import io.github.danielhp95.caracole.server.routes.search.IndexAnswers
import io.github.danielhp95.caracole.server.routes.search.SearchQuery
import io.github.danielhp95.caracole.server.routes.search.Searches
import io.github.danielhp95.caracole.server.routes.search.SongForms
import io.github.danielhp95.caracole.server.routes.search.Superseded
import io.github.danielhp95.caracole.server.routes.search.jsonResponse
import io.github.danielhp95.caracole.server.routes.search.obj
import kotlinx.serialization.json.JsonObject
import java.io.IOException
import java.time.Instant

/**
 * caracole serve's search on the phone (web/search_routes.py's `/api/search` and `/api/artist`), over the phone's
 * own database, so that the library page's search box works with the computer off.
 *
 *     GET /api/search?q=&box=  your library and the offline indexes, as JSON, for a search box (`box`, the id its
 *                              page made): search_routes.py's answer, key for key, with the LaCuerda page to read
 *                              (`lacuerda_unlisted`) and whether LaCuerda's own search may be sent (`lacuerda_search`,
 *                              its gate at [clock]'s time; null with [searchesLacuerda] false), and `progression`
 *                              and `youtube` null (no progressions on the phone yet, and no yt-dlp ever)
 *     GET /api/artist?key=     an artist of the offline index: their songs, most tabbed first, 50 from `offset`, and
 *                              yours by them; `?lacuerda=SLUG` (`?lacuerda_name=NAME`), a LaCuerda artist's songs the
 *                              index holds; `?harptabs=PATH`, a harptabs.com artist's
 *
 * A query is its words joined by one space, cut at 200 code points; one of fewer than three letters or digits (two
 * with Chinese) looks nowhere (`short`). One search runs at a time, in the order they were asked, and a search typed
 * on in the same box wins over that box's older ones, waiting or running: those answer `{query, superseded: true}`
 * ([Searches]); another box's never stops one. The offline indexes' answers are kept 300 s, the 128 made last
 * ([AnswerCache]), until [invalidate], which the phone calls after every job (a lookup adds a song, reads an artist's
 * page and changes the gate's records). A song of your library comes as its card has it ([cards]): its files, where
 * its sheet came from, its key. The sites that are on are the phone's settings' (PhoneConfig.read: the computer's
 * switches, as a sync gave them), read for each search, unless [enabled] names them (a test's). [searchesLacuerda]
 * is the app's PhoneDeps' (false under the test runner, as `WebApp(searches_lacuerda=False)`), false by default.
 * Reads go through [Database.read]; a database that can't be read is 503, `{query, error}` (an artist's, `{error}`).
 */
class SearchRoutes(val database: Database, val cards: SongCards, val enabled: Set<String>? = null,
                   val searchesLacuerda: Boolean = false, val clock: () -> Instant = Instant::now) : RouteModule {
    internal val searches = Searches()
    internal val answers = AnswerCache<IndexAnswers>()
    private val forms = SongForms()

    override val routes: List<Route> = listOf(
        Route("GET", "/api/search", "your library and the offline indexes, as JSON, for a search box (box)",
              get = GetAnswer { search(PyUrl.query(it.target)) }),
        Route("GET", "/api/artist", "an artist of an offline index (key, lacuerda, lacuerda_name, harptabs): their " +
                  "songs, and yours by them", get = GetAnswer { artist(PyUrl.query(it.target)) }),
    )

    /** After an index import or a sync: the answers kept are dropped, so a search finds what the indexes hold now. */
    fun invalidate() = answers.clear()

    /** search_routes.api_search. */
    private fun search(asked: Map<String, String>): Response {
        val q = SearchQuery.of(asked["q"] ?: "")
        if (SearchQuery.short(q)) {
            return jsonResponse(200, obj("query" to q, "library" to emptyList<Any>(), "index" to emptyList<Any>(),
                                         "short" to true))
        }
        val box = asked["box"]?.takeIf { BOX.matches(it) } ?: ""
        val superseded = obj("query" to q, "superseded" to true)
        return searches.search(box) { ticket ->
            try {
                database.read { db ->
                    val config = PhoneConfig.read(db)
                    jsonResponse(200, Found(db, on(config), cards, forms, answers, ticket::check, config, searchesLacuerda,
                                            clock()).answer(q))
                }
            } catch (e: Exception) {
                if (e is Superseded || !unreadable(e)) throw e
                if (ticket.over) throw Superseded()  // stopped by a newer one: it reads now
                jsonResponse(503, obj("query" to q, "error" to "The database can't be read: ${said(e)}"))
            }
        } ?: jsonResponse(200, superseded)
    }

    /**
     * What /api/search answers [q] (its query already made by [SearchQuery.of], never a short one), for a page of the
     * phone's own that shows a search (ShareRoutes' page of a song shared to the app): the same answer, read alone,
     * with no search of a box beside it and none to stop it. Refused (503) when the database can't be read.
     */
    internal fun answer(q: String): JsonObject = searches.alone {
        try {
            database.read { db ->
                val config = PhoneConfig.read(db)
                Found(db, on(config), cards, forms, answers, {}, config, searchesLacuerda, clock()).answer(q)
            }
        } catch (e: Exception) {
            if (!unreadable(e)) throw e
            throw Refused(503, "Can't search", "The database can't be read: ${said(e)}")
        }
    }

    /** search_routes._artist: harptabs.com's before LaCuerda's, LaCuerda's before UG's; each field stripped. */
    private fun artist(asked: Map<String, String>): Response {
        if ("harptabs" in asked) return harptabsArtist(Py.strip(asked.getValue("harptabs")))
        if ("lacuerda" in asked || "lacuerda_name" in asked) {
            return lacuerdaArtist(Py.strip(asked["lacuerda"] ?: ""), Py.split(asked["lacuerda_name"] ?: "").joinToString(" "))
        }
        return ugArtist(Py.strip(asked["key"] ?: ""), Py.strip(asked["offset"] ?: "0"))
    }

    /** search_routes.api_artist. */
    private fun ugArtist(key: String, offset: String): Response {
        if (key.isEmpty()) return jsonResponse(400, obj("error" to "Which artist? The address names none."))
        if (offset.isEmpty() || !offset.all { it in '0'..'9' }) {
            return jsonResponse(400, obj("error" to "That offset isn't a number."))
        }
        return artistAlone { it.ug(key, offset) }
    }

    /** search_routes.api_lacuerda_artist. */
    private fun lacuerdaArtist(slug: String, name: String): Response {
        if (slug.isEmpty() && name.isEmpty()) return jsonResponse(400, obj("error" to "Which artist? The address names none."))
        return artistAlone { it.lacuerda(slug, name) }
    }

    /** search_routes.api_harptabs_artist. */
    private fun harptabsArtist(path: String): Response {
        if (path.isEmpty()) return jsonResponse(400, obj("error" to "Which artist? The address names none."))
        return artistAlone { it.harptabs(path) }
    }

    /** An artist's answer, read one at a time with the searches. */
    private fun artistAlone(answer: (Artists) -> Answered): Response = searches.alone {
        try {
            val answered = database.read { db -> answer(Artists(db, on(PhoneConfig.read(db)), cards, forms)) }
            jsonResponse(answered.status, answered.json)
        } catch (e: Exception) {
            if (!unreadable(e)) throw e
            jsonResponse(503, obj("error" to "The database can't be read: ${said(e)}"))
        }
    }

    /** The sites on: [enabled], else those the settings don't turn off. */
    private fun on(config: PhoneConfig): Set<String> =
        enabled ?: config.providers.filterValues { it.enabled }.keys

    private companion object {
        /** search_routes._BOX: a search box's id, as its page makes it. */
        val BOX = Regex("[A-Za-z0-9_-]{1,64}")

        /** The bundled driver's words before SQLite's own: "Error code: 1, message: no such table: songs". */
        val DRIVER_PREFIX = Regex("^Error code: -?[0-9]+, message: ")

        /** An error as Python's `str(e)` says it: SQLite's own message ("no such table: songs"), the driver's prefix
         * left out. */
        fun said(e: Throwable): String = (e.message ?: e.toString()).replaceFirst(DRIVER_PREFIX, "")

        /** Python's `(sqlite3.Error, OSError)`: an error of the database (the bundled SQLite's SQLiteException, which
         * on Android is android.database.SQLException, so it is told by its class's name), a database too new, or a
         * file that can't be read. */
        fun unreadable(e: Throwable): Boolean {
            if (e is IOException || e is DatabaseTooNew) return true
            var c: Class<*>? = e.javaClass
            while (c != null) {
                if (c.name == "androidx.sqlite.SQLiteException" || c.name == "android.database.SQLException") return true
                c = c.superclass
            }
            return false
        }
    }
}
