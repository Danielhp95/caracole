package io.github.danielhp95.caracole.core.http

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.HttpReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** robots.txt's closed paths (http.ROBOTS_DISALLOW as data): vectors/http/robots.jsonl, and the rules of rules.jsonl. */
class RobotsTest {
    @Test fun everyUrlIsClosedOrOpenAsPythonSays() {
        val misses = Misses("http/robots.jsonl")
        HttpReplay.robots(misses)
        misses.assertNone()
    }

    @Test fun staleRetryAfterAndChallengesAreHttpPys() {
        val misses = Misses("http/rules.jsonl")
        HttpReplay.rules(misses)
        misses.assertNone()
    }

    @Test fun aRuleNamesItselfAndAStarOrADollarReadsAsRfc9309s() {
        assertEquals("/tab/track/", Robots.disallows("https://tabs.ultimate-guitar.com/tab/track/ave-fenix-guitar-pro-1149792"))
        assertEquals("/score/*/download/*", Robots.disallows("https://musescore.com/score/6159957/download/pdf"))
        assertEquals("/*.php$", Robots.disallows("https://gametabs.net/x.php"))
        assertNull(Robots.disallows("https://gametabs.net/x.php?a=1"))
        assertNull(Robots.disallows("https://acordes.lacuerda.net/tabs/e/index0.html"))
        assertEquals(Robots.NOT_A_URL, Robots.disallows("https://[::zz]/tab/1"))
    }
}
