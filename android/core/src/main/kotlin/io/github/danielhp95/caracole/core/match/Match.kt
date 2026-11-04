package io.github.danielhp95.caracole.core.match

/** match.py's names that ug/fetch.py reads. */
object Match {
    const val ARTIST_PAGE = "artist_page"  // the fetch step's matches on UG artist pages (A6)
    val TOLERANT_STEPS: List<String> = listOf("word_title", "typo_artist", "catch_all")

    /** Steps that never accept: a review made only of these leaves the song to its artist's UG page too. */
    val REVIEW_ONLY_STEPS: List<String> = TOLERANT_STEPS + "title_only"
}
