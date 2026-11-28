package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.Lookup
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.SiteStages
import io.github.danielhp95.caracole.core.lyrics.lyricsFromJson
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.caracoleResource
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.page.LibraryPage
import io.github.danielhp95.caracole.viewer.autochords.AudioUnreadable
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import io.github.danielhp95.caracole.viewer.autochords.ChordsUnavailable
import io.github.danielhp95.caracole.viewer.autochords.Heard
import io.github.danielhp95.caracole.viewer.autochords.Maker
import io.github.danielhp95.caracole.viewer.autochords.Relay
import io.github.danielhp95.caracole.viewer.autochords.SheetHalf
import io.github.danielhp95.caracole.viewer.render.InfoJson
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.CancellationException

/**
 * `caracole audio --progress --upload=ID --song="ARTIST - TITLE"` on the phone (commands/audio.py, audio_sheet.py):
 * one song's auto sheet from an audio file the owner gave, made now, a job of the queue's worker, its stages
 * audio_sheet.py's ([STAGES]: song, audio, lyrics, vocals, words, chords, pdf, pages), each said as it starts and
 * ends, so that its line, steps and outcome are the computer's for the same request (Status, Outcomes' AUDIO_STEPS).
 *
 * Before any stage, as the command does before it reads anything: a phone with no way to hear ([chords] null: the
 * release, or no `:ml` wired) or whose chord models aren't downloaded ([ready] not null) refuses in the command's
 * words ("caracole makes no sheet from an audio file here: …", exit 1); a name that isn't "Artist - Title" exits 2;
 * the upload is read as the command reads it ([AudioStore.staged]'s record, or the kept file its marker names, the
 * same job again past its audio stage): an id that isn't one exits 2, an upload gone 1. Then:
 *
 * - `song`: found by its identity key, or added ([io.github.danielhp95.caracole.core.library.LibraryStore.add], the
 *   file's album and length), get.py's [LookupWords.ADDED]; refused when it is ignored or has a human sheet (an upload
 *   always wins: no audio of its own refuses it), in one write;
 * - `audio`: the staged upload moved into place ([AudioStore.keep]) as the song's audio, "kept as its audio: MP3,
 *   3:18", the file given before named as what it replaces; the same job again goes on by the upload's marker, as
 *   audio_sheet.py's: done whole, "has this file's audio already"; cut off after the move, [AudioStore.adopt]; gone,
 *   refused in the store's words. In one write; a refusal of the store's fails the stage (exit 1), the stages after it
 *   going on as they can;
 * - `lyrics`: the lookup's lyrics stage ([Lookup.lyrics]: LRCLIB, Megalobiz, AZLyrics through its envelope, at the
 *   lookup pace and in get.py's words, where the computer's job asks at the bulk pace in youtube_sheet.py's), asked
 *   with the audio's length (the song's line's, else the file's), in one write;
 * - `vocals` and `words`: skipped, as the phone hears no words: where every lyrics site missed, "not transcribed here:
 *   the phone hears no words" (transcript.PHONE), else the offer's words of the song's lyrics ("not transcribed: its
 *   lyrics are found"); the words "no vocals";
 * - `chords`: the lookups queued meanwhile go first, then the song read again and still this job's ([stillOurs]);
 *   a sheet already made of this audio is up to date, or laid out again over its words (Relay.onto) where they
 *   changed; else [ChordModels.hear], holding no write while the models run, its steps said as the stage's running
 *   words and [JobContext.yieldToQueued] every second of it (a lookup of the song's own waits for the job: the
 *   queue's rule); then the song read again, still this job's and its audio still the file kept, and in one write
 *   the sheet laid out ([SheetHalf.make]) and kept with its version ([keep], run.py's `_keep`: who made it, [Maker],
 *   the phone with this side's kv `sync:id`, the models' [names], [ChordModels.runtime], the file's name and its
 *   hash), its end youtube_sheet.py's `holds`;
 * - `pdf` and `pages`: the song's pages ([PhoneParts.pages], PhoneRender, its re-lay first), get.py's words for a
 *   caracole that makes no PDF ([LookupWords.NO_PDFS] while there is none, [LookupWords.PAGES_MADE]) and
 *   [LookupWords.LIBRARY_PAGE].
 *
 * Failures, told apart as run.py tells them: audio the phone can't decode ([AudioUnreadable]) fails the chords "audio
 * the phone can't read: …"; the models' setup ([ChordsUnavailable]: missing, their process stopped, too hot, the
 * battery low) fails it in its words; a bug laying out the sheet fails it "a bug in caracole: …"; none records
 * anything against the song, so Try again tries them all again. A refusal (ignored, a human sheet, the song gone or
 * its audio replaced meanwhile) fails the song stage and skips the stages left. The command's last line is the
 * computer's ("No sheet made: …." with exit 1, else "Done in N s: …") and its exit status is the computer's: 0 once
 * the sheet is made, or for a site's wait; 1 for a refusal, a failure or a bug.
 */
class AudioRunner(
    val parts: PhoneParts,
    private val chords: ChordModels?,
    private val store: AudioStore,
    private val problem: () -> String? = { problemOf(chords, null) },
    private val names: () -> Map<String, String> = { emptyMap() },
    private val readOverrides: (Db) -> Overrides = Overrides::read,
    private val stages: SiteStages = SiteStages.ALL,
    private val hold: (() -> Heard) -> Heard = { it() },
) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        val line = LookupJobs.line(args, setOf("--upload", "--song"))
        for (name in line.options.keys) {
            if (name !in KNOWN) throw CommandExit(2, "No such option: $name")
        }
        if (line.words.isNotEmpty()) throw CommandExit(2, ON_THE_PHONE)
        val upload = line.options["--upload"] ?: throw CommandExit(2, ON_THE_PHONE)
        val display = line.options["--song"] ?: throw CommandExit(2, ON_THE_PHONE)
        try {
            OverrideUrls.overrideKey(display)
        } catch (e: OverridesError) {
            throw CommandExit(2, e.message.orEmpty())
        }
        val problem = if (chords == null) LibraryPage.AUDIO_PROBLEM else problem()
        if (problem != null) throw CommandExit(1, Words.text("no_chords").replace("{problem}", problem))
        val given = try {
            given(upload)
        } catch (e: AudioStore.AudioError) {
            throw CommandExit(if (e.status == 400) 2 else 1, e.message.orEmpty())
        } catch (e: IOException) {  // commands/audio.py's OSError reading the file: exit 1, "can't read …"
            throw CommandExit(1, "can't read ${Words.text("the_upload")}: ${e.message ?: e.javaClass.simpleName}")
        }
        val artist = Py.strip(display.substringBefore(" - "))
        val title = Py.strip(display.substringAfter(" - ", ""))
        Job(parts, store, chords!!, context, upload, artist, title, given, names, readOverrides, stages, hold,
            this.problem).run()
    }

    /** What the command reads of the upload before any stage (commands/audio.py `_given_already`, then `staged`): the
     * kept file its marker names, for the same job again past its audio stage; else its staged record. */
    private fun given(upload: String): Given {
        val mark = if (store.gone(upload)) store.marked(upload) else null
        if (mark != null) return Given(null, store.formatAndLength(mark.file).second)
        val staged = store.staged(upload)
        return Given(staged.tags["album"], staged.durationS)
    }

    private class Given(val album: String?, val duration: Double)

    /** One run of the job: its stages, as audio_sheet.py's `_AudioSheet` (StagedSheet's, with the audio stage the
     * upload's keep). */
    private class Job(
        parts: PhoneParts, val store: AudioStore, chords: ChordModels, context: JobContext, val upload: String,
        artist: String, title: String, val given: Given, names: () -> Map<String, String>,
        readOverrides: (Db) -> Overrides, stages: SiteStages, hold: (() -> Heard) -> Heard, problem: () -> String?,
    ) : StagedSheet(parts, chords, context, artist, title, names, readOverrides, stages, hold, problem) {
        override val stageNames: List<String> get() = STAGES.map { it.first }
        override val album: String? get() = given.album
        override val duration: Double? get() = given.duration

        override fun maker(db: Db, s: SongRow, audio: File): Maker = fileMaker(store, chords, names, db, s, audio)

        /** audio_sheet.py `audio`. */
        override fun audio(): Pair<String, String> = parts.database.writeBlocking { db ->
            val current = again(db)
            val before = store.uploaded(current)
            val replaced = if (before != null) Words.text("given_before") else null
            val mark = if (store.gone(upload)) store.marked(upload) else null
            if (mark != null && mark.done && before == mark.file) {
                kept = mark.file
                keptLength = given.duration
                return@writeBlocking "done" to Words.text("same_file")
            }
            val file: File
            val found: Pair<String, Double>
            try {
                file = if (mark != null && !mark.done) store.adopt(db, current, upload)
                       else store.keep(db, current, store.staged(upload))
                // The kept file read again, as audio_sheet.py's `audio_store.examine(kept)`: should that fail, the stage
                // fails with the audio kept, and Try again goes on by the same-file path (the marker, done).
                found = store.formatAndLength(file)
            } catch (e: AudioStore.AudioError) {
                val said = e.message.orEmpty().trimEnd('.')
                val first = if (said.isEmpty()) 0 else said.offsetByCodePoints(0, 1)  // said[:1], a code point
                return@writeBlocking fail(io.github.danielhp95.caracole.core.py.PyUnicode.lower(said.substring(0, first)) +
                                              said.substring(first))
            } catch (e: IOException) {
                return@writeBlocking fail(Words.text("cant_keep").replace("{what}", Words.text("the_upload"))
                                              .replace("{why}", e.message ?: e.javaClass.simpleName))
            }
            again(db)
            kept = file
            keptLength = found.second
            if (file == before) return@writeBlocking "done" to Words.text("same_file")
            val said = Words.text("kept_as").replace("{format}", found.first)
                .replace("{length}", JobCommands.formatDuration(PyFormat.roundHalfEven(found.second * 1000)))
            "done" to said + (replaced?.let { Words.text("replaces").replace("{replaced}", it) } ?: "")
        }
    }

    /** audio_sheet.py's, transcript.py's, youtube_sheet.py's, staged.py's and commands/audio.py's words and run.py's
     * STEPS, from data/caracole/library/audio_sheet.json (tests/test_conformance_audio_sheet.py writes it from the
     * modules). */
    internal object Words {
        private val data: JsonObject by lazy { Json.parseToJsonElement(caracoleResource(DATA)).jsonObject }
        private val words: JsonObject by lazy { data.getValue("words").jsonObject }

        val stages: List<Pair<String, String>> by lazy {
            data.getValue("stages").jsonArray.map { it.jsonArray[0].jsonPrimitive.content to it.jsonArray[1].jsonPrimitive.content }
        }
        val steps: List<String> by lazy { data.getValue("steps").jsonArray.map { it.jsonPrimitive.content } }
        val sitesAnswered: Set<String> by lazy {
            data.getValue("sites_answered").jsonArray.map { it.jsonPrimitive.content }.toSet()
        }
        val holds: Map<String, String> by lazy {
            data.getValue("holds").jsonObject.mapValues { it.value.jsonPrimitive.content }
        }

        fun text(name: String): String = words.getValue(name).jsonPrimitive.content
    }

    companion object {
        /**
         * run.py's `_generate` past the models and `_keep`: the sheet laid out from what was [heard], over the song's
         * lyrics now, kept under the song's one auto version, the song found, its info.json, then its
         * `autochords_mtime` last; the chords stage's end, and info.json's failure in [INFO_FAILED]'s words (the
         * sheet kept all the same). The audio job's and a lyrics pick's (LyricsPickJob) alike, every time [stamp],
         * the job's own (its start's, as `autochords_pending(now=…)` is given the job's). Its [maker] the phone with the
         * file the owner gave; a YouTube sheet's (StagedSheet's keep) its own, with the sheet's credit line ([source])
         * and the video ([video]) and the version's address ([url]).
         */
        internal fun keepAutoSheet(parts: PhoneParts, store: AudioStore, chords: ChordModels,
                                   names: () -> Map<String, String>, db: Db, s: SongRow, heard: Heard,
                                   audio: File, stamp: String): Pair<Pair<String, String>, String?> =
            keepAutoSheet(parts, db, s, heard, stamp, fileMaker(store, chords, names, db, s, audio),
                          "file://" + audio.absolutePath)

        /** The maker of a sheet made here from an audio file the owner gave ([audio], the song's in [store]): this
         * phone, its sync id, the models' names and runtime, the file's given name and its SHA-256's 16 digits. */
        internal fun fileMaker(store: AudioStore, chords: ChordModels, names: () -> Map<String, String>, db: Db,
                               s: SongRow, audio: File): Maker =
            Maker(MADE_ON, db.kvGet(SYNC_ID)?.ifEmpty { null }, names(), chords.runtime, store.givenName(db, s),
                  sha16(audio))

        internal fun keepAutoSheet(parts: PhoneParts, db: Db, s: SongRow, heard: Heard, stamp: String, maker: Maker,
                                   url: String, source: String? = null,
                                   video: JsonObject? = null): Pair<Pair<String, String>, String?> {
            val lyrics = lyricsFromJson(s.lyricsJson)
            val made = SheetHalf.make(s, lyrics, heard, source = source)
            val raw = SheetHalf.raw(s, lyrics, made, video = video, maker = maker)
            db.savepoint("audio_sheet") {
                val current = autoVersionOf(db, s.id)
                val versionId = Versions.upsert(db, PROVIDER, current ?: s.id.toString(), s.id, "sheet", "auto", 0.0, 0,
                                                1, null, url, raw, stamp)
                Kept.keepFile(db, parts.store, s, versionId, Versions.SHEET_FILE_NAMES[1],
                              made.text.toByteArray(Charsets.UTF_8), 1, stamp)
                db.execute("DELETE FROM versions WHERE song_id = ? AND provider = ? AND id != ? AND NOT EXISTS " +
                               "(SELECT 1 FROM files f WHERE f.version_id = versions.id)", s.id, PROVIDER, versionId)
                Versions.refreshStatus(db, s.id, ignored = false, now = stamp)
            }
            val info = try {
                InfoJson.write(db, parts.store.libraryDir, Songs.byId(db, s.id) ?: s)
                null
            } catch (e: Exception) {  // the sheet is kept: said so, and made of this audio (no hearing again)
                if (e is CancellationException) throw e
                e.message ?: e.javaClass.simpleName
            }
            Versions.updateSong(db, s.id, mapOf("autochords_mtime" to s.audioMtime), stamp)
            return ("done" to holds(raw)) to info?.let { INFO_FAILED.replace("{held}", holds(raw)).replace("{why}", it) }
        }

        /** versions.auto_version_of: the tab id of the song's one auto version, the one a kept file names first. */
        private fun autoVersionOf(db: Db, songId: Long): String? =
            db.one("SELECT tab_id FROM versions v WHERE song_id = ? AND provider = ? ORDER BY EXISTS (SELECT 1 FROM " +
                       "files f WHERE f.version_id = v.id) DESC, id LIMIT 1", songId, PROVIDER) { it.text(0) }

        const val COMMAND = "audio"
        const val DATA = "caracole/library/audio_sheet.json"
        private val KNOWN = setOf("--upload", "--song", "--progress")
        private const val SYNC_ID = StagedSheet.SYNC_ID
        private const val PROVIDER = StagedSheet.AUTO_PROVIDER

        /** sheet.Maker's side, an auto sheet's `raw["made_on"]` made here. */
        const val MADE_ON = "phone"

        /** audio_sheet.py's STAGES, its job's (name, label). */
        val STAGES: List<Pair<String, String>> get() = Words.stages

        /** The phone's own words, where the computer's have no case. */
        const val ON_THE_PHONE = "caracole audio on the phone takes --upload=ID and --song=\"ARTIST - TITLE\""
        const val NOT_DOWNLOADED = "the chord models aren't downloaded (Settings › Chords from audio)"
        const val UNREADABLE = "audio the phone can't read: "
        const val AUDIO_CHANGED = "{display}: its audio changed while its chords were worked out"
        const val INFO_FAILED = "the sheet was kept ({held}), but its info.json couldn't be written: {why}"

        /** Why this phone makes no sheet from an audio file now, or null: the one answer for the job and the audio
         * routes (server.audio's `why`). No [chords] (nothing wired): [LibraryPage.AUDIO_PROBLEM]; what keeps the phone
         * itself from hearing chords ([ChordModels.phoneProblem]: its processor, its Android, its memory), before the
         * files, as Settings offers such a phone no download; the models not installed ([modelsReady],
         * ModelsRunner.ready's answer): [NOT_DOWNLOADED], the design's §8.1 words; else the chords' own reason
         * ([ChordModels.ready]). */
        fun problemOf(chords: ChordModels?, modelsReady: String?): String? = when {
            chords == null -> LibraryPage.AUDIO_PROBLEM
            chords.phoneProblem() != null -> chords.phoneProblem()
            modelsReady != null -> NOT_DOWNLOADED
            else -> chords.ready()
        }

        /** audio_sheet.py `_unsheeted`'s refusal: [s] ignored (its row, or [overrides]' `ignore`), or with a human
         * sheet kept, in the audio job's words; null where an auto sheet may be kept over it. The audio job's and the
         * lyrics pick's check before they keep what the models heard. */
        fun notOurs(db: Db, s: SongRow, overrides: Overrides): String? = when {
            s.status == "ignored" || s.key in overrides.ignore -> Words.text("ignored").replace("{display}", s.display)
            Kept.keptFiles(db, s.id).any { it.name == Versions.SHEET_FILE_NAMES[0] } ->
                Words.text("has_sheet").replace("{display}", s.display)
            else -> null
        }

        /** youtube_sheet.holds: what the auto sheet's version (its [raw]) says the sheet holds. */
        fun holds(raw: JsonObject): String {
            fun text(member: String) = (raw[member] as? JsonPrimitive)?.takeIf { it.isString }?.content
            val nothing = raw["heard_nothing"].let { it is JsonPrimitive && !it.isString && it.content == "true" }
            val used = when {
                text("lyrics_source") == SheetHalf.LYRICS_SOURCE -> "transcript"
                nothing && text("lyrics") == "none" -> if (text("not_sung_by") == "you") "said" else "silent"
                else -> (raw["lyrics"] as? JsonPrimitive)?.content ?: "None"  // str(raw.get("lyrics"))
            }
            return Words.holds[used] ?: "chords"
        }

        /** audio.sha16: the first 16 hex digits of the file's SHA-256, read streamed. */
        fun sha16(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(1 shl 16)
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    digest.update(buffer, 0, n)
                }
            }
            val hex = "0123456789abcdef"
            return digest.digest().take(8).joinToString("") { b -> "${hex[(b.toInt() shr 4) and 15]}${hex[b.toInt() and 15]}" }
        }
    }
}
