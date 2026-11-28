package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.testing.replays.LyricsRoutesReplay
import io.github.danielhp95.caracole.server.testing.replays.WebReplay
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertTrue

/** POST /lyrics/search, GET /api/lyrics/search, POST /lyrics/pick and POST /lyrics/clear on the phone against
 * caracole serve's answers (vectors/web/lyrics_routes.jsonl, WebReplay.lyricsRoutes). */
class LyricsRoutesTest {
    @Test fun eachRouteAnswersAsCaracoleServesDoes() =
        Misses("web/lyrics_routes.jsonl").also { WebReplay.lyricsRoutes(it) }.assertNone()

    @Test fun theVectorHoldsEveryRouteAndItsRefusals() {
        val fns = Corpus.lines(LyricsRoutesReplay.VECTOR).filter { it["header"] != JsonPrimitive(true) }
            .map { it.getValue("fn").jsonPrimitive.content }.toSet()
        assertTrue(fns.containsAll(setOf("GET /api/lyrics/search", "POST /lyrics/search", "POST /lyrics/pick",
                                         "POST /lyrics/clear")), "$fns")
    }
}
