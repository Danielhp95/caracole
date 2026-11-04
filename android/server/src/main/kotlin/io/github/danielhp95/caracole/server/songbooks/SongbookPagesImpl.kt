package io.github.danielhp95.caracole.server.songbooks

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.lookup.SongbookStats

/**
 * songbook.render_songbooks on the phone: each songbook's songbook.html, recorded in kv `songbook:<folder>` as Python's
 * `_record` and `_remove_gone` (lane songbook-entries). The songbook runner calls it, and the lookup's songbooks stage
 * through [seam]. Neutral until its lane lands: it makes none, as [SongbookPages.NONE] does.
 */
class SongbookPagesImpl(val database: Database, val store: LibraryStore) : SongbookPages {
    override fun render(db: Db, only: Set<String>?): SongbookStats = SongbookStats()

    /** What the lookup's songbooks stage calls (Assembly gives it as PhoneParts.songbooks): [SongbookPages.NONE]
     * while this is neutral, so the stage calls none of milestone 6's songbooks code (Songbooks.all, .listing); lane
     * songbook-entries makes it `this`. */
    val seam: SongbookPages get() = SongbookPages.NONE
}
