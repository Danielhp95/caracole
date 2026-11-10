package io.github.danielhp95.caracole.core.share

import io.github.danielhp95.caracole.core.names.SongNames
import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlin.test.fail

/**
 * A song shared from a music app, read as [SharedText] reads it: every share of tests/fixtures/share/shares.jsonl
 * (what each app sends, and where that was found) to the app, the text and the link it reads, and the names
 * read_names then reads of that text with nothing known (no library, no index: SongNames.readNames(null, …)); and
 * the rules one at a time.
 */
class SharedTextTest {
    private fun text(o: JsonObject, name: String): String? = (o[name] as? JsonPrimitive)?.takeUnless { it is JsonNull }?.content

    @Test fun `every share in the fixture is read as it says`() {
        val shares = Corpus.fixture("share/shares.jsonl").toString(Charsets.UTF_8).split('\n')
            .filter { it.isNotEmpty() }.map { Json.parseToJsonElement(it).jsonObject }
        assertTrue(shares.size >= 10, "${shares.size} shares")
        val wrong = mutableListOf<String>()
        for (share in shares) {
            val source = text(share, "source")
            if (source.isNullOrEmpty()) wrong += "${share["sender"]}: no source"
            val got = SharedText.read(text(share, "text"), text(share, "subject"), text(share, "title"), text(share, "package"))
            val want = Shared(text(share, "app"), text(share, "said"), text(share, "link"))
            if (got != want) wrong += "${text(share, "text")} / ${text(share, "subject")}: $got, not $want"
            val names = (share["names"] as? JsonArray)?.map { (it as JsonPrimitive).content }?.let { it[0] to it[1] }
            val read = got.said?.let { SongNames.readNames(null, it, emptyList()) }
            if (read != names) wrong += "${got.said}: read_names gives $read, not $names"
        }
        if (wrong.isNotEmpty()) fail(wrong.joinToString("\n"))
    }

    @Test fun `a link alone names no song, and its app is its host's`() {
        assertEquals(Shared("Spotify", null, "https://open.spotify.com/track/7tFiyTwD0nx5a1eklYtX2J?si=1a"),
                     SharedText.read("https://open.spotify.com/track/7tFiyTwD0nx5a1eklYtX2J?si=1a", null, null, null))
        assertEquals(Shared(null, null, "https://example.org/x"), SharedText.read("  https://example.org/x.  ", "", null, null))
    }

    @Test fun `the sender's package names the app before its link's host`() {
        assertEquals("Deezer", SharedText.read("https://open.spotify.com/track/1", null, null, "deezer.android.app").app)
        assertNull(SharedText.read("Radiohead - Creep", null, null, "org.example.player").app)
    }

    @Test fun `the link is taken out, and the marks it leaves`() {
        assertEquals(Shared(null, "Radiohead - Creep", "https://example.org/a?b=c"),
                     SharedText.read("Radiohead - Creep: https://example.org/a?b=c", null, null, null))
        assertEquals("Radiohead - Creep", SharedText.read("https://example.org/a\nRadiohead - Creep", null, null, null).said)
    }

    @Test fun `with no names in the text, the subject's, then the title's`() {
        assertEquals("Creep", SharedText.read("https://example.org/a", "Creep", null, null).said)
        assertEquals("Creep", SharedText.read("https://example.org/a", "", "Creep", null).said)
    }

    @Test fun `an app's name alone, or at the text's end, is no song's`() {
        assertNull(SharedText.read("https://open.spotify.com/track/1", "Spotify", null, null).said)
        assertEquals("Radiohead - Creep", SharedText.read("Radiohead - Creep | Spotify", null, null, null).said)
        assertEquals("Radiohead - Creep", SharedText.read("Radiohead - Creep on Deezer", null, null, null).said)
        // A title that only ends with an app's word keeps it: "Spotify" after no mark is the song's.
        assertEquals("Ode to Spotify", SharedText.read("Ode to Spotify", null, null, null).said)
    }

    @Test fun `nothing shared reads nothing`() {
        assertEquals(Shared(null, null, null), SharedText.read(null, null, null, null))
        assertEquals(Shared(null, null, null), SharedText.read("   ", "\n", "", ""))
        assertEquals(Shared(null, null, null), SharedText.read("!!! — ...", null, null, null))
    }
}
