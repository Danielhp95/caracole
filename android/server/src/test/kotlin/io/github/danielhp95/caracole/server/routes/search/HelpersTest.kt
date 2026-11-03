package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.core.json.PyJson
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** The search routes' own small rules, each against what Python answers (the values below are its). */
class HelpersTest {
    @Test
    fun letters_are_named_as_lacuerdas_menu_names_them() {
        val cases = listOf(
            listOf("_num", "a", "b", "c") to "#, A–C", listOf("a", "b", "e") to "A, B, E",
            listOf("m", "n", "nn", "o") to "M–O", listOf("_num", "a") to "#, A", emptyList<String>() to "",
            listOf("z", "y", "x", "a") to "A, X–Z", listOf("a", "a", "b") to "A, B", listOf("n", "nn") to "N, Ñ",
            Looked.LETTERS to "#, A–Z",
        )
        for ((letters, said) in cases) assertEquals(said, Looked.lettersText(letters), letters.toString())
    }

    @Test
    fun counts_are_grouped_by_thousands() {
        assertEquals(listOf("10,428", "0", "999", "1,000", "1,234,567"),
                     listOf(10428L, 0L, 999L, 1000L, 1234567L).map { Looked.grouped(it) })
    }

    @Test
    fun a_harptabs_artist_is_named_by_its_pages_path() {
        assertTrue(Artists.isArtistPath("artist/1178/billy-joel"))
        for (path in listOf("artist//x", "artist/1234567890/x", "artist/1/X", "artist/1/a/b", "artist/1/", "artist/1",
                            "artists/1/x", "artist/1/" + "a".repeat(201))) {
            assertFalse(Artists.isArtistPath(path), path)
        }
    }

    @Test
    fun a_dict_merged_keeps_each_names_first_place_with_its_last_value() {
        val merged = obj("a" to 1, "top" to "old", "b" to 2) with obj("top" to "new", "c" to 3)
        assertEquals(listOf("a", "top", "b", "c"), merged.keys.toList())
        assertEquals(JsonPrimitive("new"), merged["top"])
    }

    @Test
    fun a_float_is_written_as_python_writes_it_and_an_int_as_an_int() {
        assertEquals("""{"score":100.0,"rating":2.9,"views":1100000,"none":null,"tiny":1e-05}""",
                     PyJson.dumps(obj("score" to 100.0, "rating" to 2.9, "views" to 1100000, "none" to null,
                                      "tiny" to 0.00001), compact = true))
    }

    @Test
    fun an_index_tab_lives_at_its_slugged_path_else_at_its_id() {
        assertEquals("https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169",
                     IndexTab(4169, "chords", "creep", null, "/radiohead/creep-chords-4169").url)
        assertEquals("https://tabs.ultimate-guitar.com/tab/4169", IndexTab(4169, "chords", "creep", null, "").url)
    }

    @Test
    fun json_compares_as_the_corpus_compares_it() {
        fun parse(s: String) = Json.parseToJsonElement(s)
        assertNull(difference(parse("""{"a":[1,2.5,"x",null,true]}"""), parse("""{"a":[1,2.50,"x",null,true]}""")))
        assertTrue(difference(parse("""{"score":100.0}"""), parse("""{"score":100}""")) != null, "an int is no float")
        assertTrue(difference(parse("""{"a":"1"}"""), parse("""{"a":1}""")) != null)
        assertTrue(difference(parse("""{"a":1}"""), parse("""{"a":1,"b":2}""")) != null)
        assertTrue(difference(parse("""[1,2]"""), parse("""[2,1]""")) != null, "arrays in order")
    }

    @Test
    fun what_a_card_says_of_its_folders_files_is_masked() {
        val row = obj("id" to 4, "links" to listOf("x"), "files" to obj("sheet" to "a"), "source" to "ug", "key" to "Am",
                      "instruments" to emptyList<Any>(), "status" to "wanted",
                      "library" to obj("id" to 4, "links" to emptyList<Any>()))
        assertEquals("""{"id":4,"links":"*","files":"*","source":"*","key":"*","instruments":"*","status":"wanted",""" +
                         """"library":{"id":4,"links":"*"}}""", masked(row).toString())
        val siteRow = obj("source" to "gtptabs", "library" to null)
        assertEquals(siteRow, masked(siteRow), "a row with no links is no card")
    }
}
