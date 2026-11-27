package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.py.PyText
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.time.Duration
import java.time.Instant

/**
 * The audio the phone takes from YouTube for a song's auto sheet (youtube_fetch.py's `audio_dir`, `_download`'s names
 * and `tidy`, on the phone's terms, the design's §5.4): the folder [folder] under the phone's cache (`cache/youtube/`,
 * the data's `fetch.audio_folder`), a song's file `<song id>-<video id><ext>` ([name]), a download's own folder there
 * until its file is in place (`fetch.part_prefix`, [partPrefix]), the song's `audio_path` and its `youtube:` record's
 * `audio` naming the file while it is needed.
 *
 * It goes ([letGo]: the file deleted, the song unlinked from it, the record's `audio` none) once the song's sheet is
 * kept, at a removal, and [KEPT_FOR] after its download otherwise ([sweep]): the phone keeps no audio it doesn't need.
 * The sweep also takes what a stopped job left (a download's own folder), and any file of the folder no song or record
 * names. Nothing of it is a synced column: `audio_path` never leaves the phone.
 */
object YouTubeAudio {
    /** How long a download is kept once a job stopped before its sheet (the design's §10.4). */
    val KEPT_FOR: Duration = Duration.ofDays(3)

    private val fetch: JsonObject get() = YouTubeData.read().json.getValue("fetch") as JsonObject
    private val partPrefix: String get() = fetch.getValue("part_prefix").jsonPrimitive.content

    /** The folder the phone's YouTube audio is kept in, under the phone's cache [cacheRoot]. */
    fun folder(cacheRoot: File): File = File(cacheRoot, fetch.getValue("audio_folder").jsonPrimitive.content)

    /** A song's file of a video's audio: `<song id>-<video id>` and the download's suffix, lowercased. */
    fun name(songId: Long, videoId: String, suffix: String): String = "$songId-$videoId${PyText.lower(suffix)}"

    /** The prefix of a download's own folder for [songId] (tempfile.mkdtemp's, its random part after it). */
    fun partPrefix(songId: Long): String = "$partPrefix$songId-"

    /** youtube_fetch._own_audio: the song's linked audio is the file YouTube gave it. */
    fun ownAudio(song: SongRow, record: Record): Boolean = !record.audio.isNullOrEmpty() && song.audioPath == record.audio

    /** youtube_fetch.youtube_audio: the video the song's linked audio came from, when it came from YouTube. */
    fun youtubeAudio(db: Db, song: SongRow): Video? {
        val record = Records.load(db, song.id)
        return if (ownAudio(song, record)) record.video else null
    }

    /** [path] when it is a file right inside [folder] (removal.py's `Path(p).parent == folder`), else null: no file
     * anywhere else is ever deleted. */
    fun inFolder(folder: File, path: String?): File? {
        if (path.isNullOrEmpty()) return null
        val file = File(path)
        return file.takeIf { it.parentFile?.absoluteFile == folder.absoluteFile }
    }

    /**
     * The song's YouTube audio let go: its record's file deleted (when it is one of [folder]'s), the song unlinked from
     * it where it was its audio (`audio_path` and `audio_mtime` none, as tidy unlinks one), the record's `audio` none.
     * The file deleted, or null; in the caller's write.
     */
    fun letGo(db: Db, folder: File, song: SongRow, stamp: String): File? {
        val record = Records.load(db, song.id)
        val audio = record.audio ?: return null
        if (ownAudio(song, record)) Versions.updateSong(db, song.id, mapOf("audio_path" to null, "audio_mtime" to null), stamp)
        Records.save(db, song.id, record.copy(audio = null))
        val file = inFolder(folder, audio) ?: return null
        return file.takeIf { delete(it) }
    }

    /**
     * The folder swept, in the caller's write: each download's own folder a stopped job left; each song's file
     * downloaded [KEPT_FOR] or more before [now] (its record's `downloaded_at`, else the file's time), or gone from the
     * folder, let go ([letGo]); then each file no song's `audio_path` or record names. How many files went.
     */
    fun sweep(db: Db, folder: File, now: Instant, stamp: String): Int {
        if (!folder.isDirectory) return 0
        var gone = 0
        for (entry in folder.listFiles().orEmpty()) {
            if (entry.name.startsWith(partPrefix) && entry.isDirectory) entry.deleteRecursively()
        }
        val named = HashSet<String>()
        for (song in Songs.list(db)) {
            song.audioPath?.let { named += File(it).name }
            val record = Records.load(db, song.id)
            val file = inFolder(folder, record.audio) ?: continue
            val at = record.downloadedAt?.let { Stamps.parse(it) }?.let(Stamps::instant)
                ?: if (file.isFile) Instant.ofEpochMilli(file.lastModified()) else null
            if (!file.isFile || at == null || Duration.between(at, now) >= KEPT_FOR) {
                if (letGo(db, folder, song, stamp) != null) gone++
            } else {
                named += file.name
            }
        }
        for (entry in folder.listFiles().orEmpty()) {
            if (entry.name in named || entry.name.startsWith(partPrefix)) continue
            if (Files.isRegularFile(entry.toPath(), LinkOption.NOFOLLOW_LINKS) && delete(entry)) gone++
        }
        return gone
    }

    private fun delete(file: File): Boolean = try {
        Files.deleteIfExists(file.toPath())
    } catch (_: IOException) {
        false
    }
}
