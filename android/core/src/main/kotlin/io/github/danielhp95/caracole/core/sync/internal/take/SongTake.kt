package io.github.danielhp95.caracole.core.sync.internal.take

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.OverridesStore
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.internal.LibraryFiles
import io.github.danielhp95.caracole.core.library.internal.LyricsFiles
import io.github.danielhp95.caracole.core.library.internal.PyRepr
import io.github.danielhp95.caracole.core.library.internal.Removal
import io.github.danielhp95.caracole.core.library.internal.SongKv
import io.github.danielhp95.caracole.core.library.internal.Upsert
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.sync.Take
import io.github.danielhp95.caracole.core.sync.UnitError
import io.github.danielhp95.caracole.core.sync.UnitSource
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * peer_sync._take_song on the phone (the plan's §5.6): the peer's song made the phone's, whole or not at all.
 *
 * - Its names are the peer's, written as the peer writes them, and must be the song of the unit's key here.
 * - Every file whose bytes differ here is fetched from the source and checked by its SHA-256 before anything
 *   changes: one the source can't give leaves the song as it was.
 * - A song new here is made through the one way songs are added ([LibraryStore.add], which drops a tombstone of it),
 *   then written as the document says.
 * - When the library writes the song's artist's folder otherwise in case alone, every song of that artist takes the
 *   peer's spelling and the folder is renamed once ([respell]); a song whose folder changes takes caracole's files
 *   along.
 * - In one savepoint: its names, its record's columns (SONG_COLUMNS), its versions and kept files' rows, its carried
 *   kv re-keyed to its id here, its overrides entries, its tombstone forgotten; then its files and its lyrics'
 *   files, those no longer kept going once the take is done. The folders' changes are undone when the savepoint is.
 */
internal class SongTake(private val db: Db, private val store: LibraryStore, private val source: UnitSource,
                        private val key: String, private val doc: JsonObject, private val now: String) {
    /** The song's id here, and the songs respelled to the peer's spelling of its artist. */
    data class Taken(val id: Long, val respelled: List<SongRow>)

    private class Names(val artist: String, val title: String, val artists: List<String>, val album: String?,
                        val durationMs: Long?, val variant: String?)

    fun take(): Taken {
        val names = names()
        val here = Songs.byKey(db, key)
        val folderHere = here?.let { store.folderOf(it).toPath() }

        // Every file first, from the source, checked, before anything here changes.
        val files = LinkedHashMap<String, ByteArray?>()
        val shas = LinkedHashMap<String, String>()
        for (version in versions()) {
            for (f in filesOf(version)) {
                val name = Take.checkedName(nameOf(f))
                val sha = text(need(f, "sha256"))
                val same = folderHere != null && sameFile(folderHere.resolve(name), sha)
                files[name] = if (same) null else fetched(name, sha)
                shas[name] = sha
            }
        }
        val record = need(doc, "song") as? JsonObject ?: throw UnitError("its record can't be read")
        val lyrics = LyricsFiles.of((record["lyrics_json"] as? JsonPrimitive)?.takeIf { it.isString }?.content)
        val before = here?.let { song ->
            db.query("SELECT name FROM files WHERE song_id = ?", song.id) { it.text(0)!! }.toSet()
        } ?: emptySet()
        val respelledHere = here != null && toRespell(names.artist).any { it.id == here.id }
        val newParts = SafeName.songFolder(names.artist, names.title).toList()
        // Where the song's files are once its artist's folder is respelled, and those that go to its new folder if
        // that differs: caracole's, as they are now.
        val current = here?.let { song ->
            SafeName.songFolder(if (respelledHere) names.artist else song.artist, song.title).toList()
        }
        val moving = if (here != null && current != newParts) {
            try {
                Removal.caracolesFiles(db, store.libraryDir, here).toSet()
            } catch (e: IllegalStateException) {
                throw UnitError("its folder can't be moved: ${e.message}")
            }
        } else emptySet()
        for (name in files.keys.toList()) {
            if (files[name] == null && current != newParts && name !in moving) files[name] = fetched(name, shas.getValue(name))
        }
        Stamps.stampOf(now) // peer_sync._when: a take is stamped with a time

        val folders = Folders(store.libraryDir)
        val taken = try {
            db.savepoint("peer_take") {
                val song = here ?: store.add(db, names.artist, names.title, names.album, names.durationMs,
                                             names.variant, now)
                if (song.key != key) throw UnitError("adding it brought no song of its key here")
                // Read once the song is here, so that a song new here is respelled with its artist's.
                val respell = toRespell(names.artist)
                if (here != null && respell.any { it.id == here.id } != respelledHere) {
                    throw UnitError("its artist's songs changed here meanwhile: compare again")
                }
                val respelled = respell(folders, respell, names.artist)
                if (current != null && current != newParts) {
                    folders.moveFiles(current, newParts, moving)
                    dropRenderRecords(song.id)
                }
                write(song.id, names, record, newParts)
                Upsert.forgetRemoved(db, key)
                // The files, as the rows now say: the peer's written, its lyrics', those it keeps no longer gone.
                for ((name, data) in files) if (data != null) folders.write(newParts, name, data)
                for ((name, data) in lyrics) {
                    if (data != null) folders.write(newParts, name, data) else folders.remove(newParts, name)
                }
                for (name in (before - files.keys - lyrics.keys).sortedWith(Canonical.KEY_ORDER)) {
                    folders.remove(newParts, name)
                }
                val entries = need(doc, "overrides") as? JsonObject ?: throw UnitError("its overrides can't be read")
                OverridesStore.putSongEntries(db, key, "${names.artist} - ${names.title}", entries)
                Taken(song.id, respelled)
            }
        } catch (e: Throwable) {
            folders.undo()
            throw e
        }
        folders.done()
        return taken
    }

    /** The record, versions, kept files' rows and carried kv of the song [id] as the document has them. */
    private fun write(id: Long, names: Names, record: JsonObject, parts: List<String>) {
        db.execute(
            "UPDATE songs SET artist = ?, title = ?, artists = ?, album = ?, duration_ms = ?, variant = ?, " +
                SONG_COLUMNS.joinToString(", ") { "$it = ?" } + ", updated_at = ? WHERE id = ?",
            names.artist, names.title, SongKv.namesText(names.artists), names.album, names.durationMs, names.variant,
            *SONG_COLUMNS.map { cell(record[it]) }.toTypedArray(), now, id,
        )
        db.execute("DELETE FROM versions WHERE song_id = ?", id) // and their files' rows
        for (version in versions()) {
            db.execute(
                "INSERT INTO versions (song_id, ${VERSION_COLUMNS.joinToString(", ")}) " +
                    "VALUES (?, ${VERSION_COLUMNS.joinToString(", ") { "?" }})",
                id, *VERSION_COLUMNS.map { cell(version[it]) }.toTypedArray(),
            )
            val versionId = db.lastRowid()
            for (f in filesOf(version)) {
                val name = nameOf(f)
                db.execute(
                    "INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) " +
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    versionId, id, name, (parts + name).joinToString("/"), cell(need(f, "sha256")),
                    cell(need(f, "kept_rank")), now,
                )
            }
        }
        for (prefix in CARRIED_KV) SongKv.deletePrefixed(db, prefix, id)
        val carried = doc["kv"] ?: JsonObject(emptyMap())
        if (carried !is JsonObject) throw UnitError("its records can't be read")
        for ((name, value) in carried) {
            val prefix = name.substringBefore('|')
            val more = name.substringAfter('|', "")
            if (prefix in CARRIED_KV) db.kvSet("$prefix$id$more", text(value))
        }
    }

    /** peer_sync._names_of: the document's names, checked: they are the song of the unit's key here. */
    private fun names(): Names {
        val names = need(doc, "names") as? JsonObject ?: throw UnitError("its names can't be read")
        val artist = string(names["artist"])
        val title = string(names["title"])
        val artists = (names["artists"] as? JsonArray)?.map { string(it) }
        if (artist == null || Py.strip(artist).isEmpty() || title == null || artists == null || null in artists) {
            throw UnitError("its names can't be read")
        }
        if (Normalize.identityKey(artist, title) != key) {
            throw UnitError("its names, $artist - $title, are another song's here (different caracole versions?)")
        }
        val album = names["album"]
        val duration = names["duration_ms"]
        val variant = names["variant"]
        val durationMs = if (duration == null || duration is JsonNull) null else integer(duration)
        if (!(album == null || album is JsonNull || string(album) != null) ||
            !(duration == null || duration is JsonNull || durationMs != null) ||
            !(variant == null || variant is JsonNull || string(variant) != null)) {
            throw UnitError("its album, duration or variant can't be read")
        }
        return Names(artist, title, artists.map { it!! }, string(album), durationMs, string(variant))
    }

    private fun versions(): List<JsonObject> {
        val versions = need(doc, "versions") as? JsonArray ?: throw UnitError("its versions can't be read")
        return versions.map { it as? JsonObject ?: throw UnitError("its versions can't be read") }
    }

    private fun filesOf(version: JsonObject): List<JsonObject> {
        val files = need(version, "files") as? JsonArray ?: throw UnitError("its kept files can't be read")
        return files.map { it as? JsonObject ?: throw UnitError("its kept files can't be read") }
    }

    /** A kept file's name as the document gives it: text, else UnitError as peer_sync.checked_name says it. */
    private fun nameOf(f: JsonObject): String = need(f, "name").let {
        string(it) ?: throw UnitError("a kept file named ${text(it)}, which no song's folder holds")
    }

    /** peer_sync._fetched: a kept file of the song from the source, checked against its SHA-256. */
    private fun fetched(name: String, sha256: String): ByteArray {
        val data = source.file(key, name, sha256)
        if (Canonical.sha256Hex(data) != sha256) {
            throw UnitError("$name changed there meanwhile: the song stays as it was here")
        }
        return data
    }

    private fun sameFile(path: java.nio.file.Path, sha256: String): Boolean =
        LibraryFiles.regularBytes(path)?.let { Canonical.sha256Hex(it) == sha256 } ?: false

    /**
     * peer_sync._to_respell: the songs of the artist of the unit's key whose folder differs from [artist]'s in case
     * alone, when no song has [artist]'s folder: each takes [artist]'s spelling, so that the artist keeps one folder.
     * Oldest first.
     */
    private fun toRespell(artist: String): List<SongRow> {
        val folder = SafeName.safeName(artist)
        val theirs = Upsert.artistSongs(db, key).map { (id, other) -> id to SafeName.safeName(other) }
        if (theirs.any { it.second == folder }) return emptyList()
        val wanted = PyUnicode.casefold(folder)
        return theirs.filter { PyUnicode.casefold(it.second) == wanted }.map { Songs.byId(db, it.first)!! }
    }

    /** peer_sync._respell: [songs] written as [artist] (their artist, and the first of their artists where it was the
     * same), their artist's folder renamed once, their kept files' paths with it, their render records dropped. */
    private fun respell(folders: Folders, songs: List<SongRow>, artist: String): List<SongRow> {
        val new = SafeName.safeName(artist)
        for (old in songs.map { SafeName.safeName(it.artist) }.toSet().sortedWith(Canonical.KEY_ORDER)) {
            folders.moveFolder(old, new)
        }
        for (song in songs) {
            val old = SafeName.safeName(song.artist)
            val artists = song.artists.toMutableList()
            if (artists.isNotEmpty() && artists[0] == song.artist) artists[0] = artist
            db.execute("UPDATE songs SET artist = ?, artists = ?, updated_at = ? WHERE id = ?",
                       artist, SongKv.namesText(artists), now, song.id)
            for ((fileId, path) in db.query("SELECT id, path FROM files WHERE song_id = ? ORDER BY id", song.id) {
                it.long(0)!! to it.text(1)!!
            }) {
                val parts = path.split('/').filter { it.isNotEmpty() && it != "." }
                if (parts.isNotEmpty() && parts[0] == old) {
                    db.execute("UPDATE files SET path = ? WHERE id = ?", (listOf(new) + parts.drop(1)).joinToString("/"),
                               fileId)
                }
            }
            dropRenderRecords(song.id)
        }
        return songs
    }

    /** peer_sync._drop_render_records: what render.py recorded of the song's PDFs and pages, which its next render
     * makes again where the song is now. */
    private fun dropRenderRecords(id: Long) {
        val own = "render:$id"
        db.execute("DELETE FROM kv WHERE key = ? OR substr(key, 1, ?) = ? OR key = ?",
                   own, own.length + 1, "$own:", "render:files:$id")
    }

    companion object {
        /** peer_sync.SONG_COLUMNS: a song record's columns a song unit carries, beyond its names. */
        val SONG_COLUMNS = listOf("status", "review", "match_decision", "match_step", "match_score",
                                  "match_artist_key", "match_song_key", "match_candidates", "matched_at", "ug_dirty",
                                  "ug_checked_at", "lyrics_status", "lyrics_json", "lyrics_at", "lacuerda_checked_at")

        /** peer_sync.VERSION_COLUMNS. */
        val VERSION_COLUMNS = listOf("provider", "tab_id", "slot", "kind", "rating", "votes", "version", "label",
                                     "coverage", "url", "raw", "fetched_at", "pick_rank", "gone")

        /** peer_sync.CARRIED_KV: the per-song kv a song unit carries, keyed `<prefix>|<rest>` in its document. */
        val CARRIED_KV = listOf("sheet_versions:yours:", "sheet_versions:unkeepable:", "sheet_versions:same:")

        private fun string(e: JsonElement?): String? = (e as? JsonPrimitive)?.takeIf { it.isString }?.content

        /** A document's member the take reads: UnitError in Python's words for one it lacks (peer_sync._apply's
         * KeyError). */
        fun need(obj: JsonObject, key: String): JsonElement =
            obj[key] ?: throw UnitError("its entry can't be read (KeyError: ${PyRepr.str(key)})")

        /** Python's `str()` of a JSON value a document gives where text goes: a string as it is, a number as its
         * literal, a literal as Python names it. */
        fun text(e: JsonElement?): String = when {
            e == null || e is JsonNull -> "None"
            e is JsonPrimitive && e.isString -> e.content
            e is JsonPrimitive && e.content == "true" -> "True"
            e is JsonPrimitive && e.content == "false" -> "False"
            e is JsonPrimitive -> e.content
            else -> PyJson.dumps(e)
        }

        /** A JSON integer (no fraction, no exponent, never a boolean) that SQLite holds; null for anything else. */
        fun integer(e: JsonElement): Long? {
            if (e !is JsonPrimitive || e.isString) return null
            val c = e.content
            if (c.isEmpty() || !(c[0] == '-' || c[0] in '0'..'9') || c.drop(1).any { it !in '0'..'9' }) return null
            return c.toLongOrNull()
        }

        /** A document's cell as sqlite3 binds the value json.loads gives: text, an integer (a boolean as 0 or 1), a
         * real, or NULL; UnitError for what SQLite can't hold (an object, a list, an integer beyond 64 bits). */
        fun cell(e: JsonElement?): Any? = when {
            e == null || e is JsonNull -> null
            e is JsonPrimitive && e.isString -> e.content
            e is JsonPrimitive && e.content == "true" -> 1L
            e is JsonPrimitive && e.content == "false" -> 0L
            e is JsonPrimitive -> integer(e) ?: number(e.content)
            else -> throw UnitError("a value SQLite can't hold: ${PyJson.dumps(e).take(80)}")
        }

        private fun number(literal: String): Double {
            if (literal.none { it == '.' || it == 'e' || it == 'E' } && literal !in setOf("NaN", "Infinity", "-Infinity")) {
                throw UnitError("an integer SQLite can't hold: ${literal.take(40)}")
            }
            return when (literal) {
                "NaN" -> Double.NaN
                "Infinity" -> Double.POSITIVE_INFINITY
                "-Infinity" -> Double.NEGATIVE_INFINITY
                else -> literal.toDouble()
            }
        }
    }
}
