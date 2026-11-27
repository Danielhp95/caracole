package io.github.danielhp95.caracole.viewer.autochords

import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.lyrics.Lyrics
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.viewer.ViewerData
import io.github.danielhp95.caracole.viewer.render.PlainLyrics
import io.github.danielhp95.caracole.viewer.sheet.ChordPro
import io.github.danielhp95.caracole.viewer.sheet.MusicKeys
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** transcript.Transcript as a sheet reads it: Whisper's timed lines ([lrc], LRC) and when they were made
 * ([madeAt]); the phone transcribes nothing, so one reaches it only in a synced sheet's raw or a vector. */
data class Transcript(val lrc: String, val madeAt: String)

/** sheet.Maker: who made an auto sheet and from what, as its raw keeps it (`made_on`, `made_by`, `models`, `runtime`,
 * `audio_name`, `audio_sha16`): the side ("computer", "phone"), its caracole's kv `sync:id`, the models' names, what ran
 * them, the audio file's name alone and the first 16 hex digits of its SHA-256. None of it a path. */
data class Maker(val on: String, val by: String?, val models: Map<String, String>, val runtime: String?,
                 val audioName: String?, val audioSha16: String?)

/** sheet.Timed: timed lyrics that fit the audio, and, when LRCLIB timed them for audio of another length, the
 * seconds they were shifted by ([shift], 0.0 for none) and how much longer the audio is ([longer]). */
data class Timed(val text: String, val shift: Double? = null, val longer: Double = 0.0) {
    /** Timed.note: what the sheet says of a shift; null for lyrics that fit as timed. */
    fun note(): String? {
        val shift = shift ?: return null
        if (shift != 0.0) { // Python's truth of a float: NaN is true, -0.0 false
            val later = if (shift > 0) "later" else "earlier"
            return "Lyrics' timing shifted ${PyFormat.fixed(Math.abs(shift), 1)} s $later to fit this audio"
        }
        val than = if (longer > 0) "shorter" else "longer"
        return "Lyrics' timing unshifted: LRCLIB's audio is ${PyFormat.fixed(Math.abs(longer), 1)} s $than"
    }
}

/** sheet.Made: one song's auto sheet ([text]), the lyrics it used ("synced", "plain", "none"), the key heard, the
 * shift of its timed lyrics, the transcript it was made over, nothing sung (by the owner's word: [said]), what it was
 * laid out from ([heard]) and, a re-lay's, the raw's members kept as they were ([kept], `RELAY_KEEPS`). */
data class Made(
    val text: String, val used: String, val key: String?, val shift: Double?, val transcript: Transcript? = null,
    val silent: Boolean = false, val said: Boolean = false, val heard: Heard? = null, val kept: JsonObject? = null,
)

/**
 * autochords/sheet.py on the phone, its sheet half: what words go under the chords heard ([make], make_sheet), the
 * record the sheet's version keeps ([raw], raw_of), and what that record keeps of the song's lyrics ([syncedKey],
 * [songLyricsKey], [widerLines]). A sheet made on either device from the same [Heard], lyrics, names and maker is the
 * same bytes and the same raw, so the song's sync unit is one (vectors/autochords-sheet/sheet.jsonl). Its constants
 * are sheet.py's and transcript.py's (autochords.json's `sheet` and `transcript`).
 *
 * A song's lyrics are given as [Lyrics] (lyrics.song_lyrics of the song, null for none): lyrics stored that can't be
 * read are the caller's, as make_sheet lets their ValueError out ([Relay] reads them as Python's relay_due does).
 */
object SheetHalf {
    private val data by lazy { ViewerData.table("autochords") }
    private val sheet by lazy { data.getValue("sheet").jsonObject }
    private val words by lazy { data.getValue("transcript").jsonObject }

    val MODEL: String by lazy { sheet.getValue("MODEL").jsonPrimitive.content }
    val COLUMNS: String by lazy { sheet.getValue("COLUMNS").jsonPrimitive.content }
    val CONTRACT: Int by lazy { sheet.getValue("CONTRACT").jsonPrimitive.int }
    private val SYNC_TOLERANCE_S by lazy { sheet.getValue("SYNC_TOLERANCE_S").jsonPrimitive.double }
    val MAKER_MEMBERS: List<String> by lazy { sheet.getValue("MAKER_MEMBERS").jsonArray.map { it.jsonPrimitive.content } }
    val RELAY_KEEPS: List<String> by lazy { sheet.getValue("RELAY_KEEPS").jsonArray.map { it.jsonPrimitive.content } }
    val LYRICS_SOURCE: String by lazy { words.getValue("LYRICS_SOURCE").jsonPrimitive.content }
    private val NOTE by lazy { words.getValue("NOTE").jsonPrimitive.content }
    private val SILENT by lazy { words.getValue("SILENT").jsonPrimitive.content }
    private val NOT_SUNG by lazy { words.getValue("NOT_SUNG").jsonPrimitive.content }

    /** sheet.instrumental: a site says the song is instrumental ([lyrics], the song's stored ones). */
    fun instrumental(song: SongRow, lyrics: Lyrics?): Boolean =
        song.lyricsStatus == "instrumental" || (lyrics != null && lyrics.instrumental && !lyrics.hasLyrics)

    /** sheet.sung_lyrics: the song's lyrics, when they have words. */
    fun sung(lyrics: Lyrics?): Lyrics? = lyrics?.takeIf { it.hasLyrics }

    /** sheet.song_lyrics_key: the key of the song's words (PlainLyrics.lyricsKey of their plain text), or null. */
    fun songLyricsKey(lyrics: Lyrics?): String? = sung(lyrics)?.let { PlainLyrics.lyricsKey(it.plain) }

    /** sheet.synced_key: 16 hex digits of the SHA-256 of the song's timed lyrics, or null for none. */
    fun syncedKey(lyrics: Lyrics?): String? = sung(lyrics)?.synced?.takeIf { it.isNotEmpty() }
        ?.let { Canonical.sha256Hex(it.toByteArray(Charsets.UTF_8)).substring(0, 16) }

    /** sheet.wider_lines: a timed line whose display columns aren't its characters' indexes. */
    fun widerLines(lyrics: Lyrics?): Boolean {
        val synced = sung(lyrics)?.synced?.takeIf { it.isNotEmpty() } ?: return false
        return Lrc.parse(synced).any { (_, text) -> ChordPro.displayColumns(text) != (0..Py.len(text)).toList() }
    }

    /** sheet.synced_for: the timed lyrics, if they fit the audio heard: as they are within SYNC_TOLERANCE_S of its
     * length, else shifted as Align.lyricsOffset finds clearly; null when they don't. */
    fun syncedFor(lyrics: Lyrics?, heard: Heard): Timed? {
        val synced = lyrics?.synced?.takeIf { it.isNotEmpty() } ?: return null
        val lyricsS = lyrics.duration ?: return null
        val duration = heard.duration ?: return null
        val longer = duration - lyricsS
        if (Math.abs(longer) <= SYNC_TOLERANCE_S) return Timed(synced)
        val lines = Lrc.parse(synced)
        val found = try {
            Align.lyricsOffset(lines, heard.chords, heard.beats, heard.downbeats, duration, lyricsS)
        } catch (_: Exception) { // a bug there must not pass for a purchase auto-chords can't read: the plain lyrics
            return null
        }
        val offset = found.offset ?: return null
        return Timed(if (offset != 0.0) Align.shiftedLrc(synced, offset) else synced, offset, longer)
    }

    /**
     * sheet.make_sheet: one song's auto sheet from what was [heard]. A site's lyrics whenever the song has any (and its
     * word that it is instrumental wins too), else [transcript] (no shift searched, NOTE after the shift's line), else
     * none; [silent] puts SILENT (NOT_SUNG, the owner's word, [said]) there instead where no site has words, none says
     * it is instrumental and no transcript is used. [source] is the line after the song's name. The key is estimated
     * from the chords as heard, each weighed by how long it sounds, before they are snapped to beats.
     */
    fun make(song: SongRow, lyrics: Lyrics?, heard: Heard, source: String? = null, transcript: Transcript? = null,
             silent: Boolean = false, said: Boolean = false): Made {
        val key = MusicKeys.estimateWeighted(heard.chords.filter { it.label != AutoSheet.NO_CHORD }
                                                 .map { it.label to it.end - it.start })
        val sung = sung(lyrics)
        val music = instrumental(song, lyrics)
        val over = if (sung == null && !music) transcript else null
        val timed = if (over != null) Timed(over.lrc) else syncedFor(sung, heard)
        val synced = timed?.text
        val plain = sung?.plain
        val quiet = silent && sung == null && over == null && !music
        val owners = said && quiet
        val notes = listOf(source, timed?.note(), if (over != null) NOTE else null,
                           if (quiet) (if (owners) NOT_SUNG else SILENT) else null)
        val note = notes.filter { !it.isNullOrEmpty() }.joinToString("\n")
        val text = AutoSheet.build(heard.chords, song.title, song.artist, synced, wordTimed(synced), plain, heard.beats,
                                   heard.downbeats, note.ifEmpty { null })
        val used = if (!synced.isNullOrEmpty()) "synced" else if (!plain.isNullOrEmpty()) "plain" else "none"
        return Made(text, used, key, timed?.shift, over, quiet, owners, heard)
    }

    /** sheet._word_timed: the timed lyrics read with their word stamps, when they time words. */
    private fun wordTimed(synced: String?): List<LrcLine>? {
        val lines = if (!synced.isNullOrEmpty()) Lrc.parseWords(synced) else emptyList()
        return lines.takeIf { l -> l.any { !it.words.isNullOrEmpty() } }
    }

    /**
     * sheet.raw_of: the record the sheet's version keeps, its members in raw_of's order (json.dumps writes them so,
     * and the song's sync unit hashes them): `audio` (the song's [SongRow.audioPath], or the re-laid raw's), `model`,
     * `lyrics`, `columns`, then each that applies: `key`, `lyrics_shift`, `lyrics_source`, `transcript`,
     * `transcript_made_at`, `heard_nothing`, `not_sung_by`, `synced_lyrics`, `lyrics_key`, `youtube` ([video], the
     * video's as_json, or the re-laid raw's), `heard` ([Heard.record]), and who made it: [maker]'s, or a re-lay's
     * kept as they were. [lyrics] are the song's stored ones, as [make] read them.
     */
    fun raw(song: SongRow, lyrics: Lyrics?, made: Made, video: JsonObject? = null, maker: Maker? = null): JsonObject {
        val kept = made.kept ?: JsonObject(emptyMap())
        val raw = LinkedHashMap<String, JsonElement>()
        raw["audio"] = kept["audio"] ?: (song.audioPath?.let(::JsonPrimitive) ?: JsonNull)
        raw["model"] = JsonPrimitive(MODEL)
        raw["lyrics"] = JsonPrimitive(made.used)
        raw["columns"] = JsonPrimitive(COLUMNS)
        made.key?.let { raw["key"] = JsonPrimitive(it) }
        made.shift?.let { raw["lyrics_shift"] = PyJson.float(it) }
        made.transcript?.let {
            raw["lyrics_source"] = JsonPrimitive(LYRICS_SOURCE)
            raw["transcript"] = JsonPrimitive(it.lrc)
            raw["transcript_made_at"] = JsonPrimitive(it.madeAt)
        }
        if (made.silent) raw["heard_nothing"] = JsonPrimitive(true)
        if (made.silent && made.said) raw["not_sung_by"] = JsonPrimitive("you")
        syncedKey(lyrics)?.let { raw["synced_lyrics"] = JsonPrimitive(it) }
        if ((made.used == "synced" || made.used == "plain") && made.transcript == null) {
            songLyricsKey(lyrics)?.let { raw["lyrics_key"] = JsonPrimitive(it) }
        }
        (video ?: kept["youtube"])?.let { raw["youtube"] = it }
        made.heard?.let { raw["heard"] = it.record() }
        if (maker == null) {
            for (member in MAKER_MEMBERS) kept[member]?.let { raw[member] = it }
        } else {
            raw["made_on"] = JsonPrimitive(maker.on)
            maker.by?.let { raw["made_by"] = JsonPrimitive(it) }
            if (maker.models.isNotEmpty()) {
                raw["models"] = JsonObject(maker.models.entries.associateTo(LinkedHashMap()) { (k, v) -> k to JsonPrimitive(v) })
            }
            maker.runtime?.let { raw["runtime"] = JsonPrimitive(it) }
            maker.audioName?.let { raw["audio_name"] = JsonPrimitive(it) }
            maker.audioSha16?.let { raw["audio_sha16"] = JsonPrimitive(it) }
        }
        return JsonObject(raw)
    }

    /** A raw's member as Python's `==` with a text sees it: its content where it is a JSON string, else null. */
    internal fun text(raw: JsonObject, member: String): String? =
        (raw[member] as? JsonPrimitive)?.takeIf { it.isString }?.content

    /** Python's truth of a JSON value (`not raw.get(member)`): null, false, 0, "", [] and {} are false. */
    internal fun truthy(value: JsonElement?): Boolean = when (value) {
        null, JsonNull -> false
        is JsonArray -> value.isNotEmpty()
        is JsonObject -> value.isNotEmpty()
        is JsonPrimitive -> if (value.isString) value.content.isNotEmpty()
                            else value.content != "false" && !PyJson.equal(value, JsonPrimitive(0))
        else -> true
    }
}
