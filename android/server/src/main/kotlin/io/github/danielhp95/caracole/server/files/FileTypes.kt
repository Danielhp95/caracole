package io.github.danielhp95.caracole.server.files

import io.github.danielhp95.caracole.core.py.PyPath

/**
 * web/files.py's kinds of file the library serves (vectors/web/downloads.jsonl): PDFs, text (sheets, ChordPro,
 * lyrics), JSON, and Guitar Pro, Power Tab and MuseScore's files as downloads. Never HTML, SVG or anything a browser
 * would run as the server's own page: a page is the mirror's alone, with the policy caracole serve gave it.
 */
object FileTypes {
    const val MAX_BYTES = 64L * 1024 * 1024
    private const val TEXT = "text/plain; charset=utf-8"

    /** inbox.GP_EXTENSIONS and SCORE_EXTENSIONS but ".pdf": a score's PDF is a PDF like any. */
    val DOWNLOADS: Set<String> = linkedSetOf(".gp3", ".gp4", ".gp5", ".gpx", ".gp", ".ptb", ".mscz", ".mxl", ".musicxml",
                                             ".mid", ".midi")

    val TYPES: Map<String, String> = LinkedHashMap<String, String>().apply {
        put(".pdf", "application/pdf")
        put(".txt", TEXT)
        put(".cho", TEXT)
        put(".lrc", TEXT)
        put(".md", TEXT)
        put(".json", "application/json; charset=utf-8")
        for (ext in DOWNLOADS.sorted()) put(ext, "application/octet-stream")
    }

    /** PurePosixPath(name).suffix, Python 3.14's ([PyPath.suffix]). */
    fun suffix(name: String): String = PyPath.suffix(name)
}
