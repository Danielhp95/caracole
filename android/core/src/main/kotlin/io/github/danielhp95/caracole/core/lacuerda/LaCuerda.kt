package io.github.danielhp95.caracole.core.lacuerda

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.search.IndexFound
import io.github.danielhp95.caracole.core.search.SiteArtist
import io.github.danielhp95.caracole.core.search.SiteHit
import kotlinx.serialization.json.JsonObject

/** lacuerda_index.py's read side and search.py's LaCuerda glue (lane search-lacuerda; the keys are lane keys'). */
object LaCuerda {
    fun nameKey(name: String): String = Normalize.lacuerdaNameKey(name)
    fun titleKey(title: String): String = Normalize.lacuerdaTitleKey(title)

    fun searchLacuerda(db: Db, q: String, songs: Int = 5, artists: Int = 3): Pair<List<SiteArtist>, List<SiteHit>> =
        TODO("lane search-lacuerda")
    fun lacuerdaArtist(db: Db, slug: String): SiteArtist? = TODO("lane search-lacuerda")
    fun lacuerdaArtistNamed(db: Db, name: String): SiteArtist? = TODO("lane search-lacuerda")
    fun lacuerdaSongs(db: Db, slug: String, title: String? = null): List<SiteHit> = TODO("lane search-lacuerda")
    fun lacuerdaLeftOut(db: Db): Pair<String, String>? = TODO("lane search-lacuerda")
    fun lacuerdaLeads(ug: IndexFound, lc: List<SiteArtist>): Boolean = TODO("lane search-lacuerda")
    fun lettersRead(db: Db): JsonObject = TODO("lane search-lacuerda")
    fun ensureCurrentKeys(db: Db): Int = TODO("lane search-lacuerda")
}
