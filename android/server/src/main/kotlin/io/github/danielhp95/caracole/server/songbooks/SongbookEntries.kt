package io.github.danielhp95.caracole.server.songbooks

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.songbooks.Setting
import io.github.danielhp95.caracole.core.songbooks.Songbook
import io.github.danielhp95.caracole.viewer.version.Version
import java.io.File

/** songbook.Entry: one song of a songbook as it is rendered, its sheet or why it has none, the songbook's setting
 * for it and where the songbook plays it. */
data class Entry(val text: String, val title: String, val artist: String, val song: SongRow? = null,
                 val cho: String? = null, val missing: String? = null, val transpose: Int = 0,
                 val version: Version = Version(), val key: String? = null, val keySource: String? = null,
                 val setting: Setting? = null, val keepsKey: Boolean = false)

/** songbook.py's entries and where each plays (lane songbook-entries); the songbooks that list a song are
 * :core's Songbooks.listing, which the lookup calls too. */
object SongbookEntries {
    /** songbook.songbook_entries. */
    fun entries(db: Db, libraryDir: File, overrides: Overrides, book: Songbook): List<Entry> =
        TODO("lane songbook-entries")
    fun songsToGet(entries: List<Entry>, overrides: Overrides): List<SongRow> = TODO("lane songbook-entries")
    fun withCapo(entry: Entry, setting: Setting, overrides: Overrides): Setting = TODO("lane songbook-entries")
    fun onInstrument(entry: Entry, setting: Setting, keyGiven: Boolean = false, capoGiven: Boolean = false): Setting =
        TODO("lane songbook-entries")
    fun playsIn(entry: Entry): String? = TODO("lane songbook-entries")
}
