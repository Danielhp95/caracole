package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.server.testing.json
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.net.URLEncoder
import kotlin.test.assertEquals
import kotlin.test.fail

/**
 * A site's row names the song of yours it is (search_routes._owners, _Mine) as caracole serve names it: by an accepted
 * or pinned match (a cover, whose row is another artist's: `same_artist` false), by identity key, or by the compact
 * forms of its names (UG's "Billy Joel" is your "BillyJoel"), on every site's rows (Ultimate Guitar's, gtptabs.com's,
 * harptabs.com's, gametabs.net's, LaCuerda's) and every artist's most tabbed; a harptabs.com tab by its title alone
 * names none. The search corpus's own fixtures hold no such songs, so these add them by SQL; the answers below are
 * caracole serve's over the same rows (WebApp.handle, its answer masked as the vectors are, then [owners]).
 */
class OwnersTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test
    fun every_sites_row_names_its_song_of_yours_and_whether_its_artist_is_yours() {
        val failures = ArrayList<String>()
        for ((fixture, asked) in ANSWERS.groupBy { it.first }) {
            SearchApp(tmp.newFolder(fixture), fixture).use { search ->
                search.app.database.writeBlocking { db -> for (sql in SONGS.getValue(fixture)) sql(db) }
                for ((_, q, expected) in asked) {
                    val answer = search.app.get("/api/search?q=${URLEncoder.encode(q, Charsets.UTF_8)}&box=t")
                    assertEquals(200, answer.status, q)
                    difference(Json.parseToJsonElement(expected), owners(masked(answer.json).jsonObject))
                        ?.let { failures += "$fixture \"$q\": $it" }
                }
            }
        }
        if (failures.isNotEmpty()) fail(failures.joinToString("\n"))
    }

    private companion object {
        const val STAMP = "2026-11-03T10:00:00Z"

        /** A song of yours, as the generator's INSERT writes it: added a minute after the one before. */
        fun song(id: Int, artist: String, title: String, key: String, minute: Int, vararg more: Pair<String, String>):
            (Db) -> Unit = { db ->
            val columns = linkedMapOf<String, Any>(
                "id" to id, "key" to key, "artist" to artist, "title" to title,
                "artists" to JsonArray(listOf(JsonPrimitive(artist))).toString(),
                "added_at" to "2026-10-02T00:%02d:00Z".format(minute), "created_at" to STAMP, "updated_at" to STAMP,
            )
            columns.putAll(more)
            db.execute("INSERT INTO songs (${columns.keys.joinToString()}) VALUES (${columns.keys.joinToString { "?" }})",
                       *columns.values.toTypedArray())
        }

        val SONGS: Map<String, List<(Db) -> Unit>> = mapOf(
            "sites" to listOf(
                song(10, "Elton John", "Your Song", "elton-john/your-song", 1),
                song(11, "Beatles", "Yesterday", "beatles/yesterday", 2),
                song(12, "BillyJoel", "Piano Man", "billyjoel/piano-man", 3, "status" to "found"),
                song(13, "Moby", "Creep", "moby/creep", 4, "match_decision" to "accept", "match_artist_key" to "radiohead",
                     "match_song_key" to "creep"),
                song(14, "HollowKnight", "Resting Grounds", "hollowknight/resting-grounds", 5),
                song(15, "Lindsey Stirling", "The White Lady", "lindsey-stirling/white-lady", 6,
                     "match_decision" to "pinned", "match_artist_key" to "hollow-knight", "match_song_key" to "white-lady"),
                song(16, "Ben Folds", "Vienna", "ben-folds/vienna", 7, "match_decision" to "accept",
                     "match_artist_key" to "billy-joel", "match_song_key" to "vienna"),
                song(17, "StoneTemplePilots", "Creep", "stonetemplepilots/creep", 8),
            ),
            "lacuerda" to listOf(
                song(10, "SodaStereo", "Persiana Americana", "sodastereo/persiana-americana", 1),
                song(11, "Shakira", "Té para 3", "shakira/te-para-3", 2, "match_decision" to "pinned",
                     "match_artist_key" to "soda-stereo", "match_song_key" to "te-para-3"),
            ),
        )

        /** A row's song of yours (`song`, `same_artist`, `library`) beside its names; a row with no artist (a
         * harptabs.com tab by its title alone) whole. */
        fun owner(row: JsonElement): JsonElement {
            val r = row.jsonObject
            if ("artist" !in r) return r
            return JsonObject(listOf("artist", "title", "song", "same_artist", "library").associateWith { r.getValue(it) })
        }

        /** What the test compares of an answer: each site's rows' owners, and those of each artist's most tabbed. */
        fun owners(answer: JsonObject): JsonObject {
            val out = LinkedHashMap<String, JsonElement>()
            for (site in listOf("index", "gtptabs", "harptabs", "gametabs", "lacuerda")) {
                out[site] = JsonArray(answer.getValue(site).jsonArray.map { owner(it) })
            }
            for (group in listOf("artists", "harptabs_artists", "lacuerda_artists")) {
                out[group] = JsonArray(answer.getValue(group).jsonArray.map { a ->
                    JsonObject(mapOf("artist" to a.jsonObject.getValue("artist"),
                                     "top" to JsonArray(a.jsonObject.getValue("top").jsonArray.map { owner(it) })))
                })
            }
            return JsonObject(out)
        }

        /** caracole serve's answers, [owners] of each (the generator: WebApp.handle over the fixture and SONGS). */
        val ANSWERS = listOf(
        Triple("sites", "your song", """{"index":[{"artist":"Elton John","title":"Your Song","song":10,"same_artist":true,"library":{"id":10,"artist":"Elton John","title":"Your Song","display":"Elton John - Your Song","status":"wanted","links":"*"}}],"gtptabs":[{"artist":"Elton John","title":"Your Song","song":10,"same_artist":true,"library":{"id":10,"artist":"Elton John","title":"Your Song","display":"Elton John - Your Song","status":"wanted","links":"*"}}],"harptabs":[],"gametabs":[],"lacuerda":[],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("sites", "yesterday", """{"index":[],"gtptabs":[{"artist":"Beatles","title":"Yesterday","song":11,"same_artist":true,"library":{"id":11,"artist":"Beatles","title":"Yesterday","display":"Beatles - Yesterday","status":"wanted","links":"*"}}],"harptabs":[{"artist":"the beatles","title":"yesterday","song":11,"same_artist":true,"library":{"id":11,"artist":"Beatles","title":"Yesterday","display":"Beatles - Yesterday","status":"wanted","links":"*"}},{"source":"harptabs","title":"Yesterday","url":"https://www.harptabs.com/tab/1999/yesterday","score":100.0}],"gametabs":[],"lacuerda":[],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("sites", "piano man", """{"index":[{"artist":"Billy Joel","title":"Piano Man","song":12,"same_artist":true,"library":{"id":12,"artist":"BillyJoel","title":"Piano Man","display":"BillyJoel - Piano Man","status":"found","links":"*"}}],"gtptabs":[],"harptabs":[{"artist":"billy joel","title":"piano man","song":12,"same_artist":true,"library":{"id":12,"artist":"BillyJoel","title":"Piano Man","display":"BillyJoel - Piano Man","status":"found","links":"*"}},{"source":"harptabs","title":"Piano Man","url":"https://www.harptabs.com/tab/29525/piano-man","score":100.0}],"gametabs":[],"lacuerda":[],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("sites", "creep", """{"index":[{"artist":"Radiohead","title":"Creep","song":13,"same_artist":false,"library":{"id":13,"artist":"Moby","title":"Creep","display":"Moby - Creep","status":"wanted","links":"*"}}],"gtptabs":[{"artist":"Radiohead","title":"Creep","song":13,"same_artist":false,"library":{"id":13,"artist":"Moby","title":"Creep","display":"Moby - Creep","status":"wanted","links":"*"}},{"artist":"Stone Temple Pilots","title":"Creep","song":17,"same_artist":true,"library":{"id":17,"artist":"StoneTemplePilots","title":"Creep","display":"StoneTemplePilots - Creep","status":"wanted","links":"*"}},{"artist":"Metallica","title":"Creeping Death","song":null,"same_artist":false,"library":null}],"harptabs":[],"gametabs":[],"lacuerda":[],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("sites", "resting grounds", """{"index":[],"gtptabs":[],"harptabs":[],"gametabs":[{"artist":"Hollow Knight","title":"Resting Grounds","song":14,"same_artist":true,"library":{"id":14,"artist":"HollowKnight","title":"Resting Grounds","display":"HollowKnight - Resting Grounds","status":"wanted","links":"*"}}],"lacuerda":[],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("sites", "white lady", """{"index":[],"gtptabs":[],"harptabs":[],"gametabs":[{"artist":"Hollow Knight","title":"The White Lady","song":15,"same_artist":false,"library":{"id":15,"artist":"Lindsey Stirling","title":"The White Lady","display":"Lindsey Stirling - The White Lady","status":"wanted","links":"*"}}],"lacuerda":[],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("sites", "vienna", """{"index":[],"gtptabs":[],"harptabs":[{"artist":"billy joel","title":"Vienna!","song":16,"same_artist":false,"library":{"id":16,"artist":"Ben Folds","title":"Vienna","display":"Ben Folds - Vienna","status":"wanted","links":"*"}}],"gametabs":[],"lacuerda":[],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("sites", "billy joel", """{"index":[],"gtptabs":[],"harptabs":[],"gametabs":[],"lacuerda":[],"artists":[{"artist":"Billy Joel","top":[{"artist":"Billy Joel","title":"Piano Man","song":12,"same_artist":true,"library":{"id":12,"artist":"BillyJoel","title":"Piano Man","display":"BillyJoel - Piano Man","status":"found","links":"*"}}]}],"harptabs_artists":[{"artist":"billy joel","top":[{"artist":"billy joel","title":"piano man","song":12,"same_artist":true,"library":{"id":12,"artist":"BillyJoel","title":"Piano Man","display":"BillyJoel - Piano Man","status":"found","links":"*"}},{"artist":"billy joel","title":"Vienna!","song":16,"same_artist":false,"library":{"id":16,"artist":"Ben Folds","title":"Vienna","display":"Ben Folds - Vienna","status":"wanted","links":"*"}},{"artist":"billy joel","title":"She's Always a Woman","song":null,"same_artist":false,"library":null}]}],"lacuerda_artists":[]}"""),
        Triple("sites", "the beatles", """{"index":[],"gtptabs":[{"artist":"Beatles","title":"Yesterday","song":11,"same_artist":true,"library":{"id":11,"artist":"Beatles","title":"Yesterday","display":"Beatles - Yesterday","status":"wanted","links":"*"}}],"harptabs":[],"gametabs":[],"lacuerda":[],"artists":[],"harptabs_artists":[{"artist":"the beatles","top":[{"artist":"the beatles","title":"yesterday","song":11,"same_artist":true,"library":{"id":11,"artist":"Beatles","title":"Yesterday","display":"Beatles - Yesterday","status":"wanted","links":"*"}}]}],"lacuerda_artists":[]}"""),
        Triple("lacuerda", "persiana americana", """{"index":[],"gtptabs":[],"harptabs":[],"gametabs":[],"lacuerda":[{"artist":"Soda Stereo","title":"Persiana Americana","song":10,"same_artist":true,"library":{"id":10,"artist":"SodaStereo","title":"Persiana Americana","display":"SodaStereo - Persiana Americana","status":"wanted","links":"*"}}],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("lacuerda", "te para 3", """{"index":[],"gtptabs":[],"harptabs":[],"gametabs":[],"lacuerda":[{"artist":"Soda Stereo","title":"Té para 3","song":11,"same_artist":false,"library":{"id":11,"artist":"Shakira","title":"Té para 3","display":"Shakira - Té para 3","status":"wanted","links":"*"}}],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("lacuerda", "soda stereo", """{"index":[],"gtptabs":[],"harptabs":[],"gametabs":[],"lacuerda":[],"artists":[],"harptabs_artists":[],"lacuerda_artists":[{"artist":"Soda Stereo","top":[{"artist":"Soda Stereo","title":"De Música Ligera","song":null,"same_artist":false,"library":null},{"artist":"Soda Stereo","title":"Persiana Americana","song":10,"same_artist":true,"library":{"id":10,"artist":"SodaStereo","title":"Persiana Americana","display":"SodaStereo - Persiana Americana","status":"wanted","links":"*"}},{"artist":"Soda Stereo","title":"Té para 3","song":11,"same_artist":false,"library":{"id":11,"artist":"Shakira","title":"Té para 3","display":"Shakira - Té para 3","status":"wanted","links":"*"}}]}]}"""),
        )
    }
}
