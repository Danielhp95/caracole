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
     *
     * What leaves a unit is any Exception its take raises, said in its own words, where Python leaves a unit for a
     * listed set (UnitError, PeerError, OSError, ValueError, a file's that won't parse, IntegrityError, and the
     * KeyError or TypeError of a document that lacks what the take reads) and lets anything else stop the take. The
     * one failure that stops this take too is the database's own ([databaseFailed]: a disk full, an I/O error, a
     * database corrupt, a statement SQLite refuses), as sqlite3's errors but IntegrityError stop Python's: each unit
     * taken before it stays taken (each is a savepoint of its own), and those after it are never tried. When the
     * phone's own units can't be read for [expectedHere]'s check, every unit it names is left saying why ("this
     * library can't be read: …"), as _digests_here says it.
     */
    fun applyUnits(db: Db, store: LibraryStore, source: UnitSource, wanted: List<Pair<String, String?>>,
                   expectedHere: Map<String, String?>, now: String, onUnit: ((String, String) -> Unit)? = null): Applied {
        val taken = mutableListOf<String>()
        val left = mutableListOf<Pair<String, String>>()
        val songs = sortedSetOf<Long>()
        val respelled = mutableListOf<String>()
        var songbooks = false
        Rekey.ensure(db, Stamps.parse(now)?.stamp ?: Stamps.now())
        // Each unit's digest here now, before the take changes any; or why this library can't be read.
        var unreadable: String? = null
        val here = if (expectedHere.isEmpty()) emptyMap() else try {
            Units.libraryState(db).mapValues { it.value.digest }
        } catch (e: Exception) {
            if (databaseFailed(e)) throw e
            unreadable = "this library can't be read: ${why(e)}"
            emptyMap()
        }
        val ordered = wanted.sortedWith { a, b ->
            val ka = kindOrder(a.first)
            val kb = kindOrder(b.first)
            if (ka != kb) ka - kb else Canonical.KEY_ORDER.compare(a.first, b.first)
        }
        for ((id, digest) in ordered) {
            try {
                if (id in expectedHere) {
                    unreadable?.let { throw UnitError(it) }
                    if (here[id] != expectedHere[id]) throw UnitError(CHANGED_HERE)
                }
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
                if (databaseFailed(e)) throw e
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

    /**
     * A backup's library tables (songs, versions, files, removed, kv and the phone's) back, exactly, in one savepoint:
     * database rows alone. What a take did on disk stays: the files it wrote, those it deleted, and the folders it
     * renamed or moved (a respelled artist's, a song's whose names changed), so after a take that changed any, the
     * rows put back may name a folder that is no longer there (the phone's storage tells case apart) or a file whose
     * bytes are no longer its SHA-256's. kv comes back whole too: an index merge's progress records written since go
     * back with it, while the index tables keep their rows. So a caller restores right after a take, before anything
     * else writes, and only when that take changed nothing on disk, or once it has undone the take's folder changes
     * itself. A file that is no backup of this caracole's is refused and nothing changes (IllegalArgumentException
     * for none there, or one of another schema or without those tables; SQLite's error for one that is no database).
     */
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
            // peer_sync._songbook_name: the songbook whose name's key is the unit's now.
            val name = SongbookStore.byKey(db, key)?.name ?: return false
            SongbookStore.put(db, name, null)
            return true
        }
        val songs = SongTake.need(doc, "songs") as? JsonArray ?: throw UnitError("its songs can't be read")
        val entries = songs.map { entry ->
            val pair = entry as? JsonArray
            val parts = pair?.getOrNull(1) as? JsonObject
            if (pair == null || pair.size != 2 || parts == null) throw UnitError("a songbook's song that can't be read")
            parts.keys.firstOrNull { it !in SETTING_PARTS }?.let {
                throw UnitError("its document can't be read (TypeError: check_setting() got an unexpected keyword " +
                                "argument ${PyRepr.str(it)})")
            }
            settingProblem(parts)?.let { throw UnitError("a setting: $it") }
            // A part that says nothing is no part of the setting (songbook_value writes those it gives).
            JsonArray(listOf(JsonPrimitive(SongTake.text(pair[0])), JsonObject(parts.filterValues { it !is JsonNull })))
        }
        SongbookStore.put(db, SongTake.text(SongTake.need(doc, "name")), JsonArray(entries))
        return true
    }

    /** The parts of a song's setting in a songbook (songbook.check_setting's). */
    private val SETTING_PARTS = setOf("key", "mode", "capo", "instrument")

    /** viewer/version.py's `_TONIC`, theory.MODES, CAPO_MAX and instruments.INSTRUMENTS' ids, in their order: what a
     * setting's parts may be. */
    private val TONIC = Regex("[A-G][#b]?")
    private val MODES = listOf("ionian", "dorian", "phrygian", "lydian", "mixolydian", "aeolian", "locrian")
    private const val CAPO_MAX = 11
    private val INSTRUMENTS = listOf("guitar", "ukulele", "ukulele-low-g", "baritone", "piano", "harmonica", "flute",
                                     "recorder")

    /** version.setting_problem: why a setting's parts (each null where it says nothing) make no setting, in Python's
     * words, or null when they make one; the songbook unit is then left, as check_setting's SongbookError leaves it. */
    internal fun settingProblem(parts: JsonObject): String? {
        fun given(name: String) = parts[name]?.takeUnless { it is JsonNull }
        fun text(e: JsonElement) = (e as? JsonPrimitive)?.takeIf { it.isString }?.content
        given("key")?.let { key ->
            if (text(key)?.let(TONIC::matches) != true) return "key must be a tonic such as \"G\", \"F#\" or \"Bb\", got ${repr(key)}"
        }
        given("mode")?.let { mode ->
            if (text(mode) !in MODES) return "mode must be one of ${MODES.joinToString(", ")}, got ${repr(mode)}"
        }
        given("capo")?.let { capo ->
            val fret = (capo as? JsonPrimitive)?.takeIf { !it.isString && isInteger(it.content) }?.content?.toBigInteger()
            if (fret == null || fret < java.math.BigInteger.ZERO || fret > CAPO_MAX.toBigInteger()) {
                return "capo must be a fret from 0 to $CAPO_MAX, got ${repr(capo)}"
            }
        }
        given("instrument")?.let { instrument ->
            if (text(instrument) !in INSTRUMENTS) {
                return "instrument must be one of ${INSTRUMENTS.joinToString(", ")}, got ${repr(instrument)}"
            }
        }
        return null
    }

    /** A literal json.loads reads as an int (never a boolean, a fraction or an exponent). */
    private fun isInteger(literal: String): Boolean = literal.removePrefix("-").let { d -> d.isNotEmpty() && d.all { it in '0'..'9' } }

    /** Python's repr of the value json.loads makes of [e] (a float's as Kotlin writes it where the two agree, else its
     * literal). */
    private fun repr(e: JsonElement): String = when {
        e is JsonNull -> "None"
        e is JsonArray -> e.joinToString(", ", "[", "]") { repr(it) }
        e is JsonObject -> e.entries.joinToString(", ", "{", "}") { "${PyRepr.str(it.key)}: ${repr(it.value)}" }
        e is JsonPrimitive && e.isString -> PyRepr.str(e.content)
        e is JsonPrimitive && e.content == "true" -> "True"
        e is JsonPrimitive && e.content == "false" -> "False"
        e is JsonPrimitive && isInteger(e.content) -> e.content.toBigInteger().toString()
        else -> e.toString().toDoubleOrNull()?.takeIf { it.isFinite() }?.toString()?.takeUnless { 'E' in it } ?: e.toString()
    }

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

    /**
     * Whether [e] is the database's own failure, which stops the take (sqlite3's errors but IntegrityError, which
     * stop Python's): any SQLite error but a constraint's or a datatype mismatch's (SQLITE_CONSTRAINT and
     * SQLITE_MISMATCH, sqlite3's IntegrityError), which is the unit's own refusal and leaves it alone. The bundled
     * driver says its result code first ("Error code: 275, message: CHECK constraint failed: …", an extended code
     * whose low byte is the primary one); one that says none is taken for a failure.
     */
    internal fun databaseFailed(e: Exception): Boolean {
        if (e !is SQLiteException) return false
        val code = RESULT_CODE.find(e.message ?: "")?.groupValues?.get(1)?.toIntOrNull() ?: return true
        return (code and 0xFF) != SQLITE_CONSTRAINT && (code and 0xFF) != SQLITE_MISMATCH
    }

    private val RESULT_CODE = Regex("^Error code: ([0-9]+)")
    private const val SQLITE_CONSTRAINT = 19
    private const val SQLITE_MISMATCH = 20
}
