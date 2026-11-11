package io.github.danielhp95.caracole.viewer.pages

import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.web.Inline
import io.github.danielhp95.caracole.viewer.ViewerAssets
import io.github.danielhp95.caracole.viewer.pages.internal.PageConstants
import io.github.danielhp95.caracole.viewer.pages.internal.PageData
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import io.github.danielhp95.caracole.viewer.version.Version
import io.github.danielhp95.caracole.viewer.version.Versions
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** book.BookSong: one song of a songbook as its page draws it: its sheet's ChordPro ([cho], as caracole wrote it) or
 * why it has none ([missing]), with its key and its `[transpose]`; [start] the version the viewer starts it in (its
 * songbook setting, else its own version), as the viewer's address writes one, null for its [transpose] alone; [id]
 * names it the same wherever the songbook puts it. */
data class BookSong(val title: String, val artist: String, val cho: String? = null, val key: String? = null,
                    val keySource: String? = null, val transpose: Int = 0, val missing: String? = null,
                    val id: String = "", val start: String? = null)

/**
 * viewer/book.py: a songbook as one page for the phone, songbook.html, byte for byte as `build_songbook` writes it for
 * the same inputs, over the sheet page's frame (SheetPage: `_page`, `_read_song`, `_song_html`, `_facts`, `_footer`,
 * `names_table`, `zh_attr`, `artist_line`, `pdf_line` and `_CONTROLS`, page.py's own, from caracole/viewer/page.json);
 * book.py's HTML is its own functions', ported each by name. Its stylesheets and scripts are ViewerAssets.Page.SONGBOOK's
 * (book.css, book.js before the viewer's). Every answer is held by vectors/viewer/songbook_pages.jsonl.
 *
 * The page opens on the contents, every song in the songbook's order, each with its artist, key and capo; a song
 * without a sheet is named there as missing and has no page. Each song with a sheet is a section with its own data
 * block (`data-N`); the fingerings, which most songs share, are one block for the page (`voicings`), and so are the
 * easy keys of each instrument (`easy`), the winds' fingerings and the harps' notes (`winds`), and the names of its
 * songs whose sheets are Chinese (`song-names`).
 */
object SongbookPage {
    /** build_songbook: the page of a songbook called [name]: its contents, then each song with a sheet. [pdf] and
     * [cho] name the songbook's PDF and ChordPro file beside the page, linked when given, and [pdfTraditional] its PDF
     * in Traditional characters, which the PDF's link opens while the page shows its Chinese so. */
    fun build(name: String, songs: List<BookSong>, pdf: String? = null, cho: String? = null,
              pdfTraditional: String? = null): String {
        val playable = songs.withIndex().filter { it.value.cho != null }.map { (i, song) -> i + 1 to song.title }
        val chinese = songs.filter { it.cho != null && SheetPage.isChinese(it.cho) }.flatMap { listOf(it.title, it.artist) }
        val names = SheetPage.namesTable(chinese.isNotEmpty(), chinese)
        val voicings = LinkedHashMap<String, JsonElement>()
        var easy: JsonElement? = null  // every song's alike: one block for the page
        var winds: JsonElement? = null  // so are the winds' fingerings and the harps' notes
        val sections = StringBuilder()
        val about = HashMap<Int, String>()
        for ((i, pair) in playable.withIndex()) {
            val n = pair.first
            val prev = if (i > 0) playable[i - 1] else null
            val next = if (i + 1 < playable.size) playable[i + 1] else null
            val (html, data, line) = song(songs[n - 1], n, songs.size, prev, next, names)
            about[n] = line
            (data.remove("voicings") as? JsonObject)?.let { voicings.putAll(it) }
            data.remove("easy")?.let { easy = it }
            data.remove("winds")?.let { winds = it }
            sections.append(html).append(Inline.jsonBlock("data-$n", JsonObject(data))).append("</section>\n")
        }
        val count = "${songs.size} song${if (songs.size == 1) "" else "s"}"
        val files = SheetPage.pdfLine(listOfNotNull(
            pdf?.takeIf { it.isNotEmpty() }?.let { Triple(it, "PDF", pdfTraditional) },
            cho?.takeIf { it.isNotEmpty() }?.let { Triple(it, "ChordPro file", null) },
        ))
        val body = StringBuilder()
            .append("<div class=\"page\">\n<header class=\"head book-head\">\n")
            .append("<a class=\"back\" href=\"").append(PageConstants.LIBRARY_PAGE).append("\">‹ Library</a>\n")
            .append("<h1>").append(PyText.escape(name)).append("</h1>\n<p class=\"artist\">Songbook · ").append(count)
            .append("</p>\n</header>\n")
            .append(contents(songs, about, files, names))
            .append(sections)
            .append(Inline.jsonBlock("voicings", JsonObject(voicings)))
            .append(easy?.let { Inline.jsonBlock("easy", it) } ?: "")
            .append(winds?.let { Inline.jsonBlock("winds", it) } ?: "")
            .append(if (!names.isNullOrEmpty()) Inline.jsonBlock("song-names", PageData.names(names)) else "")
            .append(SheetPage.footer(files))
            .append("</div>\n")
            .append(PageConstants.CONTROLS)
            .toString()
        return SheetPage.page("$name · songbook", body, ViewerAssets.styles(ViewerAssets.Page.SONGBOOK),
                              ViewerAssets.scripts(ViewerAssets.Page.SONGBOOK))
    }

    /** _contents: each song's number and title, and on a line under it its artist and, for a song with a sheet, its
     * key and capo ([about], by number); a name the page's [shown] convert marked so. */
    internal fun contents(songs: List<BookSong>, about: Map<Int, String>, files: String,
                          shown: Map<String, Map<String, String>>? = null): String {
        val items = songs.withIndex().map { (i, song) ->
            val n = i + 1
            val mark = SheetPage.zhAttr(song.artist, shown)
            val artist = if (mark.isNotEmpty()) "<span$mark>${PyText.escape(song.artist)}</span>" else PyText.escape(song.artist)
            val line = listOf(artist, about[n] ?: "").filter { it.isNotEmpty() }.joinToString(" · ")
            val names = "<span class=\"n\">$n</span><span class=\"t\"${SheetPage.zhAttr(song.title, shown)}>" +
                "${PyText.escape(song.title)}</span>" + (if (line.isNotEmpty()) "<span class=\"a\">$line</span>" else "")
            if (song.cho == null) {
                val why = PyText.escape(song.missing?.takeIf { it.isNotEmpty() } ?: "no sheet yet")
                "<li class=\"missing\"><span class=\"row\">$names<span class=\"why\">Missing: $why</span></span></li>"
            } else {
                "<li><a class=\"row\" href=\"#song-$n\" data-id=\"${PyText.escape(song.id)}\">$names</a></li>"
            }
        }
        val filesRow = if (files.isNotEmpty()) "<p class=\"files\">\n$files</p>\n" else ""
        return "<nav class=\"toc\" id=\"contents\" aria-labelledby=\"contents-title\">\n" +
            "<h2 class=\"lbl\" id=\"contents-title\">Contents</h2>\n" +
            "<ol class=\"toc-list\">\n${items.joinToString("\n")}\n</ol>\n$filesRow</nav>\n"
    }

    /** _song: a song's section without its closing tag, its data (with its fingerings), and its key and capo as the
     * contents give them; [prev] and [next] the songs with a sheet around it (number, title). */
    private fun song(song: BookSong, n: Int, total: Int, prev: Pair<Int, String>?, next: Pair<Int, String>?,
                     names: Map<String, Map<String, String>>?): Triple<String, LinkedHashMap<String, JsonElement>, String> {
        val read = SheetPage.readSong(song.cho ?: "", song.key, song.keySource, song.transpose)
        val data = read.data
        data["start"] = song.start?.let(::JsonPrimitive) ?: JsonNull  // where the viewer starts, as sheet.html's
        val id = PyText.escape(song.id)
        val html = "<section class=\"song\" id=\"song-$n\" data-n=\"$n\" data-id=\"$id\" " +
            "aria-labelledby=\"title-$n\">\n<header class=\"head\">\n" +
            pager("Songs", prev, next, names) +
            "<p class=\"pos\">Song $n of $total</p>\n" +
            "<h2 class=\"title\" id=\"title-$n\"${SheetPage.zhAttr(song.title, names)}>${PyText.escape(song.title)}</h2>\n" +
            SheetPage.artistLine(song.artist, names) +
            "<p class=\"facts\" id=\"facts-$n\">${SheetPage.facts(read.key, read.origin, read.sheet.capo ?: 0)}</p>\n" +
            "</header>\n" +
            SheetPage.songHtml(read.sheet, "-$n", song.title) +
            pager("Songs, end of sheet", prev, next, names)  // at the end of a long sheet, no scrolling back up
        return Triple(html, data, keyAndCapo(read.key, opensIn(song), read.sheet.capo))
    }

    /** _opens_in: the version the viewer opens the song in, as viewer.js reads its data: its start, at its transpose
     * where that names no `t`; else its transpose. */
    internal fun opensIn(song: BookSong): Version {
        val start = song.start
        if (start.isNullOrEmpty()) return Version(t = song.transpose)
        val version = Versions.fromQuery(start)
        val query = if (start.startsWith("#") || start.startsWith("?")) start.substring(1) else start
        return if ("t" in PyUrl.parseQs(query, keepBlank = true)) version else version.copy(t = song.transpose)
    }

    /** _key_and_capo: "Em · capo 2", as the contents give a song: the key of the shapes the viewer opens it in
     * ([version], as Versions.playedKey has it) and its capo. A screen reader hears "key Em". */
    internal fun keyAndCapo(key: Key?, version: Version, capoSheet: Int?): String {
        val (shown, capo) = Versions.playedKey(version, key, capoSheet)
        val parts = ArrayList<String>()
        if (shown != null) parts += "<span class=\"vh\">key </span>${PyText.escape(Theory.keyName(shown))}"
        if (capo != 0) parts += "capo $capo"
        return parts.joinToString(" · ")
    }

    /** _pager: Previous, Contents and Next, above a song's sheet and again after it, each named for a screen reader. */
    internal fun pager(label: String, prev: Pair<Int, String>?, next: Pair<Int, String>?,
                       names: Map<String, Map<String, String>>? = null): String =
        "<nav class=\"pager\" aria-label=\"${PyText.escape(label)}\">" +
            (if (prev != null) {
                "<a href=\"#song-${prev.first}\" rel=\"prev\"><span class=\"arrow\" aria-hidden=\"true\">‹ </span>" +
                    "<span class=\"vh\">Previous: </span><span class=\"name\"${SheetPage.zhAttr(prev.second, names)}>" +
                    "${PyText.escape(prev.second)}</span></a>"
            } else {
                "<span class=\"none\"></span>"
            }) +
            "<a href=\"#contents\">Contents</a>" +
            (if (next != null) {
                "<a href=\"#song-${next.first}\" rel=\"next\"><span class=\"lead\">Next: </span>" +
                    "<span class=\"name\"${SheetPage.zhAttr(next.second, names)}>${PyText.escape(next.second)}</span>" +
                    "<span class=\"arrow\" aria-hidden=\"true\"> ›</span></a>"
            } else {
                "<span class=\"none\"></span>"
            }) +
            "</nav>\n"
}
