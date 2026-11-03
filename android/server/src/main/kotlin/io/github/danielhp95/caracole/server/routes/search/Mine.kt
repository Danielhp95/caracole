package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.SongRow

/** Each song's name forms, by its names, kept between two searches (WebApp's `_song_forms`); [KEPT] at most, then
 * forgotten all at once. Used under the searches' lock alone. */
internal class SongForms {
    private val forms = HashMap<Triple<String, List<String>, String>, Pair<Set<String>, Set<String>>>()

    /** The compacted forms of a song's artists and of its title, made once for its names. */
    fun of(song: SongRow): Pair<Set<String>, Set<String>> {
        val names = Triple(song.artist, song.artists, song.title)
        forms[names]?.let { return it }
        if (forms.size >= KEPT) forms.clear()
        val artists = LinkedHashSet<String>()
        for (a in LinkedHashSet(song.artists.ifEmpty { listOf(song.artist) })) {
            for (f in Normalize.nameForms(a)) artists.add(Normalize.compact(f))
        }
        val titles = Normalize.nameForms(Normalize.cleanTitle(song.title)).mapTo(LinkedHashSet()) { Normalize.compact(it) }
        return (artists as Set<String> to titles as Set<String>).also { forms[names] = it }
    }

    companion object {
        /** search_routes.FORMS_KEPT: the songs whose forms are kept between two searches. */
        const val KEPT = 10_000
    }
}

/**
 * search_routes._Mine: your library's songs, to tell which one a site's song is, as `caracole search --add` tells
 * it: the song matched to it (an accepted or pinned match, a variant counted as its song), else the song its names
 * are, by identity key or by `normalize.name_forms` (UG's "Acdc", "R E M" and "Song Dongye" are your AC/DC, R.E.M.
 * and 宋冬野). A review's keys are only a candidate's, often a cover by another artist, so they make no song of yours.
 */
internal class Mine(songs: List<SongRow>, private val forms: SongForms) {
    private val songs = songs.sortedBy { it.id }
    private val byKey = HashMap<String, SongRow>().apply { for (s in this@Mine.songs) put(s.key, s) }
    private val matched = HashMap<Pair<String, String>, SongRow>().apply {
        for (s in this@Mine.songs) {
            val artistKey = s.matchArtistKey
            val songKey = s.matchSongKey
            if (s.matchDecision in DECIDED && !artistKey.isNullOrEmpty() && !songKey.isNullOrEmpty()) {
                putIfAbsent(artistKey to Normalize.splitVariant(songKey).first, s)
            }
        }
    }

    /** The song of yours a site's song (its artist's key, its song's, and its names as the site writes them) is;
     * null for one your library hasn't. */
    fun songFor(artistKey: String, songKey: String, artist: String, title: String): SongRow? {
        val base = Normalize.splitVariant(songKey).first
        val found = matched[artistKey to base] ?: byKey[Normalize.identityKey(artist, title)]
        if (found != null) return found
        val wantedArtist = Normalize.compact(artistKey)
        val wantedTitle = Normalize.compact(base)
        return songs.firstOrNull { song ->
            val (artists, titles) = forms.of(song)
            wantedArtist in artists && wantedTitle in titles
        }
    }

    /** Whether a site's artist (its key and its name) is one of your song's artists, by their names' forms: UG's
     * "Acdc" is your AC/DC, "Song Dongye" your 宋冬野; the artist of the original you matched your cover to is not. */
    fun sameArtist(song: SongRow, artistKey: String, artist: String): Boolean {
        val (artists, _) = forms.of(song)
        return Normalize.compact(artistKey) in artists || Normalize.nameForms(artist).any { Normalize.compact(it) in artists }
    }

    private companion object {
        val DECIDED = setOf("accept", "pinned")
    }
}
