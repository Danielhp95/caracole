package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.lacuerda.LaCuerda
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.search.ArtistHit
import io.github.danielhp95.caracole.core.search.IndexHit
import io.github.danielhp95.caracole.core.search.Search
import io.github.danielhp95.caracole.core.search.SearchLimits
import io.github.danielhp95.caracole.core.search.SiteArtist
import io.github.danielhp95.caracole.core.search.SiteHit

/**
 * search.lacuerda_unlisted on the phone, /api/search's `lacuerda_unlisted`: for a query LaCuerda's index has no artist
 * by, while it hasn't read whole the listing of the letter their name would be in (LaCuerda.unreadLetter), the name
 * whose page can tell whether LaCuerda has them, and that letter as LaCuerda's menu names it ("E"); null when the
 * index can tell.
 *
 * LaCuerda's own answer ([lacuerda]: searchLacuerda's artists and songs) tells first: anything strong, and there is
 * nothing to offer. Then the Ultimate Guitar index's ([artists], [songs], [lead], findIndex's): a song by its title
 * alone that is strong is a title, no name; else the artist that leads, or one named whole or by a run of their
 * name's words ([namedInARun]: "bunbury" of Enrique Bunbury, never "silvio rodriguez" of Silvio Martinez Rodriguez);
 * else the artist of a strong song. Else none when LaCuerda has an artist whose whole name is among the query's
 * words (their row, LaCuerdaFind.NAMED, says it); else the artist of an Ultimate Guitar song read by both its names
 * whose whole name starts or ends the query ([namedAtAnEnd]); else the query less a title an index knows at its end
 * or its start ([lessATitle]); else the query. A name LaCuerda's listings give, under any of its spellings, is no
 * page to read (LaCuerda.artistSlugs). vectors/web/api_search.jsonl and api_search_gate.jsonl hold it to Python's
 * answers (tests/test_conformance_lookup_routes.py).
 */
internal object Unlisted {
    /** search.TITLE_WORDS: a title at a query's end that leaves the rest as its artist is two words at least. */
    private const val TITLE_WORDS = 2

    /** lacuerda_index.NAMED: a LaCuerda artist's whole name among the query's words (LaCuerdaFind's, internal to
     * :core; the vectors hold the two alike). */
    private const val NAMED = 80.0

    /** search_routes._lacuerda_unlisted: the name and the letter, or null. */
    fun lacuerdaUnlisted(db: Db, q: String, artists: List<ArtistHit>, songs: List<IndexHit>, lead: String?,
                         lacuerda: List<Any>): Pair<String, String>? {
        if (lacuerda.any { score(it) >= SearchLimits.STRONG }) return null
        val name = unlistedName(db, q, artists, songs, lead, lacuerda) ?: return null
        if (LaCuerda.artistSlugs(db, name).isNotEmpty()) return null  // LaCuerda lists them, under the name it writes
        val letter = LaCuerda.unreadLetter(db, name) ?: return null
        return name to LaCuerda.lettersText(listOf(letter))
    }

    private fun score(hit: Any): Double = when (hit) {
        is SiteArtist -> hit.score
        is SiteHit -> hit.score
        else -> throw IllegalArgumentException("not a site's hit: $hit")
    }

    /** search._unlisted_name. */
    private fun unlistedName(db: Db, q: String, artists: List<ArtistHit>, songs: List<IndexHit>, lead: String?,
                             lacuerda: List<Any>): String? {
        val first = songs.firstOrNull { it.score >= SearchLimits.STRONG }
        val byTitle = first != null && first.via == "title"  // a strong song by its title alone: a title, no name
        val named = artists.filter { !it.part || namedInARun(q, it.artistKey) }
        if (named.isNotEmpty() && (lead == "artist" || !byTitle)) return named[0].artist
        if (byTitle) return null
        if (first != null && first.artist.isNotEmpty() && !Search.noOnes(first.artistKey)) return first.artist
        if (lacuerda.any { it is SiteArtist && it.via == "both" && it.score >= NAMED }) return null
        return namedAtAnEnd(q, songs) ?: lessATitle(db, q) ?: q
    }

    /** search._named_in_a_run: whether the query's words are a run of an artist's name's words (UG's key). */
    private fun namedInARun(q: String, artistKey: String): Boolean {
        val words = Normalize.nameWords(q)
        val name = artistKey.split("-")
        return words.isNotEmpty() && (0..name.size - words.size).any { i -> name.subList(i, i + words.size) == words }
    }

    /** search._less_a_title: the query less the longest run of its last (else first) words that is a title Ultimate
     * Guitar's index or LaCuerda's knows exactly, of [TITLE_WORDS] words or more, one of four letters, and fewer than
     * all: the words left, as typed. Null for none. By the indexes' keys alone. */
    private fun lessATitle(db: Db, q: String): String? {
        val typed = Py.split(q)
        for (n in typed.size - 1 downTo TITLE_WORDS) {
            val runs = listOf(typed.takeLast(n) to typed.dropLast(n), typed.take(n) to typed.drop(n))
            for ((run, rest) in runs) {
                val words = Normalize.nameWords(run.joinToString(" "))
                if (words.size < TITLE_WORDS || words.none { Py.len(it) >= 4 } ||
                    Normalize.nameWords(rest.joinToString(" ")).isEmpty()) {
                    continue
                }
                val text = run.joinToString(" ")
                val inUg = db.one("SELECT 1 FROM ug_index WHERE song_key = ? LIMIT 1", Normalize.slugKey(text)) { 1 } != null
                if (inUg || db.one("SELECT 1 FROM lacuerda_index WHERE title_key = ? AND title != '' LIMIT 1",
                                   LaCuerda.titleKey(text)) { 1 } != null) {
                    return rest.joinToString(" ")
                }
            }
        }
        return null
    }

    /** search._named_at_an_end: the artist of an Ultimate Guitar song the search read by both its names, whose whole
     * name is a run of the query's words at its start or its end, fewer than all of them: the longest run's, the
     * better song's at a tie. Null for none. */
    private fun namedAtAnEnd(q: String, songs: List<IndexHit>): String? {
        val words = Normalize.nameWords(q)
        val runs = HashMap<String, Int>()
        for (n in words.size - 1 downTo 1) {
            for (run in listOf(words.take(n), words.takeLast(n))) {
                for (form in Normalize.nameForms(run.joinToString(" "))) runs.putIfAbsent(Normalize.compact(form), n)
            }
        }
        var best: Pair<Int, String>? = null
        for (h in songs) {
            val n = if (h.via == "both" && h.artist.isNotEmpty() && !Search.noOnes(h.artistKey)) {
                runs[Normalize.compact(h.artistKey)] ?: 0
            } else 0
            if (n != 0 && (best == null || n > best.first)) best = n to h.artist
        }
        return best?.second
    }
}
