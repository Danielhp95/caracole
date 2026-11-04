package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.library.internal.overrides.Addresses

/**
 * overrides.LaCuerdaPick: a LaCuerda song you picked (`[lacuerda]`), its artist's slug and its own, and the version
 * whose sheet you picked ([version] its `-N` page, 1 its first, null the song's best Letra y Acordes version).
 */
data class LaCuerdaPick(val artist: String, val song: String, val version: Int? = null) {
    /** The song's page, or the version's: as caracole writes the pick and asks for it. */
    val url: String
        get() = if (version == null) {
            "${Addresses.LACUERDA_BASE}/$artist/$song"
        } else {
            "${Addresses.LACUERDA_BASE}/$artist/$song${if (version == 1) "" else "-$version"}.shtml"
        }

    /** Whether a LaCuerda version, by its tab id (`artist/song-N`, as lacuerda_fetch.py records it), is the one
     * picked: that version, or for a song, any of its versions. */
    fun holds(tabId: String): Boolean {
        val artist = tabId.substringBefore('/')
        val rest = tabId.substringAfter('/', "")
        val dash = rest.lastIndexOf('-')
        if (dash < 0) return false
        val song = rest.substring(0, dash)
        val n = rest.substring(dash + 1)
        return artist == this.artist && song == this.song && (version == null || n == version.toString())
    }
}

/** overrides.HarpTabsPick: a harptabs.com tab you picked (`[harptabs]`), the site's id of it and its page's slug. */
data class HarpTabsPick(val tabId: Long, val slug: String) {
    /** Its page's path, as harptabs.com's index keeps it (`tab/25/piano-man`). */
    val path: String get() = "tab/$tabId/$slug"

    /** Its page: as caracole writes the pick and asks for it. */
    val url: String get() = "${Addresses.HARPTABS_BASE}/$path"
}

/** overrides.GameTabsPick: a gametabs.net tab you picked (`[gametabs]`), its game's slug and its own. */
data class GameTabsPick(val game: String, val slug: String) {
    /** Its page's path, as gametabs.net's index keeps it (`tabs/actraiser/fillmore`). */
    val path: String get() = "tabs/$game/$slug"

    /** Its page: as caracole writes the pick and asks for it. */
    val url: String get() = "${Addresses.GAMETABS_BASE}/$path"
}

/** ug/sitemap.IndexRow: the index row a tab page's address gives (`OverrideUrls.classifyTabUrl`), its keys
 * canonical (`ug_slug_key`) and [path] the address after `/tab/` as it is. */
data class TabUrlRow(val tabId: Long, val artistKey: String, val songKey: String, val type: String, val path: String)
