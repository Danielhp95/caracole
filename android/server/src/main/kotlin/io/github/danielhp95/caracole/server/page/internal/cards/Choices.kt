package io.github.danielhp95.caracole.server.page.internal.cards

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.match.Match
import io.github.danielhp95.caracole.core.match.MatchCandidate
import io.github.danielhp95.caracole.core.match.Matcher
import io.github.danielhp95.caracole.core.search.Search
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * A song in review's candidates as its picker shows them: library_page.review_choices, over review.py's
 * candidates_of, ref and step_words and search.index_song. The review lane's page reads them too.
 */
internal object Choices {
    /** review.SHOWN: the candidates a review lists, numbered 1 to 9. */
    const val SHOWN = 9

    /** review.SEARCH: the step of a candidate caracole search found, for a song not found. */
    const val SEARCH = "search"

    /** review._STEP_WORDS: why the matcher thought of a candidate, by the step that found it. */
    private val STEP_WORDS = mapOf(
        SEARCH to "a caracole search hit for its artist and title",
        "exact" to "same artist and title",
        "alias" to "under the artist's [alias]",
        "fuzzy_title" to "title spelled differently",
        "fuzzy_artist" to "artist spelled differently",
        "word_title" to "a title of the artist's with words more or fewer",
        "typo_artist" to "artist a letter or two off",
        "title_only" to "title only: another artist's song, probably a cover",
        "override" to "your [match] in overrides.toml",
        "pin" to "pinned in overrides.toml",
        "artist_page" to "on the artist's UG page",
    )

    /** library_page._TAB_KINDS: a UG tab type as a picker names it. */
    private val TAB_KINDS = mapOf("chords" to "Chords", "tabs" to "Tabs", "ukulele" to "Ukulele Chords")

    /** review.candidates_of: the song's stored candidates that name a UG song, best first, nine at most. */
    fun candidatesOf(song: SongRow): List<MatchCandidate> = Matcher.candidatesOf(song).take(SHOWN)

    /** review.ref: a candidate as overrides.toml names a UG song, "artist-key/song-key". */
    fun ref(cand: MatchCandidate): String = "${cand.artistKey}/${cand.songKey}"

    /** review.step_words: why the matcher thought of a candidate, in plain words; an unknown step as it is. */
    fun stepWords(cand: MatchCandidate): String {
        val step = cand.step ?: ""
        if (step == "catch_all") {
            val performer = if (cand.artistKey in Match.PERFORMER_CATCH_ALLS) ", the performer's name first" else ""
            return "under UG's catch-all ${cand.artistKey}$performer"
        }
        return STEP_WORDS[step] ?: step
    }

    /** library_page.review_choices: each candidate ([cands], else the song's own) as the picker shows it, numbered:
     * its ref, its artist and title as UG writes them (named from its keys when the index no longer has it, with no
     * tabs and no page), its score rounded, why, its tabs per type and its UG page. */
    fun reviewChoices(db: Db, song: SongRow, cands: List<MatchCandidate>? = null): List<JsonObject> =
        (cands ?: candidatesOf(song)).mapIndexed { i, cand ->
            val hit = Search.indexSong(db, cand.artistKey, cand.songKey)
            val (artist, title) = if (hit != null) hit.artist to hit.title
                                  else Search.displayFromKeys(cand.artistKey, cand.songKey)
            JsonObject(linkedMapOf(
                "n" to JsonPrimitive(i + 1),
                "ref" to JsonPrimitive(ref(cand)),
                "artist" to JsonPrimitive(artist),
                "title" to JsonPrimitive(title),
                "score" to JsonPrimitive(Math.rint(cand.score ?: 0.0).toLong()),
                "why" to JsonPrimitive(stepWords(cand)),
                "tabs" to JsonPrimitive(hit?.let { tabCounts(it.counts) } ?: ""),
                "href" to JsonPrimitive(hit?.url ?: ""),
            ))
        }

    /** library_page._tab_counts: "Chords ×2 · Tabs ×1", a UG song's tabs per type, in the hit's order. */
    private fun tabCounts(counts: Map<String, Int>): String =
        counts.entries.joinToString(" · ") { (kind, n) -> "${TAB_KINDS[kind] ?: kind} ×$n" }
}
