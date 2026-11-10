package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.KeptFile
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.viewer.pages.SheetPage
import io.github.danielhp95.caracole.viewer.sheet.ChordPro
import io.github.danielhp95.caracole.viewer.sheet.MusicKeys
import io.github.danielhp95.caracole.viewer.sheet.SheetView
import io.github.danielhp95.caracole.viewer.sheet.Sheets
import io.github.danielhp95.caracole.viewer.sheet.SongKey
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.version.Version
import io.github.danielhp95.caracole.viewer.version.Versions
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.attribute.BasicFileAttributes
import io.github.danielhp95.caracole.core.library.Versions as Rows

/** render.py's RenderError of an export on the phone: the song keeps no sheet, or one the viewer's code can't read. */
class ExportError(message: String) : Exception(message)

/**
 * The sheet a song's exports are made from (render.py's `ExportSheet`, `export_sheet`): the human one, else the auto
 * one ([Exports.viewer]), read once for what a request asks of it: its ChordPro text as its .cho is written, its key
 * (keys.sheet_keys, [found]), and the key of its shapes and its capo as its viewer reads them. Its methods raise
 * [ExportError] for a sheet the viewer's code can't read (a bug). vectors/web/export.jsonl's `render.ExportSheet`
 * records hold each answer to Python's (ExportReplay).
 */
class ExportSheet(val song: SongRow, val text: String, val found: SongKey?, val shapes: Key?, val capo: Int?) {
    /** own: the song's own version on this sheet (render.own_version), where its viewer starts. */
    fun own(overrides: Overrides): Version = Versions.ownVersion(overrides, song, text, found?.key, found?.source)

    /** label: the name of the version [v] of this sheet ("G Dorian, capo 0"); in Traditional characters, for a sheet
     * whose words are Chinese, it says so ("G Dorian, capo 0, Traditional"). */
    fun label(v: Version, traditional: Boolean = false): String {
        val named = read { Versions.label(v, shapes, capo) }
        return if (traditional && chinese()) "$named, ${Exports.TRADITIONAL}" else named
    }

    /** chinese: whether this sheet's words are Chinese (page.written_script), so an export of it is in the characters
     * its viewer shows them in. */
    fun chinese(): Boolean = read { SheetPage.writtenScript(text) != null }

    /** query: the version [v] as an export's address, `trad=1` in it for one in Traditional characters of a sheet
     * whose words are Chinese. */
    fun query(v: Version, traditional: Boolean = false): String = Exports.query(v, traditional && chinese())

    /** entry: the `[version]` Make this my version writes for [v] of this sheet: [v] kept by its key
     * (Versions.entry), else, for a sheet with no key, a move from it as an address that names its `t`. */
    fun entry(v: Version): String = read { Versions.entry(v, text, shapes, capo) } ?: Exports.query(v)

    /** kept: what Make this my version leaves in the song's `[version]` for [v] ([entry]), or null where [v] plays this
     * sheet where the song plays without one (its `[transpose]`, else as written): the entry goes. */
    fun kept(v: Version, overrides: Overrides): String? {
        val entry = entry(v)
        return if (entry == entry(Version(t = overrides.transpose[song.key] ?: 0))) null else entry
    }

    private fun <T> read(read: () -> T): T = try {
        read()
    } catch (e: Exception) {
        throw ExportError("cannot read the sheet: ${e.javaClass.simpleName}: ${e.message}")
    } catch (e: StackOverflowError) {  // Python's RecursionError, which its `except Exception` holds too
        throw ExportError("cannot read the sheet: RecursionError: ${e.message}")
    }
}

/**
 * render.py's export half on the phone, which prints the viewer itself and makes no PDF: the version an address
 * holds ([version], `export_version`), as an export's address ([query], `export_query`), whether it asks for
 * Traditional characters ([traditional]), the viewer the song's exports are made from ([viewer], `export_viewer`) and
 * the sheet they are made from ([sheet], `export_sheet` over `_export_source`: `_human_sheet`, `_auto_sheet` and
 * `_sheet_cho`), each as Python's, held by vectors/web/export.jsonl (ExportReplay).
 */
object Exports {
    /** songs.HUMAN_SHEET and AUTO_SHEET: the kept sheets; and render.HUMAN_OUTPUTS[2] and AUTO_OUTPUTS[2], their
     * viewers. */
    const val HUMAN_SHEET = "sheet.txt"
    const val AUTO_SHEET = "sheet (auto).txt"
    const val HUMAN_VIEWER = "sheet.html"
    const val AUTO_VIEWER = "sheet (auto).html"

    /** keys.SHEET_DOC: the human sheet's markup, beside it. */
    const val SHEET_DOC = "sheet.json"

    /** render.TRADITIONAL: what an export's label says of one in Traditional characters. */
    const val TRADITIONAL = "Traditional"

    /** autochords.merge.AUTO_MARKER: an auto sheet's first line. */
    private const val AUTO_MARKER = "auto-generated, unverified"

    /** render._VERSION_NAMES: what of a viewer's address names where the song is played. */
    private val VERSION_NAMES = setOf("t", "mode", "capo", "alt", "at")

    /** youtube_urls.VIDEO_ID. */
    private val VIDEO_ID: Regex by lazy { PyRegex.compile("[A-Za-z0-9_-]{11}") }

    /**
     * export_version: the version an address [query] holds (Versions.fromQuery), as the viewer reads its own: one that
     * names none of the version (its `t`, `mode`, `capo`, `alt` or `at`) is the song's own, [own], and one that names no
     * `t` is at the own version's. Its instrument is the one `inst` names; with none named, the own version's where the
     * address names none of the version, else the guitar.
     */
    fun version(query: String, own: Version): Version {
        val names = names(query)
        val version = Versions.fromQuery(query)
        if (names.none { it in VERSION_NAMES }) {
            if ("inst" !in names) return own
            return own.copy(inst = version.inst, at = if (version.inst != own.inst) emptyMap() else own.at)
        }
        return if ("t" in names) version else version.copy(t = own.t)
    }

    /** export_query: the version as an address that always says its `t`; with [traditional], `trad=1` last. */
    fun query(v: Version, traditional: Boolean = false): String {
        val rest = Versions.query(v).split('&').filter { it.isNotEmpty() && !it.startsWith("t=") }
        return (listOf("t=${v.t}") + rest + (if (traditional) listOf("trad=1") else emptyList())).joinToString("&")
    }

    /** export_traditional: whether a viewer's address shows its Chinese in Traditional characters, `trad=1` (the
     * first `trad`, as URLSearchParams.get reads it). */
    fun traditional(query: String): Boolean = PyUrl.parseQs(stripped(query), keepBlank = true)["trad"]?.first() == "1"

    /** export_viewer: the viewer of the sheet the song's exports are made from: the human sheet's, else the auto
     * sheet's; null when it keeps no sheet. */
    fun viewer(db: Db, songId: Long): String? {
        val names = Kept.keptFiles(db, songId).map { it.name }.toSet()
        return when {
            HUMAN_SHEET in names -> HUMAN_VIEWER
            AUTO_SHEET in names -> AUTO_VIEWER
            else -> null
        }
    }

    /** export_sheet: the sheet the song's exports are made from, as its viewer reads it. [ExportError] when the song
     * keeps no sheet, or keeps one the viewer's code can't read. */
    fun sheet(db: Db, libraryDir: File, song: SongRow): ExportSheet {
        val files = Kept.keptFiles(db, song.id).associateBy { it.name }
        val human = files[HUMAN_SHEET]
        val auto = files[AUTO_SHEET]
        val source = when {
            human != null -> humanSheet(db, libraryDir, human)
            auto != null -> autoSheet(db, libraryDir, auto)
            else -> throw ExportError("${song.display} keeps no sheet to export")
        }
        val (humanKey, autoKey) = MusicKeys.sheetKeys(db, libraryDir, song.id)
        val found = if (source.auto) autoKey else humanKey
        val text = cho(song, source)
        val (shapes, capo) = try {
            SheetView.viewerKey(text, found?.key, found?.source) to Sheets.parse(text).capo
        } catch (e: Exception) {
            throw ExportError("cannot read the sheet: ${e.javaClass.simpleName}: ${e.message}")
        } catch (e: StackOverflowError) {
            throw ExportError("cannot read the sheet: RecursionError: ${e.message}")
        }
        return ExportSheet(song, text, found, shapes, capo)
    }

    // --- render._Sheet and its readers ---------------------------------------------------------------------------

    /** render._Sheet: what a song's ChordPro is made from, an auto sheet's credit too. */
    private class Source(val markup: String, val key: String? = null, val capo: Int? = null, val auto: Boolean = false,
                         val credit: String? = null)

    /** _human_sheet over _ug_sheet: the markup in the sheet.json beside the kept sheet, the key UG gives its version
     * (`tonality_name`, stripped), and the capo in its `meta`. */
    private fun humanSheet(db: Db, libraryDir: File, kept: KeptFile): Source {
        val doc = File(File(libraryDir, kept.path).parentFile, SHEET_DOC)
        val raw = raw(db, kept.versionId)
        val text = PyText.utf8(regular(doc)) ?: throw ExportError("cannot read $doc: not UTF-8")
        val data = try {
            PyJson.loads(text)
        } catch (e: Exception) {  // json's DecodeError, and its RecursionError past PyJson's depth
            throw ExportError("cannot read $doc: ${e.message}")
        }
        val content = ((data as? JsonObject)?.get("content") as? JsonPrimitive)?.takeIf { it.isString }?.content
        if (content == null || Py.strip(content).isEmpty()) throw ExportError("$doc holds no sheet content")
        val key = (raw["tonality_name"] as? JsonPrimitive)?.takeIf { it.isString }?.content?.let(Py::strip)
            ?.takeIf { it.isNotEmpty() }
        return Source(ChordPro.decodeTwice(content), key = key, capo = MusicKeys.sheetCapo((data as JsonObject)["meta"]))
    }

    /** _auto_sheet: an auto sheet without its two header lines, nor the line after them that says where its audio
     * came from, which is its credit, made again from the YouTube video its version names (merge.youtube_credit). */
    private fun autoSheet(db: Db, libraryDir: File, kept: KeptFile): Source {
        val file = File(libraryDir, kept.path)
        var lines = PyStr.splitlines(PyText.utf8(regular(file)) ?: throw ExportError("cannot read $file: not UTF-8"))
        var credit: String? = null
        if (lines.isNotEmpty() && Py.strip(lines[0]) == AUTO_MARKER) {
            lines = lines.drop(2)  // the marker, then "Artist - Title"
            if (lines.isNotEmpty() && Py.strip(lines[0]).isNotEmpty()) {
                credit = Py.strip(lines[0])
                lines = lines.drop(1)
            }
        }
        val video = (raw(db, kept.versionId)["youtube"] as? JsonObject)
        val id = (video?.get("id") as? JsonPrimitive)?.takeIf { it.isString }?.content
        if (video != null && id != null && PyRe.fullmatch(VIDEO_ID, id) != null && credit != null) {
            credit = youtubeCredit(oneLine(video["title"]), oneLine(video["channel"]), id)
        }
        return Source(lines.joinToString("\n"), auto = true, credit = credit)
    }

    /** autochords.merge.youtube_credit. */
    private fun youtubeCredit(title: String, channel: String, videoId: String): String {
        val named = Py.split(title.ifEmpty { videoId }).joinToString(" ")
        val ch = Py.split(channel).joinToString(" ")
        return if (ch.isNotEmpty()) "Audio from YouTube: $named ($ch)" else "Audio from YouTube: $named"
    }

    private fun oneLine(value: Any?): String =
        (value as? JsonPrimitive)?.takeIf { it.isString }?.let { Py.split(it.content).joinToString(" ") } ?: ""

    /** _sheet_cho: the ChordPro text of one of the song's sheets, as its .cho is written: an auto sheet's credit its
     * first line. */
    private fun cho(song: SongRow, sheet: Source): String {
        val markup = if (!sheet.credit.isNullOrEmpty()) "${sheet.credit}\n${sheet.markup}" else sheet.markup
        return ChordPro.chordProText(markup, Normalize.cleanTitle(song.title), song.artist, sheet.key, sheet.capo,
                                     auto = sheet.auto)
    }

    /** versions.get_version(...).raw. */
    private fun raw(db: Db, versionId: Long): JsonObject =
        Rows.get(db, versionId)?.raw ?: throw ExportError("no version with id $versionId")

    /** render._read_text's read_regular: a library file's bytes, never through a link in its place. */
    private fun regular(file: File): ByteArray {
        val path = file.toPath()
        try {
            val attrs = Files.readAttributes(path, BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
            if (!attrs.isRegularFile) throw ExportError("cannot read $file: not a regular file")
            return Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS).use { it.readBytes() }
        } catch (e: IOException) {
            throw ExportError("cannot read $file: ${e.message}")
        }
    }

    /** The names an address's query or fragment holds, as the viewer's URLSearchParams reads them. */
    private fun names(query: String): Set<String> = PyUrl.parseQs(stripped(query), keepBlank = true).keys

    private fun stripped(q: String): String = if (q.startsWith("#") || q.startsWith("?")) q.substring(1) else q
}
