package io.github.danielhp95.caracole.core.lookup.internal

import io.github.danielhp95.caracole.core.library.GameTabsPick
import io.github.danielhp95.caracole.core.library.HarpTabsPick
import io.github.danielhp95.caracole.core.library.LaCuerdaPick

/**
 * overrides.py's picks' pages, as a lookup records and reads them: LaCuerdaPick.url and holds, HarpTabsPick.url and
 * GameTabsPick.url. Phase A's (waiting on overrides-model, whose Picks.kt gives each pick these members): Phase B
 * reads the picks' own and drops this file.
 */
internal object PickPages {
    private const val LACUERDA_BASE = "https://acordes.lacuerda.net"
    private const val HARPTABS_BASE = "https://www.harptabs.com"
    private const val GAMETABS_BASE = "https://gametabs.net"

    /** LaCuerdaPick.url: the song's page, or the version's. */
    fun url(pick: LaCuerdaPick): String = if (pick.version == null) {
        "$LACUERDA_BASE/${pick.artist}/${pick.song}"
    } else {
        "$LACUERDA_BASE/${pick.artist}/${pick.song}${if (pick.version == 1) "" else "-${pick.version}"}.shtml"
    }

    /** HarpTabsPick.url. */
    fun url(pick: HarpTabsPick): String = "$HARPTABS_BASE/tab/${pick.tabId}/${pick.slug}"

    /** GameTabsPick.url. */
    fun url(pick: GameTabsPick): String = "$GAMETABS_BASE/tabs/${pick.game}/${pick.slug}"

    /** LaCuerdaPick.holds: whether a LaCuerda version, by its tab id (`artist/song-N`), is the one picked: that
     * version, or for a song, any of its versions. */
    fun holds(pick: LaCuerdaPick, tabId: String): Boolean {
        val slash = tabId.indexOf('/')
        val artist = if (slash >= 0) tabId.substring(0, slash) else tabId
        val rest = if (slash >= 0) tabId.substring(slash + 1) else ""
        val dash = rest.lastIndexOf('-')
        if (dash < 0) return false
        return artist == pick.artist && rest.substring(0, dash) == pick.song &&
            (pick.version == null || rest.substring(dash + 1) == pick.version.toString())
    }
}
