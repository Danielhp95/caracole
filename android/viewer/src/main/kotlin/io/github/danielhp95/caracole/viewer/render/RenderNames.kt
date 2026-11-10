package io.github.danielhp95.caracole.viewer.render

import io.github.danielhp95.caracole.core.py.PyRegex

/**
 * What render.py, songs.py, keys.py, library.py and icons.py name that the phone's render names too, each under its
 * Python name: vectors/viewer/render.jsonl's `constants` record holds them as the modules do, and RenderReplay
 * compares.
 */
object RenderNames {
    /** render.FILES_KEY: kv, then the song's id: each .cho and page written, its SHA-256 and size, and on the phone
     * the song unit's digest it was made at ([WrittenPages]). */
    const val FILES_KEY = "render:files:"

    /** render.OWN_VERSIONS_KEY: kv, the `[version]` entries rewritten for a letter alone read minor ([OwnVersions]). */
    const val OWN_VERSIONS_KEY = "keys:own_versions"

    /** render.STATUS_KEY: the to-do page's record of a pass, which the phone never writes. */
    const val STATUS_KEY = "render:status"

    /** kv `render:<song id>:phone`, the phone's record of each song it rendered (helpers/phone_render.py PHONE_KV). */
    const val PHONE_KV = ":phone"

    /** songs.HUMAN_SHEET and AUTO_SHEET: the kept sheets. */
    const val HUMAN_SHEET = "sheet.txt"
    const val AUTO_SHEET = "sheet (auto).txt"

    /** songs.SHEET_OUTPUTS: what render.py makes of each kept sheet, its ChordPro, its PDF and its page. */
    val HUMAN_OUTPUTS: List<String> = listOf("sheet.cho", "sheet.pdf", "sheet.html")
    val AUTO_OUTPUTS: List<String> = listOf("sheet (auto).cho", "sheet (auto).pdf", "sheet (auto).html")
    val SHEET_OUTPUTS: Map<String, List<String>> = linkedMapOf(HUMAN_SHEET to HUMAN_OUTPUTS, AUTO_SHEET to AUTO_OUTPUTS)

    /** songs.TRADITIONAL_PDFS: a Chinese sheet's PDF in Traditional characters, which the phone never makes. */
    val TRADITIONAL_PDFS: Map<String, String> =
        linkedMapOf(HUMAN_SHEET to "sheet (Traditional).pdf", AUTO_SHEET to "sheet (auto, Traditional).pdf")

    /** keys.SHEET_DOC: the human sheet's markup, beside it. */
    const val SHEET_DOC = "sheet.json"

    /** autochords.merge.AUTO_MARKER: an auto sheet's first line. */
    const val AUTO_MARKER = "auto-generated, unverified"

    /** render._LETTER: a key named by its letter alone. */
    const val LETTER = "[A-G][#b]?"
    val LETTER_RE: Regex by lazy { PyRegex.compile(LETTER) }

    /** inbox's harmonica tabs: their version's kind, their files' names and their pages' (core.inbox.HarmonicaFiles). */
    const val HARMONICA_KIND = "harmonica"
    const val HARMONICA_FILE = """harmonica-(\d+)\.txt"""
    const val HARMONICA_PAGE = """harmonica-(\d+)\.html"""

    /** library.LYRICS_PAGES: the lyrics sites whose fair use asks a link back, and where their pages are. */
    val LYRICS_PAGES: Map<String, String> =
        linkedMapOf("megalobiz" to "https://megalobiz.com/", "azlyrics" to "https://www.azlyrics.com/")

    /** icons.YOUTUBE: the mark of an auto sheet whose audio came from YouTube. */
    const val YOUTUBE = "youtube"

    /** A song's status the render passes over (songs.py's). */
    const val IGNORED = "ignored"

    /** What a song's failure that is no RenderError nor a file's says first (the lookup's words for a bug). */
    const val BUG = "a bug in caracole"

    /** The kv of the phone's build its pages were last made by (the render job's). */
    const val BUILD_KEY = "phone:render-build"

    /** kv `render:<song id>:phone`. */
    fun phoneKey(songId: Long): String = "render:$songId$PHONE_KV"

    /** The song's sync unit, as peer_sync names it. */
    fun unitOf(key: String): String = "song/$key"
}
