package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.testing.replays.UgLinkReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** Area ug-link: vectors/web/ug_link.jsonl (read_link, both routes over each scene) and
 * vectors/lookup/commands_ug_link.jsonl (`caracole ug --link`), answered as Python answered them. */
class UgLinkReplayTest {
    @Test fun `every shape is read as Python reads it`() {
        val misses = Misses("ug-link: read_link")
        UgLinkReplay.links(misses)
        misses.assertNone()
    }

    @Test fun `each route answers as caracole serve's over each scene`() {
        val misses = Misses("ug-link: the routes")
        UgLinkReplay.routes(misses)
        misses.assertNone()
        assertTrue(misses.checked > 20, "${misses.checked} answers checked")
    }

    @Test fun `caracole ug --link reads, records and says what Python's does`() {
        val misses = Misses("ug-link: the command")
        UgLinkReplay.commands(misses)
        misses.assertNone()
    }

    /** A block during the link's read, of its tab's page or of its artist's, is told once, as every lookup's block is
     * on the phone (InteractiveAsk's Alerts.blocked): the computer's command sends none. */
    @Test fun `a block of the tab's page or of its artist's page is told once`() {
        val told = LinkedHashMap<String, Int>()
        val misses = Misses("ug-link: the command, its alerts")
        UgLinkReplay.commands(misses, told)
        misses.assertNone()
        assertEquals(mapOf("a block" to 1, "a block of the artist's page, the tab read" to 1), told)
    }
}
