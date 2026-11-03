package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.library.OverridesStore
import io.github.danielhp95.caracole.core.library.SongbookStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.sync.internal.units.Cells
import io.github.danielhp95.caracole.core.sync.internal.units.Documents
import io.github.danielhp95.caracole.core.sync.internal.units.SongUnits
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File

/** One unit of a library's state, as peer_sync.library_state lists it. */
data class SyncUnit(val id: String, val label: String, val digest: String) {
    val kind: String get() = id.substringBefore('/')
}

/** A unit the two sides hold differently, and what the comparison proposes (mine, theirs or conflict). */
data class Difference(val id: String, val label: String, val mine: SyncUnit?, val theirs: SyncUnit?,
                      val proposal: String, val why: String)

/** A stored base: per unit, its digest (or null) and the stamp it was agreed at. */
typealias Base = Map<String, Pair<String?, String>>

/** A unit that can't be taken, or a document that isn't one of its kind (peer_sync.UnitError): why, in words. */
class UnitError(message: String) : Exception(message)

/**
 * peer_sync.py's units on the phone: what the library holds, cut into units each compared and taken whole, each with
 * the value its digest is of (Canonical.digest) and the label the owner reads, exactly as the computer gives them
 * for the same library:
 *
 * - `song/<key>`: a song's names, decisions, versions (by provider and tab, in SQLite's order), kept files' hashes
 *   and every overrides.toml entry about it (phone_overrides, [OverridesStore.songEntries]), "Artist - Title";
 * - `removed/<key>`: a tombstone's names, "Artist - Title (removed)";
 * - `songbook/<name key>`: a songbook's name and songs (phone_songbooks, [SongbookStore]), "the songbook Name";
 * - `alias/<artist key>`, `artist_url/<artist key>`, `block/<tab>`: overrides.toml's entries about an artist or a
 *   tab, "the alias of key", "the UG page of Name", "the blocked tab 4242".
 *
 * A unit's document (GET /api/peer/unit's "unit") is everything another side needs to take it, and
 * [valueOfDocument] reads the value back from it alone, so what a side receives is checked against the digest it
 * compared. Every function reads; none writes, and each reads in one transaction of its own (a savepoint), so a
 * value or a whole state is of one state of the library.
 *
 * Python's library_state lists the songs only once their keys are current (list_songs runs ensure_current_keys);
 * these read the songs as stored. After a KEY_VERSION change, a caller runs LibraryStore.ensureCurrentKeys inside
 * Database.write first (a sync's compare and take do), else every song re-keyed on the other side compares as on one
 * side alone.
 */
object Units {
    const val FORMAT = 2

    /** Every unit of this library, by id: its songs (newest added first), its tombstones, its songbooks in their
     * order, its aliases, artists' pages and blocked tabs. */
    fun libraryState(db: Db): Map<String, SyncUnit> = db.savepoint(SNAPSHOT) {
        val units = LinkedHashMap<String, SyncUnit>()
        fun add(id: String, label: String, value: JsonElement) {
            units[id] = SyncUnit(id, label, Canonical.digest(value))
        }
        for (song in Songs.list(db)) add("song/${song.key}", "${song.artist} - ${song.title}", SongUnits.value(db, song))
        for (stone in Cells.rows(db, "SELECT key, artist, title FROM removed")) {
            val (key, artist, title) = listOf("key", "artist", "title").map { Cells.text(stone[it])!! }
            add("removed/$key", "$artist - $title (removed)", Documents.removedValue(artist, title))
        }
        for (book in SongbookStore.all(db)) {
            add("songbook/${SongbookStore.nameKey(book.name)}", "the songbook ${book.name}",
                Documents.songbookValue(book.name, book.songs))
        }
        for ((artist, slugs) in OverridesStore.aliases(db)) add("alias/$artist", "the alias of $artist", slugs)
        for ((artist, value) in OverridesStore.artistUrls(db)) {
            add("artist_url/$artist", "the UG page of ${(value.getValue("name") as JsonPrimitive).content}", value)
        }
        for (tab in OverridesStore.blocks(db)) add("block/$tab", "the blocked tab $tab", JsonPrimitive(true))
        units
    }

    /** One unit's digest now, for the mirror's gate; null for a unit this side hasn't got. */
    fun digestOf(db: Db, unitId: String): String? = value(db, unitId)?.let(Canonical::digest)

    /** One unit's value (peer_sync.unit_value), what its digest is of; null for a unit this side hasn't got. */
    fun value(db: Db, unitId: String): JsonElement? =
        db.savepoint(SNAPSHOT) { Documents.unit(db, unitId, document = false)?.first }

    /** As /api/peer/unit's "unit" (peer_sync.unit_document's): null for a unit this side hasn't got. A song's kept
     * files are named with their hashes; their bytes stay in [libraryDir]. */
    @Suppress("UNUSED_PARAMETER")
    fun document(db: Db, libraryDir: File, unitId: String): JsonObject? =
        db.savepoint(SNAPSHOT) { Documents.unit(db, unitId, document = true)?.second }

    /** peer_sync.value_of_document: the unit's value from its document alone; null for no document; a [UnitError]
     * for one that isn't a document of its kind, or of a kind this caracole doesn't know. */
    fun valueOfDocument(unitId: String, doc: JsonObject?): JsonElement? = Documents.valueOf(unitId, doc)

    /** The savepoint each reading runs in: one read transaction, so a unit's many statements see one state of the
     * library even on a pooled reader while a take commits on the writer; inside a write's own, it nests. */
    private const val SNAPSHOT = "units"
}
