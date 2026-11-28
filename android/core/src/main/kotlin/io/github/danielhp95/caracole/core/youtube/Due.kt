package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lyrics.internal.PyValues
import io.github.danielhp95.caracole.core.todo.Todo
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.time.Instant

/**
 * youtube_fetch.phone_due: the songs a phone takes the audio of from YouTube by itself (its automatic pass, the
 * phone-youtube design's §5.3), held to Python's by vectors/youtube/due.jsonl (YouTubeReplay).
 *
 * `songs_for_youtube`'s songs (`_due`: wanted and settled on the sites, todo.songs_to_buy's rule, [Todo.songsToBuy];
 * not ignored; `[youtube]` not "none"; a video pasted that isn't the one found unusable, else no search of it that
 * found nothing in the last `fetch.recheck_after_days`), less those with audio of their own (`audio_path`: an upload,
 * YouTube's audio kept, a purchase) and those with any sheet kept, human or auto, whoever made it. Nor one whose
 * video's download the phone couldn't hear within `recheck_after_days` ([UNHEARD_PREFIX]), until another video is
 * given. Of `_due`'s other branches none can reach the phone's list: a song with YouTube's audio kept has an
 * `audio_path`, and R3's `left_elsewhere` weighs only a song that keeps an auto sheet.
 *
 * On a [paired] phone only the songs it noted (kv `youtube-wanted:<id>`, a lookup that ended "Not on the sites"): the
 * rest are the computer's nightly work. Order: the noted first, then the rest, newest first in each (Songs.list's);
 * those whose last try failed (their record's `error`) after the others, the noted first among them.
 */
object Due {
    const val WANTED_PREFIX = "youtube-wanted:"

    /** youtube_fetch.UNHEARD_PREFIX: kv `youtube-unheard:<id>`, the video whose download the phone couldn't hear
     * (`video`, `at`, `error`), written by YouTubeSheetRunner's chords stage, gone once its sheet is kept. */
    const val UNHEARD_PREFIX = "youtube-unheard:"

    private val recheckAfterUs: Long
        get() = (YouTubeData.read().json.getValue("fetch") as JsonObject).getValue("recheck_after_days").jsonPrimitive
            .long * 86_400_000_000L

    fun songs(db: Db, overrides: Overrides, now: Instant, paired: Boolean): List<SongRow> {
        val songs = Songs.list(db)
        val buy = Todo.songsToBuy(db, songs, overrides, now).mapTo(HashSet()) { it.id }
        val since = Stamps.micros(now) - recheckAfterUs
        val due = ArrayList<Triple<Boolean, Boolean, SongRow>>()
        for (song in songs) {
            if (song.status == "ignored" || song.key in overrides.ignore) continue
            if (song.key in overrides.youtube && overrides.youtube[song.key] == null) continue  // "none"
            if (!song.audioPath.isNullOrEmpty() || song.id !in buy) continue
            val record = Records.load(db, song.id)
            val pasted = overrides.youtube[song.key]
            if (!pasted.isNullOrEmpty()) {
                if (record.unusable == pasted) continue
            } else if (Stamps.parse(record.missingAt)?.let { it > since } == true) {
                continue
            }
            if (kept(db, song.id, Versions.SHEET_FILE_NAMES)) continue
            if (unheard(db, song, record, pasted, since)) continue
            val noted = db.kvGet(WANTED_PREFIX + song.id) != null
            if (paired && !noted) continue
            due += Triple(!record.error.isNullOrEmpty(), !noted, song)  // Python's truth
        }
        return due.sortedWith(compareBy<Triple<Boolean, Boolean, SongRow>> { it.first }.thenBy { it.second })
            .map { it.third }
    }

    /** youtube_fetch._unheard: the note names the video the song would take now (its `[youtube]` video, else its
     * record's pick) and is younger than `recheck_after_days`. */
    private fun unheard(db: Db, song: SongRow, record: Record, pasted: String?, since: Long): Boolean {
        val note = db.kvGet(UNHEARD_PREFIX + song.id)?.let { PyJson.loads(it) } as? JsonObject ?: return false
        fun text(name: String): String? = PyValues.string(note[name])?.takeIf { it.isNotEmpty() }
        val video = text("video") ?: return false
        val taking = pasted?.takeIf { it.isNotEmpty() } ?: record.video?.id
        return video == taking && Stamps.parse(text("at"))?.let { it > since } == true
    }

    private fun kept(db: Db, songId: Long, names: List<String>): Boolean = names.any { name ->
        db.one("SELECT 1 FROM files WHERE song_id = ? AND name = ? LIMIT 1", songId, name) { true } != null
    }
}
