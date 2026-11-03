package io.github.danielhp95.caracole.core.sync

import androidx.sqlite.SQLiteException
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.OverridesStore
import io.github.danielhp95.caracole.core.library.SongbookStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.internal.PyRepr
import io.github.danielhp95.caracole.core.library.internal.Rekey
import io.github.danielhp95.caracole.core.library.internal.Stamps
import io.github.danielhp95.caracole.core.library.internal.Upsert
import io.github.danielhp95.caracole.core.sync.internal.take.Backups
import io.github.danielhp95.caracole.core.sync.internal.take.SongTake
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File

/** What a take did: the units taken, those left (with why), the songs it wrote (to render again: those taken and
 * those respelled, by id, in order), the songs respelled to the artist's spelling a song taken writes (their unit
 * ids), and whether a songbook changed. */
data class Applied(val taken: List<String>, val left: List<Pair<String, String>>, val songs: List<Long>,
                   val respelled: List<String>, val songbooksChanged: Boolean)

/**
 * peer_sync.apply_units on the phone (the plan's §5.6, the rules both sides keep): each unit chosen read from a
 * [UnitSource] and made the phone's, whole or not at all, and left, saying why, when either side holds it otherwise
 * than when the two were compared. applyUnits, backupBeforeSync and restore are called inside Database.write.
 */
object Take {
    /** Why a unit is left: either side holds it otherwise than when the two were compared. */
    const val CHANGED_HERE = "changed here since the comparison"
    const val CHANGED_THERE = "changed there since the comparison"

    /** The order units are taken in: songs first, then tombstones, songbooks and the rest (peer_sync._KINDS). */
    private val KINDS = listOf("song", "removed", "songbook", "alias", "artist_url", "block")

    /**
     * Take each of [wanted] (a unit's id, and the digest the source had of it when compared, null for a unit it hadn't
     * got) from [source]: songs first, then tombstones, songbooks and the rest, each by id. A unit is left, saying
     * why, when its document no longer has the digest compared ([CHANGED_THERE]), when the phone's digest of it
     * differs from [expectedHere]'s ([CHANGED_HERE]: the phone's digests when compared, null for a unit it hadn't;
     * a unit it doesn't name isn't checked), or when it can't be taken: an error in one unit never stops the rest.
     * [now] (a stored time) stamps what the take writes. [onUnit] is told of each unit as it is done: its id, and
     * "taken" or "left" (the why is in [Applied.left]).
     */
    fun applyUnits(db: Db, store: LibraryStore, source: UnitSource, wanted: List<Pair<String, String?>>,
                   expectedHere: Map<String, String?>, now: String, onUnit: ((String, String) -> Unit)? = null): Applied {
        val taken = mutableListOf<String>()
        val left = mutableListOf<Pair<String, String>>()
        val songs = sortedSetOf<Long>()
        val respelled = mutableListOf<String>()
        var songbooks = false
        Rekey.ensure(db, Stamps.parse(now)?.stamp ?: Stamps.now())
        // Each unit's digest here now, before the take changes any.
        val here = if (expectedHere.isEmpty()) emptyMap() else Units.libraryState(db).mapValues { it.value.digest }
        val ordered = wanted.sortedWith { a, b ->
            val ka = kindOrder(a.first)
            val kb = kindOrder(b.first)
            if (ka != kb) ka - kb else Canonical.KEY_ORDER.compare(a.first, b.first)
        }
        for ((id, digest) in ordered) {
            try {
                if (id in expectedHere && here[id] != expectedHere[id]) throw UnitError(CHANGED_HERE)
                val doc = source.unit(id)
                val there = doc?.let { Canonical.digest(Units.valueOfDocument(id, it) ?: JsonNull) }
                if (there != digest) throw UnitError(CHANGED_THERE)
                val kind = id.substringBefore('/')
                val rest = id.substringAfter('/', "")
                when (kind) {
                    "song" -> if (doc == null) {
                        store.remove(db, rest, now)
                    } else {
                        val song = SongTake(db, store, source, rest, doc, now).take()
                        songs += song.id
                        songs += song.respelled.map { it.id }
                        respelled += song.respelled.filter { it.key != rest }.map { "song/${it.key}" }
                    }
                    "removed" -> takeRemoved(db, rest, doc)
                    "songbook" -> if (takeSongbook(db, rest, doc)) songbooks = true
                    "alias" -> OverridesStore.putAlias(db, rest, rest, doc?.let { slugs(it) })
                    "artist_url" -> OverridesStore.putArtistUrl(db, rest, doc?.let {
                        JsonObject(mapOf("name" to JsonPrimitive(SongTake.text(SongTake.need(it, "name"))),
                                         "page" to JsonPrimitive(SongTake.text(SongTake.need(it, "page")))))
                    })
                    "block" -> OverridesStore.putBlock(db, tab(rest), doc != null)
                    else -> throw UnitError("this caracole doesn't know units of kind ${PyRepr.str(kind)}")
                }
            } catch (e: Exception) {
                val why = why(e)
                left += id to why
                onUnit?.invoke(id, "left")
                continue
            }
            taken += id
            onUnit?.invoke(id, "taken")
        }
        return Applied(taken, left, songs.toList(), respelled, songbooks)
    }

    /** A full openable database of the library's tables (songs, versions, files, removed, kv and the phone's), as
     * `stateDir/backups/before-sync-<UTC time>.sqlite`, three kept; null, and none made, without free space of twice
     * what it needs. */
    fun backupBeforeSync(db: Db, stateDir: File, now: String): File? = Backups.make(db, stateDir, now)

    /** A backup's library tables back, in one savepoint. */
    fun restore(db: Db, backup: File): Unit = Backups.restore(db, backup)

    /** peer_sync.checked_name: a kept file's name as a song's document gives it, when a song's folder can hold it (no
     * `/`, `\` or NUL, nothing that starts with `.`, not empty); else UnitError. */
    fun checkedName(name: String): String {
        if ('/' in name || '\\' in name || '\u0000' in name || name.startsWith(".") || name.isEmpty() || name == "..") {
            throw UnitError("a kept file named ${PyRepr.str(name)}, which no song's folder holds")
        }
        return name
    }

    private fun kindOrder(id: String): Int = KINDS.indexOf(id.substringBefore('/')).let { if (it < 0) 99 else it }

    /** A tombstone the peer has made where neither the song nor a tombstone of it is here; one it has no longer
     * forgotten. */
    private fun takeRemoved(db: Db, key: String, doc: JsonObject?) {
        if (doc == null) {
            Upsert.forgetRemoved(db, key)
            return
        }
        if (Songs.byKey(db, key) != null || Upsert.removedSong(db, key) != null) return
        val artist = SongTake.text(SongTake.need(doc, "artist"))
        val title = SongTake.text(SongTake.need(doc, "title"))
        val ids = doc["source_ids"]
        val sourceIds = if (ids == null || falsy(ids)) JsonObject(emptyMap()) else ids
        val removedAt = SongTake.text(SongTake.need(doc, "removed_at"))
        db.execute("INSERT INTO removed (key, artist, title, source_ids, removed_at) VALUES (?, ?, ?, ?, ?)",
                   key, artist, title, PyJson.dumps(sourceIds), removedAt)
    }

    /** A songbook the peer has put in its place, one it has no longer dropped; whether one changed. */
    private fun takeSongbook(db: Db, key: String, doc: JsonObject?): Boolean {
        if (doc == null) {
            val name = SongbookStore.all(db).firstOrNull { it.key == key }?.name ?: return false
            SongbookStore.put(db, name, null)
            return true
        }
        val songs = SongTake.need(doc, "songs") as? JsonArray ?: throw UnitError("its songs can't be read")
        val entries = songs.map { entry ->
            val pair = entry as? JsonArray
            val parts = pair?.getOrNull(1) as? JsonObject
            if (pair == null || pair.size != 2 || parts == null || parts.keys.any { it !in SETTING_PARTS }) {
                throw UnitError("a songbook's song that can't be read")
            }
            // A part that says nothing is no part of the setting (songbook_value writes those it gives).
            JsonArray(listOf(JsonPrimitive(SongTake.text(pair[0])), JsonObject(parts.filterValues { it !is JsonNull })))
        }
        SongbookStore.put(db, SongTake.text(SongTake.need(doc, "name")), JsonArray(entries))
        return true
    }

    /** The parts of a song's setting in a songbook (songbook.check_setting's). */
    private val SETTING_PARTS = setOf("key", "mode", "capo", "instrument")

    private fun slugs(doc: JsonObject): JsonArray {
        val slugs = SongTake.need(doc, "slugs") as? JsonArray ?: throw UnitError("its slugs can't be read")
        return JsonArray(slugs.map { JsonPrimitive(SongTake.text(it)) })
    }

    /** peer_sync.tab_of: the tab a `block/<tab>` unit names, ASCII digits with no leading zero as library_state
     * writes it; else UnitError. */
    private fun tab(rest: String): Long =
        rest.takeIf { it.isNotEmpty() && it.all { c -> c in '0'..'9' } && (it == "0" || it[0] != '0') }?.toLongOrNull()
            ?: throw UnitError("${PyRepr.str(rest)} isn't a tab's id")

    /** Python's truth of a JSON value: null, false, 0, "", [] and {} are false. */
    private fun falsy(e: JsonElement): Boolean = when (e) {
        is JsonNull -> true
        is JsonObject -> e.isEmpty()
        is JsonArray -> e.isEmpty()
        is JsonPrimitive -> if (e.isString) e.content.isEmpty() else e.content in setOf("false", "0", "0.0", "-0", "-0.0")
    }

    /** The words a unit is left with: its error's message, SQLite's own for a refusal of the database's. */
    private fun why(e: Exception): String {
        val message = e.message ?: e::class.simpleName ?: "an error"
        if (e is SQLiteException) return message.substringAfter("message: ", message)
        return message
    }
}
