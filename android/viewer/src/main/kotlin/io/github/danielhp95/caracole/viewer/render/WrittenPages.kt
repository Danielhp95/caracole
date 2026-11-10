package io.github.danielhp95.caracole.viewer.render

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.SongbookStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.sync.Units
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.LinkOption

/** A page the phone wrote, as kv `render:files:<song id>` records it: its bytes' SHA-256, their size, and the song
 * unit's digest it was made at ("" for an entry that names none: one the phone never made, which is current at no
 * digest). */
data class Written(val sha256: String, val size: Long, val unitDigest: String)

/** The phone's record of a song it rendered, kv `render:<song id>:phone`: the song unit's digest and the phone's build
 * it was made at, and the characters its sheet's Chinese is written in ("simplified", "traditional"), none for a
 * sheet in no Chinese. */
data class Rendered(val unit: String, val build: String, val script: String?)

/**
 * The records of the pages the phone writes (lane phone-render), which the phone serves while they are current
 * (lane written-pages).
 *
 * kv `render:files:<song id>` is render.py's (`_written`, `_note_written`, `_forget_written`): `{name: {"sha256",
 * "size"}}`, each .cho and page in the order first written, an entry that says neither left out (render.written_entry);
 * the phone's entries also name `unit`, the song unit's digest the page was made at (Units.digestOf), each page a pass
 * writes or finds as written noted at it ([note]), one it didn't keeping its own. kv `render:<song id>:phone` is the
 * phone's alone ([Rendered]); a songbook's, kv `songbook:<folder>`, is songbook.py's `{"inputs": {file: digest},
 * "files": {file: {"sha256", "size"}}}`, each file's entry naming too, as `unit`, the digest of the songbook's unit
 * (`songbook/<name key>`, [songbookUnit]) it was made at, when a songbook has that folder. The phone serves a page
 * while its unit is still at that digest ([current], [songbookCurrent]) and forgets one a take superseded
 * (PhoneRender.afterSync). Every write is the caller's, inside Database.write.
 */
object WrittenPages {
    /** _written: the song's record, its odd entries left out. */
    fun record(db: Db, songId: Long): LinkedHashMap<String, JsonObject> {
        val out = LinkedHashMap<String, JsonObject>()
        val record = read(db, "${RenderNames.FILES_KEY}$songId") as? JsonObject ?: return out
        for ((name, entry) in record) {
            if (entryOf(entry) != null) out[name] = entry as JsonObject
        }
        return out
    }

    /** written_file, the phone's: what the record says of the file [name], or null where the phone wrote none. */
    fun written(db: Db, songId: Long, name: String): Written? {
        val entry = record(db, songId)[name] ?: return null
        val (sha, size) = entryOf(entry)!!
        return Written(sha, size, unitOf(entry))
    }

    /** _note_written: the file [name] in the song's folder holds [bytes], made at the unit digest [unitDigest]. */
    fun note(db: Db, songId: Long, name: String, bytes: ByteArray, unitDigest: String) {
        val written = record(db, songId)
        val entry = entry(Canonical.sha256Hex(bytes), bytes.size.toLong(), unitDigest)
        if (written[name] != entry) {
            written[name] = entry
            save(db, songId, written)
        }
    }

    /** Whether the song's unit is still at the digest its page [name] was made at. */
    fun current(db: Db, songId: Long, name: String): Boolean {
        val written = written(db, songId, name) ?: return false
        val song = Songs.byId(db, songId) ?: return false
        return written.unitDigest.isNotEmpty() && Units.digestOf(db, RenderNames.unitOf(song.key)) == written.unitDigest
    }

    /** _forget_written: the files [names] forgotten; with [folder], each first deleted while it is still as written
     * (library.holds), so a file of yours by that name stays. */
    fun forget(db: Db, songId: Long, names: Collection<String>, folder: File? = null) {
        val written = record(db, songId)
        val gone = names.filter { it in written }
        if (gone.isEmpty()) return
        for (name in gone) {
            val (sha, size) = entryOf(written.remove(name)!!)!!
            val path = folder?.let { File(it, name).toPath() }
            if (path != null && Kept.holds(path, sha, size)) Files.deleteIfExists(path)
        }
        save(db, songId, written)
    }

    /** Every entry of the song's record made at [unitDigest], for a caller that knows each page it records is of the
     * song at that digest (a pass over the song notes its pages one by one instead: one it couldn't make keeps the
     * digest it was made at, so it is never served as the song's now). */
    fun restamp(db: Db, songId: Long, unitDigest: String) {
        val written = record(db, songId)
        if (written.isEmpty()) return
        val stamped = LinkedHashMap<String, JsonObject>()
        for ((name, entry) in written) {
            val (sha, size) = entryOf(entry)!!
            stamped[name] = entry(sha, size, unitDigest)
        }
        if (stamped != written) save(db, songId, stamped)
    }

    /** kv `render:<song id>:phone`, or null for a song the phone never rendered (or a record it can't read). */
    fun rendered(db: Db, songId: Long): Rendered? {
        val record = read(db, RenderNames.phoneKey(songId)) as? JsonObject ?: return null
        fun text(name: String) = (record[name] as? JsonPrimitive)?.takeIf { it.isString }?.content
        return Rendered(text("unit") ?: return null, text("build") ?: return null, text("script"))
    }

    /** kv `render:<song id>:phone` made [rendered]: its members in that order, `script` only for a Chinese sheet. */
    fun noteRendered(db: Db, songId: Long, rendered: Rendered) {
        val value = linkedMapOf<String, JsonElement>("unit" to JsonPrimitive(rendered.unit),
                                                     "build" to JsonPrimitive(rendered.build))
        rendered.script?.let { value["script"] = JsonPrimitive(it) }
        db.kvSetJson(RenderNames.phoneKey(songId), JsonObject(value))
    }

    /** A songbook's written files, kv `songbook:<folder>`: each name's SHA-256 and size. */
    fun songbook(db: Db, folder: String): Map<String, Pair<String, Long>> {
        val out = LinkedHashMap<String, Pair<String, Long>>()
        for ((name, entry) in songbookFiles(db, folder)) entryOf(entry)?.let { out[name] = it }
        return out
    }

    /** What kv `songbook:<folder>` says of its file [name]: its SHA-256, its size and the songbook unit's digest it
     * was made at ("" for an entry that names none), or null where the phone recorded none. */
    fun songbookWritten(db: Db, folder: String, name: String): Written? {
        val entry = songbookFiles(db, folder)[name] as? JsonObject ?: return null
        val (sha, size) = entryOf(entry) ?: return null
        return Written(sha, size, unitOf(entry))
    }

    /** Whether the songbook whose folder is `_songbooks/<folder>/` is still at the digest its file [name] was made
     * at: false for a file the phone recorded none of, or made at no digest, or a folder no songbook has now. */
    fun songbookCurrent(db: Db, folder: String, name: String): Boolean {
        val written = songbookWritten(db, folder, name) ?: return false
        val unit = songbookUnit(db, folder) ?: return false
        return written.unitDigest.isNotEmpty() && songbookDigest(db, unit) == written.unitDigest
    }

    /** A songbook unit's digest now, or null for one that isn't there, or whose songs can't be read (Units'
     * IllegalStateException: "the songbook Name's songs aren't a list"), which is current at no digest. */
    fun songbookDigest(db: Db, unit: String): String? = try {
        Units.digestOf(db, unit)
    } catch (_: IllegalStateException) {
        null
    }

    /** The sync unit of the songbook whose folder is `_songbooks/<folder>/` (offline_routes' `books`: a songbook's
     * folder is its name's `library.safe_name`, its unit `songbook/<name key>`), or null for a folder no songbook has
     * now. Only the songbooks' names are read (phone_songbooks, SongbookStore's), so a songbook whose songs can't
     * be read still has its folder. */
    fun songbookUnit(db: Db, folder: String): String? =
        db.query("SELECT name FROM phone_songbooks ORDER BY position, key") { it.text(0)!! }
            .firstOrNull { SafeName.safeName(it) == folder }?.let { "$SONGBOOK_UNIT${SongbookStore.nameKey(it)}" }

    /** The folders kv `songbook:<folder>` records files of. */
    fun songbookFolders(db: Db): List<String> =
        db.query("SELECT key FROM kv WHERE substr(key, 1, ?) = ? ORDER BY key", SONGBOOK.length, SONGBOOK) {
            it.text(0)!!.substring(SONGBOOK.length)
        }

    /** A songbook's files written ([files], each name's bytes), made of [inputs] (their digest), into kv
     * `songbook:<folder>` as songbook.py records them: each file's entry and its inputs' digest replaced, the
     * others kept. Each entry names the digest of the folder's songbook's unit now ([songbookUnit]), the one the
     * files were made at, while a songbook has that folder. */
    fun noteSongbook(db: Db, folder: String, inputs: String, files: Map<String, ByteArray>) {
        val key = "$SONGBOOK$folder"
        val record = read(db, key) as? JsonObject
        val madeOf = LinkedHashMap((record?.get("inputs") as? JsonObject).orEmpty())
        val written = LinkedHashMap((record?.get("files") as? JsonObject).orEmpty())
        val unit = songbookUnit(db, folder)?.let { songbookDigest(db, it) }
        for ((name, bytes) in files) {
            madeOf[name] = JsonPrimitive(inputs)
            val entry = linkedMapOf<String, JsonElement>("sha256" to JsonPrimitive(Canonical.sha256Hex(bytes)),
                                                         "size" to JsonPrimitive(bytes.size))
            unit?.let { entry["unit"] = JsonPrimitive(it) }
            written[name] = JsonObject(entry)
        }
        val out = LinkedHashMap(record.orEmpty())
        out["inputs"] = JsonObject(madeOf)
        out["files"] = JsonObject(written)
        db.kvSetJson(key, JsonObject(out))
    }

    /** The songbook's files [names] forgotten, each with its inputs' digest; with [library], each first deleted from
     * `_songbooks/<folder>/` while it is still as written (library.holds: a file of yours by that name stays, and
     * nothing is deleted through a link in place of either folder), and the folder too once that leaves it empty.
     * A record left with no file goes ([gone]: a songbook no longer there, as songbook._remove_gone drops its record). */
    fun forgetSongbook(db: Db, folder: String, names: Collection<String>, library: File? = null, gone: Boolean = false) {
        val key = "$SONGBOOK$folder"
        val record = read(db, key) as? JsonObject ?: return
        val madeOf = LinkedHashMap((record["inputs"] as? JsonObject).orEmpty())
        val written = LinkedHashMap((record["files"] as? JsonObject).orEmpty())
        val forgotten = names.filter { it in written || it in madeOf }
        if (forgotten.isEmpty() && !gone) return
        val dir = library?.let { songbookDir(it, folder) }
        for (name in forgotten) {
            val entry = entryOf(written.remove(name))
            madeOf.remove(name)
            if (dir != null && entry != null && isFileName(name)) {
                val path = dir.resolve(name)
                if (Kept.holds(path, entry.first, entry.second)) Files.deleteIfExists(path)
            }
        }
        if (dir != null && written.isEmpty()) {
            try {
                Files.delete(dir) // only when empty: a file of yours stays, and so does its folder
            } catch (_: IOException) {
            }
        }
        if (written.isEmpty() && (gone || madeOf.isEmpty())) {
            db.kvDelete(key)
        } else {
            val out = LinkedHashMap(record)
            out["inputs"] = JsonObject(madeOf)
            out["files"] = JsonObject(written)
            db.kvSetJson(key, JsonObject(out))
        }
    }

    /** render.written_entry: the SHA-256 and the length an entry says (a string, and an int that is no bool), or null
     * for an entry that says neither. */
    fun entryOf(entry: JsonElement?): Pair<String, Long>? {
        if (entry !is JsonObject) return null
        val sha = (entry["sha256"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return null
        val size = (entry["size"] as? JsonPrimitive)?.takeIf { !it.isString && isInteger(it.content) }?.longOrNull
            ?: return null
        return sha to size
    }

    private const val SONGBOOK = "songbook:"
    private const val SONGBOOK_UNIT = "songbook/"

    /** songbook.FOLDER: where a songbook's files go, a folder a songbook. */
    private const val SONGBOOKS = "_songbooks"

    /** kv `songbook:<folder>`'s files, or none. */
    private fun songbookFiles(db: Db, folder: String): JsonObject =
        (read(db, "$SONGBOOK$folder") as? JsonObject)?.get("files") as? JsonObject ?: JsonObject(emptyMap())

    /** The digest an entry names as `unit`, or "". */
    private fun unitOf(entry: JsonObject): String =
        (entry["unit"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: ""

    /** A name one folder holds: no separator, no NUL, never `.`, `..` nor hidden. */
    private fun isFileName(name: String): Boolean =
        name.isNotEmpty() && !name.startsWith(".") && '/' !in name && '\\' !in name && '\u0000' !in name

    /** `_songbooks/<folder>/` under [library] while both are folders of their own (no link in place of either), else
     * null: nothing is deleted through a link (songbook._remove_gone). */
    private fun songbookDir(library: File, folder: String): java.nio.file.Path? {
        if (!isFileName(folder)) return null
        val books = library.toPath().resolve(SONGBOOKS)
        val dir = books.resolve(folder)
        return if (Files.isDirectory(books, LinkOption.NOFOLLOW_LINKS) && Files.isDirectory(dir, LinkOption.NOFOLLOW_LINKS)) dir
        else null
    }

    private fun isInteger(text: String): Boolean = text.isNotEmpty() && text.trimStart('-').all { it in '0'..'9' }

    private fun entry(sha: String, size: Long, unit: String) = JsonObject(linkedMapOf(
        "sha256" to JsonPrimitive(sha), "size" to JsonPrimitive(size), "unit" to JsonPrimitive(unit)))

    private fun save(db: Db, songId: Long, written: Map<String, JsonObject>) {
        val key = "${RenderNames.FILES_KEY}$songId"
        if (written.isEmpty()) db.kvDelete(key) else db.kvSetJson(key, JsonObject(written))
    }

    /** A kv record's JSON, as json.loads reads it; null for none, or one that isn't JSON. */
    private fun read(db: Db, key: String): JsonElement? {
        val text = db.kvGet(key) ?: return null
        return try {
            PyJson.loads(text)
        } catch (_: IllegalArgumentException) {
            null
        } catch (_: IOException) {
            null
        }
    }
}
