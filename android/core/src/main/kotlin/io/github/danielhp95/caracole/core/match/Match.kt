package io.github.danielhp95.caracole.core.match

/** match.py's names: its decisions and steps, the catch-alls step 4 reads, and the few ug/fetch.py imports. */
object Match {
    const val ARTIST_PAGE = "artist_page"  // the fetch step's matches on UG artist pages (A6)

    /** match.DECISIONS. */
    val DECISIONS: List<String> = listOf("accept", "review", "not_found", "pinned", "ignored")

    /** Names that aren't quite UG's (step 4). */
    val TOLERANT_STEPS: List<String> = listOf("word_title", "typo_artist", "catch_all")

    /** match.STEPS. */
    val STEPS: List<String> = listOf("override", "pin", "exact", "alias", "fuzzy_title", "fuzzy_artist") +
        TOLERANT_STEPS + "title_only"

    /** match.LADDER_STEPS: the index's. */
    val LADDER_STEPS: List<String> = listOf("exact", "alias", "fuzzy_title", "fuzzy_artist") + TOLERANT_STEPS +
        "title_only"

    /** Steps that never accept: a review made only of these leaves the song to its artist's UG page too. */
    val REVIEW_ONLY_STEPS: List<String> = TOLERANT_STEPS + "title_only"

    /** Steps whose candidate is filed under another artist than the song's: choosing one makes no [alias]. */
    val NO_ALIAS_STEPS: List<String> = listOf("catch_all", "title_only")

    const val CATCH_ALL_PREFIX = "misc-"

    /** Two songs in one title: neither is the one you want. */
    val NOT_CATCH_ALL: Set<String> = setOf("misc-mashups")

    /** The catch-alls step 4 reads that file a show's songs, the show's name anywhere in the title. */
    val SHOW_CATCH_ALLS: Set<String> = setOf("misc-musicals", "misc-soundtrack", "misc-cartoons", "misc-television",
                                             "misc-computer-games")

    /** A performer's catch-alls, which start each title with the performer's name. */
    val PERFORMER_CATCH_ALLS: Set<String> = setOf("misc-originals", "misc-unsigned-bands")

    /** A show's catch-all title that ends in yours: "hamilton-my-shot" for "My Shot". */
    const val CATCH_ALL_ENDING = 90.0
    const val MAX_CANDIDATES = 5

    /** A review keeps the best hit of each among its [MAX_CANDIDATES], however many others score more. */
    val KEPT_STEPS: List<String> = listOf("catch_all", "typo_artist")

    /** Words a catch-all title may put next to a show's name: "epic-the-musical-not-sorry-for-loving-you". */
    val SHOW_WORDS: Set<String> = setOf(
        "the", "musical", "soundtrack", "ost", "movie", "film", "show", "series", "tv", "theme", "from",
        "original", "cast", "broadway", "game", "anime", "opening", "ending",
    )

    /** match.is_catch_all: every `misc-…` key but `misc-mashups`. */
    fun isCatchAll(artistKey: String): Boolean = artistKey.startsWith(CATCH_ALL_PREFIX) && artistKey !in NOT_CATCH_ALL
}
