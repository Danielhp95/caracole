package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.CachedAnswers
import io.github.danielhp95.caracole.core.http.HttpxUrl
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.OverrideWriters
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SharedFolder
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.CommandContext
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lyrics.AzLyrics
import io.github.danielhp95.caracole.core.lyrics.Lrclib
import io.github.danielhp95.caracole.core.lyrics.Lyrics
import io.github.danielhp95.caracole.core.lyrics.Megalobiz
import io.github.danielhp95.caracole.core.lyrics.internal.PyValues
import io.github.danielhp95.caracole.core.lyrics.lyricsFromJson
import io.github.danielhp95.caracole.core.py.PyFormat
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import java.io.File
import java.io.IOException
import java.math.BigInteger
import java.time.Instant

/**
 * lyrics_pick.py's song and lyrics stages on the phone (`caracole lyrics --song X --record SITE:ID`), which lane
 * lyrics-search's LyricsRunner runs as a staged job (song, lyrics, chords, pdf, pages: [STAGES]):
 *
 * - [findSong] (`find_song`): the song by its identity key and the row of its kept search ([LyricsSearchCommands]),
 *   refused in lyrics_pick.py's words ([Refused]);
 * - [lyrics] (`lyrics`, `_read`, `_keep`): LRCLIB's record from the search's answers in the phone's HTTP cache, with
 *   no request ([cachedLrclib]), else asked by its id through the command's asking (Megalobiz's `/lrc/{id}`, AZLyrics'
 *   page, one request each), a site off, cooling, out of its asks or blocking a wait and its error a failure, none of
 *   them changing anything; kept: the lyric files first, then `[lyrics]`' record (OverrideWriters.setLyricsRecord),
 *   then in one savepoint the question asked anew, the song's lyrics found and its auto sheet made due where the words
 *   changed and it keeps no `heard` ([modelsRemake]). The phone's info.json is PhoneRender's, at the pdf stage.
 *
 * vectors/lookup/lyrics_pick.jsonl holds it to Python's (tests/test_conformance_lyrics_pick.py).
 */
object LyricsPickCommands {
    val STAGES: List<Pair<String, String>> = listOf(
        "song" to "Find the song", "lyrics" to "Lyrics", "chords" to "Chords from the audio", "pdf" to "PDF",
        "pages" to "The logbook page",
    )
    const val NO_NEW = "no new lyrics"
    const val NOTHING_KEPT = "; nothing kept"
    const val NO_LYRICS_NOW = " has no lyrics now"
    const val KEPT_FAILED_AFTER = "Lyrics kept; the job failed after"
    const val NOTHING_KEPT_LINE = "No lyrics kept"
    const val ELSEWHERE_UNREAD = "its auto sheet was made on your other caracole and can't be laid out again here over " +
        "these lyrics (what was heard there can't be read here): ask for a new sheet here, from an audio file or a video"
    private const val AUTO_SHEET = "sheet (auto).txt"

    /** A refusal of the song stage, in lyrics_pick.py's words (staged.py's `_Stop`). */
    class Refused(message: String) : Exception(message)

    /** What [findSong] found: the song, its kept search and the row picked. */
    class Picked(val song: SongRow, val search: LyricsSearchCommands.Search, val row: LyricsSearchCommands.Row)

    /** What the lyrics stage came to: its end, and whether a local failure (the files, overrides.toml) failed the job. */
    class Ended(val state: String, val detail: String, val failed: Boolean = false)

    /** lyrics_pick._Pick.find_song: the song of [artist] and [title], not ignored, and the row of its last search that
     * names [record] (or its [pick]th row), that search within its week. */
    fun findSong(db: Db, artist: String, title: String, overrides: Overrides, now: Instant, record: String?,
                 pick: Int? = null): Picked {
        val display = "$artist - $title"
        val key = Normalize.identityKey(artist, title)
        val song = Songs.byKey(db, key) ?: throw Refused("$display isn't in the book")
        if (song.status == "ignored" || key in overrides.ignore) throw Refused("${song.display} is ignored (overrides.toml)")
        val search = LyricsSearchCommands.lastSearch(db, song.id, now)
            ?: throw Refused("search ${song.display}'s lyrics first (caracole lyrics --song … --as …)")
        if (!LyricsSearchCommands.pickable(search, now)) throw Refused("its last search is over a week old: search again")
        val row = if (pick != null) {
            if (pick < 1 || pick > search.rows.size) {
                throw Refused("its last search listed ${search.rows.size} records: there is no row $pick")
            }
            search.rows[pick - 1]
        } else {
            LyricsSearchCommands.rowOf(search, record ?: "")
                ?: throw Refused("“$record” isn't among the records its last search listed")
        }
        return Picked(song, search, row)
    }

    /** The song stage's words once found. */
    fun found(picked: Picked): String = "in the book; its last search's ${picked.row.record}"

    /** lyrics_pick._Pick._cached_lrclib: LRCLIB's record of [id] as the search's answers in the HTTP cache hold it (its
     * search, then its get of the name and the audio's length), with no request; null when the cache no longer does. */
    fun cachedLrclib(cacheDir: File, search: LyricsSearchCommands.Search, id: Long): Lyrics? {
        val cache = CachedAnswers(Lrclib.PROVIDER, cacheDir)
        val (artist, title) = search.asked
        val get = Lrclib.getParams(artist, title, album = null, durationS = search.length)
        for ((url, params) in listOf("${Lrclib.API}/search" to search.lrclib, "${Lrclib.API}/get" to get)) {
            val address = if (params.isEmpty()) url else HttpxUrl.withParams(url, params).toString()
            val answer = cache.cached(address) ?: continue
            val found = try {
                answer.json()
            } catch (e: IllegalArgumentException) {
                continue
            }
            for (record in if (found is JsonArray) found else listOf(found)) {
                if (record is JsonObject && PyValues.bigInt(record["id"]) == BigInteger.valueOf(id)) {
                    return Lyrics.fromRecord(record)
                }
            }
        }
        return null
    }

    /**
     * lyrics_pick._Pick.lyrics: the record read and kept (the module's docstring), its end. [audioLength] is the
     * song's (LyricsSearchCommands.audioLength), [lib] the library its lyric files go into.
     */
    fun lyrics(c: CommandContext, config: PhoneConfig, cacheDir: File, lib: LibraryStore, picked: Picked,
               audioLength: Double?): Ended {
        val row = picked.row
        val site = row.record.substringBefore(':')
        val id = row.record.substringAfter(':')
        val (read, stopped) = read(c, config, cacheDir, picked, site, id)
        if (stopped != null) return stopped
        if (read == null || !read.hasLyrics || read.instrumental) {
            return Ended("skipped", "${possessive(LookupWords.name(site))} record $id$NO_LYRICS_NOW$NOTHING_KEPT")
        }
        val db = c.db
        val song = Songs.byId(db, picked.song.id)
            ?: throw Refused("${picked.song.display} left the book while its lyrics were picked")
        val before = readable(song)
        keep(c, lib, song, row.record, read, before)?.let { return it }
        return Ended("done", keptSaid(row, read, before, audioLength))
    }

    private fun read(c: CommandContext, config: PhoneConfig, cacheDir: File, picked: Picked, site: String,
                     id: String): Pair<Lyrics?, Ended?> {
        if (site == Lrclib.PROVIDER) cachedLrclib(cacheDir, picked.search, id.toLong())?.let { return it to null }
        LyricsSearchCommands.notNow(config, c.db, c.now, site)?.let { (_, said) ->
            return null to Ended("skipped", "$said$NOTHING_KEPT")
        }
        val asked = c.asking.ask(site) { client ->
            when (site) {
                Lrclib.PROVIDER -> Lrclib.fetchRecord(client, id.toLong())
                Megalobiz.PROVIDER -> Megalobiz.fetchRecord(client, BigInteger(id))
                else -> AzLyrics.fetchAzLyrics(client, "", "", page = "${AzLyrics.SITE}lyrics/$id.html")
            }
        }
        if (asked !is Asked.Done) {
            val (state, said) = LyricsSearchCommands.stopped(c, config, site, asked, whose = "this pick's", why = true)
            val end = if (state == LyricsSearchCommands.BLOCKED) ", nothing kept" else NOTHING_KEPT
            return null to Ended(if (state == LyricsSearchCommands.FAILED) "failed" else "skipped", "$said$end")
        }
        if (Health.answeredAny(c.db, LyricsSearchCommands.runOf(c), site, c.asking.requests[site] ?: 0)) {
            Health.recordOk(c.db, site, c.now)
        }
        return asked.value to null
    }

    /** lyrics_pick._Pick._keep: the lyric files, then the record, then the database; an end only where it failed. */
    private fun keep(c: CommandContext, lib: LibraryStore, song: SongRow, record: String, lyrics: Lyrics,
                     before: Lyrics?): Ended? {
        val db = c.db
        val folder = lib.folderOf(song)
        try {
            Lrclib.writeLyrics(folder, lyrics)
        } catch (e: IOException) {
            return Ended("failed", "couldn't write its lyrics (${e.message})${putBack(folder, before)}", failed = true)
        } catch (e: SharedFolder) {
            return Ended("failed", "couldn't write its lyrics (${e.message})${putBack(folder, before)}", failed = true)
        }
        OverrideWriters.setLyricsRecord(db, song.display, record)
        val otherWords = before == null || before.plain != lyrics.plain || before.synced != lyrics.synced
        val columns = linkedMapOf<String, Any?>("lyrics_status" to "found", "lyrics_json" to lyrics.toJson(),
                                                "lyrics_at" to Stamps.of(c.now))
        if (otherWords && modelsRemake(db, song)) columns["autochords_mtime"] = null
        db.savepoint("lyrics_pick") {
            LyricsSearchCommands.askAnew(db, song, c.now)
            Versions.updateSong(db, song.id, columns, Stamps.of(c.now))
        }
        return null
    }

    /** lyrics_pick._Pick._put_back: the lyric files as the song's stored lyrics had them. */
    private fun putBack(folder: File, before: Lyrics?): String = try {
        Lrclib.writeLyrics(folder, before ?: Lyrics("", null, false, null, null))
        NOTHING_KEPT
    } catch (e: Exception) {
        "; nothing else kept, but its lyric files may hold the new words (putting them back failed: ${e.message})"
    }

    /** lyrics_pick._models_remake: the song's auto sheet is the models' to make again over other words: one kept that
     * keeps no `heard`. */
    fun modelsRemake(db: Db, song: SongRow): Boolean {
        val auto = Kept.keptFiles(db, song.id).firstOrNull { it.name == AUTO_SHEET } ?: return false
        val raw = Versions.get(db, auto.versionId)?.raw ?: return false
        return raw["heard"].let { it == null || it is JsonNull }
    }

    /** lyrics_pick._readable: the song's stored lyrics, none for lyrics that can't be read. */
    fun readable(song: SongRow): Lyrics? = try {
        lyricsFromJson(song.lyricsJson)
    } catch (e: IllegalArgumentException) {
        null
    }

    /** lyrics_pick._Pick._kept_said. */
    private fun keptSaid(row: LyricsSearchCommands.Row, lyrics: Lyrics, before: Lyrics?, audio: Double?): String {
        val name = LookupWords.name(row.site)
        val length = lyrics.duration?.takeIf { it != 0.0 } ?: row.duration?.takeIf { it != 0.0 }
        val facts = listOfNotNull(row.album.ifEmpty { null }, length?.let(LyricsSearchCommands::clock))
        var said = "${if (!lyrics.synced.isNullOrEmpty()) "timed" else "plain"} lyrics from $name: " +
            "${row.artist.ifEmpty { "(no artist)" }} - ${row.title}" +
            if (facts.isNotEmpty()) " (${facts.joinToString(", ")})" else ""
        if (before != null && before.hasLyrics) {
            said += "; in place of ${possessive(LookupWords.name(before.provider))} " +
                "${if (!before.synced.isNullOrEmpty()) "timed" else "plain"} lyrics"
        }
        val gapOf = lyrics.duration?.takeIf { it != 0.0 } ?: row.duration
        if (audio != null && gapOf != null && Math.abs(audio - gapOf) > LyricsSearchCommands.FAR) {
            val gap = PyFormat.roundHalfEven(Math.abs(audio - gapOf))
            said += "; the audio is $gap s ${if (audio > gapOf) "longer" else "shorter"}"
        }
        return said
    }

    private fun possessive(name: String): String = if (name.endsWith("s")) "$name'" else "$name's"
}
