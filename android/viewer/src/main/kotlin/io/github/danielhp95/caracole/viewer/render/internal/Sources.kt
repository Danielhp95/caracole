package io.github.danielhp95.caracole.viewer.render.internal

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.KeptFile
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.viewer.render.RenderNames
import io.github.danielhp95.caracole.viewer.sheet.ChordPro
import io.github.danielhp95.caracole.viewer.sheet.MusicKeys
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.IOException
import io.github.danielhp95.caracole.core.library.Versions as Rows

/** render._Video: the YouTube video an auto sheet's audio came from, as autochords/run.py keeps it in the version's
 * `raw`. */
internal data class Video(val id: String, val title: String, val channel: String) {
    val url: String get() = OverrideUrls.watchUrl(id)
}

/** render._Sheet: what a song's ChordPro file is made from: an auto sheet's [credit] too, the line on where its audio
 * came from, and the [video] it came from, if any. */
internal data class SheetSource(val markup: String, val key: String? = null, val capo: Int? = null,
                                val auto: Boolean = false, val credit: String? = null, val video: Video? = null)

/** Where a song's sheets come from: render.py's `_human_sheet`, `_ug_sheet`, `_auto_sheet`, `_video_of` and
 * `_sheet_cho`, over the phone's library. */
internal object Sources {
    private val VIDEO_ID: Regex = Regex("[A-Za-z0-9_-]{11}")

    /** _human_sheet: the sheet the fetch kept, the markup in the sheet.json beside it, the key UG gives the version. */
    fun human(db: Db, libraryDir: File, kept: KeptFile): SheetSource =
        ug(File(libraryDir, kept.path).resolveSibling(RenderNames.SHEET_DOC), raw(db, kept.versionId))

    /** _ug_sheet: a sheet from the JSON the fetch keeps beside its text (sheet.json, a version's `version-<tab>.json`):
     * its markup and its capo, and the key UG gives the version ([raw]). RenderError for a file that can't be read,
     * or holds no sheet. */
    fun ug(file: File, raw: JsonObject): SheetSource {
        val doc = try {
            LibraryReads.json(file)
        } catch (e: IOException) {
            throw RenderError("cannot read ${file.path}: ${e.message}")
        } catch (e: IllegalArgumentException) {
            throw RenderError("cannot read ${file.path}: ${e.message}")
        }
        val content = ((doc as? JsonObject)?.get("content") as? JsonPrimitive)?.takeIf { it.isString }?.content
        if (content == null || Py.strip(content).isEmpty()) throw RenderError("${file.path} holds no sheet content")
        return SheetSource(ChordPro.decodeTwice(content), key = keyOf(raw), capo = MusicKeys.sheetCapo((doc as JsonObject)["meta"]))
    }

    /** _key: the key UG gives a version (`tonality_name`, often empty). */
    private fun keyOf(raw: JsonObject): String? {
        val value = (raw["tonality_name"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return null
        return Py.strip(value).ifEmpty { null }
    }

    /** _auto_sheet: an auto-chords sheet without its two header lines, nor the line after them that says where its
     * audio came from (its [SheetSource.credit]); its video's credit as autochords writes one now. */
    fun auto(db: Db, libraryDir: File, kept: KeptFile): SheetSource {
        var lines = PyStr.splitlines(LibraryReads.text(File(libraryDir, kept.path)))
        var credit: String? = null
        if (lines.isNotEmpty() && Py.strip(lines[0]) == RenderNames.AUTO_MARKER) {
            lines = lines.drop(2)
            if (lines.isNotEmpty() && Py.strip(lines[0]).isNotEmpty()) {
                credit = Py.strip(lines[0])
                lines = lines.drop(1)
            }
        }
        val video = videoOf(raw(db, kept.versionId))
        if (video != null && credit != null) credit = youtubeCredit(video.title, video.channel, video.id)
        return SheetSource(lines.joinToString("\n"), auto = true, credit = credit, video = video)
    }

    /** _video_of: the YouTube video an auto sheet's version names (`raw`'s `youtube`), by its id; null for none. */
    fun videoOf(raw: JsonObject): Video? {
        val found = raw["youtube"] as? JsonObject ?: return null
        val id = (found["id"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return null
        if (PyRe.fullmatch(VIDEO_ID, id) == null) return null
        return Video(id, oneLine(found["title"]), oneLine(found["channel"]))
    }

    private fun oneLine(value: JsonElement?): String =
        (value as? JsonPrimitive)?.takeIf { it.isString }?.let { Py.split(it.content).joinToString(" ") } ?: ""

    /** autochords.merge.youtube_credit: the line after an auto sheet's name of one made from a YouTube video. */
    fun youtubeCredit(title: String, channel: String, videoId: String): String {
        val named = Py.split(title.ifEmpty { videoId }).joinToString(" ")
        val ch = Py.split(channel).joinToString(" ")
        return if (ch.isNotEmpty()) "Audio from YouTube: $named ($ch)" else "Audio from YouTube: $named"
    }

    /** _sheet_cho: the ChordPro text of one of the song's sheets, as its .cho is written: an auto sheet's credit its
     * first line; without [credit], none (its viewer's, which draws its video instead). */
    fun cho(song: SongRow, sheet: SheetSource, credit: Boolean = true): String {
        val markup = if (credit && !sheet.credit.isNullOrEmpty()) "${sheet.credit}\n${sheet.markup}" else sheet.markup
        return ChordPro.chordProText(markup, Normalize.cleanTitle(song.title), song.artist, sheet.key, sheet.capo,
                                     auto = sheet.auto)
    }

    /** versions.get_version(...).raw. */
    fun raw(db: Db, versionId: Long): JsonObject =
        (Rows.get(db, versionId) ?: throw NoSuchElementException("no version with id $versionId")).raw
}
