package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.search.GameTabHit
import io.github.danielhp95.caracole.core.search.HarpTabHit
import io.github.danielhp95.caracole.core.search.IndexHit
import io.github.danielhp95.caracole.core.search.LibraryHit
import io.github.danielhp95.caracole.core.search.Search
import io.github.danielhp95.caracole.core.search.SearchLimits
import io.github.danielhp95.caracole.core.search.SiteArtist
import io.github.danielhp95.caracole.core.search.SiteHit
import io.github.danielhp95.caracole.core.sites.SiteSearch
import io.github.danielhp95.caracole.server.page.SongCards
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull

/** search_routes.TABS_SHOWN: an index song's tabs a row lists. */
internal const val TABS_SHOWN = 24

/** The keys a row merges on across sites (`normalize.identity_key`, split), search_routes._keys. */
internal fun keys(artist: String, title: String): JsonObject = keyParts(Normalize.identityKey(artist, title))

/** search_routes._key_parts: an identity key's two parts, `artist_key` and `title_key`. */
internal fun keyParts(key: String): JsonObject =
    obj("artist_key" to key.substringBefore('/'), "title_key" to key.substringAfter('/', ""))

/** search_routes._group_key: an artist's group on the library page, the artist key of their songs' rows. */
internal fun groupKey(artist: String): String = Normalize.identityKey(artist, "").substringBefore('/')

/** ug.index.index_count: how many tabs the index holds (0: it was never built). */
internal fun indexCount(db: Db): Long = db.one("SELECT COUNT(*) FROM ug_index") { it.long(0) } ?: 0L

/** One tab of UG's index (ug/lookup.py's IndexTab). */
internal data class IndexTab(val tabId: Long, val type: String, val songKey: String, val label: String?, val path: String) {
    /** ug.page.page_url: a slugged tab only at its slugged path. */
    val url: String
        get() = if (path.isNotEmpty()) "https://tabs.ultimate-guitar.com/tab/${path.trimStart('/')}"
        else "https://tabs.ultimate-guitar.com/tab/$tabId"
}

/** ug.lookup.song_tabs: every indexed tab of a song, its variant slugs (`song-key-acoustic`) included. */
internal fun songTabs(db: Db, artistKey: String, songKey: String): List<IndexTab> {
    val rows = db.query(
        "SELECT tab_id, type, song_key, path FROM ug_index WHERE artist_key = ? AND (song_key = ? OR song_key LIKE ?) " +
            "ORDER BY tab_id",
        artistKey, songKey, "$songKey-%",
    ) { r -> IndexTab(r.long(0)!!, r.text(1)!!, r.text(2)!!, null, r.text(3) ?: "") }
    return rows.mapNotNull { tab ->
        if (tab.songKey == songKey) return@mapNotNull tab
        val (base, label) = Normalize.splitVariant(tab.songKey)
        if (base == songKey) tab.copy(label = label) else null
    }
}

/**
 * search_routes._hit_json: an Ultimate Guitar song of the index as the page draws it: its names, its tabs per type and
 * its first [TABS_SHOWN] tabs, chords first; `no_ones` when its artist is one of UG's `misc-…` keys.
 */
internal fun hitJson(db: Db, h: IndexHit): JsonObject {
    val order = SearchLimits.TYPE_ORDER
    val tabs = songTabs(db, h.artistKey, h.songKey).sortedWith(
        compareBy<IndexTab>({ order.indexOf(it.type).let { i -> if (i < 0) order.size else i } }, { it.label != null })
            .thenBy { it.tabId },
    ).take(TABS_SHOWN)
    return obj(
        "artist" to h.artist, "title" to h.title, "ug" to "${h.artistKey}/${h.songKey}", "counts" to h.counts,
        "score" to h.score, "url" to h.url, "labels" to h.labels, "via" to h.via, "no_ones" to Search.noOnes(h.artistKey),
        "tabs" to tabs.map { t -> obj("id" to t.tabId, "type" to t.type, "label" to t.label, "url" to t.url) },
    )
}

/**
 * The rows of one answer, as search_routes.py draws them, over the library's [songs] (`list_songs`'s): your songs'
 * rows with their cards, each site's rows with the song of yours each is (`_owners`, [Mine]), and the artists'.
 *
 * A card is the library page's ([SongCards], by song id), read as result_cards' four members: its files (`links`, the
 * page card's `files`), where its sheet came from (`source`), its key and what it holds for one instrument. A row of
 * your songs says where its sheet can be read (`files`, get.readable_files): its kept sheet, by the database, and its
 * PDF and viewer where its card lists them.
 */
internal class Rows(private val db: Db, val songs: List<SongRow>, private val cards: SongCards, forms: SongForms,
                    private val enabled: Set<String>) {
    private val mine = Mine(songs, forms)

    /** search_routes._rows: your songs' rows ([hits]) and the index's ([index], as [hitJson] writes them), each of the
     * index's naming its song of yours, with its links, and whether its artist is your song's (`same_artist`). */
    fun rows(hits: List<LibraryHit>, index: List<JsonObject>): Pair<List<JsonObject>, List<JsonObject>> {
        val owners = index.map { hit ->
            val ug = hit.text("ug")
            mine.songFor(ug.substringBefore('/'), ug.substringAfter('/', ""), hit.text("artist"), hit.text("title"))
        }
        val cards = Cards(hits.map { it.song } + owners.filterNotNull())
        val library = hits.map { h ->
            obj(
                "id" to h.song.id, "display" to h.song.display, "artist" to h.song.artist, "title" to h.song.title,
                "status" to h.song.status, "review" to h.song.review, "score" to h.score, "via" to h.via,
                "files" to cards.readable(h.song),
            ) with cards.result(h.song.id)
        }
        val rows = index.zip(owners).map { (hit, song) ->
            hit with keys(hit.text("artist"), hit.text("title")) with obj(
                "song" to song?.id,
                "same_artist" to (song != null && mine.sameArtist(song, hit.text("ug").substringBefore('/'), hit.text("artist"))),
                "library" to song?.let { cards.owner(it) },
            )
        }
        return library to rows
    }

    /** search_routes._owners: each site hit's song of yours (`song`, `library`), and whether its artist is your
     * song's (`same_artist`). */
    fun owners(hits: List<SiteHit>): List<JsonObject> {
        val owners = hits.map { mine.songFor(it.artistKey, it.titleKey, it.artist, it.title) }
        val cards = Cards(owners.filterNotNull())
        return hits.zip(owners).map { (h, song) ->
            obj(
                "song" to song?.id,
                "same_artist" to (song != null && mine.sameArtist(song, h.artistKey, h.artist)),
                "library" to song?.let { cards.owner(it) },
            )
        }
    }

    /** search_routes._gtptabs_rows: gtptabs.com's pages as the page draws them. */
    fun gtptabs(hits: List<SiteHit>): List<JsonObject> = hits.zip(owners(hits)).map { (h, mine) ->
        obj(
            "source" to h.source, "artist" to h.artist, "title" to h.title, "url" to h.url, "uploads" to h.uploads,
            "score" to h.score, "via" to h.via,
        ) with keys(h.artist, h.title) with mine
    }

    /** search_routes._lacuerda_rows: LaCuerda's songs, its page, the sheet Get it keeps (`sheet`) and its versions. */
    fun lacuerda(hits: List<SiteHit>): List<JsonObject> = hits.zip(owners(hits)).map { (h, mine) ->
        obj(
            "source" to h.source, "artist" to h.artist, "title" to h.title, "url" to h.url, "sheet" to h.sheet,
            "versions" to h.uploads, "score" to h.score, "via" to h.via,
        ) with keys(h.artist, h.title) with mine
    }

    /** search_routes._harptabs_rows: a song by an artist whose page caracole read, with its tabs, the most viewed first,
     * and its song of yours; a tab by its title alone (no artist), its title and page alone. */
    fun harptabs(hits: List<SiteHit>): List<JsonObject> {
        val owners = owners(hits.filter { it.artist.isNotEmpty() }).iterator()
        return hits.map { h ->
            if (h.artist.isEmpty()) {
                obj("source" to h.source, "title" to h.title, "url" to h.url, "score" to h.score)
            } else {
                obj(
                    "source" to h.source, "artist" to h.artist, "title" to h.title, "url" to h.url,
                    "uploads" to h.uploads, "score" to h.score, "via" to h.via, "page" to h.page,
                    "tabs" to h.tabs.map { it as HarpTabHit }.map { t ->
                        obj("title" to t.title, "url" to t.url, "views" to t.views, "rating" to t.rating,
                            "key" to t.key, "difficulty" to t.difficulty)
                    },
                ) with keys(h.artist, h.title) with owners.next()
            }
        }
    }

    /** search_routes._gametabs_rows: gametabs.net's tracks, the game as the artist, their tabs, what they are for and
     * who composed them, and its song of yours. */
    fun gametabs(hits: List<SiteHit>): List<JsonObject> {
        val owners = owners(hits).iterator()
        return hits.map { h ->
            obj(
                "source" to h.source, "artist" to h.artist, "title" to h.title, "url" to h.url, "uploads" to h.uploads,
                "score" to h.score, "via" to h.via, "page" to h.page,
                "instruments" to LinkedHashSet(h.tabs.flatMap { instruments(it) }).toList(),
                "composers" to LinkedHashSet(h.tabs.flatMap { composers(it) }).toList(),
                "tabs" to h.tabs.map { t ->
                    val (title, url, views, rating) = when (t) {
                        is GameTabHit -> Quad(t.title, t.url, t.views, t.rating)
                        is HarpTabHit -> Quad(t.title, t.url, t.views, t.rating)
                        else -> throw IllegalArgumentException("not a tab: $t")
                    }
                    obj("title" to title, "url" to url, "views" to views, "rating" to rating,
                        "instruments" to instruments(t), "composers" to composers(t))
                },
            ) with keys(h.artist, h.title) with owners.next()
        }
    }

    /** search_routes._harptabs_artist_json: the tabs their page says they have, those the index holds and the songs
     * they are of (`held`), whether caracole read their page, their most viewed songs, their page's path. */
    fun harptabsArtist(a: SiteArtist): JsonObject {
        val held = db.one("SELECT COUNT(DISTINCT song_key) FROM harptabs_artist_tabs WHERE artist = ?", a.slug) {
            it.long(0)
        } ?: 0L
        return obj(
            "source" to a.source, "artist" to a.artist, "path" to a.slug, "url" to a.url, "songs" to a.songs,
            "known" to a.known, "held" to held, "read" to a.read, "score" to a.score, "via" to a.via, "part" to a.part,
            "group_key" to groupKey(a.artist), "top" to harptabs(a.top),
        )
    }

    /** search_routes._lacuerda_artist_json: their songs as the listing counts them, those the index holds, the most
     * popular with chords, and their group. */
    fun lacuerdaArtist(a: SiteArtist): JsonObject = obj(
        "source" to a.source, "artist" to a.artist, "slug" to a.slug, "url" to a.url, "songs" to a.songs,
        "known" to a.known, "score" to a.score, "via" to a.via, "group_key" to groupKey(a.artist),
        "top" to lacuerda(a.top),
    )

    /** search_routes._gtptabs_songs: an artist's songs on gtptabs.com, none while it is turned off. */
    fun gtptabsSongs(artist: String): Int = if ("gtptabs" in enabled) SiteSearch.gtptabsSongs(db, artist) else 0

    private data class Quad(val title: String, val url: String, val views: Int, val rating: Double?)

    private fun instruments(t: Any): List<String> = (t as? GameTabHit)?.instruments ?: emptyList()

    private fun composers(t: Any): List<String> = (t as? GameTabHit)?.composers ?: emptyList()

    /** The cards of [songs] (each once, by id), as library_page.result_cards gives them. */
    private inner class Cards(songs: List<SongRow>) {
        private val page: Map<Long, JsonObject>

        init {
            val distinct = LinkedHashMap<Long, SongRow>()
            for (s in songs) distinct[s.id] = s
            page = if (distinct.isEmpty()) emptyMap() else cards.cards(db, distinct.values.toList())
        }

        /** result_cards' card: `links`, `source`, `key`, `instruments`. */
        fun result(id: Long): JsonObject {
            val card = page[id]
            return obj(
                "links" to (card?.get("files") ?: JsonArray(emptyList())), "source" to (card?.get("source") ?: JsonNull),
                "key" to (card?.get("key") ?: JsonNull), "instruments" to (card?.get("instruments") ?: JsonArray(emptyList())),
            )
        }

        /** A site row's song of yours: its names, its status and its card's links. */
        fun owner(song: SongRow): JsonObject = obj(
            "id" to song.id, "artist" to song.artist, "title" to song.title, "display" to song.display,
            "status" to song.status, "links" to result(song.id)["links"],
        )

        /** get.readable_files: where the song's sheet can be read, as paths in the library: `sheet` (its kept text),
         * and `pdf` and `viewer` (render's HTML viewer) where its card lists them; empty without a kept sheet. */
        fun readable(song: SongRow): JsonObject {
            val kept = db.query("SELECT name, path FROM files WHERE song_id = ? ORDER BY name", song.id) {
                it.text(0)!! to it.text(1)!!
            }.toMap()
            val name = SHEET_FILE_NAMES.firstOrNull { it in kept } ?: return JsonObject(emptyMap())
            val path = kept.getValue(name)
            val base = path.substringBeforeLast('/', "")
            val stem = name.substringBeforeLast('.')
            val listed = (page[song.id]?.get("files") as? JsonArray).orEmpty()
                .mapNotNull { ((it as? JsonObject)?.get("name") as? JsonPrimitive)?.content }.toSet()
            val files = LinkedHashMap<String, Any?>()
            files["sheet"] = path
            for ((what, file) in listOf("pdf" to "$stem.pdf", "viewer" to "$stem.html")) {
                if (file in listed) files[what] = if (base.isEmpty()) file else "$base/$file"
            }
            return obj(*files.map { it.key to it.value }.toTypedArray())
        }
    }

    private companion object {
        /** songs.SHEET_FILE_NAMES: a song's sheets, the human one first. */
        val SHEET_FILE_NAMES = listOf("sheet.txt", "sheet (auto).txt")
    }
}

/** A row's `song` member, the id of its song of yours; null for none, or a row that names none. */
internal fun songOf(row: JsonObject): Long? = (row["song"] as? JsonPrimitive)?.longOrNull
