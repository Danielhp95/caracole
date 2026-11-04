package io.github.danielhp95.caracole.core.testing

import io.github.danielhp95.caracole.core.http.HttpRequest
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** The test fixtures a lane builds on: a fake site, the corpus's fixtures, the replays' registry. */
class FakesTest {
    @Test fun aFakeSiteAnswersWhatItWasGivenAndNothingElse() {
        val site = FakeTransport(mapOf("GET https://x.test/1" to FakeTransport.answer(200, "one")))
        assertEquals("one", String(site.send(HttpRequest("GET", "https://x.test/1", emptyList())).body))
        assertFailsWith<AssertionError> { site.send(HttpRequest("GET", "https://x.test/2", emptyList())) }
        assertEquals(listOf("GET https://x.test/1", "GET https://x.test/2"), site.said)
    }

    @Test fun aRecordsFixtureIsReadFromTestsFixtures() {
        assertTrue(Corpus.fixture("guitar/synthetic.gp").isNotEmpty())
    }

    @Test fun everyAreaIsNamedOnce() {
        val names = Replays.all.map { it.area }
        assertEquals(names.size, names.toSet().size)
        assertEquals(listOf("unicode", "keys"), Replays.named(listOf("unicode", "keys")).map { it.area })
        assertFailsWith<IllegalArgumentException> { Replays.named(listOf("nowhere")) }
    }
}
