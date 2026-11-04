package io.github.danielhp95.caracole.core.lacuerda

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import java.time.Instant

/** /api/search's `lacuerda_search`: whether the pages may send LaCuerda's own search (auto, button, failed, off…). */
data class SearchGate(val state: String, val query: String, val key: String, val why: String?)

/** lacuerda.LCArtist. */
data class LaCuerdaArtist(val slug: String, val name: String, val songs: Int)

/** lacuerda.LCSong: [types] one letter a version, version 1 first; [ranking] its versions' order. */
data class LaCuerdaSong(val slug: String, val title: String, val types: String, val ranking: List<Int>, val lcd: String = "")

/** lacuerda.SearchSong. */
data class LaCuerdaSearchSong(val artistSlug: String, val artist: String, val song: LaCuerdaSong)

/** lacuerda.SearchAnswer: what LaCuerda's search answered. */
data class LaCuerdaSearchAnswer(val songs: List<LaCuerdaSearchSong> = emptyList(),
                                val artists: List<LaCuerdaArtist> = emptyList(), val stated: Int = 0)

/** lacuerda_search.py: LaCuerda's own search, one query at the lookup pace, and its gate. */
object LaCuerdaSearch {
    fun queryKey(q: String): String? = TODO("lane lacuerda-pages")
    fun gate(cfg: PhoneConfig, db: Db, q: String, now: Instant): SearchGate? = TODO("lane lacuerda-pages")
    fun search(db: Db, client: Client, q: String, now: Instant): LaCuerdaSearchAnswer = TODO("lane lacuerda-pages")
}
