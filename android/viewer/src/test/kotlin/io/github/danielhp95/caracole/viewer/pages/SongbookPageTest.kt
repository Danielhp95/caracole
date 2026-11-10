package io.github.danielhp95.caracole.viewer.pages

import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.viewer.ViewerAssets
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.version.Version
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** viewer/book.py on the phone: every songbook page of the corpus (vectors/viewer/songbook_pages.jsonl, which the
 * songbook-tab area replays on the device too), byte for byte, and its parts by hand. */
class SongbookPageTest {
    @Test fun everySongbookPageIsBookPysByteForByte() {
        val records = Corpus.records("viewer/songbook_pages.jsonl")
        assertTrue(records.size >= 15, "${records.size} pages")
        val wrong = ArrayList<String>()
        for (r in records) {
            val name = r.args[0].jsonPrimitive.content
            val songs = r.args[1].jsonArray.map { song ->
                val o = song.jsonObject
                fun text(key: String) = (o[key] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
                BookSong(text("title")!!, text("artist")!!, cho = text("cho"), key = text("key"),
                         keySource = text("key_source"), transpose = o.getValue("transpose").jsonPrimitive.int,
                         missing = text("missing"), id = text("id") ?: "", start = text("start"))
            }
            fun kw(key: String) = (r.kw[key] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
            val html = SongbookPage.build(name, songs, pdf = kw("pdf"), cho = kw("cho"), pdfTraditional = kw("pdf_traditional"))
            val want = r.out!!.jsonObject
            if (sha(html) != want.getValue("sha256").jsonPrimitive.content) {
                val mine = pieces(html)
                val theirs = want.getValue("pieces").jsonArray.map { it.jsonArray.map { p -> p.jsonPrimitive.content } }
                val at = mine.indices.firstOrNull { it >= theirs.size || mine[it] != theirs[it] }
                wrong += "$name (${songs.size} songs, ${r.kw}): piece $at ${at?.let { mine.getOrNull(it) }}, " +
                    "Python's ${at?.let { theirs.getOrNull(it) }}"
            }
        }
        assertEquals(emptyList(), wrong)
    }

    @Test fun aSongbookOfNoneIsItsHeadingAndContentsAlone() {
        val html = SongbookPage.build("Empty <b>", emptyList())
        assertTrue("<h1>Empty &lt;b&gt;</h1>\n<p class=\"artist\">Songbook · 0 songs</p>" in html)
        assertTrue("<title>Empty &lt;b&gt; · songbook</title>" in html)
        assertFalse("id=\"data-" in html)
        assertTrue("<script type=\"application/json\" id=\"voicings\">{}</script>" in html)
        for (asset in ViewerAssets.scripts(ViewerAssets.Page.SONGBOOK)) assertTrue(asset in html)
    }

    @Test fun aMissingSongIsNamedInTheContentsAndHasNoPage() {
        val cho = "{title: Creep}\n{artist: Radiohead}\n{key: G}\n[G]Words [B]here\n"
        val songs = listOf(BookSong("Hysteria", "Muse", missing = "no sheet yet", id = "a1"),
                           BookSong("Creep", "Radiohead", cho = cho, id = "b2", start = "t=2&capo=1"),
                           BookSong("Nothing", "Nobody", id = "c3"))
        val html = SongbookPage.build("Gig", songs, pdf = "songbook.pdf")
        assertTrue("<span class=\"why\">Missing: no sheet yet</span>" in html)
        assertTrue("<span class=\"why\">Missing: no sheet yet</span>" in html.substringAfter("Nothing"))  // none said
        assertTrue("<section class=\"song\" id=\"song-2\" data-n=\"2\" data-id=\"b2\"" in html)
        assertFalse("id=\"song-1\"" in html || "id=\"song-3\"" in html)
        assertTrue("<p class=\"pos\">Song 2 of 3</p>" in html)
        val data = Json.parseToJsonElement(html.substringAfter("id=\"data-2\">").substringBefore("</script>")).jsonObject
        assertEquals(JsonPrimitive("t=2&capo=1"), data["start"])
        assertFalse("voicings" in data || "easy" in data || "winds" in data)  // one block of each for the page
    }

    @Test fun aSongOpensInItsStartAtItsTransposeWhereTheStartNamesNoT() {
        assertEquals(Version(t = 3), SongbookPage.opensIn(BookSong("A", "B", transpose = 3)))
        assertEquals(Version(t = 3, mode = "dorian"), SongbookPage.opensIn(BookSong("A", "B", transpose = 3, start = "mode=dorian")))
        assertEquals(Version(t = -1, capo = 2), SongbookPage.opensIn(BookSong("A", "B", transpose = 3, start = "?t=-1&capo=2")))
        assertEquals(Version(t = 0), SongbookPage.opensIn(BookSong("A", "B", transpose = 3, start = "#t=")))
        assertEquals("<span class=\"vh\">key </span>Em · capo 2",
                     SongbookPage.keyAndCapo(Key(4, "aeolian"), Version(), 2))
        assertEquals("", SongbookPage.keyAndCapo(null, Version(), 0))
    }

    private fun sha(text: String) = Canonical.sha256Hex(text.toByteArray())

    /** The generator's pieces: the page cut at its JSON blocks. */
    private fun pieces(html: String): List<List<String>> {
        val block = "<script type=\"application/json\" id=\""
        val out = ArrayList<List<String>>()
        var at = 0
        while (true) {
            val start = html.indexOf(block, at)
            if (start < 0) break
            out += listOf("text", sha(html.substring(at, start)).take(16))
            val nameEnd = html.indexOf("\">", start)
            val name = html.substring(start + block.length, nameEnd)
            val end = html.indexOf("</script>", nameEnd)
            val payload = html.substring(nameEnd + 2, end)
            out += listOf(name, if (!name.startsWith("data-")) sha(payload).take(16) else
                (Json.parseToJsonElement(payload) as JsonObject).entries.joinToString(" ") { (k, v) ->
                    "$k=${sha(PyJson.dumps(v, compact = true)).take(8)}"
                })
            at = end
        }
        out += listOf("text", sha(html.substring(at)).take(16))
        return out
    }
}
