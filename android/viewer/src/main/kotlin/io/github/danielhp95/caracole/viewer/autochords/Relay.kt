package io.github.danielhp95.caracole.viewer.autochords

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SharedFolder
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lyrics.Lyrics
import io.github.danielhp95.caracole.core.lyrics.lyricsFromJson
import io.github.danielhp95.caracole.viewer.render.InfoJson
import io.github.danielhp95.caracole.viewer.render.RenderNames
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.IOException
import io.github.danielhp95.caracole.core.library.Versions as Rows

/** sheet.Noted: what a caracole notes of the words of the audio a sheet was heard from: the transcript of that audio,
 * and whether nothing sung was heard in it ([silent]), by the owner's word ([said]). */
data class Noted(val transcript: Transcript? = null, val silent: Boolean = false, val said: Boolean = false)

/**
 * An auto sheet laid out again from what was heard when its words alone changed (the design's R2), with no model and
 * no audio: sheet.py's [due] (relay_due), [relay] and the guards of who may ([relaysHere], [madeByAnother],
 * [notedIn]), and sheet_lyrics.py's [onto] (relay_onto_sheets), PhoneRender's first step after PlainLyrics as
 * render_all's. Two caracoles that re-lay the same sheet over the same words write the same sheet and the same raw
 * (vectors/autochords-sheet/sheet.jsonl and relay.jsonl), so a sheet the phone made and the computer re-lays is the one
 * the phone re-lays, and a sync finds nothing between them.
 */
object Relay {
    private const val ID_KEY = "sync:id"

    /** What [onto] did: the songs re-laid, and those whose re-lay failed with why (relay_onto_sheets' `errors`, which
     * it logs: "<song>: <why>", a bug's "<song>: a bug in caracole: <exception>"), which PhoneRender's stats carry. */
    data class Relayed(val songs: List<SongRow>, val failed: Map<Long, String>)

    /** sheet.noted_in: what the sheet was laid out with, as its raw keeps it. */
    fun notedIn(raw: JsonObject): Noted {
        val lrc = SheetHalf.text(raw, "transcript")
        val transcript = if (SheetHalf.text(raw, "lyrics_source") == SheetHalf.LYRICS_SOURCE && lrc != null) {
            Transcript(lrc, SheetHalf.text(raw, "transcript_made_at") ?: "")
        } else null
        val silent = raw["heard_nothing"] == JsonPrimitive(true)
        return Noted(transcript, silent, silent && SheetHalf.text(raw, "not_sung_by") == "you")
    }

    /** sheet.made_by_another: the raw names a maker (`made_by`, a text) that isn't [own] (kv `sync:id`). */
    fun madeByAnother(raw: JsonObject, own: String?): Boolean {
        val by = SheetHalf.text(raw, "made_by") ?: return false
        return by != own
    }

    /** sheet.relays_here: the sheet may be laid out again on this side: made by another caracole ([elsewhere]), or
     * heard from the audio this side holds now (`autochords_mtime` its `audio_mtime`), or this side holds none. */
    fun relaysHere(song: SongRow, elsewhere: Boolean = false): Boolean {
        if (elsewhere || song.audioPath.isNullOrEmpty()) return true
        val heardFrom = song.autochordsMtime ?: return false
        val now = song.audioMtime ?: return false
        return heardFrom == now
    }

    /** sheet.relay_due: why the sheet ([raw], its version's) is to be laid out again from what was heard, its words
     * alone having changed (or their timing: a timed sheet whose `synced_lyrics` isn't the song's syncedKey now), or
     * null. [noted] defaults to [notedIn]. Lyrics stored that can't be read are none. */
    fun due(song: SongRow, raw: JsonObject, noted: Noted? = null): String? {
        val lyrics = try {
            lyricsFromJson(song.lyricsJson)
        } catch (_: IllegalArgumentException) {
            return null
        }
        return due(song, lyrics, raw, noted ?: notedIn(raw))
    }

    private fun due(song: SongRow, stored: Lyrics?, raw: JsonObject, noted: Noted): String? {
        val lyrics = SheetHalf.sung(stored)
        val music = SheetHalf.instrumental(song, stored)
        val used = SheetHalf.text(raw, "lyrics")
        val overTranscript = SheetHalf.text(raw, "lyrics_source") == SheetHalf.LYRICS_SOURCE
        if (used == "none" && lyrics != null) return "lyrics came to a sheet of none"
        if (overTranscript) {
            if (lyrics != null) return "a site's lyrics came to a sheet over a transcript"
            if (music) return "a site says it is instrumental, over a transcript"
            val transcript = noted.transcript
            if (transcript == null || !sameText(raw["transcript_made_at"], transcript.madeAt)) {
                return "its transcript is gone or made again"
            }
        } else if (used == "none" && noted.transcript != null && !music) {
            return "a transcript came to a sheet of none"
        } else if (used == "none" && !SheetHalf.truthy(raw["heard_nothing"]) && !music && noted.silent) {
            return "nothing sung was noted since"
        }
        val words = raw["lyrics_key"]?.takeIf { it !is JsonNull }
        val onWords = words != null && (used == "synced" || used == "plain") && !overTranscript
        val key = SheetHalf.songLyricsKey(stored)
        if (onWords && key != null && !sameText(words, key)) return "its lyrics are other words now"
        if (onWords && lyrics == null) return "its lyrics are gone, or a site says it is instrumental"
        val synced = SheetHalf.syncedKey(stored)
        val timed = raw["synced_lyrics"] // the timed lyrics a timed sheet was laid beside (SheetHalf.raw's syncedKey)
        if (used == "synced" && !overTranscript && words != null && synced != null &&
            timed is JsonPrimitive && timed.isString && timed.content != synced
        ) {
            return "its timed lyrics are others now" // untimed now, or no lyrics_key: as it is
        }
        if (used == "plain" && synced != null && !sameText(raw["synced_lyrics"], synced)) {
            return "timed lyrics came to a plain sheet"
        }
        if (used == "synced" && !sameText(raw["columns"], SheetHalf.COLUMNS) && SheetHalf.widerLines(stored)) {
            return "its chords at their characters' indexes, before they went at display columns"
        }
        return null
    }

    /** Python's `value == text` of a JSON value: a JSON string of that text. */
    private fun sameText(value: JsonElement?, text: String) =
        value is JsonPrimitive && value.isString && value.content == text

    /**
     * sheet.relay: the song's auto sheet laid out again from `raw["heard"]` (Heard.of: an IllegalArgumentException,
     * Python's ValueError, for one that can't be read) over its words now, the source line the video `raw["youtube"]`
     * names, and [noted] (by default [notedIn]); the members of RELAY_KEEPS the raw holds kept as they were. A pure
     * function of its arguments: no clock, no machine, no kv. Lyrics stored that can't be read raise, as Python's.
     */
    fun relay(song: SongRow, raw: JsonObject, noted: Noted? = null): Made {
        val heard = Heard.of(raw["heard"] ?: JsonNull)
        val n = noted ?: notedIn(raw)
        val youtube = raw["youtube"] as? JsonObject
        val id = youtube?.let { SheetHalf.text(it, "id") }
        val source = if (youtube != null && id != null) {
            AutoSheet.youtubeCredit(SheetHalf.text(youtube, "title") ?: "", SheetHalf.text(youtube, "channel") ?: "", id)
        } else null
        val made = SheetHalf.make(song, lyricsFromJson(song.lyricsJson), heard, source, n.transcript, n.silent, n.said)
        val kept = LinkedHashMap<String, JsonElement>()
        for (member in SheetHalf.RELAY_KEEPS) raw[member]?.let { kept[member] = it }
        return made.copy(kept = JsonObject(kept))
    }

    /** sheet_lyrics.made_elsewhere: the sheet was made by another caracole than this one (kv `sync:id`, read alone). */
    fun madeElsewhere(db: Db, raw: JsonObject): Boolean = madeByAnother(raw, db.kvGet(ID_KEY)?.ifEmpty { null })

    /** sheet_lyrics.noted_of: what this caracole notes of the words of the audio the sheet was heard from: its kv's
     * transcript and nothing-sung verdict of the song's audio, where the sheet was heard here from the audio it holds
     * now; else, holding none, or the sheet made by another caracole, what the sheet was laid out with. The phone
     * transcribes nothing, so it notes neither of its own: transcript.py's records read as the computer's are. */
    fun notedOf(db: Db, song: SongRow, raw: JsonObject): Noted {
        if (song.audioPath.isNullOrEmpty() || madeElsewhere(db, raw) || !relaysHere(song)) return notedIn(raw)
        val transcript = transcriptOf(db, song)
        val nothing = db.kvGet("${SheetHalf.HEARD_NOTHING_KV}${song.id}")?.let(PyJson::loads) as? JsonObject
        val silent = transcript == null && nothing != null && ownAudio(song, nothing)
        return Noted(transcript, silent, silent && nothing?.let { SheetHalf.text(it, "by") } == "you")
    }

    /** transcript.transcript_of: the kept transcript (Transcript.from_json's shape), only while its audio is the
     * song's own. */
    private fun transcriptOf(db: Db, song: SongRow): Transcript? {
        val kept = db.kvGet("${SheetHalf.TRANSCRIPT_KV}${song.id}")?.let(PyJson::loads) as? JsonObject ?: return null
        val texts = listOf("lrc", "audio", "model", "language", "device", "made_at").map { SheetHalf.text(kept, it) }
        if (texts.any { it == null }) return null
        val mtime = kept["audio_mtime"]
        if (mtime != null && mtime !is JsonNull && !(mtime is JsonPrimitive && !mtime.isString && !bool(mtime))) return null
        val dropped = kept["words_dropped"]
        if (!(dropped is JsonPrimitive && dropped !is JsonNull && !dropped.isString && !bool(dropped) &&
                dropped.content.none { it == '.' || it == 'e' || it == 'E' || it == 'N' || it == 'I' })) return null
        if (!ownAudio(song, kept)) return null
        return Transcript(texts[0]!!, texts[5]!!)
    }

    private fun bool(p: JsonPrimitive) = p.content == "true" || p.content == "false"

    /** transcript.of_audio, as far as the phone reads it: the record's `audio` and `audio_mtime` the song's (Python's
     * `==`), else its content key (`audio_sha256`) agreeing with the digits a file given the song keeps in its name
     * (AudioStore.givenSha16: no file read). Another file's bytes, which Python hashes, the phone never reads: it keeps
     * no transcript or verdict of its own (it hears no words), and none crosses at a sync, so a record of a purchase
     * moved is the computer's alone to follow. */
    private fun ownAudio(song: SongRow, record: JsonObject): Boolean {
        val audio = record["audio"]
        val mtime = record["audio_mtime"]
        val sameAudio = song.audioPath?.let { sameText(audio, it) } ?: (audio == null || audio is JsonNull)
        val sameMtime = song.audioMtime?.let { mtime != null && PyJson.equal(mtime, PyJson.float(it)) }
            ?: (mtime == null || mtime is JsonNull)
        if (sameAudio && sameMtime) return true
        val sha = (record["audio_sha256"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return false
        if (sha.length !in 16..64 || sha.any { it !in '0'..'9' && it !in 'a'..'f' }) return false
        val given = AudioStore.givenSha16(song.audioPath) ?: return false
        return sha.take(16) == given
    }

    /** sheet_lyrics._relay_candidates: the songs (of [only]) whose kept auto sheet keeps what was heard: one query, no
     * file read. */
    private fun candidates(db: Db, only: Collection<Long>?): List<Long> {
        var where = ""
        val args = mutableListOf<Any?>(RenderNames.AUTO_SHEET)
        if (only != null) {
            val ids = only.toSortedSet().toList()
            if (ids.isEmpty()) return emptyList()
            where = " AND f.song_id IN (${ids.joinToString(", ") { "?" }})"
            args.addAll(ids)
        }
        return db.query(
            "SELECT f.song_id FROM files f JOIN versions v ON v.id = f.version_id WHERE f.name = ?" + where +
                " AND json_valid(v.raw) AND COALESCE(json_type(v.raw, '$.heard'), 'null') != 'null' ORDER BY f.song_id",
            *args.toTypedArray()) { it.long(0)!! }
    }

    /** sheet_lyrics._relay_plan: what the sheet is re-laid with now, or null: none for one that keeps no `heard`, one
     * this side heard from other audio than it holds now (the models' to make again), one not due, or one whose
     * `heard` can't be read (a newer caracole's contract, a damaged record: left as it is). */
    private fun plan(db: Db, song: SongRow, raw: JsonObject): Noted? {
        if (raw["heard"].let { it == null || it is JsonNull } || !relaysHere(song, madeElsewhere(db, raw))) return null
        val noted = notedOf(db, song, raw)
        due(song, raw, noted) ?: return null
        try {
            Heard.of(raw.getValue("heard"))
        } catch (_: IllegalArgumentException) {
            return null
        }
        return noted
    }

    /**
     * sheet_lyrics.relay_onto_sheets: each auto sheet that keeps what was heard laid out again over its song's words
     * where they changed (the guards of [plan]), with no model and no audio ([laidOut], [relay]: a test's failure is
     * put there); the songs re-laid, of [only] when given, not ignored, with no human sheet, and those whose re-lay
     * failed, with why ([Relayed]). The version's raw and the sheet are written in one savepoint, info.json after (its
     * failure the song's, said, the sheet re-laid all the same); one that can't be laid out or written is left as it
     * is, stopping no other, and tried again at the next pass. A second pass writes nothing: a sheet not due is passed
     * over with no file read.
     */
    fun onto(db: Db, libraryDir: File, overrides: Overrides, only: Collection<Long>? = null,
             laidOut: (SongRow, JsonObject, Noted) -> Made = ::relay): Relayed {
        val lib = LibraryStore(libraryDir)
        val done = ArrayList<SongRow>()
        val failed = LinkedHashMap<Long, String>()
        for (id in candidates(db, only)) {
            val song = Songs.byId(db, id) ?: continue
            if (song.status == RenderNames.IGNORED || song.key in overrides.ignore) continue
            val files = Kept.keptFiles(db, id)
            val auto = files.firstOrNull { it.name == RenderNames.AUTO_SHEET } ?: continue
            if (files.any { it.name == RenderNames.HUMAN_SHEET }) continue
            val version = Rows.get(db, auto.versionId) ?: continue
            val noted = plan(db, song, version.raw) ?: continue
            val why = attempt(song) {
                val made = laidOut(song, version.raw, noted)
                val raw = SheetHalf.raw(song, lyricsFromJson(song.lyricsJson), made)
                db.savepoint("relay") {
                    Rows.setRaw(db, version.id, raw)
                    Kept.keepFile(db, lib, song, version.id, RenderNames.AUTO_SHEET, made.text.toByteArray(Charsets.UTF_8),
                                  auto.keptRank, Stamps.now())
                }
            }
            if (why != null) {
                failed[id] = why
                continue
            }
            attempt(song) { InfoJson.write(db, libraryDir, Songs.byId(db, id) ?: song) }?.let { failed[id] = "$it (info.json)" }
            done.add(Songs.byId(db, id) ?: song)
        }
        return Relayed(done, failed)
    }

    /** [block], and null; or why it failed, as PhoneRender words a song's failure: a file that can't be written
     * ("<song>: <why>"), else a bug ("<song>: a bug in caracole: <exception>"). */
    private inline fun attempt(song: SongRow, block: () -> Unit): String? = try {
        block()
        null
    } catch (e: IOException) {
        "${song.display}: ${e.message}"
    } catch (e: SharedFolder) {
        "${song.display}: ${e.message}"
    } catch (e: Exception) {
        "${song.display}: ${RenderNames.BUG}: $e"
    } catch (e: StackOverflowError) {
        "${song.display}: ${RenderNames.BUG}: $e"
    }
}
