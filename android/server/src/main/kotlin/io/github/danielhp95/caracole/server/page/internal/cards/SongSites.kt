package io.github.danielhp95.caracole.server.page.internal.cards

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * song_sites.py: which sites have a song, had nothing for it or weren't asked yet, its card's marks (`sites`), each
 * `{source, state, said}`, a site each of [shown]'s in [ORDER].
 */
internal object SongSites {
    const val HAVE = "have"
    const val NONE = "none"
    const val UNASKED = "unasked"

    /** song_sites.ORDER and NAMES. */
    val ORDER = listOf("ug", "lacuerda", "lrclib", "gtptabs", "harptabs", "gametabs", "musescore", "youtube")
    private val NAMES = mapOf("ug" to "UG", "lacuerda" to "LaCuerda", "lrclib" to "LRCLIB",
                              "gtptabs" to "gtptabs", "harptabs" to "harptabs", "gametabs" to "gametabs",
                              "musescore" to "MuseScore", "youtube" to "YouTube")

    /** song_sites.CHECKED: the steps' kv prefixes of a miss. */
    private val CHECKED = linkedMapOf("gtptabs" to "gtptabs:checked:", "harptabs" to "harptabs:checked:",
                                      "gametabs" to "gametabs:checked:")

    /** song_sites._YOUTUBE: a song's state on YouTube's route, its mark ("declined" none). */
    private val YOUTUBE = mapOf("downloaded" to HAVE, "chords" to HAVE, "missing" to NONE, "unusable" to NONE,
                                "queued" to UNASKED, "blocked" to UNASKED)

    /** song_sites.shown: the sites a line names, those on, in [ORDER]. */
    fun shown(config: PhoneConfig): List<String> = ORDER.filter { config.provider(it).enabled }

    /** song_sites.checked: when each site's step last found nothing for a song, by site and song id (a key after its
     * prefix of decimal digits alone, as str.isdigit and int() read it). */
    fun checked(db: Db): Map<String, Map<Long, String>> = CHECKED.mapValues { (_, prefix) ->
        val found = LinkedHashMap<Long, String>()
        db.query("SELECT key, value FROM kv WHERE substr(key, 1, ?) = ?", prefix.length, prefix) {
            it.text(0)!! to it.text(1)!!
        }.forEach { (key, value) -> idOf(key.substring(prefix.length))?.let { found[it] = value } }
        found
    }

    /** int() of a run of decimal digits in any script (str.isdigit's Nd), or null for anything else. */
    private fun idOf(rest: String): Long? {
        if (rest.isEmpty()) return null
        val ascii = StringBuilder()
        var i = 0
        while (i < rest.length) {
            val cp = rest.codePointAt(i)
            if (!PyUnicode.isDecimal(cp)) return null
            var zero = cp
            while (PyUnicode.isDecimal(zero - 1)) zero--
            ascii.append('0' + (cp - zero) % 10)
            i += Character.charCount(cp)
        }
        return ascii.toString().toBigInteger().takeIf { it.bitLength() < 64 }?.toLong()
    }

    /** song_sites.musescore_read: whether MuseScore's index holds anything. */
    fun musescoreRead(db: Db): Boolean = db.one("SELECT 1 FROM musescore_index LIMIT 1") { true } ?: false

    /** song_sites.song_sites: the song's marks, a site each of [sites]. */
    fun songSites(song: SongRow, sites: List<String>, origins: Map<String, String>, checks: Map<String, Map<Long, String>>,
                  lacuerda: Boolean, musescore: Boolean?, musescoreRead: Boolean, youtube: String?): List<JsonObject> {
        val came = origins.values.toSet()
        val marks = ArrayList<JsonObject>()
        for (site in sites) {
            var state = UNASKED
            var looked: String? = null
            if (site in came) {
                state = HAVE
            } else when (site) {
                "ug" -> when (song.matchDecision) {
                    "accept", "pinned" -> state = HAVE
                    "not_found" -> { state = NONE; looked = song.matchedAt }
                }
                "lacuerda" -> if (lacuerda) state = HAVE
                    else if (!song.lacuerdaCheckedAt.isNullOrEmpty()) { state = NONE; looked = song.lacuerdaCheckedAt }
                "lrclib" -> if ((origins["lyrics.txt"] ?: "lrclib") != "lrclib") { state = NONE; looked = song.lyricsAt }
                    else if (song.lyricsStatus == "found" || song.lyricsStatus == "instrumental") state = HAVE
                    else if (song.lyricsStatus == "missing") { state = NONE; looked = song.lyricsAt }
                in CHECKED -> checks[site]?.get(song.id)?.let { state = NONE; looked = it }
                "musescore" -> if (musescore == true) state = HAVE else if (musescoreRead) state = NONE
                "youtube" -> state = YOUTUBE[youtube] ?: continue
            }
            marks += JsonObject(linkedMapOf("source" to JsonPrimitive(site), "state" to JsonPrimitive(state),
                                            "said" to JsonPrimitive(said(site, state, looked, song))))
        }
        return marks
    }

    private fun said(site: String, state: String, looked: String?, song: SongRow): String {
        val name = NAMES.getValue(site)
        val when_ = if (!looked.isNullOrEmpty()) " · looked ${day(looked)}" else ""
        return when {
            state == HAVE && site == "lrclib" && song.lyricsStatus == "instrumental" -> "$name: instrumental, no words"
            state == HAVE && site == "musescore" -> "$name: maybe, by its title"
            state == HAVE -> "$name: has it"
            state == NONE && site == "lrclib" && song.lyricsStatus == "found" -> "$name: nothing timed$when_"
            state == NONE -> "$name: not there$when_"
            site == "ug" && song.matchDecision == "review" -> "$name: unsure which song"
            else -> "$name: not asked yet"
        }
    }

    /** song_sites._day: a stored time's day ("2026-10-18T03:30:00Z") as the pages write one, "18/10/26"; anything
     * else as its first ten code points. */
    private fun day(stamp: String): String {
        val year = Py.slice(stamp, 0, 4)
        val month = Py.slice(stamp, 5, 7)
        val dd = Py.slice(stamp, 8, 10)
        val digits = year + month + dd
        val isDigit = digits.isNotEmpty() && digits.codePoints().allMatch { PyUnicode.isDigit(it) }
        return if (Py.slice(stamp, 4, 5) == "-" && Py.slice(stamp, 7, 8) == "-" && isDigit) {
            "$dd/$month/${Py.slice(year, 2, null)}"
        } else {
            Py.slice(stamp, 0, 10)
        }
    }

    /** text[:n], in code points. */
    private fun prefix(text: String, n: Int): String {
        val end = if (text.codePointCount(0, text.length) <= n) text.length else text.offsetByCodePoints(0, n)
        return text.substring(0, end)
    }
}
