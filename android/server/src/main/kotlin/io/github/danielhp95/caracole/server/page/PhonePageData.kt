package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.SongRow
import kotlinx.serialization.json.JsonObject

/**
 * The library page's data and cards from the phone's own library (library_page.song_cards; lane library-cards): every
 * song's card made by the phone, its icons, sites and catalogue still the mirror's ([mirror]). Until its lane lands,
 * it is the mirror's whole ([MirrorPageData]).
 */
class PhonePageData(val mirror: MirrorPageData, val store: LibraryStore, val config: () -> PhoneConfig) :
    PageData, SongCards {
    override fun data(db: Db, now: String): JsonObject = mirror.data(db, now)

    override fun cards(db: Db, songs: List<SongRow>): Map<Long, JsonObject> = mirror.cards(db, songs)
}
