package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.db.Db

/** What a render pass did: the songs whose pages it wrote, those it found unchanged, and those it couldn't, why. */
data class RenderStats(val written: Int = 0, val unchanged: Int = 0, val failed: Map<Long, String> = emptyMap())

/** The pdf stage's seam: a song's pages made on the phone (milestone 5's PhoneRender, once its `seam` is itself).
 * [NONE] makes none, and the stage says get.py's words for a caracole with no PDFs: a lookup tells the two apart by
 * identity, `pages === SongPages.NONE`. */
fun interface SongPages {
    fun render(db: Db, songIds: Collection<Long>, between: (() -> Unit)?): RenderStats

    companion object {
        val NONE: SongPages = SongPages { _, _, _ -> RenderStats() }
    }
}

/**
 * songbook.SongbookStats, one pass over the songbooks, its fields in Python's order: [rendered] songbooks had a file
 * written, [skipped] ones were up to date, [failed] names those with a file that couldn't be made, [fontError] says
 * once which wait for a CJK font, [error] why the songbooks can't be read, and [removed] counts the songbooks gone
 * whose files went too. What get.py's songbooks stage words its end by.
 */
data class SongbookStats(val rendered: Int = 0, val skipped: Int = 0, val failed: List<String> = emptyList(),
                         val fontError: String? = null, val error: String? = null, val removed: Int = 0)

/** The songbooks stage's seam: songbook.render_songbooks(only=…), the songbooks that list a song made again
 * (milestone 6's SongbookPagesImpl, once its `seam` is itself). While it is [NONE] the stage calls none of
 * milestone 6's songbooks code: a lookup tells by identity, `songbooks === SongbookPages.NONE`. */
fun interface SongbookPages {
    fun render(db: Db, only: Set<String>?): SongbookStats

    companion object {
        val NONE: SongbookPages = SongbookPages { _, _ -> SongbookStats() }
    }
}
