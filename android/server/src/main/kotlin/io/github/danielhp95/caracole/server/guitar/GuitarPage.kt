package io.github.danielhp95.caracole.server.guitar

import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.web.Inline
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.http.PageIcon
import io.github.danielhp95.caracole.server.http.caracoleResource
import java.util.Base64

/** alphatab.AlphaTab: the bundle as the page loads it, its file name under `/assets/alphatab/` ([href]), its bytes
 * (none for the APK's, AlphaTabBundle.installed: the app answers it from its assets), its SRI string, the CSP source
 * that allows it and the one that allows the stylesheet alphaTab adds. */
class AlphaTab(val name: String, val body: ByteArray, val integrity: String, val scriptSource: String,
               val fontFace: String) {
    val href: String get() = AlphaTabBundle.ASSETS + name
}

/**
 * web/guitar_page.py on the phone: a song's kept Guitar Pro file drawn and played by alphaTab, the page byte for byte
 * caracole serve's for the same song, file and bundle (vectors/web/guitar.jsonl).
 *
 * At its top the song's title and artist, the file it shows, and links: back to the song in the library
 * (`/#song=<id>`), its sheet viewer when it has one, and the file itself as a download; under them the bar of
 * controls, then the score. The page holds the file's bytes (base64, in a `<script type="application/octet-stream">`
 * block, which nothing runs), its stylesheet (base.css, then guitar.css) and its script (guitar.js), both copied from
 * caracole's own files at build time, and loads one thing: alphaTab's bundle, by its hash. Its policy ([policy]) is
 * that and nothing else. The files a song keeps are :core's GuitarFiles.of (inbox.guitar_files).
 */
object GuitarPage {
    /** guitar_page.SHARED_STUB: the stylesheet named alphaTabStyle, whose being there keeps alphaTab from adding its
     * own shared rules (they are in guitar.css). */
    const val SHARED_STUB = "/* alphaTab's shared rules are in the page's stylesheet */"

    private val styleText: String by lazy {
        caracoleResource("caracole/library_assets/base.css") + readText(caracoleResource("caracole/web/guitar.css"))
    }
    private val scriptText: String by lazy { readText(caracoleResource("caracole/web/guitar.js")) }

    /** guitar_page.style: BASE_STYLE, then guitar.css. */
    fun style(): String = styleText

    /** guitar_page.script: guitar.js. */
    fun script(): String = scriptText

    /** guitar_page.policy: the page's Content-Security-Policy, without the sandbox and `frame-ancestors`, which the
     * route adds. */
    fun policy(at: AlphaTab): String =
        "default-src 'none'; script-src ${at.scriptSource} ${Inline.sha256Source(script())}; " +
            "style-src ${Inline.sha256Source(style())} ${Inline.sha256Source(SHARED_STUB)} ${at.fontFace}; " +
            "img-src data:; font-src data:; worker-src blob:; base-uri 'none'; form-action 'none'"

    /**
     * guitar_page.build_page: the page for the Guitar Pro file at [path] (its library path, [label] naming it:
     * "Guitar Pro 1"), of the song [songId] ([title] by [artist]), its bytes [data]; [sheet], the library path of the
     * song's sheet viewer, when it has one; [libraryName], the library the server shows.
     */
    fun build(title: String, artist: String, songId: Long, path: String, label: String, data: ByteArray, at: AlphaTab,
              sheet: String? = null, libraryName: LibraryName? = null): String {
        val href = "/" + PyUrl.quote(path)
        val links = StringBuilder("<a class=\"navlink\" href=\"/#song=$songId\">‹ The song</a>")
        if (!sheet.isNullOrEmpty()) links.append("<a class=\"navlink\" href=\"/${esc(PyUrl.quote(sheet))}\">Sheet</a>")
        links.append("<a class=\"navlink\" href=\"${esc(href)}\" download>Download</a>")
        val name = path.substringAfterLast('/')
        val subLine = (if (artist.isNotEmpty()) "<span class=\"by\">${esc(artist)}</span> · " else "") +
            "<span class=\"file\" title=\"${esc(name)}\">${esc(label)}</span>"
        val tabTitle = libraryName?.title("$title · $label") ?: "$title · $label · caracole"
        return "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n" +
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n" +
            "<meta name=\"color-scheme\" content=\"light dark\">\n<meta name=\"referrer\" content=\"same-origin\">\n" +
            (libraryName?.icon() ?: PageIcon.link) +
            "<title>${esc(tabTitle)}</title>\n" +
            "<style>${style()}</style>\n" +
            "<style id=\"alphaTabStyle\">$SHARED_STUB</style>\n" +
            "</head>\n<body>\n<div class=\"page gp\">\n" +
            top(title, links.toString(), label = "This song", sub = subLine, libraryName = libraryName) +
            BAR +
            "<p class=\"gp-status\" id=\"gp-status\" role=\"status\">Loading alphaTab…</p>\n" +
            "<div class=\"score\" id=\"score\"></div>\n" +
            "<noscript><p class=\"gp-status\">Turn on JavaScript to see and hear the tab, or download the file.</p></noscript>\n" +
            "</div>\n" +
            "<script type=\"application/octet-stream\" id=\"gp\">${Base64.getEncoder().encodeToString(data)}</script>\n" +
            "<script src=\"${esc(at.href)}\" integrity=\"${esc(at.integrity)}\" crossorigin=\"anonymous\"></script>\n" +
            "<script>${script()}</script>\n</body>\n</html>\n"
    }

    /**
     * top.py's header: the "¿" and caracole's name, which lead home, the library's name and its badge, the page's
     * [title] after them and its [links] at the end, named [label] to a screen reader; [sub], a muted line under it,
     * markup the caller has escaped.
     */
    internal fun top(title: String, links: String, label: String = "Pages", sub: String = "",
                     libraryName: LibraryName? = null): String =
        "<header class=\"top\">\n" +
            "  <a class=\"app\" href=\"/\">${PageIcon.mark}<span class=\"word\">caracole</span></a>\n" +
            (if (libraryName != null) "  ${libraryName.markup()}\n" else "") +
            "  <span class=\"sep\" aria-hidden=\"true\">›</span>\n" +
            "  <h1>${esc(title)}</h1>\n" +
            "  <nav class=\"links\" aria-label=\"${esc(label)}\">$links</nav>\n</header>\n" +
            (if (sub.isNotEmpty()) "<p class=\"top-sub\">$sub</p>\n" else "")

    /** html.escape(text, quote=True). */
    private fun esc(text: String): String = PyText.escape(text)

    /** Path.read_text's newlines: universal, each `\r\n` and `\r` read as `\n`. */
    private fun readText(text: String): String = text.replace("\r\n", "\n").replace('\r', '\n')

    /** guitar_page._BAR: Play and Stop, the tempo, the view, and the row of tracks. */
    private const val BAR = """<div class="gp-bar" id="gp-bar">
<div class="gp-play" role="toolbar" aria-label="Playback">
<button type="button" class="btn primary" id="play" aria-pressed="false" disabled>Play</button>
<button type="button" class="btn" id="stop" disabled>Stop</button>
<label class="tempo" for="tempo"><span class="word">Tempo</span> <input type="range" id="tempo" min="50" max="125" step="5" value="100">
<output id="tempo-now" for="tempo">100%</output></label>
<fieldset class="view" id="view"><legend class="visually-hidden">Show</legend>
<label><input type="radio" name="view" value="tab"><span>Tab<span class="long"> only</span></span></label>
<label><input type="radio" name="view" value="score"><span><span class="long">Score and tab</span><span class="short">Score</span></span></label></fieldset>
</div>
<div class="gp-tracks" id="tracks" role="group" aria-label="Tracks" hidden></div>
</div>
"""
}
