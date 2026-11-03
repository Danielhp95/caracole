package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.server.page.SongCards
import io.github.danielhp95.caracole.server.testing.json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.net.URLEncoder
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ExecutionException
import java.util.concurrent.Executors
import java.util.concurrent.Future
import java.util.concurrent.TimeUnit
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * One search at a time, the newest of each box winning (search_routes.api_search's `_searching` and `_newest`): a
 * search typed on in the same box stops the one before it, running or waiting, which answers `superseded`; a search
 * of another box never stops one, and both are answered.
 */
class SupersedeTest {
    @get:Rule val tmp = TemporaryFolder()

    private val pool = Executors.newCachedThreadPool()

    @After
    fun stop() {
        pool.shutdownNow()
    }

    /** A search of [box] that runs until [release] once it has begun ([begun]), on a thread of its own. */
    private inner class Held(val searches: Searches, box: String, val answer: String) {
        val begun = CountDownLatch(1)
        val release = CountDownLatch(1)
        val result: Future<String?> = pool.submit<String?> {
            searches.search(box) { ticket ->
                begun.countDown()
                release.await(10, TimeUnit.SECONDS)
                ticket.check()  // between two queries
                answer
            }
        }
    }

    private fun waitFor(what: String, condition: () -> Boolean) {
        val until = System.nanoTime() + TimeUnit.SECONDS.toNanos(10)
        while (!condition()) {
            check(System.nanoTime() < until) { "no $what within 10 s" }
            Thread.sleep(2)
        }
    }

    @Test
    fun a_second_search_of_the_same_box_supersedes_the_first() {
        val searches = Searches()
        val first = Held(searches, "box-1", "first")
        assertTrue(first.begun.await(10, TimeUnit.SECONDS))
        val second = pool.submit<String?> { searches.search("box-1") { "second" } }
        waitFor("search waiting") { searches.waiting == 1 }
        first.release.countDown()
        assertNull(first.result.get(10, TimeUnit.SECONDS), "the first, typed over, is superseded")
        assertEquals("second", second.get(10, TimeUnit.SECONDS))
    }

    @Test
    fun another_boxs_search_never_does() {
        val searches = Searches()
        val first = Held(searches, "box-1", "first")
        assertTrue(first.begun.await(10, TimeUnit.SECONDS))
        val other = pool.submit<String?> { searches.search("box-2") { "other" } }
        waitFor("search waiting") { searches.waiting == 1 }
        first.release.countDown()
        assertEquals("first", first.result.get(10, TimeUnit.SECONDS))
        assertEquals("other", other.get(10, TimeUnit.SECONDS))
    }

    @Test
    fun a_search_waiting_its_turn_is_superseded_before_it_begins() {
        val searches = Searches()
        val running = Held(searches, "box-1", "running")
        assertTrue(running.begun.await(10, TimeUnit.SECONDS))
        var ran = false
        val waiting = pool.submit<String?> { searches.search("box-2") { ran = true; "older" } }
        waitFor("search waiting") { searches.waiting == 1 }
        val newer = pool.submit<String?> { searches.search("box-2") { "newer" } }
        waitFor("second search waiting") { searches.waiting == 2 }
        running.release.countDown()
        assertEquals("running", running.result.get(10, TimeUnit.SECONDS))
        assertNull(waiting.get(10, TimeUnit.SECONDS))
        assertEquals("newer", newer.get(10, TimeUnit.SECONDS))
        assertFalse(ran, "a search typed over before its turn reads nothing")
    }

    @Test
    fun a_search_of_no_box_is_of_one_box_with_every_other_such() {
        val searches = Searches()
        val first = searches.ask("")
        searches.ask("")
        assertTrue(first.over)
    }

    @Test
    fun a_box_forgotten_has_its_search_as_its_newest() {
        val searches = Searches(boxes = 3)
        val old = searches.ask("a")
        for (box in listOf("b", "c", "d")) searches.ask(box)  // "a" asked least lately: forgotten
        assertFalse(old.over)
        searches.ask("a")
        assertTrue(old.over)
    }

    // --- through the route, over the ug fixture ---------------------------------------------------------------------

    /** Cards that hold the first search that asks for them until [release]: a search halfway, its queries made. */
    private class HoldingCards : SongCards {
        val begun = CountDownLatch(1)
        val release = CountDownLatch(1)
        @Volatile private var first = true

        override fun cards(db: Db, songs: List<SongRow>): Map<Long, JsonObject> {
            if (first) {
                first = false
                begun.countDown()
                release.await(10, TimeUnit.SECONDS)
            }
            return PageCards.cards(db, songs)
        }
    }

    private fun search(q: String, box: String) = "/api/search?q=${URLEncoder.encode(q, Charsets.UTF_8)}&box=$box"

    /** [first] started on a thread of its own, and seen to be halfway (or, waiting on a lane, the test skipped). */
    private fun started(search: SearchApp, cards: HoldingCards, first: String): Future<JsonObject> {
        val answer = pool.submit<JsonObject> { search.app.get(first).json.jsonObject }
        while (!cards.begun.await(5, TimeUnit.MILLISECONDS)) {
            if (answer.isDone) {
                try {
                    answer.get()
                } catch (e: ExecutionException) {
                    Producers.needs { throw e.cause!! }
                }
                error("the first search ended without asking for its cards")
            }
        }
        return answer
    }

    @Test
    fun through_the_route_a_search_typed_on_in_its_box_answers_superseded() {
        val cards = HoldingCards()
        SearchApp(tmp.newFolder("ug"), "ug", cards).use { search ->
            val first = started(search, cards, search("creep", "page-1"))
            val second = pool.submit<JsonObject> { search.app.get(search("creep radiohead", "page-1")).json.jsonObject }
            waitFor("search waiting") { search.routes.searches.waiting == 1 }
            cards.release.countDown()
            assertEquals(obj("query" to "creep", "superseded" to true), first.get(10, TimeUnit.SECONDS))
            val answer = second.get(10, TimeUnit.SECONDS)
            assertEquals("creep radiohead", answer.getValue("query").toString().trim('"'))
            assertTrue("looked" in answer)
        }
    }

    @Test
    fun through_the_route_another_boxs_search_waits_its_turn_and_both_are_answered() {
        val cards = HoldingCards()
        SearchApp(tmp.newFolder("ug"), "ug", cards).use { search ->
            val first = started(search, cards, search("creep", "page-1"))
            val other = pool.submit<JsonObject> { search.app.get(search("creep radiohead", "page-2")).json.jsonObject }
            waitFor("search waiting") { search.routes.searches.waiting == 1 }
            cards.release.countDown()
            val answer = first.get(10, TimeUnit.SECONDS)
            assertFalse("superseded" in answer)
            assertTrue("looked" in answer)
            assertTrue("looked" in other.get(10, TimeUnit.SECONDS))
        }
    }
}
