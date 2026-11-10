package io.github.danielhp95.caracole.viewer.pages

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.web.DownloadNames
import io.github.danielhp95.caracole.core.web.Inline
import io.github.danielhp95.caracole.viewer.ViewerAssets
import io.github.danielhp95.caracole.viewer.chinese.Hanzi
import io.github.danielhp95.caracole.viewer.chinese.ViewerPinyin
import io.github.danielhp95.caracole.viewer.pages.internal.PageConstants
import io.github.danielhp95.caracole.viewer.pages.internal.PageData
import io.github.danielhp95.caracole.viewer.pages.internal.PageFrame
import io.github.danielhp95.caracole.viewer.pages.internal.PageHtml
import io.github.danielhp95.caracole.viewer.sheet.Section
import io.github.danielhp95.caracole.viewer.sheet.Sheet
import io.github.danielhp95.caracole.viewer.sheet.SheetView
import io.github.danielhp95.caracole.viewer.sheet.Sheets
import io.github.danielhp95.caracole.viewer.theory.Key
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigInteger

/** page.build_viewer's arguments, in its order. */
data class ViewerInputs(val cho: String, val key: String? = null, val keySource: String? = null, val transpose: Int = 0,
                        val start: String? = null, val pdf: String? = null, val export: Boolean = true,
                        val versions: JsonObject? = null, val guitar: List<String> = emptyList(),
                        val harmonica: List<JsonObject> = emptyList(), val pdfTraditional: String? = null,
                        val video: JsonObject? = null)

/** page._read_song: a sheet as its page shows it: the sheet read, the key of its shapes and where it came from in
 * words, and the data its block gives the script, which a caller may change before the page is written (book.py
 * takes the winds' data out of each song's). */
class ReadSong(val sheet: Sheet, val key: Key?, val origin: String?, val data: LinkedHashMap<String, JsonElement>)

/**
 * viewer/page.py: a sheet's page (sheet.html, and a kept version's page), byte for byte as `build_viewer` writes it
 * for the same inputs, and the page's frame book.py and harptab_page.py reuse (`_page`, `_read_song`, `_song_html`,
 * `_facts`, `_footer`, `names_table`, `zh_attr`, `artist_line`, `pdf_line`, `_words`, `_CONTROLS`), each named after
 * Python's. Its HTML and constants are page.py's own, from data/caracole/viewer/page.json, which
 * tests/test_conformance_viewer_pages.py writes from the module; its stylesheets and scripts viewer/'s files, inlined
 * as page.py inlines them (ViewerAssets.Page.SHEET). A names table ([namesTable]) is `{"simplified": {name: as
 * shown}, "traditional": {…}}`, Hanzi.names'. build_version is Python's alone: the phone never embeds or compares it.
 */
object SheetPage {
    /** page.LIBRARY_PAGE: the library's index.html relative to a song's page. */
    val LIBRARY_PAGE: String get() = PageConstants.LIBRARY_PAGE

    /** page._CONTROLS: the bar, the settings and the chord card a songbook shares with a sheet. */
    val CONTROLS: String get() = PageConstants.CONTROLS

    /** build_viewer: the page of a ChordPro sheet as caracole writes it ([ViewerInputs] says each input). */
    fun build(i: ViewerInputs): String {
        val read = readSong(i.cho, i.key, i.keySource, i.transpose)
        val sheet = read.sheet
        val data = read.data
        data["start"] = i.start?.let(::JsonPrimitive) ?: JsonNull
        if (i.versions != null) data["versions"] = i.versions
        if (i.video != null) data["video"] = i.video
        if (i.harmonica.isNotEmpty()) {
            data["harmonicaTabs"] = JsonArray(i.harmonica.map { tab -> JsonObject(tab.filterKeys { it != "harp" }) })
            val harps = i.harmonica.mapNotNull { pyInt(it["harp"]) }
            if (read.key != null && harps.isNotEmpty()) {
                // a harmonica takes no capo: the key the song sounds in
                val sounds = BigInteger.valueOf(read.key.tonic.toLong() + (sheet.capo ?: 0))
                data["harpTabs"] = JsonArray(harps.map { (it - sounds).mod(TWELVE).toInt() }.distinct().map(::JsonPrimitive))
            }
        }
        if (i.guitar.isNotEmpty()) {
            data["guitar"] = JsonArray(i.guitar.map(::JsonPrimitive))
            val clean = Normalize.cleanTitle(sheet.title)
            data["guitarDownload"] = JsonArray(i.guitar.map { JsonPrimitive(DownloadNames.downloadName(sheet.artist, clean, it)) })
        }
        val title = sheet.title.ifEmpty { "Untitled" }
        val pageTitle = if (sheet.artist.isNotEmpty()) "$title · ${sheet.artist}" else title
        val names = namesTable("hanzi" in data, listOf(title, sheet.artist, pageTitle))
        val body = body(sheet, title, read.key, read.origin, i.pdf, export = i.export, guitar = i.guitar.isNotEmpty(),
                        names = names, pdfTraditional = i.pdfTraditional, credit = i.video != null) +
            Inline.jsonBlock("song", JsonObject(data)) +
            (if (names != null) Inline.jsonBlock("song-names", PageData.names(names)) else "")
        return page(pageTitle, body, ViewerAssets.styles(ViewerAssets.Page.SHEET),
                    ViewerAssets.scripts(ViewerAssets.Page.SHEET), names)
    }

    /** viewer_csp: the Content-Security-Policy a server sends with [page], a viewer caracole wrote: its own policy
     * with a sandbox, or one that runs and loads nothing for a page whose policy can't be read. */
    fun viewerCsp(page: ByteArray): String = PageFrame.viewerCsp(page)

    /** names_table: [texts] in either script, for a page whose sheet is Chinese ([chinese]); null for any other page,
     * or one whose names are the same in either script. */
    fun namesTable(chinese: Boolean, texts: List<String>): Map<String, Map<String, String>>? {
        if (!chinese) return null
        val found = Hanzi.names(texts.filter { it.isNotEmpty() })
        return if (found.values.any { it.isNotEmpty() }) found else null
    }

    /** zh_attr: ` data-zh="…"` on an element that shows [text], where [names] convert it; "" elsewhere. */
    fun zhAttr(text: String, names: Map<String, Map<String, String>>?): String = PageHtml.zhAttr(text, names)

    /** artist_line: the artist's line under a song's title, a link to the library page on their songs. */
    fun artistLine(artist: String, names: Map<String, Map<String, String>>? = null): String = PageHtml.artistLine(artist, names)

    /** pdf_line: the links to the files beside a page, each (name, label, its twin in Traditional characters). */
    fun pdfLine(files: List<Triple<String, String, String?>>): String = PageHtml.pdfLine(files)

    /** written_script: "simplified" or "traditional", the characters a sheet's Chinese is written in; null for a
     * sheet in no Chinese. */
    fun writtenScript(cho: String): String? {
        val sheet = Sheets.parse(cho)
        if (!ViewerPinyin.isChinese(SheetView.drawnLines(sheet))) return null
        return if (Hanzi.writtenInTraditional(SheetView.writtenTexts(sheet))) "traditional" else "simplified"
    }

    /** is_chinese: whether a sheet's words are Chinese, as its page judges them. */
    fun isChinese(cho: String): Boolean = ViewerPinyin.isChinese(SheetView.drawnLines(Sheets.parse(cho)))

    /** _page: a whole page, [title] in its head with the icon, [styles], the policy allowing them and [scripts] by
     * their hashes; [body]; then the scripts. */
    fun page(title: String, body: String, styles: List<String>, scripts: List<String>,
             names: Map<String, Map<String, String>>? = null): String = PageFrame.page(title, body, styles, scripts, names)

    /** _read_song: the sheet read, its key and where that came from, and its data. */
    fun readSong(cho: String, key: String?, keySource: String?, transpose: Int): ReadSong {
        val sheet = Sheets.parse(cho)
        val chords = SheetView.chords(sheet)
        val (songKey, origin) = SheetView.songKey(sheet, chords, key, keySource)
        return ReadSong(sheet, songKey, origin, PageData.data(sheet, chords, songKey, origin, transpose))
    }

    /** _song_html: what follows a song's header, on sheet.html and in a songbook alike; [suffix] tells a songbook's
     * songs apart ("-3"), [named] is what a songbook calls the song. */
    fun songHtml(sheet: Sheet, suffix: String = "", named: String = "", credit: Boolean = false): String =
        PageHtml.songHtml(sheet, suffix, named, credit)

    /** _sheet_html: the sheet as its page shows it (SheetView.shown): the notes before the song, then its sections. */
    fun sheetHtml(sheet: Sheet): String = PageHtml.sheetHtml(sheet)

    /** _preamble_html: the notes before the song, folded after their first two lines unless they are two or fewer;
     * [names] the sheet's chords. */
    fun preambleHtml(section: Section, names: List<String>): String = PageHtml.preambleHtml(section, names)

    /** _section_html: a section of the song, its label and its lines; [names] the sheet's chords. */
    fun sectionHtml(section: Section, names: List<String>): String = PageHtml.sectionHtml(section, names)

    /** _facts: the key line under the title, as HTML. */
    fun facts(key: Key?, origin: String?, capo: Int): String = PageHtml.facts(key, origin, capo)

    /** _footer: [links] to the files beside the page, chords-db's credit and licence, a word on privacy. */
    fun footer(links: String): String = PageHtml.footer(links)

    /** _words: [text] cut where a line may wrap. */
    fun words(text: String): List<String> = PageHtml.words(text)

    /** _body: the page's header (‹ Library, the title, the artist, the key line, the versions), the song, the
     * footer, and the controls. */
    private fun body(sheet: Sheet, title: String, key: Key?, origin: String?, pdf: String?, export: Boolean,
                     guitar: Boolean, names: Map<String, Map<String, String>>?, pdfTraditional: String?,
                     credit: Boolean): String {
        val pdfLink = if (!pdf.isNullOrEmpty()) pdfLine(listOf(Triple(pdf, "PDF", pdfTraditional))) else ""
        val controls = if (export) PageConstants.SHEET_CONTROLS else PageConstants.CONTROLS
        return "<div class=\"page\">\n<header class=\"head\">\n" +
            "<a class=\"back\" href=\"${PageConstants.LIBRARY_PAGE}\">‹ Logbook</a>\n" +
            "<h1${zhAttr(title, names)}>${PyText.escape(title)}</h1>\n" +
            artistLine(sheet.artist, names) +
            "<p class=\"facts\" id=\"facts\">${facts(key, origin, sheet.capo ?: 0)}</p>\n" +
            PageConstants.VERSIONS +
            "</header>\n" +
            songHtml(sheet, credit = credit) +
            footer(pdfLink) +
            "</div>\n" +
            withGuitar(controls, guitar) +
            PageConstants.VERSION_LIST
    }

    /** _with_guitar: [controls] with the Guitar Pro row after Harmony's, when the song has Guitar Pro files. */
    private fun withGuitar(controls: String, guitar: Boolean): String {
        if (!guitar) return controls
        val at = controls.indexOf(PageConstants.HARMONY_ROW)
        if (at < 0) return controls
        val end = at + PageConstants.HARMONY_ROW.length
        return controls.substring(0, end) + PageConstants.GUITAR_ROW + controls.substring(end)
    }

    private val TWELVE = BigInteger.valueOf(12)

    /** A JSON value Python's isinstance(value, int) holds: an integer, or a bool (True is 1); else null. */
    private fun pyInt(value: JsonElement?): BigInteger? {
        val p = value as? JsonPrimitive ?: return null
        if (p is JsonNull || p.isString) return null
        return when (val c = p.content) {
            "true" -> BigInteger.ONE
            "false" -> BigInteger.ZERO
            else -> if (c.isNotEmpty() && c.trimStart('-').let { d -> d.isNotEmpty() && d.all { it in '0'..'9' } }) BigInteger(c) else null
        }
    }
}
