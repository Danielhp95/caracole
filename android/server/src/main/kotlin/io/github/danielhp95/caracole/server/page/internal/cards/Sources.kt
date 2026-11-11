package io.github.danielhp95.caracole.server.page.internal.cards

import io.github.danielhp95.caracole.core.db.Db

/**
 * icons.py's sources of a song's kept files, as the library page's cards read them: [keptSources] (where each kept
 * file came from, by song and name) and [sourceOf] (where any file of the song's folder came from, given those).
 */
internal object Sources {
    /** icons.LYRICS, AUTO, INBOX, YOUTUBE. */
    const val LYRICS = "lrclib"
    const val AUTO = "auto"
    const val INBOX = "inbox"
    const val YOUTUBE = "youtube"

    /** icons.SOURCES' keys: the places a file comes from, the sites and the audio model and the inbox. */
    val KEYS: Set<String> = setOf("ug", "lacuerda", "lrclib", "megalobiz", "azlyrics", "gtptabs", "musescore",
                                  "harptabs", "gametabs", "youtube", AUTO, INBOX)

    const val HUMAN_SHEET = "sheet.txt"
    const val AUTO_SHEET = "sheet (auto).txt"

    /** songs.SHEET_FILE_NAMES: a song's sheets, the human one first (icons.SHEETS). */
    val SHEETS: List<String> = listOf(HUMAN_SHEET, AUTO_SHEET)

    /** songs.SHEET_OUTPUTS and TRADITIONAL_PDFS: what render.py makes of each kept sheet. */
    private val OUTPUTS = linkedMapOf(
        HUMAN_SHEET to listOf("sheet.cho", "sheet.pdf", "sheet.html", "sheet (Traditional).pdf"),
        AUTO_SHEET to listOf("sheet (auto).cho", "sheet (auto).pdf", "sheet (auto).html",
                             "sheet (auto, Traditional).pdf"),
    )

    /** icons._MADE_FROM: a file caracole makes from a kept sheet, and that sheet. */
    private val MADE_FROM: Map<String, String> = OUTPUTS.flatMap { (sheet, outs) -> outs.map { it to sheet } }.toMap()

    private val LYRICS_FILES = listOf("lyrics.txt", "lyrics.lrc")

    /**
     * icons.kept_sources: where each kept file came from, by song id and file name: its version's provider; YouTube's
     * for an auto sheet whose version's raw names its video (`youtube`, an object); and the lyrics files of a found
     * song whose lyrics another site than LRCLIB gave (its lyrics_json's provider, one of [KEYS]).
     */
    fun keptSources(db: Db): Map<Long, Map<String, String>> {
        val found = LinkedHashMap<Long, LinkedHashMap<String, String>>()
        db.query(
            "SELECT f.song_id, f.name, v.provider, " +
                "CASE WHEN json_valid(v.raw) THEN json_type(v.raw, '$.youtube') END = 'object' " +
                "FROM files f JOIN versions v ON v.id = f.version_id",
        ) { Triple(it.long(0)!!, it.text(1)!!, it.text(2)!! to (it.long(3) == 1L)) }.forEach { (song, name, from) ->
            val (provider, youtube) = from
            found.getOrPut(song) { LinkedHashMap() }[name] = if (provider == AUTO && youtube) YOUTUBE else provider
        }
        for ((song, provider) in lyricsProviders(db)) {
            if (provider != LYRICS) {
                val kept = found.getOrPut(song) { LinkedHashMap() }
                for (name in LYRICS_FILES) kept[name] = provider
            }
        }
        return found
    }

    /** icons._lyrics_providers: the site each found song's lyrics came from: LRCLIB's for lyrics that name none, or
     * name a provider caracole has no source for (a provider that is no text, json_extract's number, is none). */
    private fun lyricsProviders(db: Db): List<Pair<Long, String>> = db.query(
        "SELECT id, CASE WHEN json_valid(lyrics_json) THEN json_extract(lyrics_json, '$.provider') END, " +
            "CASE WHEN json_valid(lyrics_json) THEN json_type(lyrics_json, '$.provider') END " +
            "FROM songs WHERE lyrics_status = 'found'",
    ) {
        val provider = if (it.text(2) == "text") it.text(1) else null
        it.long(0)!! to (if (provider != null && provider in KEYS) provider else LYRICS)
    }

    /**
     * icons.source_of: where a song's file [name] came from, given its [kept] files' sources: a kept file's own; the
     * lyrics LRCLIB's ([kept] names another site's); an export the sheet's; a file made of a kept sheet that sheet's;
     * an auto sheet's outputs the audio model's; null for a file of caracole's own or one put there by hand.
     */
    fun sourceOf(name: String, kept: Map<String, String>): String? {
        kept[name]?.let { return it }
        if (name in LYRICS_FILES) return LYRICS
        if (isExport(name)) return sheetSource(kept)
        val base = MADE_FROM[name] ?: name
        kept[base]?.let { return it }
        return if (base == AUTO_SHEET) AUTO else null
    }

    /** icons.sheet_source: where a song's sheet came from, its human sheet's source, else its auto sheet's. */
    fun sheetSource(kept: Map<String, String>): String? = SHEETS.firstNotNullOfOrNull { kept[it] }

    /** songs.is_export: a PDF of a sheet in another version ("sheet (G Dorian, capo 0).pdf"), not the auto sheet's
     * own PDF nor a sheet's own in Traditional characters. */
    fun isExport(name: String): Boolean =
        name.startsWith("sheet (") && name.endsWith(").pdf") && name !in OUTPUTS.getValue(AUTO_SHEET) &&
            name !in setOf("sheet (Traditional).pdf", "sheet (auto, Traditional).pdf")
}
