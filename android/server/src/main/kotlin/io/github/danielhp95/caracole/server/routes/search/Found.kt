package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.lacuerda.LaCuerda
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSearch
import io.github.danielhp95.caracole.core.lacuerda.SearchGate
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.names.SongNames
import io.github.danielhp95.caracole.core.search.IndexFound
import io.github.danielhp95.caracole.core.search.IndexHit
import io.github.danielhp95.caracole.core.search.LibraryHit
import io.github.danielhp95.caracole.core.search.Search
import io.github.danielhp95.caracole.core.search.SearchLimits
import io.github.danielhp95.caracole.core.search.SiteArtist
import io.github.danielhp95.caracole.core.search.SiteHit
import io.github.danielhp95.caracole.core.search.Suggest
import io.github.danielhp95.caracole.core.search.Suggestion
import io.github.danielhp95.caracole.core.sites.SiteSearch
import io.github.danielhp95.caracole.server.page.SongCards
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import java.time.Instant

/** search_routes.LIBRARY_HITS, INDEX_HITS, SITE_HITS: your songs, the index's songs and each site's a search gives. */
internal const val LIBRARY_HITS = 5
internal const val INDEX_HITS = 8
internal const val SITE_HITS = 5

/**
 * What the offline indexes answer a query (search_routes.IndexAnswers), kept a while ([AnswerCache]): Ultimate
 * Guitar's (`find_index`'s, its songs and artists as JSON, the hint and what the pages say of an artist it may not
 * see), gtptabs.com's and MuseScore's pages, harptabs.com's and LaCuerda's artists and songs, gametabs.net's tracks,
 * and the artists and songs spelled close to the query ([close]: null until looked for, once a song of yours doesn't
 * make it moot).
 */
internal class IndexAnswers(
    val indexFound: IndexFound, val index: List<JsonObject>, val artists: List<JsonObject>, val hint: String?,
    val unseen: JsonObject?, val gtptabs: List<SiteHit>, val musescore: List<SiteHit>,
    val harpArtists: List<SiteArtist>, val harptabs: List<SiteHit>, val lcArtists: List<SiteArtist>,
    val lacuerda: List<SiteHit>, val gametabs: List<SiteHit>,
) {
    @Volatile var close: List<Suggestion>? = null
}

/**
 * One search's answer, as search_routes._found_for makes it, over [db]: your songs, the artists the query names, the
 * index's songs, which leads, the row Enter may act on, each site's rows, the songs spelled close to it, where it
 * looked, a LaCuerda artist's page to read (`lacuerda_unlisted`, [Unlisted]) and whether LaCuerda's own search may be
 * sent for it (`lacuerda_search`: LaCuerdaSearch.gate under [config] at [now], with its `why` when it failed lately;
 * null with [searchesLacuerda] false, as `WebApp(searches_lacuerda=False)` answers). What the phone can't answer is
 * null: `progression` (M5's progressions) and `youtube` (the phone runs no yt-dlp). [check] is called between two of
 * its queries, and throws to stop it ([Superseded]).
 */
internal class Found(
    private val db: Db, private val enabled: Set<String>, private val cards: SongCards, private val forms: SongForms,
    private val answers: AnswerCache<IndexAnswers>, private val check: () -> Unit,
    private val config: PhoneConfig = PhoneConfig.DEFAULTS, private val searchesLacuerda: Boolean = false,
    private val now: Instant = Instant.EPOCH,
) {
    fun answer(q: String): JsonObject {
        val mine = Search.searchLibrary(db, q, LIBRARY_HITS)
        check()
        // A song of yours by its title matches well: nothing to suggest, and no close spelling looked for.
        val yours = mine.any { it.score >= SearchLimits.STRONG && it.via != "artist" }
        val removed = Search.searchRemoved(db, q, LIBRARY_HITS)
        check()
        val looked = Looked(db, enabled)
        val (skipped, partial) = looked.skipped()
        val leftOut = skipped.mapTo(HashSet()) { it.source }
        val kept = indexAnswers(q, leftOut)
        val close = if (yours) emptyList() else suggested(q, kept, leftOut)
        check()
        val answer = Search.found(mine, kept.indexFound)
        val leads = LaCuerda.lacuerdaLeads(kept.indexFound, kept.lcArtists)
        val songs = Songs.list(db)
        check()
        val rows = Rows(db, songs, cards, forms, enabled)
        val (library, hits, artists) = libraryAndIndexRows(rows, mine, kept)
        check()
        // LaCuerda's group leads: Ultimate Guitar's artist a word names is no lead, and Enter opens LaCuerda's artist.
        val lead = if (leads && answer.lead == "artist") "song" else answer.lead
        val names = SongNames.readNames(db, q, songs)?.let { (artist, title) -> obj("artist" to artist, "title" to title) }
        check()
        val removedRows = removed.map { h ->
            obj("artist" to h.artist, "title" to h.title, "key" to h.key, "removed_at" to h.removedAt) with keyParts(h.key)
        }
        val gtptabs = rows.gtptabs(if ("gtptabs" !in leftOut) kept.gtptabs else emptyList())
        val musescore = (if ("musescore" !in leftOut) kept.musescore else emptyList()).map { h ->
            obj("source" to h.source, "title" to h.title, "url" to h.url, "score" to h.score)
        }
        // harptabs.com's songs, a song's harmonica tabs by an artist whose page caracole read, else a tab by its title
        // alone, a possible match, as MuseScore's pages are; and its artists, as LaCuerda's
        val harptabs = rows.harptabs(kept.harptabs)
        val harptabsArtists = kept.harpArtists.map { rows.harptabsArtist(it) }
        check()
        // gametabs.net's tracks of games, the game as the artist, each with its tabs
        val gametabs = rows.gametabs(kept.gametabs)
        val lacuerda = rows.lacuerda(kept.lacuerda)
        val lacuerdaArtists = kept.lcArtists.map { a ->
            rows.lacuerdaArtist(a) with obj("gtptabs" to rows.gtptabsSongs(a.artist))
        }
        check()
        val suggest = close.map { suggestion(rows, it) }
        check()
        val unlisted = Unlisted.lacuerdaUnlisted(db, q, kept.indexFound.artists, kept.indexFound.songs, kept.indexFound.lead,
                                                 kept.lcArtists + kept.lacuerda)
            ?.let { (name, letter) -> obj("name" to name, "letter" to letter) }
        check()
        val gate = if (searchesLacuerda) lacuerdaSearchGate(q, kept, mine) else null
        check()
        return obj(
            "query" to q, "library" to library, "index" to hits, "artists" to artists, "lead" to lead,
            "best" to best(answer.best), "hint" to kept.hint, "progression" to null, "unseen" to kept.unseen,
            // the artist and the title the query names, which the request form is filled in with; null for none
            "names" to names, "removed" to removedRows, "gtptabs" to gtptabs, "musescore" to musescore,
            "harptabs" to harptabs, "harptabs_artists" to harptabsArtists, "gametabs" to gametabs, "lacuerda" to lacuerda,
            "lacuerda_artists" to lacuerdaArtists, "lacuerda_unlisted" to unlisted, "lacuerda_leads" to leads,
            "lacuerda_search" to gate, "youtube" to null, "suggest" to suggest,
            "skipped" to skipped.map { it.json() }, "partial" to partial.map { it.json() },
            "looked" to looked.looked(skipped, partial),
        )
    }

    /** search_routes._lacuerda_search_gate: what sending LaCuerda's search for [q] would be, with no request: null,
     * or its `state`, the `query` and its `key`, and, `failed`, why the page doesn't send it by itself (`why`). None
     * when the answer's own hits answer it well already (LaCuerdaSearch.answersWell: LaCuerda's index's, [kept], and
     * your library's, [mine]). */
    private fun lacuerdaSearchGate(q: String, kept: IndexAnswers, mine: List<LibraryHit>): JsonObject? {
        val strong = LaCuerdaSearch.answersWell(kept.lcArtists, kept.lacuerda, mine)
        val said = SearchGate.of(q, LaCuerdaSearch.gate(config, db, q, strong, now)) ?: return null
        return obj("state" to said.state, "query" to said.query, "key" to said.key) with
            (said.why?.let { obj("why" to it) } ?: obj())
    }

    /** search_routes._index_answers: those kept, [AnswerCache.SECONDS] old at most, else made now and kept, none of a
     * site [leftOut] (nor of gametabs.net while it is turned off). */
    private fun indexAnswers(q: String, leftOut: Set<String>): IndexAnswers {
        answers.get(q)?.let { return it }
        val since = answers.era
        val ug = indexHits(q)
        check()
        val gtptabs = if ("gtptabs" !in leftOut) SiteSearch.searchGtptabs(db, q, SITE_HITS) else emptyList()
        check()
        val musescore = if ("musescore" !in leftOut) SiteSearch.searchMusescore(db, q, SITE_HITS) else emptyList()
        check()
        val (harpArtists, harptabs) =
            if ("harptabs" !in leftOut) SiteSearch.searchHarptabs(db, q, songs = SITE_HITS) else emptyList<SiteArtist>() to emptyList()
        check()
        val (lcArtists, lacuerda) =
            if ("lacuerda" !in leftOut) LaCuerda.searchLacuerda(db, q, songs = SITE_HITS) else emptyList<SiteArtist>() to emptyList()
        check()
        val gametabs = if ("gametabs" in enabled) SiteSearch.searchGametabs(db, q, SITE_HITS) else emptyList()
        check()
        return IndexAnswers(ug.found, ug.index, ug.artists, ug.hint, ug.unseen, gtptabs, musescore, harpArtists, harptabs,
                            lcArtists, lacuerda, gametabs).also { answers.put(q, it, since) }
    }

    private class UgHits(val found: IndexFound, val index: List<JsonObject>, val artists: List<JsonObject>,
                         val hint: String?, val unseen: JsonObject?)

    /** search_routes._index_hits: Ultimate Guitar's songs and artists, each artist with their most tabbed songs, as
     * the index's songs are, and the group the library page puts them in; the hint, and what the pages say of an
     * artist the index may not see. */
    private fun indexHits(q: String): UgHits {
        if (indexCount(db) == 0L) return UgHits(IndexFound(), emptyList(), emptyList(), Looked.UG_EMPTY, null)
        val answer = Search.findIndex(db, q, songs = INDEX_HITS)
        val artists = answer.artists.map { a ->
            obj(
                "artist_key" to a.artistKey, "artist" to a.artist, "score" to a.score, "songs" to a.songs,
                "tabs" to a.tabs, "part" to a.part, "group_key" to groupKey(a.artist),
                "top" to a.top.map { hitJson(db, it) },
            )
        }
        val index = answer.songs.map { hitJson(db, it) }
        val hits: List<Any> = answer.songs + answer.artists
        return UgHits(answer, index, artists, Search.bareIdHint(q, hits), Search.bareIdUnseen(q, hits))
    }

    /** search_routes._suggested: the artists and songs spelled close to [q] beside the indexes' answers, looked for
     * once and kept with them. */
    private fun suggested(q: String, kept: IndexAnswers, leftOut: Set<String>): List<Suggestion> {
        kept.close?.let { return it }
        val sites: List<Any> = kept.lcArtists + kept.lacuerda + kept.gtptabs + kept.musescore + kept.harpArtists +
            kept.harptabs
        return Suggest.suggestions(
            db, q, kept.indexFound, sites, lacuerda = "lacuerda" !in leftOut, harptabs = "harptabs" !in leftOut,
            gtptabs = "gtptabs" !in leftOut,
        ).also { kept.close = it }
    }

    /** search_routes._library_and_index_rows: your songs' rows, the index's songs' and its artists': the artists' most
     * tabbed songs are the index's songs too, each with its song of yours, and an artist's songs on gtptabs.com
     * counted. */
    private fun libraryAndIndexRows(rows: Rows, mine: List<LibraryHit>, kept: IndexAnswers):
        Triple<List<JsonObject>, List<JsonObject>, List<JsonObject>> {
        val tops = kept.artists.flatMap { (it["top"] as JsonArray).map { t -> t as JsonObject } }
        val (library, all) = rows.rows(mine, kept.index + tops)
        val owned = all.subList(kept.index.size, all.size).iterator()
        val artists = kept.artists.map { a ->
            a with obj("top" to (a["top"] as JsonArray).map { owned.next() }, "gtptabs" to rows.gtptabsSongs(a.text("artist")))
        }
        return Triple(library, all.subList(0, kept.index.size), artists)
    }

    /** search_routes._best_json: a song of yours by its id, an Ultimate Guitar song by its keys; null for none. */
    private fun best(best: Any?): JsonObject? = when (best) {
        null -> null
        is LibraryHit -> obj("library" to best.song.id)
        is IndexHit -> obj("ug" to "${best.artistKey}/${best.songKey}")
        else -> throw IllegalArgumentException("not a hit: $best")
    }

    /** search_routes._suggestion_json: a suggestion as the pages draw it: the artist's band (their site, name, songs
     * there, group, and what /api/artist takes of them); a song's, its title too, the song on each index that has it
     * (`song`, each as the search's rows of that site are) and, for a song of yours, its row as your songs' are. */
    private fun suggestion(rows: Rows, s: Suggestion): JsonObject {
        val said = obj(
            "source" to s.source, "artist" to s.artist, (SUGGESTED_KEY[s.source] ?: "key") to s.key, "songs" to s.songs,
            "group_key" to groupKey(s.artist),
        )
        if (s.title.isEmpty()) return said
        val found = LinkedHashMap<String, JsonObject>()
        for (h in s.hits) {
            val source = if (h is IndexHit) "ug" else (h as SiteHit).source
            if (source in found) continue
            found[source] = when {
                h is IndexHit -> rows.rows(emptyList(), listOf(hitJson(db, h))).second[0]
                source == "lacuerda" -> rows.lacuerda(listOf(h as SiteHit))[0]
                source == "gtptabs" -> rows.gtptabs(listOf(h as SiteHit))[0]
                else -> rows.harptabs(listOf(h as SiteHit))[0]
            }
        }
        val yours = found.values.firstNotNullOfOrNull { songOf(it) }
        val song = rows.songs.firstOrNull { it.id == yours }
        val library = song?.let { rows.rows(listOf(LibraryHit(it, 100.0, "title")), emptyList()).first[0] }
        return said with obj("title" to s.title, "song" to found, "library" to (library ?: JsonNull))
    }

    private companion object {
        /** search_routes.SUGGESTED_KEY: what /api/artist takes of each site's artist. */
        val SUGGESTED_KEY = mapOf("ug" to "artist_key", "lacuerda" to "slug", "harptabs" to "path")
    }
}
