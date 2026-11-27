package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.JsonText
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.FileAlreadyExistsException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.NoSuchFileException
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption
import java.nio.file.attribute.BasicFileAttributes
import java.nio.file.attribute.FileTime
import java.nio.file.attribute.PosixFilePermissions
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/**
 * audio_store.py on the phone: the audio files the owner gives caracole for a song's auto sheet, in caracole's own
 * folder, `stateDir/audio/` (0700, each file 0600), never the library, never synced. Every rule, name, limit and word
 * is audio_store.py's, read from data/caracole/library/audio_store.json (tests/test_conformance_audio_store.py), its
 * patterns through PyRegex; vectors/library/audio_store.jsonl holds Python's answers.
 *
 * - **A staged upload** is `.upload-<16 hex><ext>` beside its record `.upload-<id>.json` ([stage]), until a job keeps
 *   it as a song's audio ([keep]): at most one no job names waits (a new stage lets go of the others [stage]'s
 *   `named` doesn't hold), one left [EXPIRES] that no job names is swept ([sweep]), or dropped at once ([drop]).
 * - **A kept file** is `<song id>-<sha256 16 hex><ext>`, named by the song's `audio_path` ([uploaded]); kv
 *   `audio:name:<id>` ([NAME_KEY]) the name it was given under. [tidy] deletes those no song names.
 * - **A moved upload's marker**, `.upload-<id>.kept`, is written before the data's move, so a keep cut off at any
 *   point finishes when asked again ([marked], [adopt]).
 *
 * Where the phone departs from the computer: [stage] spools a stream (Python's takes the bytes a route read whole),
 * its partial file `.upload-<id>.part`, refused as soon as it is known (its head no audio, past [AUDIO_MAX], the
 * room running out), the room checked exactly once the bytes are all there; and the store reads no audio itself:
 * the release app ships `:core`, so an [Examiner] the app gives reads the length and the tags, the store judging
 * what Python judges around mutagen's read ([Examiner]'s contract).
 *
 * The store's lock ([held]) is one for the process, as audio_store's `_lock` is caracole serve's: the phone runs one.
 */
class AudioStore(
    val stateDir: File,
    private val examiner: Examiner,
    private val freeSpace: (File) -> Long = { it.usableSpace },
    private val clock: () -> Double = { now() },
) {
    /** The folder, `stateDir/audio`, there or not. */
    val root: File = File(stateDir, FOLDER)

    /** A file refused, or an upload that isn't there: why, in audio_store's words, and caracole serve's status. */
    class AudioError(message: String, val status: Int = 400) : Exception(message)

    /** What an [Examiner] read of a file: its [format] (a key of [FORMATS]), its length in seconds, and for each tag
     * of the store (`artist`, `title`, `album`) the values the reader found, in music.py's key order. */
    data class Audio(val format: String, val durationS: Double, val tags: Map<String, List<String>>)

    /**
     * The reader of the app's audio, which `:core` hasn't. Given a file and the format its bytes say ([sniff]), it
     * reads it as mutagen does on the computer (audio_store._read), or throws: anything it throws (but an IOException
     * of a file kept on the disk, which is the disk's) is a refusal, [NOT_AUDIO]. Its contract:
     * - [Audio.format] is the format it read the file as, the one it was given;
     * - [Audio.durationS] is mutagen's `info.length`, but for an MP3 the length its frames count (mpeg_frames.py's
     *   `counted_length`: ID3v2 and ID3v1/APE left out, each frame's samples over its own rate) wherever that count is
     *   not 0, as audio_store._read takes it: never the size over the first frame's bitrate;
     * - an M4A with no sound track (no `soun` handler with channels and a rate) is refused, by throwing;
     * - [Audio.tags]: for `artist` the values of music._ARTIST_KEYS, `title` _TITLE_KEYS, `album` _ALBUM_KEYS, a
     *   key's first value each (an ID3 frame's first text), in that order; the store keeps the first whose
     *   stripped text isn't empty, stripped (music._first).
     * The store judges the rest: a length that isn't over 0 or isn't finite, [NOT_AUDIO]; past [MAX_SECONDS],
     * [TOO_LONG].
     *
     * A stage hands it the spool, `.upload-<id>.part`, named with no audio extension: a reader goes by the format it
     * is given, never the file's name. An IOException reading the spool is [NOT_AUDIO], as Python's read of a stage's
     * bytes in memory (io.BytesIO) makes any error a refusal; reading a kept file ([keep], [adopt]) it is the disk's.
     */
    fun interface Examiner {
        fun examine(file: File, format: String): Audio
    }

    /** A staged upload: its id, its file, the name it was sent under (a name to show), its size, SHA-256, format,
     * length, tags and when it came (audio_store.Staged). */
    data class Staged(val id: String, val file: File, val name: String, val size: Long, val sha256: String,
                      val format: String, val durationS: Double, val tags: Map<String, String?>, val at: Double) {
        /** `.upload-<id>.json`'s text, as stage writes it: `json.dumps(up.record())`. */
        fun record(): String = recordText(name, size, sha256, format, durationS, tags, at)
    }

    /** A moved upload's marker: the kept file it became, the song it was kept for, when, and whether its keep is
     * over (the staged record gone: the song's row named the file). */
    data class Marked(val upload: String, val file: File, val song: Long, val at: Double, val done: Boolean)

    /** The staged uploads' lock, for a caller to hold across a check and what it does after it (audio_store.held):
     * Make sheet's [staged] and its job queued, a drop's check and its [drop]. Re-entrant. Its order: never a
     * database write under it (a `named` callback, a block given here), as a job's write may call into the store; so
     * nothing the store does inside a write ([keep], [adopt], [tidy]) takes it. */
    fun <T> held(block: () -> T): T = LOCK.withLock(block)

    // --- what a file is ---------------------------------------------------------------------------------------------

    /** What the staged or kept file is, as audio_store._examine reads it: [sniff] of its first [HEAD] bytes, then the
     * examiner's read. [onDisk]: an IOException of the examiner's is the disk's, raised as it is (a file of the
     * folder); else, as a stage's bytes, a refusal. */
    private fun examine(file: File, onDisk: Boolean, head: ByteArray = headOf(file)): Examined {
        val format = sniff(head) ?: throw refusal("not_audio")
        val read = try {
            examiner.examine(file, format)
        } catch (e: AudioError) {
            throw e
        } catch (e: IOException) {
            if (onDisk) throw e
            null
        } catch (e: Exception) { // a file anyone may send: whatever it makes the reader raise
            null
        } ?: throw refusal("not_audio")
        val length = read.durationS
        if (read.format != format || !length.isFinite() || length <= 0.0) throw refusal("not_audio")
        if (length > MAX_SECONDS) throw refusal("too_long")
        return Examined(format, length, TAGS.associateWith { first(read.tags[it].orEmpty()) })
    }

    private class Examined(val format: String, val durationS: Double, val tags: Map<String, String?>)

    // --- a staged upload --------------------------------------------------------------------------------------------

    /**
     * An upload's bytes, read from [input] as they come and sent under [name], staged in the folder until a job keeps
     * them ([keep]). [NO_NAME] (400) before a byte is read. Spooled into `.upload-<id>.part`, a chunk at a time, and
     * refused as soon as it is known, the partial file deleted each time: [NOT_AUDIO] (415) once the first [HEAD]
     * bytes are in and [sniff] names no format; [TOO_BIG] (413) at the first byte past [AUDIO_MAX]; [NO_ROOM] (507),
     * checked every MiB, as soon as the disk's free bytes and those of every staged upload a stage may let go (the
     * folder listed again at each check) are fewer than the bytes spooled and [ROOM] (a condition Python's check
     * needs: free before ≥ 2 × size + ROOM implies free now ≥ size + ROOM, so it refuses nothing Python accepts);
     * [EMPTY] (400) with none. Then read as
     * audio_store._examine reads one (415, 422), and under the store's lock every other staged upload [named]
     * (called under it) doesn't hold goes and the room is checked exactly as audio_store._room checks it (the disk's
     * free bytes now, the spooled ones counted free, under twice them and [ROOM]); the file takes its name, its record
     * beside it.
     *
     * A refusal before the stream's end leaves the rest of [input] unread, and [stage] never closes it: its caller
     * (the upload route) drains or closes it. A read that returns 0 bytes into a buffer with room is a broken stream:
     * an IOException, as is any of the stream's or the disk's, raised as it is.
     */
    fun stage(input: InputStream, name: String, named: () -> Collection<String>): Staged {
        val shown = displayName(name)
        if (shown.isEmpty()) throw refusal("no_name")
        held { store() }
        var id = token()
        var spool = File(root, "$STAGED$id$PART_END")
        while (!createPrivate(spool)) {
            id = token()
            spool = File(root, "$STAGED$id$PART_END")
        }
        var moved = false
        try {
            val digest = MessageDigest.getInstance("SHA-256")
            val head = ByteArray(HEAD)
            var size = 0L
            var format: String? = null
            // What the stage may let go at its end: the other staged uploads as they are now, listed again at each
            // check (another tab's staged meanwhile counts), never this one's own spool.
            fun freeable() = held {
                (stagedIds() - id).sumOf { other -> pieces(other).sumOf { attributes(it)?.size() ?: 0L } }
            }
            var checked = 0L
            FileChannel.open(spool.toPath(), StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS).use { out ->
                val buffer = ByteArray(CHUNK)
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    if (n == 0) throw IOException("the upload's stream read nothing into a buffer with room: broken")
                    if (size + n > AUDIO_MAX) throw refusal("too_big")
                    if (size < HEAD) {
                        System.arraycopy(buffer, 0, head, size.toInt(), minOf(n.toLong(), HEAD - size).toInt())
                    }
                    digest.update(buffer, 0, n)
                    val bytes = ByteBuffer.wrap(buffer, 0, n)
                    while (bytes.hasRemaining()) out.write(bytes)
                    size += n
                    if (format == null && size >= HEAD) format = sniff(head) ?: throw refusal("not_audio")
                    if (size - checked >= ROOM_EVERY) {
                        checked = size
                        if (freeSpace(root) + freeable() < size + ROOM) throw refusal("no_room")
                    }
                }
            }
            if (size == 0L) throw refusal("empty")
            if (format == null) sniff(head.copyOf(size.toInt())) ?: throw refusal("not_audio")
            val found = examine(spool, onDisk = false, head = head.copyOf(minOf(size, HEAD.toLong()).toInt()))
            return held {
                store()
                val holding = named().toSet()
                for (other in stagedIds() - holding) dropPieces(other)
                if (freeSpace(root) + size < 2 * size + ROOM) throw refusal("no_room")
                val ext = FORMATS.getValue(found.format)
                while (pieceThere(id)) id = token()
                val file = File(root, "$STAGED$id$ext")
                val up = Staged(id, file, shown, size, JsonText.hex(digest.digest()), found.format, found.durationS,
                                found.tags, clock())
                try {
                    Files.move(spool.toPath(), file.toPath(), StandardCopyOption.ATOMIC_MOVE)
                    moved = true
                    val record = File(root, "$STAGED$id$RECORD")
                    if (!createPrivate(record)) throw FileAlreadyExistsException(record.path)
                    record.writeBytes(up.record().toByteArray(Charsets.UTF_8))
                } catch (e: Throwable) {
                    dropPieces(id)
                    throw e
                }
                up
            }
        } finally {
            if (!moved) unlink(spool)
        }
    }

    /** [stage] of the ids [named] holds. */
    fun stage(input: InputStream, name: String, named: Set<String>): Staged = stage(input, name) { named }

    /**
     * The staged upload [uploadId] names (audio_store.staged): [WHICH] (400) for an id that isn't 16 hex, [GONE] (404)
     * for none here: no record of it, no audio file or more than one under its id, one that isn't a regular file (a
     * link planted in its place), or that isn't what its record says.
     */
    fun staged(uploadId: String): Staged {
        checkId(uploadId)
        if (!isStore(root)) throw refusal("gone")
        val there = FORMATS.values.filter { lexists(File(root, "$STAGED$uploadId$it")) }
        val record = readRecord(File(root, "$STAGED$uploadId$RECORD"))
        if (there.size != 1 || record == null || FORMATS[record.format] != there[0]) throw refusal("gone")
        val file = File(root, "$STAGED$uploadId${there[0]}")
        val attrs = attributes(file) ?: throw refusal("gone")
        if (!attrs.isRegularFile || record.size == null || attrs.size() != record.size) throw refusal("gone")
        return Staged(uploadId, file, record.name, record.size, record.sha256, record.format, record.duration,
                      record.tags, record.at)
    }

    /** Whether [uploadId] is a well-formed id that names no staged upload ([staged]'s 404), never one that isn't an
     * id (400). */
    fun gone(uploadId: String?): Boolean {
        if (uploadId == null || !ID.matches(uploadId)) return false
        return try {
            staged(uploadId)
            false
        } catch (e: AudioError) {
            e.status == 404
        }
    }

    /** The staged upload [uploadId] deleted now, whatever is left of it (the page's Cancel): [WHICH] (400), [GONE]
     * (404) for none here. */
    fun drop(uploadId: String) {
        checkId(uploadId)
        held {
            if (!isStore(root) || !dropPieces(uploadId)) throw refusal("gone")
        }
    }

    /**
     * audio_store.sweep: each staged upload left [EXPIRES] (by [now]) that [named] (called under the lock) doesn't
     * hold deleted, whatever is left of it; the ids deleted. A marker goes, with what is left of its upload,
     * [MARKED] after its keep, and before that only once the kept file it names and its staged data are both gone and
     * no job names its id. The phone's spooled `.upload-<id>.part` an upload stopped mid-way left goes too, an
     * [EXPIRES] after it was last written.
     */
    fun sweep(named: () -> Collection<String>, now: Double = clock()): List<String> = held {
        if (!isStore(root)) return@held emptyList()
        val holding = named().toSet()
        val gone = (stagedIds() - holding).filter { now - touched(it) > EXPIRES }.sorted()
        for (id in gone) dropPieces(id)
        for (id in markers()) {
            val found = readMarker(id)
            val marker = markerFile(id)
            val at = found?.at ?: (attributes(marker)?.let { seconds(it.lastModifiedTime()) } ?: continue)
            val data = FORMATS.values.any { lexists(File(root, "$STAGED$id$it")) }
            if (now - at <= MARKED && (data || id in holding || (found != null && regular(found.file)))) continue
            dropPieces(id)
            unlink(marker)
        }
        for (name in root.list().orEmpty()) {
            if (!name.startsWith(STAGED) || !name.endsWith(PART_END)) continue
            if (!ID.matches(name.substring(STAGED.length, name.length - PART_END.length))) continue
            val spool = File(root, name)
            val attrs = attributes(spool) ?: continue
            if (attrs.isRegularFile && now - seconds(attrs.lastModifiedTime()) > EXPIRES) unlink(spool)
        }
        gone
    }

    /** [sweep] of the ids [named] holds. */
    fun sweep(named: Set<String>, now: Double = clock()): List<String> = sweep({ named }, now)

    /** The marker of an upload a keep moved (or began moving) into place, while the kept file it names is a regular
     * file of the folder (audio_store.marked); null for none. */
    fun marked(uploadId: String?): Marked? {
        if (uploadId == null || !ID.matches(uploadId) || !isStore(root)) return null
        return readMarker(uploadId)?.takeIf { regular(it.file) }
    }

    // --- a song's own audio -----------------------------------------------------------------------------------------

    /** The file the owner gave the song, when its audio is one (a kept file of the folder), else null. */
    fun uploaded(song: SongRow): File? = keptIn(root, song.audioPath)

    /**
     * audio_store.keep(move=True): the staged upload moved into place as the song's audio, `<song id>-<sha256 16
     * hex><ext>`, whatever it had (an upload always wins), its hash read streamed from the file; the song's row names
     * it ([named]'s order of writes). The marker is written before the data's move, and the staged record goes only
     * once the row names the kept file, so the same job asked again finishes at every point of a kill. AudioError:
     * a song no longer in the book (404, nothing read or moved), a file that isn't a staged upload's regular file
     * (404), one caracole doesn't read (415) or past [MAX_SECONDS] (422). Called inside the job's write.
     */
    fun keep(db: Db, song: SongRow, staged: Staged): File {
        val current = Songs.byId(db, song.id) ?: throw notInBook(song)
        val source = staged.file
        val match = STAGED_AUDIO.matchEntire(source.name)
        if (source.parentFile?.path != root.path || match == null || !isStore(root)) throw refusal("gone")
        if (attributes(source)?.isRegularFile != true) throw refusal("gone")
        val format = examine(source, onDisk = true).format
        val uploadId = match.groups["id"]!!.value
        val kept = File(root, keptName(current.id, hashOf(source), format))
        writeMarker(uploadId, kept, current.id)
        if (regular(kept)) unlink(source) // the song's audio already
        else Files.move(source.toPath(), kept.toPath(), StandardCopyOption.ATOMIC_MOVE)
        syncFolder(root)
        return named(db, current, kept, uploadId)
    }

    /** audio_store.adopt: the kept file an upload's marker names made the song's audio, for a keep cut off after the
     * move and before the song's row named it. That exact name, kept for this song; [GONE] (404) for anything else. */
    fun adopt(db: Db, song: SongRow, uploadId: String): File {
        val found = if (ID.matches(uploadId) && isStore(root)) readMarker(uploadId) else null
        if (found == null || found.done || found.song != song.id || !regular(found.file)) throw refusal("gone")
        val current = Songs.byId(db, song.id) ?: throw notInBook(song)
        examine(found.file, onDisk = true) // still audio caracole reads
        return named(db, current, found.file, uploadId)
    }

    /** The name the song's given file had ([NAME_KEY]); null for none. */
    fun givenName(db: Db, song: SongRow): String? = db.kvGet("$NAME_KEY${song.id}")?.takeIf { it.isNotEmpty() }

    /**
     * audio_store.tidy: the kept files no song's `audio_path` names deleted (by name: a kept file's name is unique in
     * the folder), and the copies a stopped write left (`.keep-<16 hex>.part`); how many went. A kept file the marker
     * of a keep not over names stays for that keep's retry. The staged uploads are [sweep]'s; any other file stays.
     * Called inside a database write, it takes no store lock (audio_store.tidy takes none).
     */
    fun tidy(db: Db): Int {
        if (!isStore(root)) return 0
        val named = db.query("SELECT audio_path FROM songs WHERE audio_path IS NOT NULL") { File(it.text(0)!!).name }
            .toSet()
        val pending = liveKept()
        var deleted = 0
        for (name in root.list().orEmpty()) {
            val mine = (KEPT.matches(name) && name !in named && name !in pending) || PART.matches(name)
            if (!mine || attributes(File(root, name))?.isDirectory != false) continue
            try {
                if (unlink(File(root, name))) deleted++
            } catch (_: IOException) {
            }
        }
        return deleted
    }

    /** The song's row naming the kept file and the name it was given under, in one savepoint; then the staged record
     * let go; then the file the song had there before, unless another song's row names it (audio_store._named). */
    private fun named(db: Db, current: SongRow, kept: File, uploadId: String): File {
        val mtime = seconds(Files.getLastModifiedTime(kept.toPath(), LinkOption.NOFOLLOW_LINKS))
        val shown = sentName(uploadId)
        db.savepoint("audio_named") {
            if (current.audioPath != kept.path || current.audioMtime != mtime) {
                Versions.updateSong(db, current.id, mapOf("audio_path" to kept.path, "audio_mtime" to mtime))
            }
            if (shown.isNotEmpty()) db.kvSet("$NAME_KEY${current.id}", shown) else db.kvDelete("$NAME_KEY${current.id}")
        }
        unlink(File(root, "$STAGED$uploadId$RECORD")) // the row names the kept file now
        val earlier = keptIn(root, current.audioPath)
        if (earlier != null && earlier != kept && !namedByAnother(db, earlier, current.id)) unlink(earlier)
        return kept
    }

    /** The name a staged upload was sent under, from its record ([displayName]'s); "" when it can't be read. */
    private fun sentName(uploadId: String): String {
        val record = try {
            PyJson.loads(File(root, "$STAGED$uploadId$RECORD").readBytes())
        } catch (_: IOException) {
            return ""
        } catch (_: IllegalArgumentException) {
            return ""
        }
        val name = (record as? JsonObject)?.get("name") as? JsonPrimitive
        return if (name != null && name.isString) displayName(name.content) else ""
    }

    // --- the folder -------------------------------------------------------------------------------------------------

    /** The folder, made if it isn't there, 0700; [NOT_A_STORE] (500) when its place holds a link or anything else. */
    private fun store(): File {
        stateDir.mkdirs()
        root.mkdir()
        if (!isStore(root)) throw AudioError(WORDS.getValue("not_a_store").replace("{path}", root.path),
                                             STATUSES.getValue("not_a_store"))
        privateMode(root.toPath(), "rwx------")
        return root
    }

    private fun stagedIds(): Set<String> {
        val names = root.list()?.toList() ?: return emptySet()
        val marked = names.mapNotNull { MARKER.matchEntire(it)?.groups?.get("id")?.value }.toSet()
        return names.mapNotNull { PIECE.matchEntire(it)?.groups?.get("id")?.value }.toSet() - marked
    }

    private fun pieces(uploadId: String): List<File> =
        (FORMATS.values + RECORD).map { File(root, "$STAGED$uploadId$it") }

    private fun pieceThere(uploadId: String): Boolean = pieces(uploadId).any { lexists(it) }

    private fun dropPieces(uploadId: String): Boolean = pieces(uploadId).map { unlink(it) }.any { it }

    private fun touched(uploadId: String): Double =
        pieces(uploadId).mapNotNull { attributes(it)?.lastModifiedTime()?.let(::seconds) }.maxOrNull() ?: 0.0

    private fun markerFile(uploadId: String) = File(root, "$STAGED$uploadId$MARKER_END")

    private fun markers(): List<String> =
        root.list().orEmpty().mapNotNull { MARKER.matchEntire(it)?.groups?.get("id")?.value }.sorted()

    private fun liveKept(): Set<String> =
        markers().mapNotNull { readMarker(it) }.filter { !it.done }.map { it.file.name }.toSet()

    private fun readMarker(uploadId: String): Marked? {
        val read = markerOf(readSmall(markerFile(uploadId)) ?: return null) ?: return null
        val done = !lexists(File(root, "$STAGED$uploadId$RECORD"))
        return Marked(uploadId, File(root, read.first), read.second, read.third, done)
    }

    /** The marker written whole: a temporary name, then a rename over any before it, before the data's move. */
    private fun writeMarker(uploadId: String, kept: File, songId: Long) {
        val part = File(root, "$PART_START${token()}$PART_END")
        try {
            if (!createPrivate(part)) throw FileAlreadyExistsException(part.path)
            FileChannel.open(part.toPath(), StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS).use { out ->
                out.write(ByteBuffer.wrap(markerText(kept.name, songId, clock()).toByteArray(Charsets.UTF_8)))
                out.force(true)
            }
            Files.move(part.toPath(), markerFile(uploadId).toPath(), StandardCopyOption.REPLACE_EXISTING,
                       StandardCopyOption.ATOMIC_MOVE)
        } catch (e: Throwable) {
            unlink(part)
            throw e
        }
    }

    private fun checkId(uploadId: String) {
        if (!ID.matches(uploadId)) throw refusal("which")
    }

    private fun notInBook(song: SongRow) =
        AudioError(WORDS.getValue("not_in_book").replace("{song}", song.display), STATUSES.getValue("not_in_book"))

    /** A record's fields, read as audio_store._read_record checks them. */
    internal class Record(val name: String, val size: Long?, val sha256: String, val format: String,
                          val duration: Double, val tags: Map<String, String?>, val at: Double)

    companion object {
        private val RULES: JsonObject by lazy {
            Json.parseToJsonElement(Database.resource("caracole/library/audio_store.json")).jsonObject
        }
        private fun rule(name: String) = RULES.getValue(name)
        private fun text(name: String) = rule(name).jsonPrimitive.content
        private fun texts(name: String) = rule(name).jsonArray.map { it.jsonPrimitive.content }
        private val PATTERNS by lazy {
            rule("patterns").jsonObject.mapValues { PyRegex.compile(it.value.jsonPrimitive.content) }
        }
        private val NAMES by lazy { rule("names").jsonObject.mapValues { it.value.jsonPrimitive.content } }

        /** audio_store.FOLDER: the store's folder in the state directory. */
        val FOLDER: String by lazy { text("folder") }

        /** audio_store.NAME_KEY: kv of the name a song's given file was given under. */
        val NAME_KEY: String by lazy { text("name_key") }
        val AUDIO_MAX: Long by lazy { rule("audio_max").jsonPrimitive.long }
        val MAX_SECONDS: Double by lazy { rule("max_seconds").jsonPrimitive.content.toDouble() }
        val ROOM: Long by lazy { rule("room").jsonPrimitive.long }
        val EXPIRES: Double by lazy { rule("expires").jsonPrimitive.content.toDouble() }
        val MARKED: Double by lazy { rule("marked").jsonPrimitive.content.toDouble() }
        val HEAD: Int by lazy { rule("head").jsonPrimitive.int }
        private val RECORD_MAX: Int by lazy { rule("record_max").jsonPrimitive.int }
        private val DISPLAY_MOST: Int by lazy { rule("display_most").jsonPrimitive.int }

        /** audio_store.FORMATS: each format caracole keeps, its extension, in order. */
        val FORMATS: Map<String, String> by lazy {
            rule("formats").jsonObject.entries.associateTo(LinkedHashMap()) { it.key to it.value.jsonPrimitive.content }
        }
        private val MP4_BRANDS: Set<String> by lazy { texts("mp4_brands").toSet() }
        private val TAGS: List<String> by lazy { rule("tags").jsonArray.map { it.jsonPrimitive.content } }
        private val RECORD_FIELDS: List<String> by lazy { texts("record_fields") }
        private val MARKER_FIELDS: List<String> by lazy { texts("marker_fields") }

        /** Every refusal's words, by their name in audio_store.json (`not_audio`, `too_big`…), and their statuses. */
        val WORDS: Map<String, String> by lazy { rule("words").jsonObject.mapValues { it.value.jsonPrimitive.content } }
        val STATUSES: Map<String, Int> by lazy { rule("statuses").jsonObject.mapValues { it.value.jsonPrimitive.int } }

        /** removal.py's words of a removal that deletes the file the owner gave: describe's line, brief's part. */
        val REMOVAL_GOES: String by lazy { rule("removal").jsonObject.getValue("goes").jsonPrimitive.content }
        val REMOVAL_BRIEF: String by lazy { rule("removal").jsonObject.getValue("brief").jsonPrimitive.content }

        val ID: Regex by lazy { PATTERNS.getValue("id") }
        val PIECE: Regex by lazy { PATTERNS.getValue("piece") }
        val STAGED_AUDIO: Regex by lazy { PATTERNS.getValue("staged_audio") }
        val MARKER: Regex by lazy { PATTERNS.getValue("marker") }
        val KEPT: Regex by lazy { PATTERNS.getValue("kept") }
        val PART: Regex by lazy { PATTERNS.getValue("part") }
        private val SHA256: Regex by lazy { PATTERNS.getValue("sha256") }
        private val SPLIT: Regex by lazy { PATTERNS.getValue("display_split") }

        private val STAGED: String by lazy { NAMES.getValue("staged") }
        private val RECORD: String by lazy { NAMES.getValue("record") }
        private val MARKER_END: String by lazy { NAMES.getValue("marker") }
        private val PART_START: String by lazy { NAMES.getValue("part") }
        private val PART_END: String by lazy { NAMES.getValue("part_end") }

        private const val CHUNK = 1 shl 16

        /** How often (in bytes spooled) [stage] checks the room as an upload comes. */
        private const val ROOM_EVERY = 1L shl 20

        private val LOCK = ReentrantLock()
        private val random = SecureRandom()

        private fun refusal(name: String) = AudioError(WORDS.getValue(name), STATUSES.getValue(name))

        /** time.time(): seconds since the epoch, a float. */
        fun now(): Double = java.time.Instant.now().let { it.epochSecond + it.nano * 1e-9 }

        /** os.lstat's st_mtime, as CPython makes the float of it: seconds plus nanoseconds times 1e-9. */
        fun seconds(time: FileTime): Double = time.toInstant().let { it.epochSecond + it.nano * 1e-9 }

        /** A kept file's name, as keep names it: `<song id>-<sha256 16 hex><ext>`. */
        fun keptName(songId: Long, sha256: String, format: String): String =
            "$songId-${sha256.take(16)}${FORMATS.getValue(format)}"

        /** secrets.token_hex(8). */
        private fun token(): String = JsonText.hex(ByteArray(8).also(random::nextBytes))

        /**
         * audio_store.sniff: the format the first bytes of a file say it is (a key of [FORMATS]), or null: an ID3
         * tag or an MPEG audio frame's header, MP3; `ftyp` with an MP4 audio brand as its major or a compatible one,
         * M4A; `fLaC`, FLAC; `RIFF…WAVE`, WAV; `OggS`, Ogg; `FORM…AIFF` or `AIFC`, AIFF.
         */
        fun sniff(head: ByteArray): String? = when {
            at(head, 0, "ID3") || mpegFrame(head) -> "MP3"
            at(head, 4, "ftyp") && mp4Audio(head) -> "M4A"
            at(head, 0, "fLaC") -> "FLAC"
            at(head, 0, "RIFF") && at(head, 8, "WAVE") -> "WAV"
            at(head, 0, "OggS") -> "Ogg"
            at(head, 0, "FORM") && (at(head, 8, "AIFF") || at(head, 8, "AIFC")) -> "AIFF"
            else -> null
        }

        /** audio_store._mpeg_frame: whether [head] begins with an MPEG audio frame's header that exists. */
        fun mpegFrame(head: ByteArray): Boolean {
            if (head.size < 3) return false
            val (b0, b1, b2) = Triple(head[0].toInt() and 0xFF, head[1].toInt() and 0xFF, head[2].toInt() and 0xFF)
            if (b0 != 0xFF || b1 and 0xE0 != 0xE0) return false
            val version = (b1 shr 3) and 3
            val layer = (b1 shr 1) and 3
            return version != 1 && layer != 0 && b2 shr 4 != 15 && (b2 shr 2) and 3 != 3
        }

        /** audio_store._mp4_audio: whether an MP4 file's `ftyp` names an audio brand, its major or a compatible one. */
        fun mp4Audio(head: ByteArray): Boolean {
            var size = 0L
            for (k in 0 until minOf(4, head.size)) size = (size shl 8) or (head[k].toLong() and 0xFF)
            val brands = mutableListOf(latin1(head, 8, 12))
            var at = 16L
            val stop = minOf(size, head.size.toLong()) - 3
            while (at < stop) {
                brands += latin1(head, at.toInt(), at.toInt() + 4)
                at += 4
            }
            return brands.any { it in MP4_BRANDS }
        }

        private fun latin1(head: ByteArray, from: Int, to: Int): String {
            val out = StringBuilder()
            for (k in from until minOf(to, head.size)) out.append((head[k].toInt() and 0xFF).toChar())
            return out.toString()
        }

        /** Whether [head][from:from + len(ascii)] is [ascii]'s bytes. */
        private fun at(head: ByteArray, from: Int, ascii: String): Boolean =
            head.size >= from + ascii.length && ascii.indices.all { head[from + it].toInt() and 0xFF == ascii[it].code }

        /** audio_store._display_name: the name an upload was sent under as a name to show: its last part, control
         * characters (Cc) out, stripped, [DISPLAY_MOST] code points at most; never a path. */
        fun displayName(name: String): String {
            val last = SPLIT.split(name).last()
            val out = StringBuilder()
            var k = 0
            while (k < last.length) {
                val cp = last.codePointAt(k)
                if (PyUnicode.category(cp) != "Cc") out.appendCodePoint(cp)
                k += Character.charCount(cp)
            }
            return Py.slice(Py.strip(out.toString()), 0, DISPLAY_MOST)
        }

        /** music._first: the first of [values] whose stripped text isn't empty, stripped; null for none. */
        private fun first(values: List<String>): String? = values.firstNotNullOfOrNull { Py.strip(it).ifEmpty { null } }

        /** A staged upload's record's text, `json.dumps(record)`: its members in Staged's order, ASCII-escaped. */
        fun recordText(name: String, size: Long, sha256: String, format: String, durationS: Double,
                       tags: Map<String, String?>, at: Double): String = written(RECORD_FIELDS, mapOf(
            "name" to JsonPrimitive(name), "size" to JsonPrimitive(size), "sha256" to JsonPrimitive(sha256),
            "format" to JsonPrimitive(format), "duration" to PyJson.float(durationS),
            "tags" to JsonObject(TAGS.associateWithTo(LinkedHashMap()) { tags[it]?.let(::JsonPrimitive) ?: JsonNull }),
            "at" to PyJson.float(at),
        ))

        /** A marker's text, as _write_marker writes it. */
        fun markerText(kept: String, songId: Long, at: Double): String = written(MARKER_FIELDS, mapOf(
            "kept" to JsonPrimitive(kept), "song" to JsonPrimitive(songId), "at" to PyJson.float(at),
        ))

        /** json.dumps of [values] in the data's member order [fields] (each a value here, every value a field). */
        private fun written(fields: List<String>, values: Map<String, JsonElement>): String {
            check(fields.toSet() == values.keys) { "the data's members $fields aren't ${values.keys}" }
            return PyJson.dumps(JsonObject(fields.associateWithTo(LinkedHashMap()) { values.getValue(it) }),
                                indent = null, ensureAscii = true)
        }

        /** audio_store._read_record of a record's bytes: its fields, or null when they aren't a record's. */
        internal fun recordOf(bytes: ByteArray): Record? {
            if (bytes.size > RECORD_MAX) return null
            val read = try {
                PyJson.loads(bytes)
            } catch (_: IllegalArgumentException) {
                return null
            } as? JsonObject ?: return null
            val name = string(read["name"])
            val sha = string(read["sha256"])
            val format = string(read["format"])
            val tags = read["tags"] as? JsonObject
            val duration = number(read["duration"])
            val at = number(read["at"])
            val size = read["size"]
            if (name == null || size == null || !isInt(size) || sha == null || !SHA256.matches(sha) ||
                format == null || format !in FORMATS || duration == null || at == null || tags == null ||
                tags.keys != TAGS.toSet() || tags.values.any { it !is JsonNull && string(it) == null }) return null
            return Record(name, (size as JsonPrimitive).content.toLongOrNull(), sha, format, duration,
                          TAGS.associateWith { string(tags[it]) }, at)
        }

        /** audio_store._read_marker of a marker's bytes: its kept file's name, its song and when; null for none. */
        internal fun markerOf(bytes: ByteArray): Triple<String, Long, Double>? {
            val read = try {
                PyJson.loads(bytes)
            } catch (_: IllegalArgumentException) {
                return null
            } as? JsonObject ?: return null
            val kept = string(read["kept"]) ?: return null
            val song = read["song"]?.takeIf { isInt(it) }?.jsonPrimitive?.content?.toLongOrNull() ?: return null
            val at = number(read["at"]) ?: return null
            return if (KEPT.matches(kept)) Triple(kept, song, at) else null
        }

        private fun string(e: JsonElement?): String? = (e as? JsonPrimitive)?.takeIf { it.isString }?.content

        /** Python's `type(x) is int` of a value json.loads gave: an integer's literal (never a bool). */
        private fun isInt(e: JsonElement): Boolean {
            val p = e as? JsonPrimitive ?: return false
            if (p is JsonNull || p.isString) return false
            val digits = p.content.removePrefix("-")
            return digits.isNotEmpty() && digits.all { it in '0'..'9' }
        }

        /** `type(x) in (int, float)` of a value json.loads gave, as Python's float of it; null for any other. */
        private fun number(e: JsonElement?): Double? {
            val p = e as? JsonPrimitive ?: return null
            if (p is JsonNull || p.isString || p.content == "true" || p.content == "false") return null
            return p.content.toDoubleOrNull()
        }

        /**
         * audio_store.given_file: whether [audioPath] names a file the owner gave a song, with no store at hand
         * (songs._merge's): a regular file by a kept file's name in a folder named as the store is.
         */
        fun givenFile(audioPath: String?): Boolean {
            if (audioPath.isNullOrEmpty()) return false
            val file = File(audioPath)
            return KEPT.matches(file.name) && file.parentFile?.name == FOLDER && regular(file)
        }

        /** audio_store.kept_in: the kept file [audioPath] names in the folder [store], as [store] spells it: a regular
         * file of that folder by a kept file's name, however the path spells the folder; null for any other. */
        fun keptIn(store: File, audioPath: String?): File? {
            if (audioPath.isNullOrEmpty()) return null
            val file = File(audioPath)
            if (!KEPT.matches(file.name) || !isStore(store) || !regular(file)) return null
            val same = try {
                Files.isSameFile((file.parentFile ?: File(".")).toPath(), store.toPath())
            } catch (_: IOException) {
                false
            }
            return if (same) File(store, file.name) else null
        }

        /** audio_store.named_by_another: whether a song other than [songId]'s row names the kept file [file] (by its
         * name, however a row spells the folder). */
        fun namedByAnother(db: Db, file: File, songId: Long): Boolean {
            val tail = "/" + file.name
            return db.one("SELECT 1 FROM songs WHERE id != ? AND (audio_path = ? OR substr(audio_path, -?) = ?)"
                          + " LIMIT 1",
                          songId, file.path, tail.length, tail) { true } ?: false
        }

        private fun attributes(file: File): BasicFileAttributes? = try {
            Files.readAttributes(file.toPath(), BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
        } catch (_: IOException) {
            null
        }

        private fun isStore(dir: File) = attributes(dir)?.isDirectory == true
        private fun regular(file: File) = attributes(file)?.isRegularFile == true
        private fun lexists(file: File) = attributes(file) != null

        /** os.unlink: [file] deleted (a link itself, never what it points at); whether it was there. A folder is
         * none to delete. */
        private fun unlink(file: File): Boolean {
            val attrs = attributes(file) ?: return false
            if (attrs.isDirectory) return false
            return try {
                Files.delete(file.toPath())
                true
            } catch (_: NoSuchFileException) {
                false
            }
        }

        /** The first [HEAD] bytes of [file], read through no link. */
        private fun headOf(file: File): ByteArray =
            FileChannel.open(file.toPath(), StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS).use { channel ->
                val buffer = ByteBuffer.allocate(HEAD)
                while (buffer.hasRemaining() && channel.read(buffer) >= 0) Unit
                buffer.array().copyOf(buffer.position())
            }

        /** The SHA-256 of [file]'s bytes, read a chunk at a time through no link. */
        private fun hashOf(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            FileChannel.open(file.toPath(), StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS).use { channel ->
                val buffer = ByteBuffer.allocate(1 shl 20)
                while (channel.read(buffer) >= 0) {
                    buffer.flip()
                    digest.update(buffer)
                    buffer.clear()
                }
            }
            return JsonText.hex(digest.digest())
        }

        /** A small JSON file of the folder's bytes, read through no link; null when it is gone, no regular file, or
         * past [RECORD_MAX]. */
        private fun readSmall(file: File): ByteArray? {
            if (!regular(file)) return null
            return try {
                FileChannel.open(file.toPath(), StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS).use { channel ->
                    val buffer = ByteBuffer.allocate(RECORD_MAX + 1)
                    while (buffer.hasRemaining() && channel.read(buffer) >= 0) Unit
                    buffer.array().copyOf(buffer.position())
                }
            } catch (_: IOException) {
                null
            }
        }

        private fun readRecord(file: File): Record? = readSmall(file)?.let(::recordOf)

        /** os.open(O_CREAT | O_EXCL | O_NOFOLLOW, 0600): [file] made new and private; false when its place is taken. */
        private fun createPrivate(file: File): Boolean = try {
            try {
                val mode = PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------"))
                Files.createFile(file.toPath(), mode)
            } catch (_: UnsupportedOperationException) {
                Files.createFile(file.toPath())
                privateMode(file.toPath(), "rw-------")
            }
            true
        } catch (_: FileAlreadyExistsException) {
            false
        }

        private fun privateMode(path: Path, mode: String) {
            try {
                Files.setPosixFilePermissions(path, PosixFilePermissions.fromString(mode))
            } catch (_: UnsupportedOperationException) {
                val file = path.toFile()
                file.setReadable(false, false); file.setReadable(true, true)
                file.setWritable(false, false); file.setWritable(true, true)
                if (mode[2] == 'x') { file.setExecutable(false, false); file.setExecutable(true, true) }
            }
        }

        /** audio_store._sync: the folder's entries synced to the disk. */
        private fun syncFolder(dir: File) {
            FileChannel.open(dir.toPath(), StandardOpenOption.READ).use { it.force(true) }
        }
    }
}
