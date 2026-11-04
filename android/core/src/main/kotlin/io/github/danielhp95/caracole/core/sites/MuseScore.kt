package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow

/** musescore.SongPage: a possible match, by its title alone. */
data class MuseScorePage(val pageId: Long, val path: String, val titleKey: String)

/** musescore.py: links from the index alone. */
object MuseScorePages {
    fun songPages(db: Db, song: SongRow, limit: Int = 3): List<MuseScorePage> = TODO("lane tab-files")
}
