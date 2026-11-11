package io.github.danielhp95.caracole.server.page.internal.cards

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSheets
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.match.Matcher
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.ug.UgFetch
import java.time.Instant

/**
 * What a card's buy links rest on: todo.songs_to_buy (the to-do page's buy list), over :core's ports of what it asks
 * (ug/fetch.py's fetch_due, UgFetch.fetchDue; ug/index.py's index_state, Matcher.indexState; lacuerda_fetch.may_ask,
 * LaCuerdaSheets.mayAsk), and todo.search_links.
 */
internal object ToBuy {
    /**
     * todo.songs_to_buy's buy list: the wanted songs (not ignored, no audio linked) whose next step is buying the track,
     * once nothing caracole will still do may find them a sheet: matched and fetched, or not found with the index read
     * whole; no fetch due, no LaCuerda check due, no pick on LaCuerda still to come. By id, in [songs]' order.
     */
    fun songsToBuy(db: Db, songs: List<SongRow>, overrides: Overrides, now: Instant, audio: Map<Long, String?>):
        List<SongRow> {
        val partial = Matcher.indexState(db) == "partial"
        val buy = ArrayList<SongRow>()
        for (s in songs) {
            if (s.status != "wanted" || !audio[s.id].isNullOrEmpty() || s.key in overrides.ignore) continue
            if (s.matchDecision !in listOf("accept", "pinned", "not_found")) continue
            val unfetched = s.matchDecision != "not_found" && s.ugCheckedAt.isNullOrEmpty()
            val picked = s.key in overrides.lacuerda && s.lacuerdaCheckedAt == null
            if (unfetched || UgFetch.fetchDue(db, s, overrides, now) || lacuerdaDue(s) || picked) continue
            if (!(partial && s.matchDecision == "not_found")) buy += s
        }
        return buy
    }

    /** todo._lacuerda_due: LaCuerda never answered for the song, and may have it. */
    private fun lacuerdaDue(song: SongRow): Boolean = song.lacuerdaCheckedAt == null && LaCuerdaSheets.mayAsk(song)

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
