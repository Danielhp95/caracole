package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow
import kotlinx.serialization.json.JsonObject

/** search.py: your songs, UG's index and its artists (lane search-ug). */
object Search {
    fun searchLibrary(db: Db, q: String, limit: Int = 10, reading: String? = null): List<LibraryHit> = TODO("lane search-ug")
    fun searchRemoved(db: Db, q: String, limit: Int = 10): List<RemovedHit> = TODO("lane search-ug")
    fun findIndex(db: Db, q: String, artists: Int = 3, songs: Int = 8, reading: String? = null): IndexFound =
        TODO("lane search-ug")
    fun found(library: List<LibraryHit>, index: IndexFound): Found = TODO("lane search-ug")
    fun artistSongs(db: Db, artistKey: String, limit: Int = 50, offset: Int = 0, title: String? = null): Pair<List<IndexHit>, Int> =
        TODO("lane search-ug")
    fun indexArtist(db: Db, artistKey: String): ArtistHit? = TODO("lane search-ug")
    fun libraryByArtist(songs: List<SongRow>, name: String, artistKey: String? = null): List<SongRow> = TODO("lane search-ug")
    fun bareIdHint(q: String, hits: List<Any>, artist: String? = null): String? = TODO("lane search-ug")
    fun bareIdUnseen(q: String, hits: List<Any>): JsonObject? = TODO("lane search-ug")
    fun noOnes(artistKey: String): Boolean = TODO("lane search-ug")
}
