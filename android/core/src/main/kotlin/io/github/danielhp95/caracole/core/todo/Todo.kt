package io.github.danielhp95.caracole.core.todo

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSheets
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.match.Matcher
import io.github.danielhp95.caracole.core.ug.UgFetch
import java.time.Instant

/**
 * todo.py's rule of the songs whose next step is buying the track, over :core's ports of what it asks (ug/fetch.py's
 * fetch_due, UgFetch.fetchDue; ug/index.py's index_state, Matcher.indexState; lacuerda_fetch.may_ask,
 * LaCuerdaSheets.mayAsk): the library page's cards' buy links and the phone's YouTube pass (core.youtube.Due) read it.
 */
object Todo {
    /**
     * todo.songs_to_buy's buy list: the wanted songs (not ignored, no audio linked: [audio] by id, the song's own
     * `audio_path` where it names none) whose next step is buying the track, once nothing caracole will still do may
     * find them a sheet: matched and fetched, or not found with the index read whole; no fetch due, no LaCuerda check
     * due, no pick on LaCuerda still to come. In [songs]' order.
     */
    fun songsToBuy(db: Db, songs: List<SongRow>, overrides: Overrides, now: Instant,
                   audio: Map<Long, String?> = emptyMap()): List<SongRow> {
        val partial = Matcher.indexState(db) == "partial"
        val buy = ArrayList<SongRow>()
        for (s in songs) {
            val path = if (s.id in audio) audio[s.id] else s.audioPath
            if (s.status != "wanted" || !path.isNullOrEmpty() || s.key in overrides.ignore) continue
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
}
