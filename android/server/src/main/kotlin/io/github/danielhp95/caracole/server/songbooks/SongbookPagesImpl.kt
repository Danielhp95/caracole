package io.github.danielhp95.caracole.server.songbooks

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.lookup.RenderStats
import io.github.danielhp95.caracole.core.lookup.SongbookPages

/**
 * songbook.render_songbooks on the phone: each songbook's songbook.html, recorded in kv `songbook:<folder>` as Python's
 * `_record` and `_remove_gone` (lane songbook-entries). The seam the lookup's songbooks stage and the songbook runner
 * call. Neutral until its lane lands: it makes none, as [SongbookPages.NONE] does.
 */
class SongbookPagesImpl(val database: Database, val store: LibraryStore) : SongbookPages {
    override fun render(db: Db, only: Set<String>?): RenderStats = RenderStats()
}
