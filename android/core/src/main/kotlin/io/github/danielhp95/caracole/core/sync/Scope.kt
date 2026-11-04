package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * peer_sync.py's parts of a sync on the phone (the sync redesign's §3.2, vectors/sync/scope.jsonl): a sync, or a
 * file, is of some of three parts ([PARTS]), the library (songs, tombstones and the entries about an artist or a
 * tab), the songbooks, and the site indexes, which no unit is of ([partOf]).
 *
 * A difference is in a sync's scope ([inScope]) when its unit is of a part asked for, or is a song a songbook lists
 * ([listedSongs], by any cut of an entry's "Artist - Title", Songbooks.entryKeys) while the songbooks are, which
 * brings it along to the side that lacks it but never removes it: a part left out is never read as a removal. A unit
 * a file lacks of a part the file doesn't hold is never read as removed there (`holds`). [changeOf] says what each
 * side did to a unit since the base, and [namesOf] reads a song's names from its label, for the pages.
 */
object Scope {
    const val LIBRARY = "library"
    const val SONGBOOKS = "songbooks"
    const val INDEXES = "indexes"

    /** What a sync, or a file, may be of, in order; no unit is of the indexes. */
    val PARTS: List<String> = listOf(LIBRARY, SONGBOOKS, INDEXES)

    private val PART_OF = mapOf("song" to LIBRARY, "removed" to LIBRARY, "alias" to LIBRARY,
                                "artist_url" to LIBRARY, "block" to LIBRARY, "songbook" to SONGBOOKS)

    /** The part a unit is of, by its kind: [LIBRARY] or [SONGBOOKS]; null for a kind caracole doesn't know. */
    fun partOf(unitId: String): String? = if ('/' in unitId) PART_OF[unitId.substringBefore('/')] else null

    /**
     * The songs songbooks list: for each song unit of [units] an entry of a songbook of [books] (`{songbook unit:
     * its value, {"name", "songs": [[text, parts], …]}}`, of either side) names by any cut of its "Artist - Title"
     * (Songbooks.entryKeys), the songbook units listing it, in code-point order, each once; by song unit, in
     * code-point order. A songbook or an entry that isn't of that shape lists nothing.
     */
    fun listedSongs(books: Map<String, JsonElement?>, units: Collection<String>): Map<String, List<String>> {
        val held = units.toHashSet()
        val listed = HashMap<String, MutableSet<String>>()
        for ((book, value) in books) {
            val songs = (value as? JsonObject)?.get("songs") as? JsonArray ?: continue
            for (entry in songs) {
                val text = (entry as? JsonArray)?.takeIf { it.size == 2 }?.get(0)
                    ?.let { it as? JsonPrimitive }?.takeIf { it.isString }?.content ?: continue
                for (key in Songbooks.entryKeys(text)) {
                    val song = "song/$key"
                    if (song in held) listed.getOrPut(song) { HashSet() }.add(book)
                }
            }
        }
        return listed.keys.sortedWith(Canonical.KEY_ORDER).associateWithTo(LinkedHashMap()) { song ->
            listed.getValue(song).sortedWith(Canonical.KEY_ORDER)
        }
    }

    /**
     * The differences of [found] (in its order) a sync of [parts] is about: a unit of a part asked for, or a song a
     * songbook lists ([listed], [listedSongs]'s) while the songbooks are, which comes along to the side that lacks
     * it, never removed from either (a removal, given, taken or asked, is the library's: left out). With [holds],
     * the parts a file holds, a unit of a part it doesn't hold that the file lacks is left out: a file of the
     * songbooks alone removes no song.
     */
    fun inScope(found: List<Difference>, parts: Collection<String>, listed: Map<String, List<String>> = emptyMap(),
                holds: Collection<String>? = null): List<Difference> {
        val asked: Set<String?> = parts.toSet()
        val held: Set<String?>? = holds?.toSet()
        return found.filter { d ->
            val part = partOf(d.id)
            val comes = part in asked ||
                (d.id.startsWith("song/") && SONGBOOKS in asked && d.id in listed && !removes(d))
            comes && !(held != null && part !in held && d.theirs == null)
        }
    }

    /** Whether [d] may remove its unit on a side: one side lacks it and the proposal isn't to bring it there. */
    private fun removes(d: Difference): Boolean =
        (d.mine == null && d.proposal != Compare.THEIRS) || (d.theirs == null && d.proposal != Compare.MINE)

    /** What each side did to [d]'s unit since the base (or since the answer [kept] remembers for it), this side's
     * then the other's: `"new"`, `"changed"`, `"gone"`, or null for a side that didn't change it. With no base, a
     * unit on one side alone is new there, and one on both changed on both. */
    fun changeOf(d: Difference, base: Map<String, String?>?, kept: Map<String, KeptPair>? = null): Pair<String?, String?> {
        val here = d.mine?.digest
        val there = d.theirs?.digest
        val pair = kept?.get(d.id)
        if (pair != null) return change(here, pair.here) to change(there, pair.there)
        if (base != null) {
            val was = base[d.id]
            return change(here, was) to change(there, was)
        }
        if (here != null && there != null) return CHANGED to CHANGED
        return (if (here != null) NEW else null) to (if (there != null) NEW else null)
    }

    private fun change(now: String?, was: String?): String? = when {
        now == was -> null
        was == null -> NEW
        now == null -> GONE
        else -> CHANGED
    }

    const val NEW = "new"
    const val CHANGED = "changed"
    const val GONE = "gone"

    /** A song unit's artist and title, read from its label ("Artist - Title"): the cut at a " - " whose
     * Normalize.identityKey is the unit's key (an artist's name may hold one: "Earth - Wind - Fire"), else the first;
     * null for a label with no cut and for a unit of another kind. */
    fun namesOf(unitId: String, label: String): Pair<String, String>? {
        val kind = unitId.substringBefore('/')
        val key = if ('/' in unitId) unitId.substringAfter('/') else ""
        val parts = label.split(" - ")
        if (kind != "song" || parts.size < 2) return null
        val cuts = (1 until parts.size).map { i ->
            parts.subList(0, i).joinToString(" - ") to parts.subList(i, parts.size).joinToString(" - ")
        }
        return cuts.firstOrNull { (artist, title) -> Normalize.identityKey(artist, title) == key } ?: cuts.first()
    }
}
