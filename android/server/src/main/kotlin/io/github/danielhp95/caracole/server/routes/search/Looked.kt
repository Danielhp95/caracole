package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.lacuerda.LaCuerda
import io.github.danielhp95.caracole.core.sites.SiteKeys
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull

/** A site a search left out (`skipped`) or searched in part (`partial`), and why, worded to follow its name. */
internal data class Left(val source: String, val name: String, val why: String) {
    fun json(): JsonObject = obj("source" to source, "name" to name, "why" to why)
}

/**
 * Where a search looked, as search_routes.py says it: the sites it left out and why (`_skipped`), those it searched
 * in part, and a mark a site (`_looked`), read from the indexes' tables and their records alone. A site is on when
 * [enabled] names it (caracole.toml's `enabled`: gtptabs.com, MuseScore, harptabs.com and gametabs.net can be turned
 * off; LaCuerda and Ultimate Guitar can't). MuseScore blocking caracole is its kv `provider:musescore`'s strikes,
 * which the phone, sending no request, never records: there, nothing cools down.
 */
internal class Looked(private val db: Db, private val enabled: Set<String>) {
    /** search_routes._skipped: the sites left out, and those searched only in part. */
    fun skipped(): Pair<List<Left>, List<Left>> {
        val left = ArrayList<Left>()
        for ((source, name, table) in listOf(Triple("gtptabs", "gtptabs.com", "gtptabs_index"),
                                             Triple("musescore", "MuseScore", "musescore_index"))) {
            val why = when {
                source !in enabled -> "turned off in caracole.toml"
                holds(table) -> continue
                source == "musescore" && strikes(source) != 0L -> "MuseScore is blocking caracole, so its index is empty"
                else -> "its index is empty: the nightly run reads its sitemaps"
            }
            left.add(Left(source, name, why))
        }
        val partial = ArrayList<Left>()
        LaCuerda.lacuerdaLeftOut(db)?.let { (kind, why) ->
            (if (kind == "empty") left else partial).add(Left("lacuerda", "LaCuerda", "its $why"))
        }
        harptabsLeftOut()?.let { (kind, why) ->
            (if (kind == "partial") partial else left).add(Left("harptabs", "harptabs.com", why))
        }
        return left to partial
    }

    /** search_routes._harptabs_left_out: ("off", …), ("empty", …) before its sitemap is read, ("partial", …) while
     * its artist pages aren't all read; null once every one is. */
    private fun harptabsLeftOut(): Pair<String, String>? {
        if ("harptabs" !in enabled) return "off" to "turned off in caracole.toml"
        if (!holds("harptabs_index")) return "empty" to "its index is empty: the nightly run reads its sitemap"
        val (read, artists) = harptabsState()
        if (read >= artists) return null
        return "partial" to ("its artist pages are still being read: ${grouped(read)} of ${grouped(artists)} artists " +
            "so far; caracole harptabs --index reads the rest")
    }

    /** search_routes._looked: a mark a site, Ultimate Guitar's index, gtptabs.com's, LaCuerda's, MuseScore's,
     * harptabs.com's and gametabs.net's: its `state`, its `label` and its `detail`. */
    fun looked(skipped: List<Left>, partial: List<Left>): List<JsonObject> {
        val said = LinkedHashMap<String, Left>()
        for (s in skipped + partial) said[s.source] = s
        val inPart = partial.toSet()
        val looked = ArrayList<JsonObject>()
        val ugEmpty = !holds("ug_index")
        looked.add(mark("ug", "Ultimate Guitar", if (ugEmpty) "empty" else "done", if (ugEmpty) "UG: empty" else "UG ✓",
                        if (ugEmpty) UG_EMPTY else "Ultimate Guitar: caracole's copy of its index, searched whole."))
        for ((source, name) in listOf("gtptabs" to "gtptabs.com", "lacuerda" to "LaCuerda", "musescore" to "MuseScore",
                                      "harptabs" to "harptabs.com")) {
            val s = said[source]
            val why = s?.why ?: ""
            if (source == "harptabs" && s != null && s in inPart) {
                val (read, artists) = harptabsState()
                looked.add(mark(source, name, "partial", "$name: ${grouped(read)} of ${grouped(artists)} artists",
                                "$name's ${why.removePrefix("its ")}."))
                continue
            }
            looked.add(when {
                s == null -> mark(source, name, "done", "$name ✓", "$name: caracole's copy of its index, searched whole.")
                why.startsWith("turned off") -> mark(source, name, "off", "$name: off", "$name is turned off in caracole.toml.")
                "blocking" in why -> mark(source, name, "blocked", "$name blocked", upperFirst(why) + ".")
                s in inPart -> {
                    val read = LaCuerda.letters(db)
                    val letters = LaCuerda.LETTERS
                    var run = 0
                    while (run < read.size && run < letters.size && read[run] == letters[run]) run++
                    val label = when {
                        run == read.size && run > 0 -> "$name: up to ${LaCuerda.lettersText(read.subList(run - 1, run))}"
                        read.isNotEmpty() -> "$name: ${LaCuerda.lettersText(read)} only"
                        else -> "$name: in part"
                    }
                    mark(source, name, "partial", label, "$name's ${why.removePrefix("its ")}.")
                }
                else -> mark(source, name, "empty", "$name: empty", "$name's ${why.removePrefix("its ")}.")
            })
        }
        looked.add(gametabs())
        return looked
    }

    /** search_routes._gametabs_looked: turned off, empty before its sitemaps are read, in part while its game pages
     * aren't all read, else whole. */
    private fun gametabs(): JsonObject {
        val name = "gametabs.net"
        if ("gametabs" !in enabled) {
            return mark("gametabs", name, "off", "$name: off", "$name is turned off in caracole.toml.")
        }
        if (!holds("gametabs_index")) {
            return mark("gametabs", name, "empty", "$name: empty",
                        "$name's index is empty: the nightly run reads its sitemaps.")
        }
        val state = SiteKeys.gametabsIndexState(db)
        val read = state.number("read")
        val pages = state.number("pages")
        if (read < pages) {
            return mark("gametabs", name, "partial", "$name: ${grouped(read)} of ${grouped(pages)} games",
                        "$name's game pages are still being read: ${grouped(read)} of ${grouped(pages)} so far; " +
                            "caracole gametabs --index reads the rest.")
        }
        return mark("gametabs", name, "done", "$name ✓", "$name: caracole's copy of its index, searched whole.")
    }

    private fun mark(source: String, name: String, state: String, label: String, detail: String): JsonObject =
        obj("source" to source, "name" to name, "state" to state, "label" to label, "detail" to detail)

    /** Whether [table] holds a row. */
    private fun holds(table: String): Boolean = db.one("SELECT 1 FROM $table LIMIT 1") { true } ?: false

    /** health.get_state(conn, source).strikes: the blocks in a row its kv records (none on the phone). */
    private fun strikes(source: String): Long =
        ((db.kvGetJson("provider:$source") as? JsonObject)?.get("strikes") as? JsonPrimitive)?.longOrNull ?: 0L

    /** harptabs_index.index_state's artist pages read, and the artists its sitemap lists. */
    private fun harptabsState(): Pair<Long, Long> =
        SiteKeys.harptabsIndexState(db).let { it.number("read") to it.number("artists") }

    private fun JsonObject.number(name: String): Long =
        (this[name] as? JsonPrimitive)?.let { it.longOrNull ?: it.intOrNull?.toLong() } ?: 0L

    companion object {
        const val UG_EMPTY = "The offline Ultimate Guitar index is empty: run caracole index build once (about 10 minutes)."

        /** `f"{n:,}"`: thousands by commas. */
        fun grouped(n: Long): String {
            val digits = kotlin.math.abs(n).toString()
            val out = StringBuilder()
            for ((i, c) in digits.withIndex()) {
                if (i > 0 && (digits.length - i) % 3 == 0) out.append(',')
                out.append(c)
            }
            return (if (n < 0) "-" else "") + out
        }

        private fun upperFirst(s: String): String = if (s.isEmpty()) s else s.substring(0, 1).uppercase() + s.substring(1)
    }
}
