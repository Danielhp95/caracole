package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.http.GameTabsParseError
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.sites.GameListedTab
import io.github.danielhp95.caracole.core.sites.GamePage
import io.github.danielhp95.caracole.core.sites.GameTab
import io.github.danielhp95.caracole.core.sites.GameTabsFetch
import io.github.danielhp95.caracole.core.sites.GameTabsPages
import io.github.danielhp95.caracole.core.sites.GameTabsStats
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Scenarios
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long

/**
 * gametabs.net (vectors/sites/gametabs.jsonl, vectors/lookup/gametabs.jsonl; tests/test_conformance_gametabs.py)
 * answered by core.sites as Python answered it: a tab page and a game page read (GameTabsPages), the forms and fits
 * gametabs_fetch.py compares by, and a lookup's pass replayed over its world (GameTabsFetch.gametabsTabs, each
 * request carrying caracole's user agent). GameTabsTest calls it on the JVM; CorpusOnDeviceTest runs it under ART.
 */
object GameTabsReplay : AreaReplay {
    override val area = "gametabs"

    const val SITES = "sites/gametabs.jsonl"
    const val LOOKUP = "lookup/gametabs.jsonl"

    override fun replay(misses: Misses) {
        pages(misses)
        batches(misses)
        lookups(misses)
    }

    // --- what a record holds ---------------------------------------------------------------------------------

    private fun str(s: String?): JsonElement = s?.let { JsonPrimitive(it) } ?: JsonNull
    private fun names(list: List<String>) = JsonArray(list.map { JsonPrimitive(it) })
    private fun float(x: Double?): JsonElement = x?.let { PyJson.float(it) } ?: JsonNull

    /** plain(GameTab), with `raw`, its raw(). */
    fun tab(t: GameTab): JsonObject = JsonObject(linkedMapOf(
        "tab_id" to (t.tabId?.let { JsonPrimitive(it) } ?: JsonNull), "title" to str(t.title), "game" to str(t.game),
        "game_slug" to str(t.gameSlug), "slug" to str(t.slug), "body" to str(t.body), "composers" to names(t.composers),
        "instruments" to names(t.instruments), "styles" to names(t.styles), "tuning" to str(t.tuning),
        "tabber" to str(t.tabber), "views" to JsonPrimitive(t.views), "rating" to float(t.rating),
        "ratings" to JsonPrimitive(t.ratings), "created" to str(t.created), "raw" to t.raw(),
    ))

    private fun listed(t: GameListedTab): JsonObject = JsonObject(linkedMapOf(
        "path" to str(t.path), "title" to str(t.title), "composers" to names(t.composers),
        "instruments" to names(t.instruments), "styles" to names(t.styles), "platform" to str(t.platform),
        "tabber" to str(t.tabber), "views" to JsonPrimitive(t.views), "rating" to float(t.rating),
    ))

    /** plain(GamePage). */
    fun game(p: GamePage): JsonObject = JsonObject(linkedMapOf(
        "name" to str(p.name), "tabs" to JsonPrimitive(p.tabs), "listed" to JsonArray(p.listed.map { listed(it) }),
        "pages" to JsonPrimitive(p.pages),
    ))

    /** The words of what a parser raised, as the record writes Python's: its type, then its message. */
    private fun raised(e: Exception): String = when (e) {
        is GameTabsParseError -> "GameTabsParseError: ${e.message}"
        is ArithmeticException -> "OverflowError: ${e.message}"  // Python's OverflowError
        is IllegalArgumentException -> "ValueError: ${e.message}"
        else -> "${e::class.simpleName}: ${e.message}"
    }

    // --- the pages -----------------------------------------------------------------------------------------------

    private fun pages(misses: Misses) {
        for (r in Corpus.records(SITES).filter { it.fn.endsWith("parse_tab_page") || it.fn.endsWith("parse_game_page") }) {
            val case = r.extra["case"]?.jsonPrimitive?.content ?: r.fn
            val body = Scenarios.body(r.args[0])
            val url = (r.kw["url"] as? JsonPrimitive)?.takeIf { it.isString }?.content
            val got: Result<JsonObject> = try {
                Result.success(if (r.fn.endsWith("parse_tab_page")) tab(GameTabsPages.parseTabPage(body, url))
                               else game(GameTabsPages.parseGamePage(body, url)))
            } catch (e: Exception) {
                Result.failure(e)
            }
            val error = got.exceptionOrNull() as? Exception
            if (r.err != null) {
                misses.check(error != null && raised(error) == r.err) {
                    "${r.fn} ($case): ${error?.let { raised(it) } ?: got.getOrNull()}, Python raised ${r.err}"
                }
            } else {
                misses.check(error == null && got.getOrNull() == r.out) {
                    "${r.fn} ($case): ${error?.let { raised(it) } ?: got.getOrNull()}, Python's ${r.out}"
                }
            }
        }
    }

    // --- the forms and fits --------------------------------------------------------------------------------------

    /** A song of these names, as gametabs_fetch.py reads one (its artists, its artist, its title). */
    fun song(artists: List<String>, artist: String, title: String): SongRow = SongRow(
        id = 1, key = "k", artist = artist, title = title, artists = artists, album = null, durationMs = null,
        isrc = null, sourceIds = "[]", addedAt = "", variant = null, status = "pending", review = false,
        matchDecision = null, matchStep = null, matchScore = null, matchArtistKey = null, matchSongKey = null,
        matchCandidates = "[]", matchedAt = null, ugDirty = false, ugCheckedAt = null, lyricsStatus = "pending",
        lyricsJson = null, lyricsAt = null, lacuerdaCheckedAt = null, createdAt = "",
    )

    private fun strings(e: JsonElement): List<String> = e.jsonArray.map { it.jsonPrimitive.content }

    private fun batches(misses: Misses) {
        for (r in Corpus.records(SITES)) {
            val inputs = (r.args.firstOrNull() as? JsonArray) ?: continue
            val answer: (JsonElement) -> JsonElement = when (r.fn) {
                "caracole.gametabs.title_key" -> { x -> JsonPrimitive(GameTabsPages.titleKey(x.jsonPrimitive.content)) }
                "caracole.gametabs_fetch.game_forms" -> { x -> names(GameTabsFetch.gameForms(x.jsonPrimitive.content)) }
                "caracole.gametabs_fetch.song_forms" -> { x ->
                    val (artists, artist) = x.jsonArray
                    names(GameTabsFetch.songForms(song(strings(artists), artist.jsonPrimitive.content, "T"))
                              .sortedWith(Py.CODE_POINT_ORDER))
                }
                "caracole.gametabs_fetch.fits" -> { x ->
                    val (s, t) = x.jsonArray
                    val (artists, artist, title) = s.jsonArray
                    val o = t.jsonObject
                    val tab = GameTab(null, o.getValue("title").jsonPrimitive.content, o.getValue("game").jsonPrimitive.content,
                                      o.getValue("game_slug").jsonPrimitive.content, "", "x\n",
                                      composers = strings(o.getValue("composers")))
                    JsonPrimitive(GameTabsFetch.fits(song(strings(artists), artist.jsonPrimitive.content,
                                                          title.jsonPrimitive.content), tab))
                }
                else -> continue
            }
            val want = r.out!!.jsonArray
            inputs.forEachIndexed { i, x ->
                val got = answer(x)
                misses.check(got == want[i]) { "${r.fn}($x) = $got, Python's ${want[i]}" }
            }
        }
    }

    // --- a lookup's pass -------------------------------------------------------------------------------------------

    /** The pass's stats as the record writes them (its fields by Python's names; each failure its song's key, its
     * error's type and words). */
    fun stats(s: GameTabsStats): Map<String, Any?> = linkedMapOf(
        "tried" to s.tried, "errors" to s.errors, "budget_exhausted" to s.budgetExhausted,
        "failures" to s.failures.map { (song, e) -> listOf(song.key, e::class.simpleName, e.message) },
        "sitemaps" to s.sitemaps, "kept" to s.kept, "missing" to s.missing,
    )

    /** The lookup's scenario records. */
    fun lookupRecords(): List<JsonObject> = Corpus.lines(LOOKUP).filter { it["header"] != JsonPrimitive(true) }

    private fun lookups(misses: Misses) {
        for (record in lookupRecords()) {
            val case = record["case"]?.jsonPrimitive?.content ?: ""
            val agent = record.getValue("agent").jsonPrimitive.content
            Scenarios.replay(record, misses) { world ->
                val only = record.getValue("kw").jsonObject.getValue("only").jsonArray.map { it.jsonPrimitive.long }.toSet()
                try {
                    stats(GameTabsFetch.gametabsTabs(world.db, world.clients.getValue(GameTabsPages.PROVIDER),
                                                     LibraryStore(world.library), world.now, Overrides.read(world.db), only))
                } finally {
                    for (r in world.transport.requests) {
                        val sent = r.headers.filter { Py.asciiLower(it.first) == "user-agent" }.map { it.second }
                        misses.check(sent == listOf(agent)) { "$case: ${r.url} sent user agent $sent, not $agent" }
                    }
                }
            }
        }
    }
}
