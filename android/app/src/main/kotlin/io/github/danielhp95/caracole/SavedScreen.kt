package io.github.danielhp95.caracole

/**
 * What the library screen keeps when Android recreates it: the WebView's history, with the origin it was at
 * ([ORIGIN]). A launch's server may take another port than the last's (8738 taken): pages of another origin are
 * never loaded, so the history comes back only at today's.
 */
internal object SavedScreen {
    const val ORIGIN = "caracole-origin"

    fun restores(saved: String?, origin: String): Boolean = !saved.isNullOrEmpty() && saved == origin
}
