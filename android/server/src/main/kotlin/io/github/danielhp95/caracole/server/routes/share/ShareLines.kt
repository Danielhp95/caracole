package io.github.danielhp95.caracole.server.routes.share

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.server.routes.search.text
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.longOrNull

/**
 * One song of a search's answer (/api/search's, SearchRoutes.answer), every site's row of it on one line, as the library
 * page puts them on one (library.js `mergeSites`, rows.js `indexLine`): by the two parts of its identity key ([key],
 * `artist_key/title_key`), your song ([mine]: its id, names, status and card's links) and each index's row of it.
 */
internal class SongLine(val key: String) {
    var mine: JsonObject? = null
    var ug: JsonObject? = null
    var lacuerda: JsonObject? = null
    var gtptabs: JsonObject? = null
    var harptabs: JsonObject? = null
    var gametabs: JsonObject? = null

    /** The first site's row of it, whose names a Get it of a song new to the library takes (indexLine's `first`). */
    private val first: JsonObject? get() = ug ?: lacuerda ?: gtptabs ?: harptabs ?: gametabs

    /** Your song's id, else null. */
    val songId: Long? get() = (mine?.get("id") as? JsonPrimitive)?.longOrNull

    /** "Artist - Title": your song's display, else as the first site writes it. */
    val display: String
        get() = mine?.text("display")?.takeIf { it.isNotEmpty() }
            ?: first?.let { "${it.text("artist")} - ${it.text("title")}" }.orEmpty()

    /** Whether caracole found your song a sheet (rows.js `held`): its Open is what the owner likely wants. */
    val held: Boolean get() = mine?.text("status") == "found"

    /** What each site has of it, as the line's facts say it, the site named: "Ultimate Guitar: chords ×12 · tabs ×3". */
    fun facts(): List<String> = buildList {
        ug?.let { u ->
            val counts = (u["counts"] as? JsonObject).orEmpty().map { (kind, n) ->
                "${TIMES[kind] ?: kind} ×${(n as? JsonPrimitive)?.longOrNull ?: 0}"
            }
            add("Ultimate Guitar" + if (counts.isEmpty()) "" else ": " + counts.joinToString(" · "))
        }
        lacuerda?.let { lc ->
            val versions = (lc["versions"] as? JsonPrimitive)?.longOrNull?.takeIf { it > 0 } ?: 1
            add("LaCuerda ×$versions" + if (chords()) "" else ", no chords")
        }
        gtptabs?.let { add("gtptabs.com: " + many(uploads(it), "Guitar Pro file")) }
        harptabs?.let { add("harptabs.com: " + many(uploads(it), "harmonica tab")) }
        gametabs?.let { add("gametabs.net: " + many(uploads(it), "tab")) }
    }

    /**
     * The fields of its Get it, POST /lookup's as the library page's line posts them (indexLine's `chosen`): your song
     * by its id, else the first site's names; then Ultimate Guitar's song, else LaCuerda's sheet, else harptabs.com's
     * tab, else gametabs.net's.
     */
    fun pick(): List<Pair<String, String>> = buildList {
        val id = songId
        if (id != null) {
            add("song" to id.toString())
        } else {
            first?.let { add("artist" to it.text("artist")); add("title" to it.text("title")) }
        }
        val ugSong = ug?.text("ug").orEmpty()
        val harp = harptabs?.text("url").orEmpty()
        val game = gametabs?.text("url").orEmpty()
        when {
            ugSong.isNotEmpty() -> add("ug" to ugSong)
            chords() -> add("lacuerda" to lacuerda!!.text("url"))
            https(harp) -> add("harptabs" to harp)
            https(game) -> add("gametabs" to game)
        }
    }

    /** Where Open goes for your song: its line's main file (its viewer, else its PDF: rows.js `opener`), else its line
     * in the library (`#song=ID`); null for a song that isn't yours. */
    fun open(): String? {
        val id = songId ?: return null
        val main = (mine?.get("links") as? JsonArray).orEmpty().filterIsInstance<JsonObject>().firstOrNull { f ->
            (f["primary"] as? JsonPrimitive)?.booleanOrNull == true &&
                Py.asciiLower(f.text("name")).let { it.endsWith(".html") || it.endsWith(".pdf") }
        }
        val href = main?.text("href").orEmpty()
        return if (href.isNotEmpty() && !href.startsWith("/") && ':' !in href.substringBefore('/')) "/$href" else "/#song=$id"
    }

    /** LaCuerda's row with a sheet to keep (indexLine's `chords`). */
    private fun chords(): Boolean = lacuerda?.let { https(it.text("sheet")) && https(it.text("url")) } == true

    private fun uploads(row: JsonObject): Long = (row["uploads"] as? JsonPrimitive)?.longOrNull?.takeIf { it > 0 } ?: 1

    companion object {
        /** rows.js TIMES: a tab type's name. */
        private val TIMES = mapOf("chords" to "chords", "tabs" to "tabs", "ukulele" to "ukulele chords")

        private fun https(url: String): Boolean = url.startsWith("https://")

        private fun many(n: Long, word: String): String = if (n == 1L) "a $word" else "$n ${word}s"

        /**
         * The lines of [answer] (/api/search's): your songs first, then Ultimate Guitar's songs, LaCuerda's,
         * gtptabs.com's, harptabs.com's (a tab by its title alone, no artist, is no song's) and gametabs.net's, each row
         * on the line of its identity key; a site's row that is a song of yours brings it to its line too.
         */
        fun of(answer: JsonObject): List<SongLine> {
            val lines = LinkedHashMap<String, SongLine>()
            fun line(key: String) = lines.getOrPut(key) { SongLine(key) }
            fun rows(name: String): List<JsonObject> = (answer[name] as? JsonArray).orEmpty().filterIsInstance<JsonObject>()
            for (row in rows("library")) {
                val key = Normalize.identityKey(row.text("artist"), row.text("title"))
                line(key).let { if (it.mine == null) it.mine = row }
            }
            for ((name, set) in listOf<Pair<String, (SongLine, JsonObject) -> Unit>>(
                "index" to { l, r -> if (l.ug == null) l.ug = r },
                "lacuerda" to { l, r -> if (l.lacuerda == null) l.lacuerda = r },
                "gtptabs" to { l, r -> if (l.gtptabs == null) l.gtptabs = r },
                "harptabs" to { l, r -> if (l.harptabs == null) l.harptabs = r },
                "gametabs" to { l, r -> if (l.gametabs == null) l.gametabs = r },
            )) {
                for (row in rows(name)) {
                    val artistKey = row.text("artist_key")
                    if (artistKey.isEmpty() && row.text("artist").isEmpty()) continue  // a title alone
                    val l = line("$artistKey/${row.text("title_key")}")
                    set(l, row)
                    if (l.mine == null) (row["library"] as? JsonObject)?.let { l.mine = it }
                }
            }
            return lines.values.toList()
        }

        /**
         * The line the answer's `best` is (a song of yours by its id, an Ultimate Guitar song by its keys), else the
         * line whose identity is the names read ([names]); null when neither is any line's.
         */
        fun best(answer: JsonObject, lines: List<SongLine>, names: Pair<String, String>?): SongLine? {
            val best = answer["best"] as? JsonObject
            val library = (best?.get("library") as? JsonPrimitive)?.longOrNull
            val ugSong = best?.text("ug").orEmpty()
            lines.firstOrNull { library != null && it.songId == library }?.let { return it }
            lines.firstOrNull { ugSong.isNotEmpty() && it.ug?.text("ug") == ugSong }?.let { return it }
            if (names == null) return null
            val key = Normalize.identityKey(names.first, names.second)
            return lines.firstOrNull { it.key == key }
        }
    }
}

private fun JsonObject?.orEmpty(): Map<String, JsonElement> = this ?: emptyMap()
