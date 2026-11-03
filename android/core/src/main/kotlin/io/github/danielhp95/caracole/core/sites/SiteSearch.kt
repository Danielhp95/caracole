package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.search.SiteArtist
import io.github.danielhp95.caracole.core.search.SiteHit

/** search.py's other sites: gtptabs.com, MuseScore, harptabs.com, gametabs.net (lane search-sites). */
object SiteSearch {
    fun searchGtptabs(db: Db, q: String, limit: Int = 5): List<SiteHit> = TODO("lane search-sites")
    fun gtptabsSongs(db: Db, artist: String): Int = TODO("lane search-sites")
    fun searchMusescore(db: Db, q: String, limit: Int = 5): List<SiteHit> = TODO("lane search-sites")
    fun searchHarptabs(db: Db, q: String, songs: Int = 5, artists: Int = 3): Pair<List<SiteArtist>, List<SiteHit>> =
        TODO("lane search-sites")
    fun harptabsArtist(db: Db, path: String): SiteArtist? = TODO("lane search-sites")
    fun harptabsSongs(db: Db, path: String, title: String? = null): List<SiteHit> = TODO("lane search-sites")
    fun searchGametabs(db: Db, q: String, limit: Int = 5): List<SiteHit> = TODO("lane search-sites")
}
