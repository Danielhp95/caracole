package io.github.danielhp95.caracole.viewer.pages.internal

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.viewer.sheet.Blank
import io.github.danielhp95.caracole.viewer.sheet.ChordRow
import io.github.danielhp95.caracole.viewer.sheet.Item
import io.github.danielhp95.caracole.viewer.sheet.Line
import io.github.danielhp95.caracole.viewer.sheet.Lyrics
import io.github.danielhp95.caracole.viewer.sheet.Section
import io.github.danielhp95.caracole.viewer.sheet.Sheet
import io.github.danielhp95.caracole.viewer.sheet.SheetView
import io.github.danielhp95.caracole.viewer.sheet.Sheets
import io.github.danielhp95.caracole.viewer.sheet.Tab
import io.github.danielhp95.caracole.viewer.sheet.Text
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory

/** A page's names table (page.names_table's): each name in Simplified and in Traditional characters, by the name. */
internal typealias Names = Map<String, Map<String, String>>

/**
 * viewer/page.py's markup, function by function: the sheet as static HTML (each text escaped as html.escape does),
 * the key line, the artist's line, the files' links and the footer. Lengths, spaces and widths are Python's, in code
 * points (PyUnicode).
 */
internal object PageHtml {
    private fun escape(s: String): String = PyText.escape(s)

    /** zh_attr: ` data-zh="…"`, the name [text] as written, on an element that shows it, where [names] convert it. */
    fun zhAttr(text: String, names: Names?): String {
        if (names == null || names.values.none { text in it }) return ""
        return " data-zh=\"${escape(text)}\""
    }

    /** pdf_line: the links to the files beside a page, each (name, label, its twin in Traditional characters). */
    fun pdfLine(files: List<Triple<String, String, String?>>): String = buildString {
        for ((name, label, twin) in files) {
            append("<a class=\"pdf\" href=\"").append(escape(PyUrl.quote(name))).append('"')
            if (!twin.isNullOrEmpty()) append(" data-trad=\"").append(escape(PyUrl.quote(twin))).append('"')
            append('>').append(label).append("</a>\n")
        }
    }

    /** artist_line: the artist's line under a song's title, a link to the library page on their songs. */
    fun artistLine(artist: String, names: Names? = null): String {
        if (artist.isEmpty()) return ""
        val href = "${PageConstants.LIBRARY_PAGE}#by=${PyUrl.quote(artist, safe = "")}"
        return "<p class=\"artist\"><a href=\"${escape(href)}\" title=\"${escape("Songs by $artist")}\">" +
            "<span${zhAttr(artist, names)}>${escape(artist)}</span></a></p>\n"
    }

    /** _facts: the key line under the title, as viewer.js writes it for the sheet as written. */
    fun facts(key: Key?, origin: String?, capo: Int): String {
        val source = escape(origin ?: "")
        if (key == null) return if (capo != 0) "Capo <b>$capo</b>" else ""
        if (capo == 0) {
            return "Key <b>${escape(Theory.keyName(key))}</b>" +
                (if (source.isNotEmpty()) " · <span class=\"from\">$source</span>" else "")
        }
        return "<b>${escape(Theory.keyName(key))}</b> shapes · capo <b>$capo</b> · sounds " +
            "<b>${escape(Theory.keyName(Theory.sounding(key, capo)))}</b>" +
            (if (source.isNotEmpty()) " · <span class=\"from\">key $source</span>" else "")
    }

    /** _footer: the links to the files beside the page, chords-db's credit and licence, and a word on privacy. */
    fun footer(links: String): String =
        "<footer class=\"foot\">\n" + links +
            "<p>Chord shapes from <a href=\"${PageConstants.CREDIT_URL}\">chords-db</a>, © 2016 David Rubert, MIT licence.</p>\n" +
            "<details class=\"licence\"><summary>chords-db licence</summary><pre>${escape(PageConstants.CREDIT_NOTICE)}</pre></details>\n" +
            "<p>Private page: the lyrics and chords are other people's work.</p>\n" +
            "</footer>\n"

    /** _song_html: what follows a song's header: an auto sheet's notice, the credit's place, the rail of necks, the
     * strip of shapes, and the sheet, marked Chinese when its words or names ([named]) are. */
    fun songHtml(sheet: Sheet, suffix: String = "", named: String = "", credit: Boolean = false): String {
        val lang = if (Normalize.hasHan(named + sheet.title + texts(sheet).joinToString(""))) " lang=\"zh\"" else ""
        return (if (sheet.auto) PageConstants.NOTICE else "") +
            (if (credit) PageConstants.CREDIT else "") +
            "<aside class=\"necks\" id=\"necks$suffix\" hidden aria-label=\"Chord necks\"></aside>\n" +
            "<div class=\"strip\" id=\"strip$suffix\" hidden></div>\n" +
            "<article class=\"sheet\" id=\"sheet$suffix\"$lang>\n${sheetHtml(sheet)}</article>\n"
    }

    /** _texts: the words of every section's sung lines and lines of text. */
    private fun texts(sheet: Sheet): List<String> {
        val out = ArrayList<String>()
        for (section in sheet.sections) {
            for (line in section.lines) {
                when (line) {
                    is Lyrics -> line.parts.forEach { out += it.second }
                    is Text -> out += line.text
                    else -> {}
                }
            }
        }
        return out
    }

    /** _sheet_html: the notes before the song, then each section of the song, as the page shows them. */
    fun sheetHtml(sheet: Sheet): String {
        val (pre, sections) = SheetView.shown(sheet)
        return shownHtml(sheet.chords, pre, sections)
    }

    /** _sheet_html of the sheet as page._shown shows it: [pre], the notes before the song, and [sections]. */
    fun shownHtml(names: List<String>, pre: Section?, sections: List<Section>): String =
        (if (pre != null) preambleHtml(pre, names) else "") + sections.joinToString("") { sectionHtml(it, names) }

    /** _preamble_html: the notes before the song, folded after their first two lines (a `<details>`), unless they
     * are two lines or fewer. */
    fun preambleHtml(section: Section, names: List<String>): String {
        val body = section.lines.joinToString("\n") { lineHtml(it, names) }
        val lines = SheetView.peek(section, names)
        if (lines.isEmpty()) return "<div class=\"pre\">\n$body\n</div>\n"
        val peek = lines.joinToString("<br>") { escape(it) }
        return "<details class=\"pre\">\n<summary><span class=\"peek\">$peek</span><span class=\"named\">Notes</span>" +
            "<span class=\"more\">More</span><span class=\"less\">Less</span></summary>\n" +
            "<div class=\"pre-body\">\n$body\n</div>\n</details>\n"
    }

    /** _section_html: a section of the song, its label, its lines. */
    fun sectionHtml(section: Section, names: List<String>): String {
        val out = ArrayList<String>()
        out += "<section class=\"${if (section.chorus) "sec chorus" else "sec"}\">"
        if (!section.label.isNullOrEmpty()) out += "<h2 class=\"lbl\">${escape(section.label)}</h2>"
        section.lines.forEach { out += lineHtml(it, names) }
        out += "</section>\n"
        return out.joinToString("\n")
    }

    private fun chordHtml(index: Int, names: List<String>): String =
        "<b class=\"c\" data-c=\"$index\" tabindex=\"0\" role=\"button\">${escape(names[index])}</b>"

    private fun markHtml(mark: String): String = "<i class=\"m\">${escape(mark)}</i>"

    private fun itemHtml(item: Item, names: List<String>): String = when (item) {
        is Item.Chord -> chordHtml(item.index, names)
        is Item.Mark -> markHtml(item.text)
    }

    /** _line_html: a line of the sheet; a chord legend's line (sheet.is_legend) is a `legend`. */
    fun lineHtml(line: Line, names: List<String>): String {
        val legend = if (Sheets.isLegend(line, names)) " legend" else ""
        return when (line) {
            is Lyrics -> {
                val out = StringBuilder()
                for ((head, text) in line.parts) {
                    val words = ArrayDeque(words(text))
                    if (head != null) {
                        val first = if (words.isNotEmpty()) escape(words.removeFirst()) else ""
                        out.append("<span class=\"s\">").append(itemHtml(head, names))
                            .append("<span class=\"y\">").append(first).append("</span></span>")
                    }
                    words.forEach { out.append("<span class=\"w\">").append(escape(it)).append("</span>") }
                }
                "<p class=\"l$legend\">$out</p>"
            }
            is ChordRow -> "<p class=\"l chords$legend\">${line.items.joinToString(" ") { itemHtml(it, names) }}</p>"
            is Text -> "<p class=\"l\">${escape(line.text)}</p>"
            is Tab -> "<pre class=\"tab\">${escape(line.lines.joinToString("\n"))}</pre>"
            Blank -> "<div class=\"gap\"></div>"
        }
    }

    private fun wide(cp: Int): Boolean = PyUnicode.eastAsianWidth(cp).let { it == "W" || it == "F" }

    /** _words: [text] cut where a line may wrap: after each word's trailing spaces, and around each wide (CJK)
     * character, which wraps on its own. */
    fun words(text: String): List<String> {
        val words = ArrayList<String>()
        val word = StringBuilder()
        var last = -1  // the word's last code point
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            if (!PyUnicode.isSpace(cp) && word.isNotEmpty() && (wide(cp) || PyUnicode.isSpace(last) || wide(last))) {
                words += word.toString()
                word.setLength(0)
            }
            word.appendCodePoint(cp)
            last = cp
            i += Character.charCount(cp)
        }
        if (word.isNotEmpty()) words += word.toString()
        return words
    }
}
