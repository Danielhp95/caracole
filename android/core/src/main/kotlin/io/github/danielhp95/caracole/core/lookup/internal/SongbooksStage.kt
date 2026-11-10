package io.github.danielhp95.caracole.core.lookup.internal

import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.SongbookStats
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.songbooks.SongbookError

/** get.py's songbooks stage over its parts, which the frame gives it and LookupReplay replays it with. */
internal object SongbooksStage {
    /**
     * [read] songbooks.toml's songbooks (a [SongbookError] its words, nothing made), [leaves] the lookup's
     * `--no-songbooks`, [listing] the names of those that list the song, [running] the second running event with
     * them (for the line's "Remaking songbook X…"), [render] them made again: the stage's end, get.py's.
     */
    fun <B> end(read: () -> List<B>, leaves: Boolean, listing: (List<B>) -> List<String>,
                running: (String) -> Unit, render: (Set<String>) -> SongbookStats): StageEnd {
        val books = try {
            read()
        } catch (e: SongbookError) {
            return StageEnd("skipped", LookupWords.songbooksUnread(e.message))
        }
        if (leaves) return StageEnd("skipped", LookupWords.SONGBOOKS_LEFT)
        val mine = listing(books)
        if (mine.isEmpty()) return StageEnd("skipped", LookupWords.NO_SONGBOOK)
        val names = mine.joinToString(", ")
        running(names)
        return LookupWords.songbooksEnd(names, render(LinkedHashSet(mine)))
    }
}
