package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.db.Db

/** ug/lookup.py's IndexTab: a tab of the sitemap index. */
data class IndexTab(val tabId: Long, val artistKey: String, val songKey: String, val type: String, val path: String?)

/** ug/lookup.py: the sitemap index's tabs, and the artist pages learned. */
object UgLookup {
    fun songTabs(db: Db, artistKey: String, songKey: String): List<IndexTab> = TODO("lane ug-pages")
    fun artistKnown(db: Db, artistKey: String): Boolean = TODO("lane ug-pages")
    fun learnedArtistUrl(db: Db, artistKey: String): String? = TODO("lane ug-pages")
    fun rememberArtistUrl(db: Db, artistKey: String, url: String): Unit = TODO("lane ug-pages")
    fun forgetArtistUrl(db: Db, artistKey: String): Unit = TODO("lane ug-pages")
    fun indexTab(db: Db, tabId: Long): IndexTab? = TODO("lane ug-pages")
    fun tabUrlFor(db: Db, tabId: Long): String = TODO("lane ug-pages")
    fun artistTabs(db: Db, artistKey: String, limit: Int = 5): List<IndexTab> = TODO("lane ug-pages")
}
