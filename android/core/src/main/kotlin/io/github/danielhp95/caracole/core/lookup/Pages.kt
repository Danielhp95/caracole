package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.db.Db

/** What a render pass did: the songs whose pages it wrote, those it found unchanged, and those it couldn't, why. */
data class RenderStats(val written: Int = 0, val unchanged: Int = 0, val failed: Map<Long, String> = emptyMap())

/** The pdf stage's seam: a song's pages made on the phone (milestone 5's PhoneRender). [NONE] makes none, and the
 * stage says get.py's words for a caracole with no PDFs. */
fun interface SongPages {
    fun render(db: Db, songIds: Collection<Long>, between: (() -> Unit)?): RenderStats

    companion object {
        val NONE: SongPages = SongPages { _, _, _ -> RenderStats() }
    }
}

/** The songbooks stage's seam: the songbooks that list a song made again (milestone 6's SongbookPagesImpl). */
fun interface SongbookPages {
    fun render(db: Db, only: Set<String>?): RenderStats

    companion object {
        val NONE: SongbookPages = SongbookPages { _, _ -> RenderStats() }
    }
}
