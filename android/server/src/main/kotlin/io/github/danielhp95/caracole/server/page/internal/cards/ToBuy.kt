package io.github.danielhp95.caracole.server.page.internal.cards

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.todo.Todo
import java.time.Instant

/**
 * What a card's buy links rest on: todo.songs_to_buy (the to-do page's buy list, :core's Todo), and todo.search_links.
 */
internal object ToBuy {
    /** todo.songs_to_buy's buy list, :core's Todo.songsToBuy ([audio] the songs' linked audio, by id). */
    fun songsToBuy(db: Db, songs: List<SongRow>, overrides: Overrides, now: Instant, audio: Map<Long, String?>):
        List<SongRow> = Todo.songsToBuy(db, songs, overrides, now, songs.associate { it.id to audio[it.id] })

    /** todo.search_links: where to look for what caracole won't do itself: buying, Chordify, Songsterr, YouTube. */
    fun searchLinks(artist: String, title: String): Map<String, String> {
        val q = "$artist ${Normalize.cleanTitle(title)}"
        val lesson = if (Normalize.hasHan(q)) "$q 吉他教学" else "$q guitar lesson"
        val quoted = PyUrl.quote(q)
        return linkedMapOf(
            "bandcamp" to "https://bandcamp.com/search?q=$quoted&item_type=t",
            "qobuz" to "https://www.qobuz.com/us-en/search?q=$quoted",
            "itunes" to "https://music.apple.com/us/search?term=$quoted",
            "chordify" to "https://chordify.net/search/$quoted",
            "songsterr" to "https://www.songsterr.com/?pattern=$quoted",
            "youtube" to "https://www.youtube.com/results?search_query=${PyUrl.quote(lesson)}",
        )
    }
}
