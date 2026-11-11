package io.github.danielhp95.caracole

/**
 * The sync sheet's addresses on the library page (the sync redesign's §3.6): `#sheet=sync`, `#sheet=export` and
 * `#sheet=import` open the page's sheet at that flow, and sync.js takes the word out of the address once it is open.
 * The app has no JavaScript bridge: its bar's sync button, Settings' Export and Import a file, and the unattended
 * sync's notification each load one of these.
 */
object SheetAddress {
    /** The flows the sheet opens at, as MainActivity.SHEET's extra names them. */
    val SHEETS = listOf("sync", "export", "import")

    /** The library page's address ([library], its own fragment dropped) at [sheet]'s flow; the page alone for a word
     * that is none of [SHEETS]. */
    fun of(library: String, sheet: String?): String {
        val page = library.substringBefore('#')
        return if (sheet in SHEETS) "$page#sheet=$sheet" else page
    }
}
