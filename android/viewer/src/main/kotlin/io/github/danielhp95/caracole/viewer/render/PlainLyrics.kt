package io.github.danielhp95.caracole.viewer.render

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SharedFolder
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lyrics.lyricsFromJson
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.viewer.render.internal.LibraryReads
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.IOException
import java.nio.file.NoSuchFileException
import io.github.danielhp95.caracole.core.library.Versions as Rows

/**
 * autochords/sheet_lyrics.py on the phone: lyrics that came after an auto sheet was made, put on it with no model
 * (merge.with_plain_lyrics), the first thing a render does, so every page of the song has them: the sheet kept again
 * (`sheet (auto).txt`), its version's `raw` saying `"lyrics": "plain"`, and the song's info.json written.
 */
object PlainLyrics {
    /** sheet_lyrics._wanting: each song, of [only] when given, whose auto sheet has no lyrics (its version's `raw`
     * `lyrics` "none") and who has some, with those lyrics: never an ignored one, nor one with a human sheet. */
    fun wanting(db: Db, overrides: Overrides, only: Collection<Long>? = null): List<Pair<SongRow, String>> {
        val ids = db.query("SELECT f.song_id FROM files f JOIN versions v ON v.id = f.version_id " +
                               "WHERE f.name = ? AND json_valid(v.raw) AND json_extract(v.raw, '$.lyrics') = 'none'",
                           RenderNames.AUTO_SHEET) { it.long(0)!! }
        val found = ArrayList<Pair<SongRow, String>>()
        for (id in ids) {
            if (only != null && id !in only) continue
            val song = Songs.byId(db, id) ?: throw NoSuchElementException("no song with id $id")
            if (song.status == RenderNames.IGNORED || song.key in overrides.ignore) continue
            val lyrics = try {
                lyricsFromJson(song.lyricsJson)
            } catch (_: IllegalArgumentException) {
                continue
            } ?: continue
            if (!lyrics.hasLyrics || lyrics.instrumental) continue
            if (Kept.keptFiles(db, id).none { it.name == RenderNames.HUMAN_SHEET }) found.add(song to lyrics.plain)
        }
        return found
    }

    /** lyrics_onto_sheets: each song's lyrics on its auto sheet ([wanting]); the songs that took them. A sheet that
     * can't be read or written stays as it is, and stops no other. */
    fun onto(db: Db, libraryDir: File, overrides: Overrides, only: Collection<Long>? = null): List<SongRow> {
        val lib = LibraryStore(libraryDir)
        val done = ArrayList<SongRow>()
        for ((song, plain) in wanting(db, overrides, only)) {
            val auto = Kept.keptFiles(db, song.id).first { it.name == RenderNames.AUTO_SHEET }
            try {
                val text = PyText.utf8(LibraryReads.regular(File(libraryDir, auto.path))) ?: continue // ValueError
                Kept.keepFile(db, lib, song, auto.versionId, RenderNames.AUTO_SHEET,
                              withPlainLyrics(text, plain).toByteArray(Charsets.UTF_8), auto.keptRank, Stamps.now())
            } catch (_: NoSuchFileException) {
                continue // gone from its folder: auto-chords makes it again
            } catch (_: IOException) {
                continue
            } catch (_: SharedFolder) {
                continue
            }
            val version = Rows.get(db, auto.versionId) ?: throw NoSuchElementException("no version ${auto.versionId}")
            Rows.setRaw(db, version.id, JsonObject(LinkedHashMap(version.raw).apply { put("lyrics", JsonPrimitive("plain")) }))
            InfoJson.write(db, libraryDir, Songs.byId(db, song.id) ?: song)
            done.add(song)
        }
        return done
    }

    /** merge.with_plain_lyrics: a sheet build_sheet made with no lyrics, as it would have made it with [plain]: its
     * chart, then them. */
    fun withPlainLyrics(sheet: String, plain: String): String =
        (listOf(sheet.trimEnd('\n'), "") + lyricsBlock(plain)).joinToString("\n").trimEnd('\n') + "\n"

    /** merge._lyrics_block: plain lyrics as a sheet's last section, or no line for none. */
    private fun lyricsBlock(plain: String?): List<String> {
        val lyrics = PyStr.splitlines((plain ?: "").trim('\n')).map(::rstrip)
        return if (lyrics.any { it.isNotEmpty() }) listOf("[Lyrics]") + lyrics else emptyList()
    }

    /** str.rstrip(): Python's whitespace off the end. */
    private fun rstrip(s: String): String {
        var end = s.length
        while (end > 0 && PyUnicode.isSpace(s.codePointBefore(end))) end -= Character.charCount(s.codePointBefore(end))
        return s.substring(0, end)
    }
}
