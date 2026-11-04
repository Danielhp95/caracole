package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Robots
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.VersionRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.ug.internal.rank.PyValues
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigInteger

/**
 * sheet_versions.SheetVersion: one chords version of a song, as the switcher and the lists show it. [number] is UG's
 * version number, [note] the first [SheetVersions.NOTE_LENGTH] characters of the tabber's `version_description`,
 * whitespace folded; [coverage] and [complete] are null for a version never scored; [rank] is 1-based; [page] is the
 * version's viewer page in the song's folder (`sheet.html` for the one, `version-<tab>.html` for one kept beside it,
 * null for one not kept).
 */
data class SheetVersion(val versionId: Long, val tabId: String, val number: Int?, val rating: Double?, val votes: Int?,
                        val label: String?, val note: String?, val coverage: Double?, val complete: Boolean?,
                        val rank: Int, val kept: Boolean, val chosen: Boolean, val gone: Boolean, val page: String?,
                        val url: String)

/**
 * sheet_versions.py: a song's UG chords versions in rank order (the scored ones, complete first, then by the rating
 * weighed by votes; then those never scored; then those UG no longer has), which are kept and which is the one, read
 * from the tables alone as Python reads them (vectors/sites/ug_sheet_versions.jsonl, tests/test_conformance_rank.py).
 *
 * A song with no chords on UG takes its sheet from its Ukulele Chords versions: its list is the group the kept sheet
 * comes from ([groupOf]). A version an earlier match found (Versions.STALE) is another song's and isn't listed.
 * [inLibrary] lists a song's with the one, the kept versions and those whose text is a kept one's ([samePages]), as
 * the files table and kv say; [inLibraryOf] lists many songs' in a few queries, the library page's. [asData] is the
 * JSON the viewer pages and the library page read.
 */
object SheetVersions {
    const val PREFIX = "version-"
    const val PROVIDER = "ug"

    /** UG's kinds for the sheet slot: ukulele chords for a song with no chords. */
    val KINDS: List<String> = listOf("chords", "ukulele")
    const val SHEET_PAGE = "sheet.html"
    const val NOTE_LENGTH = 200
    const val SAME_KV = "sheet_versions:same:"
    const val YOURS_KV = "sheet_versions:yours:"
    const val UNKEEPABLE_KV = "sheet_versions:unkeepable:"

    /** songs.HUMAN_SHEET. */
    private const val HUMAN_SHEET = "sheet.txt"
    private val NAME = PyRegex.compile("""version-([0-9]+)\.(?:txt|json|html)""")

    /** sheet_versions._ROWS: the UG versions of the sheet's kinds of the songs a JSON list names, under their match,
     * in each song's order of ids, each with its tabber's note as SQLite reads it out of the version's JSON. */
    private val ROWS =
        "SELECT id, provider, tab_id, song_id, slot, kind, rating, votes, version, label, coverage, url, fetched_at, " +
            "pick_rank, gone, CASE WHEN json_valid(raw) THEN CASE json_type(raw, '$.version_description') WHEN 'text' " +
            "THEN json_extract(raw, '$.version_description') END END FROM versions " +
            "WHERE provider = ? AND kind IN (${KINDS.joinToString(", ") { "?" }}) AND gone != ? " +
            "AND song_id IN (SELECT value FROM json_each(?)) ORDER BY song_id, id"

    /** A kept version's text, its JSON and its viewer page: `version-<tab>.txt`, `.json`, `.html`. */
    fun versionNames(tabId: String): Triple<String, String, String> =
        "$PREFIX$tabId".let { Triple("$it.txt", "$it.json", "$it.html") }

    /** sheet_versions.tab_of: the tab id of a version file's name, else null. */
    fun tabOf(name: String): String? = PyRe.fullmatch(NAME, name)?.groupValues?.get(1)

    fun sameKey(songId: Long): String = "$SAME_KV$songId"
    fun yoursKey(songId: Long): String = "$YOURS_KV$songId"
    fun unkeepableKey(songId: Long): String = "$UNKEEPABLE_KV$songId"

    /**
     * sheet_versions.song_sheet_versions: the song's UG chords versions in rank order, gone ones last. [chosenTab] is
     * the tab kept as `sheet.txt` (null when the sheet is another site's, auto-chords' or none), [keptTabs] those kept
     * beside it, [sameAs] the versions whose text is a kept one's, by tab, with that one's page.
     */
    fun songSheetVersions(db: Db, songId: Long, policy: RankPolicy, chosenTab: String?, keptTabs: Collection<String>,
                          sameAs: Map<String, String>? = null): List<SheetVersion> {
        val ids = jsonIds(listOf(songId))
        return listed(rowsOf(db, ids)[songId].orEmpty(), policy, variants(db, ids)[songId], chosenTab, keptTabs, sameAs)
    }

    /** sheet_versions.group_of: the kind a song's list shows: the chosen one's, else chords while the song has any
     * live (or no row at all), else ukulele. */
    fun groupOf(rows: List<VersionRow>, chosenTab: String?): String {
        rows.firstOrNull { chosenTab != null && it.tabId == chosenTab }?.let { return it.kind }
        return if (rows.isEmpty() || rows.any { it.kind == "chords" && !it.gone }) "chords" else "ukulele"
    }

    /** sheet_versions.as_data: the JSON the viewer pages and the library page read, [total] UG's count of chords
     * versions; its members in Python's order, a rating as Python's repr. */
    fun asData(versions: List<SheetVersion>, total: Int): JsonObject = JsonObject(linkedMapOf(
        "total" to JsonPrimitive(total),
        "list" to JsonArray(versions.map { v ->
            JsonObject(linkedMapOf(
                "tab" to JsonPrimitive(v.tabId), "number" to v.number.json(), "rating" to v.rating.json(),
                "votes" to v.votes.json(), "label" to v.label.json(), "note" to v.note.json(),
                "rank" to JsonPrimitive(v.rank), "kept" to JsonPrimitive(v.kept), "chosen" to JsonPrimitive(v.chosen),
                "gone" to JsonPrimitive(v.gone), "page" to v.page.json(), "url" to JsonPrimitive(v.url),
            ))
        }),
    ))

    /** sheet_versions.library_state: the UG tab kept as `sheet.txt` (null when the sheet is another site's or none),
     * and the tabs kept beside it by their `kept_rank`: what the files table says caracole wrote. */
    fun libraryState(db: Db, songId: Long): Pair<String?, List<String>> =
        states(db, jsonIds(listOf(songId)))[songId] ?: (null to emptyList())

    /** sheet_versions.sheet_kind: `ukulele` for a kept UG sheet of the Ukulele Chords type, else `chords`. */
    fun sheetKind(db: Db, songId: Long): String {
        for (f in Kept.keptFiles(db, songId)) {
            if (f.name != HUMAN_SHEET) continue
            val row = Versions.get(db, f.versionId) ?: throw NoSuchElementException("no version with id ${f.versionId}")
            return if (row.provider == PROVIDER && row.kind == "ukulele") "ukulele" else "chords"
        }
        return "chords"
    }

    /** sheet_versions.same_pages: the song's versions whose text is a kept one's, by tab, with the page that shows
     * it; a page no longer kept is left out. */
    fun samePages(db: Db, songId: Long): Map<String, String> {
        val (chosen, kept) = libraryState(db, songId)
        return same(PyValues.kvJson(db, sameKey(songId)) ?: JsonObject(emptyMap()), chosen, kept)
    }

    /** sheet_versions.kept_by_you: the tabs you asked to keep beside the sheet (`caracole versions --keep`), oldest
     * first. */
    fun keptByYou(db: Db, songId: Long): List<String> = tabs(db, yoursKey(songId))

    fun noteKeptByYou(db: Db, songId: Long, tabId: String) = note(db, yoursKey(songId), tabId)
    fun noteKeptByYou(db: Db, songId: Long, tabId: Long) = noteKeptByYou(db, songId, tabId.toString())

    /** sheet_versions.unkeepable: the tabs a keep read and found it can't keep (no sheet text, or another kept file's
     * very text). */
    fun unkeepable(db: Db, songId: Long): List<String> = tabs(db, unkeepableKey(songId))

    fun noteUnkeepable(db: Db, songId: Long, tabId: String) = note(db, unkeepableKey(songId), tabId)
    fun noteUnkeepable(db: Db, songId: Long, tabId: Long) = noteUnkeepable(db, songId, tabId.toString())

    /**
     * sheet_versions.may_keep: the song's versions ([inLibrary]'s) a keep may still keep beside its sheet, in their
     * order: neither kept nor the one nor gone, not under `[block]` ([block]), not at an address robots.txt closes,
     * none a keep found it can't keep; and none at all when the list shows another group than a keep keeps.
     */
    fun mayKeep(db: Db, songId: Long, versions: List<SheetVersion>, block: Collection<Long>): List<SheetVersion> {
        val live = versions.filter { !it.gone }
        if (live.isNotEmpty()) {
            val first = Versions.get(db, live[0].versionId)
                ?: throw NoSuchElementException("no version with id ${live[0].versionId}")
            if ((first.kind == "ukulele") != (sheetKind(db, songId) == "ukulele")) return emptyList()
        }
        val cannot = unkeepable(db, songId).toSet()
        val blocked = block.map(BigInteger::valueOf).toSet()
        return versions.filter { v ->
            val tab = PyInt.parse(v.tabId) ?: throw IllegalArgumentException(
                "invalid literal for int() with base 10: ${PyStr.repr(v.tabId)}")
            !(v.kept || v.chosen || v.gone) && tab !in blocked && v.tabId !in cannot && Robots.disallows(v.url) == null
        }
    }

    /** sheet_versions.sheet_pins: of the song's `[pin]` tabs, those that choose its sheet: chords versions, by the
     * song's versions and the offline index, and a pin of a kind neither knows; any other (a text tab's) stays. */
    fun sheetPins(db: Db, songId: Long, pins: List<Long>): List<Long> = pins.filter { tab ->
        val kind = db.one("SELECT kind FROM versions WHERE song_id = ? AND provider = ? AND tab_id = ?",
                          songId, PROVIDER, tab.toString()) { it.text(0) }
            ?: db.one("SELECT type FROM ug_index WHERE tab_id = ?", tab) { it.text(0) }
        kind == null || kind in KINDS
    }

    /** sheet_versions.in_library: [songSheetVersions] with the one, the kept versions and those a kept one's text,
     * as the library holds them now. */
    fun inLibrary(db: Db, songId: Long, policy: RankPolicy): List<SheetVersion> =
        listings(db, listOf(songId), policy)[songId].orEmpty()

    /** sheet_versions.in_library_of: [inLibrary] of each song that has UG versions listed, by song id in ascending
     * order (a song with none left out), in four queries for them all. */
    fun inLibraryOf(db: Db, songIds: Collection<Long>, policy: RankPolicy): Map<Long, List<SheetVersion>> =
        listings(db, songIds, policy).filterValues { it.isNotEmpty() }

    // --- reading --------------------------------------------------------------------------------------------------

    /** json.dumps of a list of ids, as the queries' json_each reads it. */
    private fun jsonIds(ids: Collection<Long>): String = ids.joinToString(", ", "[", "]")

    /** sheet_versions._rows_of: by song id, each version with its note; its raw left empty. */
    private fun rowsOf(db: Db, ids: String): Map<Long, List<Pair<VersionRow, String?>>> {
        val found = LinkedHashMap<Long, MutableList<Pair<VersionRow, String?>>>()
        db.query(ROWS, PROVIDER, *KINDS.toTypedArray(), Versions.STALE, ids) { r ->
            VersionRow(
                id = r.long(0)!!, provider = r.text(1)!!, tabId = r.text(2)!!, songId = r.long(3)!!, slot = r.text(4)!!,
                kind = r.text(5)!!, rating = r.double(6)!!, votes = r.long(7)!!.toInt(), version = r.long(8)!!.toInt(),
                label = r.text(9), coverage = r.double(10), url = r.text(11)!!, raw = JsonObject(emptyMap()),
                fetchedAt = r.text(12)!!, pickRank = r.long(13)?.toInt(), gone = r.long(14) == Versions.GONE.toLong(),
            ) to note(r.text(15))
        }.forEach { found.getOrPut(it.first.songId) { ArrayList() }.add(it) }
        return found
    }

    /** sheet_versions._note: the tabber's note, whitespace folded, its first [NOTE_LENGTH] code points; null for
     * none. */
    private fun note(text: String?): String? {
        if (text == null) return null
        return Py.slice(Py.split(text).joinToString(" "), null, NOTE_LENGTH).ifEmpty { null }
    }

    private fun variants(db: Db, ids: String): Map<Long, String?> =
        db.query("SELECT id, variant FROM songs WHERE id IN (SELECT value FROM json_each(?))", ids) {
            it.long(0)!! to it.text(1)
        }.toMap()

    private fun candidate(row: VersionRow): Candidate =
        Candidate(provider = row.provider, tabId = row.tabId, kind = row.kind, rating = row.rating, votes = row.votes,
                  version = row.version, label = row.label, coverage = row.coverage, versionId = row.id)

    /** sheet_versions._ranked: rank_sheets' order, the versions never scored after those scored (a stable sort of
     * the rating's order). */
    private fun ranked(rows: List<VersionRow>, policy: RankPolicy, variant: String?): List<Candidate> =
        Rank.rankByRating(rows.map(::candidate), policy, variant).sortedWith(
            compareBy<Candidate> { it.coverage == null }.thenBy { !Rank.isComplete(it, policy) },
        )

    /** sheet_versions._listed: [songSheetVersions] of a song's rows and its variant. */
    private fun listed(found: List<Pair<VersionRow, String?>>, policy: RankPolicy, variant: String?, chosenTab: String?,
                       keptTabs: Collection<String>, sameAs: Map<String, String>?): List<SheetVersion> {
        val notes = found.associate { (row, note) -> row.id to note }
        val all = found.map { it.first }
        val group = groupOf(all, chosenTab)
        val rows = all.filter { it.kind == group }
        val live = ranked(rows.filter { !it.gone }, policy, variant)
        val gone = Rank.rankByRating(rows.filter { it.gone }.map(::candidate), policy, variant)
        val byId = rows.associateBy { it.id }
        val kept = keptTabs.toSet()
        val same = sameAs.orEmpty()
        return (live + gone).mapIndexed { i, c ->
            val row = byId.getValue(c.versionId!!)
            val chosen = chosenTab != null && row.tabId == chosenTab
            val page = when {
                chosen -> SHEET_PAGE
                row.tabId in kept -> versionNames(row.tabId).third
                else -> same[row.tabId]
            }
            SheetVersion(
                versionId = row.id, tabId = row.tabId, number = row.version, rating = row.rating, votes = row.votes,
                label = row.label, note = notes[row.id], coverage = row.coverage,
                complete = if (row.coverage == null) null else Rank.isComplete(c, policy), rank = i + 1,
                kept = chosen || row.tabId in kept || row.tabId in same, chosen = chosen, gone = row.gone, page = page,
                url = row.url,
            )
        }
    }

    /** sheet_versions._states: the library state of each song that has a `sheet.txt` or a `version-*` file, in one
     * query; the kept tabs by `(kept_rank, len(tab), tab)`. */
    private fun states(db: Db, ids: String): Map<Long, Pair<String?, List<String>>> {
        val chosen = LinkedHashMap<Long, String?>()
        val kept = HashMap<Long, MutableList<Pair<Long, String>>>()
        db.query("SELECT f.song_id, f.name, f.kept_rank, v.provider, v.kind, v.tab_id FROM files f " +
                     "JOIN versions v ON v.id = f.version_id WHERE f.song_id IN (SELECT value FROM json_each(?)) " +
                     "AND (f.name = ? OR substr(f.name, 1, ?) = ?)", ids, HUMAN_SHEET, Py.len(PREFIX), PREFIX) { r ->
            val songId = r.long(0)!!
            val name = r.text(1)!!
            if (songId !in chosen) chosen[songId] = null
            val tabs = kept.getOrPut(songId) { ArrayList() }
            if (name == HUMAN_SHEET) {
                if (r.text(3) == PROVIDER && r.text(4) in KINDS) chosen[songId] = r.text(5)
            } else {
                val tab = tabOf(name)
                if (tab != null && name == versionNames(tab).first) tabs += r.long(2)!! to tab
            }
        }
        val order = compareBy<Pair<Long, String>> { it.first }.thenBy { Py.len(it.second) }
            .then { a, b -> Py.CODE_POINT_ORDER.compare(a.second, b.second) }
        return chosen.mapValues { (songId, tab) -> tab to kept.getValue(songId).sortedWith(order).map { it.second } }
    }

    /** sheet_versions._same: a song's `same_pages` record kept to the pages the one and the kept tabs have. */
    private fun same(record: JsonElement, chosen: String?, kept: Collection<String>): Map<String, String> {
        if (record !is JsonObject) return emptyMap()
        val pages = kept.map { versionNames(it).third }.toMutableSet()
        if (chosen != null) pages += SHEET_PAGE
        val out = LinkedHashMap<String, String>()
        for ((tab, page) in record) {
            if (page is JsonPrimitive && page.isString && page.content in pages) out[tab] = page.content
        }
        return out
    }

    /** sheet_versions._same_records: each song's `same_pages` record, in one query. */
    private fun sameRecords(db: Db, ids: String): Map<Long, JsonElement> =
        db.query("SELECT key, value FROM kv WHERE key IN (SELECT ? || value FROM json_each(?))", SAME_KV, ids) {
            it.text(0)!!.substring(SAME_KV.length).toLong() to PyJson.loads(it.text(1)!!)
        }.toMap()

    /** sheet_versions._listings: [inLibrary]'s list of each song with a version recorded, by song id: its rows, its
     * library state, its same-pages record and its variant, each read for every song at once. */
    private fun listings(db: Db, songIds: Collection<Long>, policy: RankPolicy): Map<Long, List<SheetVersion>> {
        val rows = rowsOf(db, jsonIds(songIds.toSortedSet()))
        if (rows.isEmpty()) return emptyMap()
        val ids = jsonIds(rows.keys.sorted())
        val states = states(db, ids)
        val records = sameRecords(db, ids)
        val variants = variants(db, ids)
        val out = LinkedHashMap<Long, List<SheetVersion>>()
        for ((songId, found) in rows) {
            val (chosen, kept) = states[songId] ?: (null to emptyList())
            out[songId] = listed(found, policy, variants[songId], chosen, kept,
                                 same(records[songId] ?: JsonObject(emptyMap()), chosen, kept))
        }
        return out
    }

    // --- the kv lists ---------------------------------------------------------------------------------------------

    /** A list of tabs a kv record holds, each as Python's `str()` of it; none for a record of another shape. */
    private fun tabs(db: Db, key: String): List<String> =
        (PyValues.kvJson(db, key) as? JsonArray)?.map(PyValues::str).orEmpty()

    private fun note(db: Db, key: String, tabId: String) {
        val tabs = tabs(db, key)
        if (tabId !in tabs) db.kvSetJson(key, JsonArray((tabs + tabId).map(::JsonPrimitive)))
    }

    private fun Int?.json(): JsonElement = this?.let(::JsonPrimitive) ?: JsonNull
    private fun Double?.json(): JsonElement = this?.let(PyJson::float) ?: JsonNull
    private fun String?.json(): JsonElement = this?.let(::JsonPrimitive) ?: JsonNull
}
