package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.internal.overrides.Addresses
import io.github.danielhp95.caracole.core.library.internal.overrides.PyValues
import io.github.danielhp95.caracole.core.library.internal.overrides.Readers
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyStr
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigInteger

/**
 * overrides.Overrides, field for field: the phone's overrides.toml (`phone_overrides`) read as Python reads it.
 * [pinUrls] holds each pin's address, in [pin]'s order; [reject] each song's rejected (artist key, song key) pairs;
 * [artistUrlNames] the name each [artistUrl] entry is written under; [youtube] each song's video id, or null for
 * "none"; [version] each song's own version as the entry writes it (without a "#"); [tables] the tables that hold an
 * entry (on the phone a table is there while an entry is in it). Its key's order is its rows' (rowid).
 */
data class Overrides(
    val alias: Map<String, List<String>> = emptyMap(),
    val match: Map<String, Pair<String, String>> = emptyMap(),
    val artistUrl: Map<String, String> = emptyMap(),
    val pin: Map<String, List<Long>> = emptyMap(),
    val transpose: Map<String, Int> = emptyMap(),
    val ignore: Set<String> = emptySet(),
    val block: Set<Long> = emptySet(),
    val pinUrls: Map<String, List<String>> = emptyMap(),
    val reject: Map<String, Set<Pair<String, String>>> = emptyMap(),
    val artistUrlNames: Map<String, String> = emptyMap(),
    val youtube: Map<String, String?> = emptyMap(),
    val lacuerda: Map<String, LaCuerdaPick> = emptyMap(),
    val harptabs: Map<String, HarpTabsPick> = emptyMap(),
    val gametabs: Map<String, GameTabsPick> = emptyMap(),
    val azlyrics: Map<String, String> = emptyMap(),
    val version: Map<String, String> = emptyMap(),
    val harmonica: Map<String, Map<String, JsonElement>> = emptyMap(),
    val tables: Set<String> = emptySet(),
) {
    /** Overrides.has_table: whether the table is there, with an entry in it. */
    fun hasTable(name: String): Boolean = name in tables || when (name) {
        "alias" -> alias.isNotEmpty()
        "match" -> match.isNotEmpty()
        "artist_url" -> artistUrl.isNotEmpty()
        "pin" -> pin.isNotEmpty()
        "transpose" -> transpose.isNotEmpty()
        "ignore" -> ignore.isNotEmpty()
        "block" -> block.isNotEmpty()
        "reject" -> reject.isNotEmpty()
        "youtube" -> youtube.isNotEmpty()
        "lacuerda" -> lacuerda.isNotEmpty()
        "harptabs" -> harptabs.isNotEmpty()
        "gametabs" -> gametabs.isNotEmpty()
        "azlyrics" -> azlyrics.isNotEmpty()
        "version" -> version.isNotEmpty()
        "harmonica" -> harmonica.isNotEmpty()
        else -> false
    }

    /**
     * overrides.artist_url_entry: the `[artist_url]` entry for an artist known by [keys], as (its key, its address):
     * the one under one of the keys first, else one whose name, as it is written, shares a form with them
     * (`Normalize.nameForms`), hyphens aside; null for none.
     */
    fun artistUrlEntry(keys: List<String>): Pair<String, String>? {
        val known = keys.filter { it.isNotEmpty() }
        for (key in known) artistUrl[key]?.let { return key to it }
        val wanted = known.map(Normalize::compact).toSet()
        for ((key, url) in artistUrl) {
            if (Normalize.nameForms(artistUrlNames[key] ?: key).any { Normalize.compact(it) in wanted }) return key to url
        }
        return null
    }

    companion object {
        /** overrides._TABLES. */
        private val TABLES = setOf("alias", "match", "artist_url", "pin", "transpose", "ignore", "block", "reject",
                                   "youtube", "lacuerda", "harptabs", "gametabs", "azlyrics", "version", "harmonica")

        private class Entry(val key: String, val written: String, val value: JsonElement) {
            val where: String get() = PyStr.repr(written)
        }

        /**
         * overrides.load_overrides over the phone's rows: each table read in overrides._parse's order, each entry in
         * its row's order by the reader overrides.py reads it by, so the first that can't be read is
         * [OverridesError] with Python's words (no file is named: the phone has none). A row's key is the one its
         * table keeps it by (OverridesStore). [keyVersion] and [checkSpec] are viewer/version.py's `key_version` and
         * viewer/harptab.py's `check_spec` (M5's, each raising IllegalArgumentException with its words): a
         * `[version]` kept by its key and a `[harmonica]` reading are checked by them when given, as Python reads
         * them, and trusted otherwise (every writer of the phone checked them).
         */
        fun read(db: Db, keyVersion: ((String) -> Any?)? = null,
                 checkSpec: ((JsonElement) -> Unit)? = null): Overrides {
            val rows = db.query("SELECT tbl, key, written, value FROM phone_overrides ORDER BY rowid") {
                it.text(0)!! to Entry(it.text(1)!!, it.text(2)!!, Canonical.parse(it.text(3)!!))
            }
            val by = LinkedHashMap<String, MutableList<Entry>>()
            for ((table, entry) in rows) by.getOrPut(table) { ArrayList() }.add(entry)
            fun of(table: String): List<Entry> = by[table].orEmpty()
            val unknown = (by.keys - TABLES).sortedWith(Py.CODE_POINT_ORDER)
            if (unknown.isNotEmpty()) throw OverridesError("unknown table(s): ${unknown.joinToString(", ")}")

            val alias = LinkedHashMap<String, List<String>>()
            for (e in of("alias")) alias[e.key] = PyValues.strings(e.value, "[alias] ${e.where}").map(Normalize::ugSlugKey)
            val match = LinkedHashMap<String, Pair<String, String>>()
            for (e in of("match")) match[e.key] = Readers.ugRef(e.value, "[match] ${e.where}")
            val artistUrl = LinkedHashMap<String, String>()
            val artistUrlNames = LinkedHashMap<String, String>()
            for (e in of("artist_url")) {
                artistUrl[e.key] = Addresses.artistUrlValue(e.value) ?: throw OverridesError(
                    "[artist_url] ${e.where}: expected the artist's page (${Addresses.ARTIST_PAGE_SHAPE}) or one of " +
                        "their tab pages (${Addresses.TAB_PAGE_SHAPE}), as your browser shows it, got " +
                        PyValues.repr(e.value),
                )
                artistUrlNames[e.key] = e.written
            }
            val pin = LinkedHashMap<String, List<Long>>()
            val pinUrls = LinkedHashMap<String, List<String>>()
            for (e in of("pin")) {
                val pasted = PyValues.strings(e.value, "[pin] ${e.where}")
                try {
                    pin[e.key] = pasted.map(Addresses::tabIdFromUrl)
                    pinUrls[e.key] = pasted.map(Addresses::pinUrl)
                } catch (x: OverridesError) {
                    throw OverridesError("[pin] ${e.where}: ${x.message}")
                }
            }
            val transpose = LinkedHashMap<String, Int>()
            for (e in of("transpose")) {
                val n = PyValues.int(e.value)
                if (n == null || n < BigInteger.valueOf(-11) || n > BigInteger.valueOf(11)) {
                    throw OverridesError("[transpose] ${e.where}: expected semitones between -11 and 11")
                }
                transpose[e.key] = n.toInt()
            }
            val ignore = of("ignore").mapTo(LinkedHashSet()) { it.key }
            val block = of("block").mapNotNullTo(LinkedHashSet()) { it.key.toLongOrNull() }
            val reject = LinkedHashMap<String, Set<Pair<String, String>>>()
            for (e in of("reject")) {
                val where = "[reject] ${e.where}"
                reject[e.key] = reject[e.key].orEmpty() +
                    PyValues.strings(e.value, where).map { Readers.ugRef(JsonPrimitive(it), where) }
            }
            val youtube = LinkedHashMap<String, String?>()
            for (e in of("youtube")) youtube[e.key] = Readers.video(e.value, "[youtube] ${e.where}")
            val lacuerda = picks(of("lacuerda"), "lacuerda", "a LaCuerda song's page", Addresses::lacuerdaPickFromUrl)
            val harptabs = picks(of("harptabs"), "harptabs", "a harptabs.com tab's page", Addresses::harptabsPickFromUrl)
            val gametabs = picks(of("gametabs"), "gametabs", "a gametabs.net tab's page", Addresses::gametabsPickFromUrl)
            val azlyrics = picks(of("azlyrics"), "azlyrics", null, Addresses::azlyricsPageFromUrl)
            val version = LinkedHashMap<String, String>()
            for (e in of("version")) version[e.key] = Readers.version(e.value, "[version] ${e.where}", keyVersion)
            val harmonica = LinkedHashMap<String, Map<String, JsonElement>>()
            for (e in of("harmonica")) {
                val where = "[harmonica] ${e.where}"
                val tabs = e.value as? JsonObject ?: throw OverridesError(
                    "$where: expected a table of its harmonica tabs, each \"harmonica-1.txt\" = how it is read",
                )
                val read = LinkedHashMap(harmonica[e.key].orEmpty())
                for ((tab, spec) in tabs) read[tab] = Readers.harmonicaReading(spec, "$where ${PyStr.repr(tab)}", checkSpec)
                harmonica[e.key] = read
            }
            return Overrides(
                alias = alias, match = match, artistUrl = artistUrl, pin = pin, transpose = transpose, ignore = ignore,
                block = block, pinUrls = pinUrls, reject = reject, artistUrlNames = artistUrlNames, youtube = youtube,
                lacuerda = lacuerda, harptabs = harptabs, gametabs = gametabs, azlyrics = azlyrics, version = version,
                harmonica = harmonica, tables = by.keys.toSet(),
            )
        }

        /** overrides._read_picks: each address read by [pickFromUrl], its error said after the table and the entry;
         * [page] what a value that isn't text must be the address of (null: [pickFromUrl] says it). */
        private fun <T> picks(entries: List<Entry>, table: String, page: String?,
                              pickFromUrl: (JsonElement) -> T): Map<String, T> {
            val out = LinkedHashMap<String, T>()
            for (e in entries) {
                val where = "[$table] ${e.where}"
                if (page != null && PyValues.text(e.value) == null) {
                    throw OverridesError("$where: expected a string, the address of $page")
                }
                try {
                    out[e.key] = pickFromUrl(e.value)
                } catch (x: OverridesError) {
                    throw OverridesError("$where: ${x.message}")
                }
            }
            return out
        }
    }
}
