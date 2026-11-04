package io.github.danielhp95.caracole.core.lacuerda

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.HttpRules
import io.github.danielhp95.caracole.core.http.LaCuerdaParseError
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.lacuerda.internal.pages.PyBits
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.search.LibraryHit
import io.github.danielhp95.caracole.core.search.Search
import io.github.danielhp95.caracole.core.search.SearchLimits
import io.github.danielhp95.caracole.core.search.SiteArtist
import io.github.danielhp95.caracole.core.search.SiteHit
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Duration
import java.time.Instant

/** /api/search's `lacuerda_search`, as search_routes._lacuerda_search_gate makes it of a [LaCuerdaSearch.Gate]: its
 * [state], the [query], its [key], and, `failed`, why the page doesn't send it by itself ([why], a sentence). */
data class SearchGate(val state: String, val query: String, val key: String, val why: String?) {
    companion object {
        /** The gate's shape for /api/search: null for none. */
        fun of(query: String, gate: LaCuerdaSearch.Gate?): SearchGate? = gate?.let {
            SearchGate(it.state, query, it.key, it.failure?.let { f -> f.said("“$query”") + "." })
        }
    }
}

/** lacuerda.LCArtist: an artist of a listing (or of a search that answers artists): the slug of their page, their
 * name as LaCuerda writes it, and how many songs it counts. */
data class LaCuerdaArtist(val slug: String, val name: String, val songs: Long)

/** lacuerda.LCSong: [types] one letter a version, version 1 first; [ranking] its versions' order; [lcd] the code
 * both were read from, as the page wrote it. */
data class LaCuerdaSong(val slug: String, val title: String, val types: String, val ranking: List<Int>, val lcd: String = "")

/** lacuerda.SearchSong: a song of an answer of LaCuerda's search, the slug of their artist's page and their name as
 * the row's link has them. */
data class LaCuerdaSearchSong(val artistSlug: String, val artist: String, val song: LaCuerdaSong) {
    val title: String get() = song.title
    val slug: String get() = song.slug

    /** The song's own page, which lists its versions. */
    val url: String get() = LaCuerdaUrls.songUrl(artistSlug, song.slug)

    /** The page of its best Letra y Acordes version; null for a song with none. */
    val sheetUrl: String? get() = LaCuerdaPages.bestAcordesVersion(song)?.let { LaCuerdaUrls.versionUrl(artistSlug, song.slug, it) }
}

/** lacuerda.SearchAnswer: what a page of LaCuerda's search answered, its songs or the artists in their place, in page
 * order, and how many results it counts ([stated]). */
data class LaCuerdaSearchAnswer(val songs: List<LaCuerdaSearchSong> = emptyList(),
                                val artists: List<LaCuerdaArtist> = emptyList(), val stated: Long = 0)

/**
 * lacuerda_search.py on the phone: LaCuerda's own search, one query, one request at the lookup pace, and its gate.
 *
 * A query is the words LaCuerda reads of it, in alphabetical order ([queryKey]); it is asked at most once in 30 days
 * (kv `lacuerda:search:<key>`, [asked]), none for a query caracole answers well already ([answersWell], [answered]),
 * none while LaCuerda cools down or the hour's lookups are spent, and the page's own within [SEARCHES_PER_HOUR] an
 * hour, counted in `events` under runs named `lookup:lacuerda-search:…` ([searchesUsed]). A search that failed
 * ([recordFailure], kv `lacuerda:search-failed`) isn't sent by the page by itself for an hour, nor any once three
 * did ([failed]). [gate] says, with no request, what a search would be; [search] sends it and stores what it answers
 * in one savepoint. Every count is this side's own. tests/conformance/vectors/lookup/lacuerda_gate.jsonl and
 * lacuerda_search.jsonl hold it to Python's answers (LaCuerdaSearchTest).
 */
object LaCuerdaSearch {
    const val PROVIDER = "lacuerda"
    const val SEARCHES_PER_HOUR = 20
    val ASKED_FOR: Duration = Duration.ofDays(30)
    const val RUN = "lacuerda-search:"
    const val KV_PREFIX = "lacuerda:search:"
    val STATES: List<String> = listOf("auto", "button", "failed", "asked", "spent")
    val FAILED_FOR: Duration = Duration.ofHours(1)
    const val FAILURES_PAUSE = 3
    const val FAILED_KEY = "lacuerda:search-failed"
    const val ERROR_CHARS = 200
    const val ANSWER_HITS = 5

    private const val HOUR_US = 3_600_000_000L
    private val ASKED_FOR_US = ASKED_FOR.toDays() * 24 * HOUR_US

    /** query_key: the query as LaCuerda's search reads it, its words sorted and hyphenated; "" for none. */
    fun queryKey(q: String): String = LaCuerdaPages.searchWords(q).sortedWith(Py.CODE_POINT_ORDER).joinToString("-")

    /** asked: what LaCuerda answered the query of [key] when it was asked within 30 days, as json.loads reads kv
     * `lacuerda:search:<key>`; null when it wasn't. */
    fun asked(db: Db, key: String, now: Instant): JsonObject? {
        if (key.isEmpty()) return null
        val said = db.kvGet(KV_PREFIX + key)?.let { PyJson.loads(it) } as? JsonObject ?: return null
        return if (before(said["at"], Stamps.micros(now) - ASKED_FOR_US)) null else said
    }

    /** answers_well: a strong song of LaCuerda's index, the artist the query names, whole, whose page caracole has
     * read, or a strong song of your library. */
    fun answersWell(lcArtists: List<SiteArtist>, lcSongs: List<SiteHit>, mine: List<LibraryHit> = emptyList()): Boolean =
        lcSongs.any { it.score >= SearchLimits.STRONG } ||
            lcArtists.any { it.score >= SearchLimits.STRONG && !it.part && it.known > 0 } ||
            mine.any { it.score >= SearchLimits.STRONG }

    /** answered: [answersWell] for [q], its searches made now, LaCuerda's index and your library read alone. */
    fun answered(db: Db, q: String): Boolean {
        val (artists, songs) = LaCuerda.searchLacuerda(db, q, songs = ANSWER_HITS)
        return answersWell(artists, songs, Search.searchLibrary(db, q, ANSWER_HITS))
    }

    /** lacuerda_search.Failure: the query's own search failed within the hour ([own]), or [count] did; [error] what
     * the latest said; [until] (microseconds since 0001-01-01 UTC, as Stamps keeps a time) when the page may send it
     * by itself again. */
    data class Failure(val own: Boolean, val count: Int, val error: String, val until: Long) {
        /** Why, in a sentence without its full stop, [query] as it is shown ("“corazon tiza”"). */
        fun said(query: String): String = if (own) {
            "LaCuerda's search for $query failed less than an hour ago ($error), so the page won't send it by itself " +
                "before ${shown(until)}"
        } else {
            "$count searches of LaCuerda failed in the last hour (the last: $error), so the page sends none by itself " +
                "before ${shown(until)}"
        }
    }

    /** _failures: the searches that failed within the hour, by key, each its `at` and `error` as str() reads them. */
    private fun failures(db: Db, now: Instant): LinkedHashMap<String, Pair<String, String>> {
        val out = LinkedHashMap<String, Pair<String, String>>()
        val said = db.kvGet(FAILED_KEY)?.let { PyJson.loads(it) } as? JsonObject ?: return out
        val since = Stamps.micros(now) - HOUR_US
        for ((k, v) in said) {
            if (v !is JsonObject || before(v["at"], since)) continue
            val at = v["at"]?.let { PyBits.str(it) } ?: "None"
            val error = v["error"]?.takeUnless { falsy(it) }?.let { PyBits.str(it) } ?: ""
            out[k] = at to error
        }
        return out
    }

    /** failed: why the page doesn't send the search of [key] by itself now, or null. */
    fun failed(db: Db, key: String, now: Instant): Failure? {
        val failures = failures(db, now)
        failures[key]?.let { (at, error) -> return Failure(true, 1, error, Stamps.parse(at)!! + HOUR_US) }
        if (failures.size < FAILURES_PAUSE) return null
        val times = failures.values.sortedBy { Stamps.parse(it.first)!! }
        val until = Stamps.parse(times[times.size - FAILURES_PAUSE].first)!! + HOUR_US
        return Failure(false, times.size, times.last().second, until)
    }

    /** record_failure: the search of [key] failed now, saying [error] (its spaces collapsed, 200 characters kept);
     * failures older than an hour go. */
    fun recordFailure(db: Db, key: String, now: Instant, error: String) {
        val kept = failures(db, now)
        kept[key] = Stamps.of(now) to Py.slice(PyBits.collapsed(error), 0, ERROR_CHARS)
        write(db, kept)
    }

    /** _forget_failure. */
    fun forgetFailure(db: Db, key: String, now: Instant) {
        val kept = failures(db, now)
        kept.remove(key)
        write(db, kept)
    }

    private fun write(db: Db, failures: Map<String, Pair<String, String>>) {
        db.kvSetJson(FAILED_KEY, JsonObject(failures.mapValuesTo(LinkedHashMap()) { (_, v) ->
            JsonObject(linkedMapOf("at" to JsonPrimitive(v.first), "error" to JsonPrimitive(v.second)))
        }))
    }

    /** searches_used: the requests LaCuerda's searches sent in the last hour. */
    fun searchesUsed(db: Db, now: Instant): Int = Pace.lookupRequestsUsed(db, PROVIDER, now, run = Pace.LOOKUP_RUN + RUN)

    /** lacuerda_search.Gate: what a search of a query would be: its [state] ([STATES]), its [key], what LaCuerda
     * answered it within 30 days ([asked]), and why the page doesn't send it by itself ([failure]). */
    data class Gate(val state: String, val key: String, val asked: JsonObject? = null, val failure: Failure? = null)

    /** gate: what a search of [q] would be, with no request; null for no word LaCuerda reads, caracole answering it
     * well already ([strong], [answersWell]'s), or LaCuerda turned off. */
    fun gate(cfg: PhoneConfig, db: Db, q: String, strong: Boolean, now: Instant): Gate? {
        val key = queryKey(q)
        val p = cfg.provider(PROVIDER)
        if (key.isEmpty() || strong || !p.enabled) return null
        asked(db, key, now)?.let { return Gate("asked", key, it) }
        if (Health.isCooling(db, PROVIDER, now) || p.lookupRequests < 1 ||
            Pace.lookupRequestsUsed(db, PROVIDER, now) >= p.lookupPerHour) {
            return Gate("spent", key)
        }
        failed(db, key, now)?.let { return Gate("failed", key, failure = it) }
        if (searchesUsed(db, now) >= SEARCHES_PER_HOUR) return Gate("button", key)
        return Gate("auto", key)
    }

    /** /api/search's `lacuerda_search` for [q]: the [gate], strong as [answered] reads it, shaped as
     * search_routes._lacuerda_search_gate shapes it ([SearchGate.of]). */
    fun gate(cfg: PhoneConfig, db: Db, q: String, now: Instant): SearchGate? =
        SearchGate.of(q, gate(cfg, db, q, answered(db, q), now))

    /**
     * search: LaCuerda's search for the songs of [q] (one request, none while the cache holds an answer younger than
     * 30 days), its answer stored in the index and the query recorded asked, its failure gone, in one savepoint. A
     * cached page that won't parse is asked for once more, past the cache. Provider errors propagate (a page cut
     * short among them) and record nothing; a stale copy served because the budget is spent is [BudgetExhausted].
     * The rows stored are noted for the next push of the index (LaCuerda.storeSearch).
     */
    fun search(db: Db, client: Client, q: String, now: Instant): LaCuerdaSearchAnswer {
        val url = LaCuerdaPages.searchUrl(q)
        val resp = client.get(url, accept = setOf(200), maxAge = ASKED_FOR)
        if (HttpRules.stale(resp, now, ASKED_FOR)) throw BudgetExhausted(PROVIDER)
        val answer = HttpRules.readOnceMore(client, resp, url, { it is LaCuerdaParseError }, accept = setOf(200)) { r ->
            LaCuerdaPages.parseSearch(r.text, url = r.url)
        }
        db.savepoint("lacuerda_search") {
            LaCuerda.storeSearch(db, answer, Stamps.of(now))
            val key = queryKey(q)
            db.kvSetJson(KV_PREFIX + key, JsonObject(linkedMapOf(
                "at" to JsonPrimitive(Stamps.of(now)), "songs" to JsonPrimitive(answer.songs.size),
                "artists" to JsonPrimitive(answer.artists.size), "stated" to JsonPrimitive(answer.stated),
            )))
            forgetFailure(db, key, now)
        }
        return answer
    }

    /** stamps.before: a stored time older than [cutoff], or missing or unreadable (Stamps.parse of a value json.loads
     * made, a TypeError for a value that is no text). */
    private fun before(value: JsonElement?, cutoff: Long): Boolean {
        val at = Stamps.parse(value) ?: return true
        return at < cutoff
    }

    private fun falsy(e: JsonElement): Boolean = when (e) {
        is JsonObject -> e.isEmpty()
        is JsonArray -> e.isEmpty()
        is JsonPrimitive -> when {
            e.isString -> e.content.isEmpty()
            e.content == "null" || e.content == "false" -> true
            else -> e.content.toDoubleOrNull() == 0.0
        }
    }

    /** stamps.shown: "2026-11-03 12:30 UTC". */
    private fun shown(micros: Long): String {
        val s = Stamps.stamp(micros)
        return s.substring(0, 10) + " " + s.substring(11, 16) + " UTC"
    }
}
