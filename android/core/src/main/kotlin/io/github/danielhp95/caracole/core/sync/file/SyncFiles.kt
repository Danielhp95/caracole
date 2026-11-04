package io.github.danielhp95.caracole.core.sync.file

import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.sqlite.driver.bundled.SQLITE_OPEN_READONLY
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.CanonicalError
import io.github.danielhp95.caracole.core.json.JsonText
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.Difference
import io.github.danielhp95.caracole.core.sync.Kept
import io.github.danielhp95.caracole.core.sync.KeptPair
import io.github.danielhp95.caracole.core.sync.PeerState
import io.github.danielhp95.caracole.core.sync.Scope
import io.github.danielhp95.caracole.core.sync.SyncUnit
import io.github.danielhp95.caracole.core.sync.UnitError
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.sync.internal.client.Documents
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.OutputStream
import java.io.RandomAccessFile
import java.math.BigInteger
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.security.SecureRandom
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.zip.CRC32
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/** An export written (peer_file.Made): its file, its parts, the songs and songbooks it holds, its size, and the
 * songs left out, each (unit id, why): FileError.CHANGED, a kept file that can no longer be read as recorded, or
 * FileError.TOO_BIG. */
data class Made(val file: File, val parts: List<String>, val songs: Int, val songbooks: Int, val size: Long,
                val left: List<Pair<String, String>>)

/**
 * peer_file.py's `.caracole` file on the phone (the sync redesign's §3.3; vectors/sync/file.jsonl holds the two to
 * Python's answers): a library written to a file ([export]), read back ([read]), refused in the owner's words
 * ([checkImportable], [checkWhole]), and what an import keeps after ([recordImport]).
 *
 * **The file** is a zip of what a sync reads from the other side: `caracole.json`, the manifest (its own format
 * [FORMAT], the caracole and schema that wrote it, the sync's format, the library's id, name and when it was made,
 * its parts and its counts, the sites of its indexes); `state.json`, the state document of the file's units, as of
 * `made`; `bases.json`, every base this library keeps; `units.jsonl`, each unit's document, in Compare.order;
 * `files/<sha256>`, each kept file once; `pages.json` and `pages/<sha256>`, the pages caracole made of its units
 * ([PageSource]), a page whose bytes are a kept file's held once, under `files/`; `indexes.sqlite`, every site's
 * index. Its JSON members are deflated, written as json.dumps with sorted keys writes them, the others stored; every
 * member is dated `made`. Its units are a library's (every song, tombstone and entry about an artist or a tab) and its
 * songbooks with the songs they list (Scope.listedSongs); a song a kept file of which can't be read as recorded, or is
 * bigger than [FILE_MAX], is left out, its pages with it, and said ([Made.left]); its state still names it.
 *
 * **Reading it**: its manifest first, then its central directory, every name in the layout (`files/` and `pages/`
 * names 64 lowercase hex, nothing else, each once), each blob at most [FILE_MAX], each JSON member at most
 * [JSON_MAX], the whole at most [IMPORT_MAX]; then its state and its bases. An index export (an SQLite file holding
 * IndexTransfer.META) is a file of the indexes alone, with no id. [checkWhole] reads every member through (its CRC,
 * its size, a blob's SHA-256, each document against the state, each kept file and page it names held) before an
 * import takes anything. :core calls no JDK text API on what it reads: its JSON is Canonical's, its names PyUnicode's.
 */
object SyncFiles {
    const val FORMAT = 1
    const val SUFFIX = ".caracole"
    const val MEDIA_TYPE = "application/vnd.caracole+zip"

    const val MANIFEST = "caracole.json"
    const val STATE = "state.json"
    const val BASES = "bases.json"
    const val UNITS = "units.jsonl"
    const val PAGES = "pages.json"
    const val FILES = "files/"
    const val PAGE_BLOBS = "pages/"
    const val INDEXES = "indexes.sqlite"

    /** A kept file's or a page's bytes, at most; a JSON member's; a file's members together. */
    const val FILE_MAX = 64L * 1024 * 1024
    const val JSON_MAX = 64L * 1024 * 1024
    const val IMPORT_MAX = 8L * 1024 * 1024 * 1024

    private val JSON_MEMBERS = listOf(MANIFEST, STATE, BASES, UNITS, PAGES)
    private val NAMED = JSON_MEMBERS + INDEXES
    private val SHA256 = Regex("[0-9a-f]{64}")
    private val ID = Regex("[0-9a-f]{16}")
    private val SQLITE = "SQLite format 3\u0000".toByteArray(Charsets.US_ASCII)
    private val ZIP = byteArrayOf(0x50, 0x4B, 0x03, 0x04)
    private const val MAX_BYTES = 150  // download_names.MAX_BYTES: a name's stem, in UTF-8
    private val random = SecureRandom()

    // --- the name ---------------------------------------------------------------------------------------------------

    /** The name an export of the library [name] made at [at] goes by: its name cleaned as a download's is
     * (download_names: what a system refuses `_`, cut to 150 bytes of UTF-8, no dot or space at either end),
     * `caracole` for none, then the day in [zone], `-dd-mm-yy`, and `.caracole`. */
    fun fileName(name: String?, at: Instant, zone: ZoneId): String {
        val stem = cut(clean(name ?: "").trim(' ', '.'), MAX_BYTES).trim(' ', '.').ifEmpty { "caracole" }
        return stem + "-" + DAY.format(at.atZone(zone)) + SUFFIX
    }

    private val DAY = DateTimeFormatter.ofPattern("dd-MM-yy")

    /** download_names._clean: what a system refuses taken out, its spaces one each. */
    private fun clean(part: String): String {
        val kept = StringBuilder()
        PyUnicode.nfc(part).codePoints().forEach { cp ->
            val kind = PyUnicode.category(cp)
            when {
                PyUnicode.isSpace(cp) -> kept.append(' ')
                kind == "Cf" -> Unit
                kind.startsWith("C") || (cp < 0x80 && cp.toChar() in "/\\:*?\"<>|") -> kept.append('_')
                else -> kept.appendCodePoint(cp)
            }
        }
        return kept.toString().replace(Regex(" +"), " ").trim(' ')
    }

    /** download_names._cut: [text] cut to [size] bytes of UTF-8 on a whole character. */
    private fun cut(text: String, size: Int): String {
        val data = text.toByteArray(Charsets.UTF_8)
        if (data.size <= size) return text
        var end = size
        while (end > 0 && (data[end].toInt() and 0xC0) == 0x80) end--
        return String(data, 0, end, Charsets.UTF_8)
    }

    /** peer_file.checked_parts: the parts named, each once, in Scope.PARTS' order; a FileError for one that isn't
     * a part. */
    fun checkedParts(parts: Collection<String>): List<String> {
        parts.firstOrNull { it !in Scope.PARTS }?.let {
            throw FileError("'$it' isn't a part: parts are library, songbooks or indexes")
        }
        return Scope.PARTS.filter { it in parts }
    }

    // --- a library written to a file --------------------------------------------------------------------------------

    /**
     * This library's [parts] written to a new file at [to] (see the object's docstring), made [now] (a stamp), by
     * caracole [version], the library [id] (kv sync:id) called [name]; [pages], the pages it holds with the library.
     * Called inside Database.write, in no transaction (an index export attaches its file): its units are read in one
     * savepoint, its indexes in another. A FileError for parts that aren't the library or the songbooks (with the
     * indexes or not), for a file there already, or one that can't be written; nothing is left behind.
     */
    fun export(db: Db, libraryDir: File, pages: PageSource?, to: File, parts: List<String>, now: String, id: String,
               name: String, version: String): Made {
        val chosen = checkedParts(parts)
        if (Scope.LIBRARY !in chosen && Scope.SONGBOOKS !in chosen) {
            throw FileError("an export holds the library or the songbooks, or both: the indexes alone are caracole " +
                                "index export's")
        }
        if (to.exists() || Files.isSymbolicLink(to.toPath())) {
            throw FileError("$to already exists: name a new file, or remove that one first")
        }
        val folder = to.absoluteFile.parentFile
        if (folder == null || !folder.isDirectory) throw FileError("${to.parentFile ?: "."} is no folder: name a file in one")
        val part = File(folder, ".${to.name}.${hex(6)}.part")
        val indexes = if (Scope.INDEXES in chosen) File(folder, ".${to.name}.${hex(6)}.indexes") else null
        val spool = File(folder, ".${to.name}.${hex(6)}.pages")
        try {
            var sites = emptyList<String>()
            var newest = emptyMap<String, String>()
            if (indexes != null) {
                try {
                    sites = IndexFile.export(db, indexes, now, version)
                    newest = IndexTransfer.newest(db)
                } catch (e: FileError) {
                    throw e
                } catch (e: Exception) {
                    throw FileError("its indexes can't be exported: ${e.message ?: e.javaClass.simpleName}")
                }
            }
            val snapshot = snapshot(db, libraryDir, chosen, id)
            val held = snapshot.documents.map { text(it["id"])!! }.toSet()
            RandomAccessFile(spool, "rw").use { spooled ->
                val listed = if (pages != null && Scope.LIBRARY in chosen) {
                    pagesHeld(pages, snapshot.state, held, snapshot.files.keys, spooled)
                } else null
                val songs = snapshot.documents.count { text(it["id"])!!.startsWith("song/") }
                val songbooks = snapshot.documents.count { text(it["id"])!!.startsWith("songbook/") }
                val manifest = obj(
                    "format" to JsonPrimitive(FORMAT), "caracole" to JsonPrimitive(version),
                    "schema" to JsonPrimitive(Database.SCHEMA_VERSION), "sync" to JsonPrimitive(Units.FORMAT),
                    "id" to JsonPrimitive(id), "name" to JsonPrimitive(name), "made" to JsonPrimitive(now),
                    "parts" to JsonArray(chosen.map(::JsonPrimitive)), "songs" to JsonPrimitive(songs),
                    "songbooks" to JsonPrimitive(songbooks), "units" to JsonPrimitive(snapshot.documents.size),
                    "files" to JsonPrimitive(snapshot.files.size),
                    "pages" to JsonPrimitive(((listed?.listed?.get("files")) as? JsonArray)?.size ?: 0),
                    "indexes" to JsonArray(sites.map(::JsonPrimitive)),
                )
                val state = stateDocument(id, version, name, snapshot.state, now, newest)
                write(part, now, libraryDir, manifest, state, snapshot, listed, spooled, indexes)
                return@use Made(to, chosen, songs, songbooks, 0L, snapshot.left)
            }.let { made ->
                Files.move(part.toPath(), to.toPath(), StandardCopyOption.ATOMIC_MOVE)
                return made.copy(size = to.length())
            }
        } catch (e: IOException) {
            throw FileError("can't write $to: ${e.message ?: e.javaClass.simpleName}")
        } finally {
            part.delete()
            spool.delete()
            indexes?.delete()
        }
    }

    /** What an export reads of the database, in one savepoint. */
    private class Snapshot(val state: Map<String, SyncUnit>, val documents: List<JsonObject>,
                           val files: Map<String, Pair<String, Long>>, val bases: JsonObject,
                           val left: List<Pair<String, String>>)

    /** peer_file._snapshot: the file's units, their documents and kept files, and the bases. */
    private fun snapshot(db: Db, libraryDir: File, parts: List<String>, id: String): Snapshot = db.savepoint("export") {
        val every = Units.libraryState(db)
        val chosen = every.keys.filter { Scope.partOf(it) in parts }.toMutableSet()
        if (Scope.SONGBOOKS in parts) {
            val values = every.keys.filter { it.startsWith("songbook/") }.associateWith { Units.value(db, it) }
            chosen.addAll(Scope.listedSongs(values, every.keys).keys)
        }
        val state = every.filterKeys { it in chosen }
        val documents = ArrayList<JsonObject>()
        val files = LinkedHashMap<String, Pair<String, Long>>()
        val left = ArrayList<Pair<String, String>>()
        val order = Compare.order(state.values.map { Difference(it.id, it.label, it, null, "", "") }).map { it.id }
        for (unitId in order) {
            val unit = state.getValue(unitId)
            val value = Units.value(db, unitId)
            val doc = Units.document(db, libraryDir, unitId)
            if (value == null || doc == null || Canonical.digest(value) != unit.digest) {
                throw FileError("$unitId changed while it was read: export again")
            }
            val (kept, why) = if (unit.kind == "song") keptFiles(db, libraryDir, unitId, doc) else emptyMap<String, Pair<String, Long>>() to null
            if (why != null) {
                left.add(unitId to why)
                continue
            }
            val document = obj("format" to JsonPrimitive(Units.FORMAT), "id" to JsonPrimitive(unitId),
                               "digest" to JsonPrimitive(unit.digest), "unit" to doc)
            documents.add(Canonical.parse(PyJson.dumps(document)) as JsonObject)
            for ((sha, at) in kept) files.putIfAbsent(sha, at)
        }
        val bases = LinkedHashMap<String, JsonElement>()
        val peers = db.query("SELECT key FROM kv WHERE substr(key, 1, ?) = ? ORDER BY key", BASE_KEY.length, BASE_KEY) {
            it.text(0)!!.substring(BASE_KEY.length)
        }
        for (peer in peers) {
            val base = Compare.baseOf(db, peer) ?: continue
            bases[peer] = obj("units" to baseJson(base), "kept" to keptJson(Compare.keptOf(db, peer)))
        }
        Snapshot(state, documents, files.toSortedMap(Canonical.KEY_ORDER), JsonObject(bases), left)
    }

    private const val BASE_KEY = "sync:base:"

    /** peer_file._kept_files: the song's kept files, each by its SHA-256 (its path, its size), once each is read
     * through and is what was recorded; or why the song is left out. */
    private fun keptFiles(db: Db, libraryDir: File, unitId: String, doc: JsonObject): Pair<Map<String, Pair<String, Long>>, String?> {
        val key = unitId.substringAfter('/')
        val found = LinkedHashMap<String, Pair<String, Long>>()
        for (version in doc["versions"] as? JsonArray ?: JsonArray(emptyList())) {
            for (f in (version as JsonObject)["files"] as? JsonArray ?: JsonArray(emptyList())) {
                val file = f as JsonObject
                val path = db.one("SELECT files.path FROM files JOIN songs ON songs.id = files.song_id " +
                                      "WHERE songs.key = ? AND files.name = ?", key, text(file["name"])) { it.text(0) }
                    ?: return emptyMap<String, Pair<String, Long>>() to FileError.CHANGED
                val size = hashedSize(File(libraryDir, path), text(file["sha256"]) ?: "")
                    ?: return emptyMap<String, Pair<String, Long>>() to FileError.CHANGED
                if (size > FILE_MAX) return emptyMap<String, Pair<String, Long>>() to FileError.TOO_BIG
                found.putIfAbsent(text(file["sha256"])!!, path to size)
            }
        }
        return found to null
    }

    /** peer_file._hashed_size: the size of the regular file at [file] (no link followed): past [FILE_MAX] as it is,
     * else once its bytes, read through in chunks, have that SHA-256; null else. */
    private fun hashedSize(file: File, sha256: String): Long? {
        if (!Files.isRegularFile(file.toPath(), LinkOption.NOFOLLOW_LINKS)) return null
        return try {
            val whole = file.length()
            if (whole > FILE_MAX) return whole
            val digest = MessageDigest.getInstance("SHA-256")
            var size = 0L
            file.inputStream().use { input ->
                val buffer = ByteArray(Zip.CHUNK)
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    digest.update(buffer, 0, n)
                    size += n
                }
            }
            if (hexOf(digest.digest()) == sha256) size else null
        } catch (e: IOException) {
            null
        }
    }

    /** The pages a file holds (peer_file._pages_held): the manifest cut to them, and each page's bytes written to
     * the spool, by SHA-256, where they lie in it. */
    private class HeldPages(val listed: JsonObject, val blobs: Map<String, Pair<Long, Long>>)

    private fun pagesHeld(pages: PageSource, state: Map<String, SyncUnit>, held: Set<String>, inFiles: Set<String>,
                          spool: RandomAccessFile): HeldPages? {
        val manifest = pages.manifest(state.filterKeys { it in held }.mapValues { it.value.digest }) ?: return null
        val start = manifest["start"]
        val kept = ArrayList<JsonElement>()
        val blobs = LinkedHashMap<String, Pair<Long, Long>>()
        for (entry in manifest["files"] as? JsonArray ?: JsonArray(emptyList())) {
            val e = entry as? JsonObject ?: continue
            val unit = e["unit"].takeUnless { it == null || it is JsonNull }
            if (unit == null) {
                if (e["path"] != start) continue
            } else {
                val id = text(unit)
                if (id == null || id !in held || e["digest"] != JsonPrimitive(state.getValue(id).digest)) continue
            }
            val sha256 = text(e["sha256"])?.takeIf { SHA256.matches(it) } ?: continue
            if (sha256 !in inFiles && sha256 !in blobs) {
                val data = try {
                    pages.open(sha256)?.use { readAtMost(it, FILE_MAX) }
                } catch (_: IOException) {
                    null
                } ?: continue
                if (hexOf(MessageDigest.getInstance("SHA-256").digest(data)) != sha256) continue
                blobs[sha256] = spool.filePointer to data.size.toLong()
                spool.write(data)
            }
            kept.add(e)
        }
        return HeldPages(JsonObject(manifest + ("files" to JsonArray(kept))), blobs)
    }

    /** peer_sync.state_document of the file's units, as of [now], with no base and no kept answer (`{}`). */
    private fun stateDocument(id: String, version: String, name: String, units: Map<String, SyncUnit>, now: String,
                              indexes: Map<String, String>): JsonObject {
        val ordered = Compare.order(units.values.map { Difference(it.id, it.label, it, null, "", "") })
        return obj(
            "format" to JsonPrimitive(Units.FORMAT), "server" to JsonPrimitive(id), "caracole" to JsonPrimitive(version),
            "name" to JsonPrimitive(name), "now" to JsonPrimitive(now),
            "indexes" to JsonObject(indexes.mapValues { JsonPrimitive(it.value) }),
            "units" to JsonObject(ordered.associateTo(LinkedHashMap()) { d ->
                d.id to obj("label" to JsonPrimitive(d.label), "digest" to JsonPrimitive(d.mine!!.digest))
            }),
            "base" to JsonNull, "kept" to JsonObject(emptyMap()),
        )
    }

    /** peer_file._write: the file written to [part], its members in the layout's order, then synced to the disk. */
    private fun write(part: File, made: String, libraryDir: File, manifest: JsonObject, state: JsonObject,
                      snapshot: Snapshot, pages: HeldPages?, spool: RandomAccessFile, indexes: File?) {
        val date = dateOf(made)
        FileOutputStream(part).use { raw ->
            ZipOutputStream(raw).use { zip ->
                fun json(name: String, value: JsonElement) = text(zip, name, date, jsonText(value))
                json(MANIFEST, manifest)
                json(STATE, state)
                json(BASES, snapshot.bases)
                text(zip, UNITS, date, snapshot.documents.joinToString("") { jsonText(it).toString(Charsets.UTF_8) + "\n" }
                    .toByteArray(Charsets.UTF_8))
                for ((sha256, at) in snapshot.files) {
                    val (path, size) = at
                    stored(zip, FILES + sha256, date, size, sha256) { out -> File(libraryDir, path).inputStream().use { it.copyTo(out, Zip.CHUNK) } }
                }
                if (pages != null) {
                    json(PAGES, pages.listed)
                    for ((sha256, at) in pages.blobs) {
                        val (offset, size) = at
                        stored(zip, PAGE_BLOBS + sha256, date, size, sha256) { out -> copySpool(spool, offset, size, out) }
                    }
                }
                if (indexes != null) {
                    stored(zip, INDEXES, date, indexes.length(), null) { out -> indexes.inputStream().use { it.copyTo(out, Zip.CHUNK) } }
                }
                zip.finish()
                raw.flush()
                raw.fd.sync()
            }
        }
    }

    private fun text(zip: ZipOutputStream, name: String, date: LocalDateTime, data: ByteArray) {
        val entry = ZipEntry(name).apply { method = ZipEntry.DEFLATED; timeLocal = date }
        zip.putNextEntry(entry)
        zip.write(data)
        zip.closeEntry()
    }

    /** A stored member [name] of [size] bytes, which [copy] writes twice: once for its CRC-32 (and its SHA-256,
     * checked against [sha256] when given), then into the zip, checked again; a FileError when they changed. */
    private fun stored(zip: ZipOutputStream, name: String, date: LocalDateTime, size: Long, sha256: String?,
                       copy: (OutputStream) -> Unit) {
        val first = Checked()
        copy(first)
        if (first.size != size || (sha256 != null && first.sha256() != sha256)) {
            throw FileError("$name changed while the file was made: export again")
        }
        val entry = ZipEntry(name).apply {
            method = ZipEntry.STORED; timeLocal = date; this.size = size; compressedSize = size; crc = first.crc.value
        }
        zip.putNextEntry(entry)
        val again = Checked(zip)
        copy(again)
        zip.closeEntry()
        if (again.crc.value != first.crc.value || again.size != size) {
            throw FileError("$name changed while the file was made: export again")
        }
    }

    /** An output that counts, CRC-32s and SHA-256s what passes through it, to [out] when given. */
    private class Checked(private val out: OutputStream? = null) : OutputStream() {
        val crc = CRC32()
        private val digest = MessageDigest.getInstance("SHA-256")
        var size = 0L

        override fun write(b: Int) = write(byteArrayOf(b.toByte()), 0, 1)

        override fun write(b: ByteArray, off: Int, len: Int) {
            crc.update(b, off, len)
            digest.update(b, off, len)
            size += len
            out?.write(b, off, len)
        }

        fun sha256(): String = hexOf(digest.digest())
    }

    private fun copySpool(spool: RandomAccessFile, offset: Long, size: Long, out: OutputStream) {
        spool.seek(offset)
        val buffer = ByteArray(Zip.CHUNK)
        var left = size
        while (left > 0) {
            val n = spool.read(buffer, 0, minOf(buffer.size.toLong(), left).toInt())
            if (n < 0) break
            out.write(buffer, 0, n)
            left -= n
        }
    }

    /** peer_file._date: [made]'s fields in UTC, a member's date. */
    private fun dateOf(made: String): LocalDateTime {
        val micros = Stamps.parse(made) ?: throw FileError("$made isn't a time")
        return LocalDateTime.ofInstant(Stamps.instant(micros), ZoneOffset.UTC)
    }

    /** peer_file._text: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")), in UTF-8. */
    private fun jsonText(value: JsonElement): ByteArray =
        PyJson.dumps(value, sortKeys = true, compact = true).toByteArray(Charsets.UTF_8)

    // --- a file read back --------------------------------------------------------------------------------------------

    /**
     * The file at [file] read back: its central directory and its manifest, state and bases, each checked; a
     * FileError, in the owner's words, for a file that isn't one, of another format, or that can't be read whole.
     * [name]: an index export's own name, when [file] isn't it (an upload staged).
     */
    fun read(file: File, name: String? = null): SyncFile {
        val head = try {
            file.inputStream().use { readAtMost(it, SQLITE.size.toLong(), whole = false) }
        } catch (e: IOException) {
            throw FileError(FileError.NOT_A_FILE)
        }
        if (head.size >= SQLITE.size && head.copyOf(SQLITE.size).contentEquals(SQLITE)) return indexFile(file, name ?: file.name)
        if (head.size < ZIP.size || !head.copyOf(ZIP.size).contentEquals(ZIP)) throw FileError(FileError.NOT_A_FILE)
        val zip = try {
            Zip.open(file)
        } catch (e: Exception) {
            if (!Zip.unopened(e)) throw e
            throw unreadable("it is cut short, or no whole zip")
        }
        zip.use { z ->
            val members = z.members
            if (members.isEmpty() || members[0].name != MANIFEST) throw FileError(FileError.NOT_A_FILE)
            val manifest = jsonMember(z, members[0]) as? JsonObject ?: throw unreadable("its manifest is no object")
            if (!Documents.isNumber(manifest["format"], FORMAT)) throw FileError(FileError.otherFormat(pyStr(manifest["format"])))
            if (!Documents.isNumber(manifest["sync"], Units.FORMAT)) {
                throw FileError(FileError.otherFormat("$FORMAT, its sync's ${pyStr(manifest["sync"])}"))
            }
            checkLayout(members)
            checkManifest(manifest)
            val names = members.associateBy { it.name }
            for (needed in listOf(STATE, UNITS)) if (needed !in names) throw unreadable("it has no $needed")
            val state = try {
                Documents.state(jsonMember(z, names.getValue(STATE)))
            } catch (e: Documents.Unreadable) {
                throw unreadable("its state can't be read")
            }
            if (state.server != text(manifest["id"])) throw unreadable("its state is another caracole's than its manifest names")
            val bases = names[BASES]?.let { jsonMember(z, it) } ?: JsonObject(emptyMap())
            if (bases !is JsonObject) throw unreadable("its bases are no object")
            val asked = (manifest["parts"] as JsonArray).map { (it as JsonPrimitive).content }.toSet()
            val holds = Scope.PARTS.filter { part ->
                part in asked && (part != Scope.INDEXES ||
                    (INDEXES in names && Documents.isNumber(manifest["schema"], Database.SCHEMA_VERSION)))
            }
            return SyncFile(file, manifest, state, bases, holds, false)
        }
    }

    /** peer_file._check_layout: every member a name of the layout, once, of a size it may be, stored or deflated,
     * the whole within [IMPORT_MAX]. */
    private fun checkLayout(members: List<ZipEntry>) {
        val seen = HashSet<String>()
        var total = BigInteger.ZERO
        for (member in members) {
            val name = member.name
            val shown = Py.slice(name, null, 80)
            val blob = (name.startsWith(FILES) || name.startsWith(PAGE_BLOBS)) && SHA256.matches(name.substringAfter('/'))
            if (name !in NAMED && !blob) throw unreadable("a member outside its layout: $shown")
            if (!seen.add(name)) throw unreadable("$shown twice")
            if (member.method != ZipEntry.STORED && member.method != ZipEntry.DEFLATED) {
                throw unreadable("$shown is encrypted, or compressed as caracole doesn't")
            }
            val most = if (blob) FILE_MAX else if (name in JSON_MEMBERS) JSON_MAX else IMPORT_MAX
            if (member.size > most) throw unreadable("$shown is bigger than it may be")
            total += BigInteger.valueOf(maxOf(member.size, 0L))
        }
        if (total > BigInteger.valueOf(IMPORT_MAX)) throw unreadable("it holds more than 8 GiB")
    }

    /** peer_file._check_manifest: its caracole's id, when it was made, its parts and its library's name. */
    private fun checkManifest(manifest: JsonObject) {
        if (text(manifest["id"])?.let { ID.matches(it) } != true) throw unreadable("its manifest names no caracole")
        val made = text(manifest["made"])
        if (made == null || parsed(made) == null) throw unreadable("its manifest says no time it was made")
        val parts = manifest["parts"]
        if (parts !is JsonArray || parts.any { text(it) == null }) throw unreadable("its manifest names no parts")
        if (text(manifest["name"]) == null) throw unreadable("its manifest names no library")
    }

    /** peer_file._json_member: a JSON member read whole (at most [JSON_MAX]) and parsed as json.loads would. */
    internal fun jsonMember(zip: Zip, member: ZipEntry): JsonElement {
        val data = try {
            zip.read(member, JSON_MAX)
        } catch (e: Zip.Damaged) {
            throw unreadable(if (e.tooBig) "${member.name} is bigger than it may be" else "${member.name} is damaged or cut short")
        }
        return try {
            Canonical.parse(utf8(data) ?: throw CanonicalError("not UTF-8"))
        } catch (e: CanonicalError) {
            throw unreadable("${member.name} is no JSON")
        }
    }

    /** peer_file._index_file: an index export (`caracole index export`'s), as a file of the indexes alone. */
    private fun indexFile(file: File, name: String): SyncFile {
        val meta = LinkedHashMap<String, String?>()
        try {
            val connection = BundledSQLiteDriver().open(file.path, SQLITE_OPEN_READONLY)
            try {
                connection.prepare("SELECT key, value FROM ${IndexTransfer.META}").use { st ->
                    while (st.step()) meta[st.getText(0)] = if (st.isNull(1)) null else st.getText(1)
                }
            } finally {
                connection.close()
            }
        } catch (e: Exception) {
            if (damaged(e)) throw unreadable("its SQLite file is damaged")
            throw FileError(FileError.NOT_A_FILE)
        }
        if (meta["format"] != IndexTransfer.FORMAT) throw FileError(FileError.otherFormat(meta["format"] ?: "None"))
        val sites = try {
            (Canonical.parse(meta["sites"] ?: "[]") as? JsonArray)?.mapNotNull { text(it) } ?: emptyList()
        } catch (e: CanonicalError) {
            emptyList()
        }
        val schemaText = meta["schema"] ?: ""
        val schema: JsonElement = if (schemaText.isNotEmpty() && schemaText.all { it in '0'..'9' }) {
            JsonPrimitive(BigInteger(schemaText))
        } else {
            meta["schema"]?.let(::JsonPrimitive) ?: JsonNull
        }
        val manifest = obj(
            "format" to JsonPrimitive(FORMAT), "caracole" to (meta["caracole"]?.let(::JsonPrimitive) ?: JsonNull),
            "schema" to schema, "name" to JsonPrimitive(name),
            "made" to (meta["exported_at"]?.let(::JsonPrimitive) ?: JsonNull),
            "parts" to JsonArray(listOf(JsonPrimitive(Scope.INDEXES))), "indexes" to JsonArray(sites.map(::JsonPrimitive)),
        )
        val holds = if (Documents.isNumber(schema, Database.SCHEMA_VERSION) && schema is JsonPrimitive && !schema.isString) {
            listOf(Scope.INDEXES)
        } else emptyList()
        return SyncFile(file, manifest, null, JsonObject(emptyMap()), holds, true)
    }

    /** Whether an SQLite failure is Python's DatabaseError (a file corrupt, or no database), never its
     * OperationalError (no such table): by the driver's result code ("Error code: 26, …"). */
    private fun damaged(e: Exception): Boolean {
        val code = RESULT_CODE.find(e.message ?: "")?.groupValues?.get(1)?.toIntOrNull() ?: return false
        return (code and 0xFF) in setOf(SQLITE_CORRUPT, SQLITE_NOTADB)
    }

    private val RESULT_CODE = Regex("^Error code: ([0-9]+)")
    private const val SQLITE_CORRUPT = 11
    private const val SQLITE_NOTADB = 26

    // --- refused, and read whole ----------------------------------------------------------------------------------

    /**
     * peer_file.check_importable: a FileError, in the owner's words, for a file this library takes nothing from: its
     * own export ([own], this caracole's id), one no newer than this side's last sync with its caracole (its `made`
     * no later than the latest time this side's base for it records, a kept answer's included: said as that day in
     * [zone], `dd/mm/yy`), and an index export of another schema.
     */
    fun checkImportable(file: SyncFile, db: Db, own: String?, zone: ZoneId) {
        if (file.indexOnly) {
            if (file.holds.isEmpty()) throw FileError(FileError.otherFormat("$FORMAT, schema ${pyStr(file.manifest["schema"])}"))
            return
        }
        if (own != null && file.id == own) throw FileError(FileError.OWN_EXPORT)
        val peer = file.id ?: return
        val whens = (Compare.baseOf(db, peer) ?: emptyMap()).values.map { it.second } +
            Compare.keptOf(db, peer).values.map { it.at }
        val times = whens.mapNotNull(::parsed)
        val made = file.made?.let(::parsed)
        val latest = times.maxOrNull() ?: return
        if (made != null && made <= latest) {
            val day = OLDER_DAY.format(Stamps.instant(latest).atZone(zone))
            throw FileError(FileError.older(file.name.ifEmpty { "its caracole" }, day))
        }
    }

    private val OLDER_DAY = DateTimeFormatter.ofPattern("dd/MM/yy")

    /**
     * peer_file.check_whole: every member of [file] read through (its CRC-32 and its size as the zip declares them),
     * each blob what its name says, each unit document what the state says of it, each kept file a song names held,
     * and each page pages.json lists (under `pages/`, else `files/`); a FileError else. An index export: SQLite's
     * `quick_check`.
     */
    fun checkWhole(file: SyncFile) {
        if (file.indexOnly) {
            quickCheck(file.file)
            return
        }
        val state = file.state!!
        val zip = try {
            Zip.open(file.file)
        } catch (e: Exception) {
            if (!Zip.unopened(e)) throw e
            throw unreadable("it is cut short, or no whole zip")
        }
        val named: Map<String, JsonObject>
        val listed: JsonElement?
        val names: Set<String>
        zip.use { z ->
            names = z.members.map { it.name }.toSet()
            for (member in z.members) {
                val checked = Checked()
                try {
                    z.copy(member, checked)
                } catch (e: Zip.Damaged) {
                    throw unreadable("${member.name} is damaged or cut short")
                }
                val blob = member.name.substringAfter('/', "")
                if ((member.name.startsWith(FILES) || member.name.startsWith(PAGE_BLOBS)) && checked.sha256() != blob) {
                    throw unreadable("${member.name} isn't the file its name says")
                }
            }
            named = documents(z, state)
            listed = if (PAGES in names) jsonMember(z, z.member(PAGES)!!) else obj("files" to JsonArray(emptyList()))
        }
        val entries = (listed as? JsonObject)?.get("files") as? JsonArray ?: throw unreadable("its $PAGES lists no pages")
        for (entry in entries) {
            val sha256 = text((entry as? JsonObject)?.get("sha256"))
            if (sha256 == null || !SHA256.matches(sha256)) throw unreadable("its $PAGES lists a page with no SHA-256")
            if (PAGE_BLOBS + sha256 !in names && FILES + sha256 !in names) {
                throw unreadable("it lists a page it doesn't hold: ${Py.slice(pyStr((entry as JsonObject)["path"]), null, 80)}")
            }
        }
        for ((unitId, doc) in named) {
            if (unitId.substringBefore('/') != "song") continue
            for (version in doc.getValue("unit").let { it as JsonObject }["versions"] as JsonArray) {
                for (f in (version as JsonObject)["files"] as JsonArray) {
                    if (FILES + text((f as JsonObject)["sha256"]) !in names) throw unreadable("$unitId keeps a file it doesn't hold")
                }
            }
        }
    }

    private fun quickCheck(file: File) {
        val said = try {
            val connection = BundledSQLiteDriver().open(file.path, SQLITE_OPEN_READONLY)
            try {
                connection.prepare("PRAGMA quick_check").use { st -> if (st.step()) st.getText(0) else null }
            } finally {
                connection.close()
            }
        } catch (e: Exception) {
            throw unreadable("its SQLite file is damaged")
        }
        if (said != "ok") throw unreadable("its SQLite file is damaged")
    }

    /** peer_file._documents: units.jsonl's documents by unit id, each of a unit the state names, once, with the
     * digest the state gives it, its value read from it alone (Units.valueOfDocument) of that digest. */
    internal fun documents(zip: Zip, state: PeerState): Map<String, JsonObject> {
        val found = LinkedHashMap<String, JsonObject>()
        val member = zip.member(UNITS) ?: throw unreadable("it has no $UNITS")
        val data = try {
            zip.read(member, JSON_MAX)
        } catch (e: Zip.Damaged) {
            throw unreadable(if (e.tooBig) "$UNITS is bigger than it may be" else "$UNITS is damaged or cut short")
        }
        for ((index, line) in lines(data).withIndex()) {
            val number = index + 1
            val doc = try {
                Canonical.parse(utf8(line) ?: throw CanonicalError("not UTF-8"))
            } catch (e: CanonicalError) {
                throw unreadable("$UNITS's line $number is no JSON")
            }
            val unitId = text((doc as? JsonObject)?.get("id"))
            if (doc !is JsonObject || unitId == null || unitId !in state.units || unitId in found ||
                !Documents.isNumber(doc["format"], Units.FORMAT) || doc["unit"] !is JsonObject) {
                throw unreadable("$UNITS's line $number is no document of a unit its state names")
            }
            val digest = try {
                Units.valueOfDocument(unitId, doc["unit"] as JsonObject)?.let(Canonical::digest)
            } catch (e: UnitError) {
                throw unreadable("${Py.slice(unitId, null, 80)}'s document can't be read")
            } catch (e: CanonicalError) {
                throw unreadable("${Py.slice(unitId, null, 80)}'s document can't be read")
            }
            if (digest != state.units.getValue(unitId).digest || doc["digest"] != JsonPrimitive(digest)) {
                throw unreadable("${Py.slice(unitId, null, 80)} isn't what its state says")
            }
            found[unitId] = doc
        }
        return found
    }

    /** bytes.splitlines(): lines cut at `\n`, `\r\n` and `\r`, none for a last empty one. */
    private fun lines(data: ByteArray): List<ByteArray> {
        val found = ArrayList<ByteArray>()
        var start = 0
        var i = 0
        while (i < data.size) {
            val b = data[i]
            if (b == '\n'.code.toByte() || b == '\r'.code.toByte()) {
                found.add(data.copyOfRange(start, i))
                if (b == '\r'.code.toByte() && i + 1 < data.size && data[i + 1] == '\n'.code.toByte()) i++
                start = i + 1
            }
            i++
        }
        if (start < data.size) found.add(data.copyOfRange(start, data.size))
        return found
    }

    /** What an export of every index would be, in bytes (`GET /api/sync/sizes`' `indexes`); null where SQLite can't
     * say. */
    fun indexesSize(db: Db): Long? = IndexFile.size(db)

    // --- an import: the comparison, what it remembers, and what the two agree on after -----------------------------

    /** This library compared with a file ([compareFile]): the differences within the parts the file holds, in
     * Compare.order; this side's units; the base and the kept answers they were compared against; the songs either
     * side's songbooks list; when the two last agreed (the latest time either base records; null: never). */
    data class FileCompared(val found: List<Difference>, val mine: Map<String, SyncUnit>,
                            val base: Map<String, String?>?, val kept: Map<String, KeptPair>,
                            val listed: Map<String, List<String>>, val syncedBefore: String?)

    /**
     * peer_file.compare_file: this library and [file] compared, as a sync compares two sides: against this side's
     * base for the file's caracole merged with the one the file keeps for this side ([own], this caracole's id), with
     * the answers both remembered, within the parts the file holds (Scope.inScope with its `holds`, so a part it
     * lacks is never read as removed). A PeerError when the file's documents can't be read ([source]'s). An index
     * export: no difference.
     */
    fun compareFile(db: Db, file: SyncFile, source: FileSource, own: String?): FileCompared {
        val mine = Units.libraryState(db)
        val state = file.state
        if (file.indexOnly || state == null) return FileCompared(emptyList(), mine, null, emptyMap(), emptyMap(), null)
        val peer = file.id
        val hereBase = peer?.let { Compare.baseOf(db, it) }
        val (fileBase, fileKept) = file.baseFor(own)
        val base = Compare.mergedBase(hereBase, fileBase)
        val kept = Compare.mergedKept(hereBase, peer?.let { Compare.keptOf(db, it) } ?: emptyMap(), fileBase, fileKept)
        val found = Compare.compare(mine, state.units, base, kept)
        val hereBooks = mine.keys.filter { it.startsWith("songbook/") }.associateWith { Units.value(db, it) }
        val fileBooks = source.documents().filterKeys { it.startsWith("songbook/") }.mapValues { it.value["unit"] }
        val listed = Scope.listedOn(listOf(hereBooks, fileBooks), mine.keys + state.units.keys)
        val agreed = listOfNotNull(hereBase, fileBase).flatMap { b -> b.values.map { it.second } }
        return FileCompared(Scope.inScope(found, file.holds, listed, file.holds), mine, base, kept, listed,
                            agreed.maxWithOrNull(Py.CODE_POINT_ORDER))
    }

    /** peer_file.in_parts: the differences of [compared] an import of [parts] is about (Scope.inScope). */
    fun inParts(compared: FileCompared, parts: Collection<String>): List<Difference> =
        Scope.inScope(compared.found, parts, compared.listed)

    // --- what an import remembers, and what the two agree on after ----------------------------------------------

    /** peer_file.kept_answers: the answers "keep mine" an import remembers: of the differences [kept] here (decide's
     * second list, each as chosen), those the file would have given ([found]'s proposal for it theirs or conflict),
     * each with this side's digest and the file's. */
    fun keptAnswers(found: List<Difference>, kept: List<Difference>): Map<String, Pair<String?, String?>> {
        val proposed = found.associate { it.id to it.proposal }
        return kept.filter { (proposed[it.id] ?: Compare.MINE) != Compare.MINE }
            .associateTo(LinkedHashMap()) { it.id to (it.mine?.digest to it.theirs?.digest) }
    }

    /** peer_file.speaks_for: whether [file] says what its caracole holds of the unit: one of a part it holds, or one
     * it carries (a song its songbooks list). */
    fun speaksFor(file: SyncFile, unitId: String): Boolean =
        (file.state != null && unitId in file.state.units) || Scope.partOf(unitId) in file.holds

    /**
     * peer_file.record_import: after an import of [file], keep, as agreed with its caracole at its `made`, each unit
     * the file speaks for that this library ([mine], its whole state now) and the file hold the same, or both lack;
     * then remember each answer "keep mine" ([keptHere]) beside the base (Compare.recordKept). The base and the kept
     * answer of every unit the file says nothing of stay as they were. Called inside Database.write. How many units
     * were agreed; an index export records nothing.
     */
    fun recordImport(db: Db, file: SyncFile, mine: Map<String, SyncUnit>,
                     keptHere: Map<String, Pair<String?, String?>>): Int {
        val state = file.state ?: return 0
        val peer = file.id ?: return 0
        val made = file.made ?: return 0
        if (file.indexOnly) return 0
        return db.savepoint("peer_import_agreement") {
            val beforeBase = Compare.baseOf(db, peer) ?: emptyMap()
            val beforeKept = Compare.keptOf(db, peer)
            val agreed = Compare.recordAgreement(db, peer, mine.filterKeys { speaksFor(file, it) },
                                                 state.units.filterKeys { speaksFor(file, it) }, made)
            val base = LinkedHashMap(Compare.baseOf(db, peer) ?: emptyMap())
            val kept = LinkedHashMap(Compare.keptOf(db, peer))
            for (unitId in base.keys + beforeBase.keys) {
                if (speaksFor(file, unitId)) continue
                val was = beforeBase[unitId]
                if (was != null) base[unitId] = was else base.remove(unitId)
            }
            for (unitId in kept.keys + beforeKept.keys) {
                if (speaksFor(file, unitId)) continue
                val was = beforeKept[unitId]
                if (was != null) kept[unitId] = was else kept.remove(unitId)
            }
            Compare.writeBase(db, peer, base, kept)
            Compare.recordKept(db, peer, keptHere, made)
            agreed
        }
    }

    // --- what they share ------------------------------------------------------------------------------------------

    internal fun unreadable(why: String) = FileError(FileError.unreadable(why))

    /** stamps.parse, a time out of range none. */
    private fun parsed(stamp: String): Long? = try {
        Stamps.parse(stamp)
    } catch (_: ArithmeticException) {
        null
    }

    private fun text(e: JsonElement?): String? = (e as? JsonPrimitive)?.takeIf { it.isString }?.content

    private fun obj(vararg members: Pair<String, JsonElement>) = JsonObject(linkedMapOf(*members))

    private fun baseJson(base: Map<String, Pair<String?, String>>) = JsonObject(
        base.keys.sortedWith(Canonical.KEY_ORDER).associateWithTo(LinkedHashMap()) { id ->
            val (digest, at) = base.getValue(id)
            JsonArray(listOf(JsonPrimitive(digest), JsonPrimitive(at)))
        })

    private fun keptJson(kept: Kept) = JsonObject(
        kept.keys.sortedWith(Canonical.KEY_ORDER).associateWithTo(LinkedHashMap()) { id ->
            val e = kept.getValue(id)
            JsonArray(listOf(JsonPrimitive(e.here), JsonPrimitive(e.there), JsonPrimitive(e.at)))
        })

    /** Python's `str()` of a JSON value json.loads read, as a refusal's words show it. */
    internal fun pyStr(e: JsonElement?): String = when {
        e == null || e is JsonNull -> "None"
        e is JsonPrimitive && e.isString -> e.content
        e is JsonPrimitive -> when (e.content) {
            "true" -> "True"
            "false" -> "False"
            else -> if (e.content.removePrefix("-").all { it in '0'..'9' }) BigInteger(e.content).toString()
                    else e.content.toDoubleOrNull()?.let { x ->
                        when {
                            x.isNaN() -> "nan"
                            x.isInfinite() -> if (x > 0) "inf" else "-inf"
                            else -> PyJson.floatText(x)
                        }
                    } ?: e.content
        }
        e is JsonArray -> e.joinToString(", ", "[", "]") { repr(it) }
        else -> (e as JsonObject).entries.joinToString(", ", "{", "}") { (k, v) -> "'$k': ${repr(v)}" }
    }

    private fun repr(e: JsonElement): String =
        if (e is JsonPrimitive && e.isString) "'${e.content}'" else pyStr(e)

    /** The whole of [input] if it holds at most [limit] bytes, else what was read past it is refused; with
     * [whole] false, its first [limit] bytes. */
    private fun readAtMost(input: java.io.InputStream, limit: Long, whole: Boolean = true): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        val buffer = ByteArray(Zip.CHUNK)
        var total = 0L
        while (true) {
            val want = if (whole) buffer.size else minOf(buffer.size.toLong(), limit - total).toInt()
            if (want <= 0) return out.toByteArray()
            val n = input.read(buffer, 0, want)
            if (n < 0) return out.toByteArray()
            total += n
            if (whole && total > limit) throw IOException("more than $limit bytes")
            out.write(buffer, 0, n)
        }
    }

    private fun hex(bytes: Int) = ByteArray(bytes).also(random::nextBytes).let(::hexOf)

    private fun hexOf(bytes: ByteArray) = JsonText.hex(bytes)

    /** [data] as UTF-8, strictly (bytes.decode("utf-8")); null for bytes that aren't. */
    private fun utf8(data: ByteArray): String? = try {
        Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(data)).toString()
    } catch (e: CharacterCodingException) {
        null
    }
}
