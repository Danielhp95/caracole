package io.github.danielhp95.caracole

/**
 * What the library screen keeps when Android recreates it: the WebView's history, with the origin it was at
 * ([ORIGIN]). A launch's server may take another port than the last's (8738 taken): pages of another origin are
 * never loaded, so the history comes back only at today's. A screen recreated because the WebView's renderer died
 * has no history to save (its WebView is gone): the page it showed ([GONE_AT]) is opened again instead.
 */
internal object SavedScreen {
    const val ORIGIN = "caracole-origin"

    /** The page a screen showed as its renderer died. */
    const val GONE_AT = "caracole-gone-at"

    fun restores(saved: String?, origin: String): Boolean = !saved.isNullOrEmpty() && saved == origin

    /** The page to open again after the renderer died: the one it showed ([goneAt]), saved at today's [origin], when
     * the WebView loads it ([loads]: the server's own pages alone); null otherwise. */
    fun reopened(goneAt: String?, saved: String?, origin: String, loads: (String) -> Boolean): String? =
        goneAt?.takeIf { restores(saved, origin) && it.startsWith("$origin/") && loads(it) }
}
