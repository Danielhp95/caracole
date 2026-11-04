package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.library.SongRow
import java.time.Instant

/** ug/fetch.py for a lookup's song: its sheet, its versions and its tab. */
object UgFetch {
    fun processSong(ctx: FetchContext, song: SongRow, guitar: Boolean = true): SongFetchOutcome = TODO("lane ug-fetch-sheet")

    /** kept, same, held, sheet, gone, unreadable, closed, no text or unknown. */
    fun keepVersion(ctx: FetchContext, song: SongRow, tabId: Long): String = TODO("lane ug-fetch-sheet")
    fun checkedSince(song: SongRow, since: Instant): Boolean = TODO("lane ug-fetch-sheet")
}
