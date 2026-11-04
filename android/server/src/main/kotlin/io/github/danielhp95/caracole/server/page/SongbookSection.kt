package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.LibraryStore
import kotlinx.serialization.json.JsonObject

/**
 * songbook_section.songbooks_data from phone_songbooks: the Songbooks tab's data, which `/jobs.json` gives again once a
 * job is over (lane songbook-entries; the phone makes its 'Phone page' alone, never chordpro's PDF or .cho). Neutral
 * until its lane lands: null, the page's own data standing.
 */
object SongbookSection {
    fun data(db: Db, store: LibraryStore): JsonObject? = null
}
