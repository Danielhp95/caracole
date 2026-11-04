package io.github.danielhp95.caracole.core.match

import org.junit.Test
import kotlin.test.assertEquals

/** match.py's names that ug/fetch.py reads. */
class MatchTest {
    @Test fun theNamesArePythons() {
        assertEquals("artist_page", Match.ARTIST_PAGE)
        assertEquals(listOf("word_title", "typo_artist", "catch_all", "title_only"), Match.REVIEW_ONLY_STEPS)
    }
}
