package io.github.danielhp95.caracole.core.ug.internal.fetch

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.ug.IndexTab
import io.github.danielhp95.caracole.core.ug.UgLookup
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * The artist-page route (A6), the seam [SongFetch.processSong] calls: lane ug-fetch-artist's, which follows this
 * lane on internal/fetch/ (ug/fetch.py's `_artist_page_route` and `_artist_page_versions`). This seam replaces the
 * skeleton's `ArtistRoute.find`, which nothing calls: ug-fetch-artist fills [route] and [versions] here, and deletes
 * ArtistRoute.kt or makes these delegate to it, so the phone has one seam.
 *
 * Until it lands, the phone reads no artist page, and each answer is the one Python gives for a list the page cap cut
 * short: the song waits for the next run, as it was, never checked or clean on an artist page nobody read.
 * [artistIsKnown] is whole already (it reads, never asks).
 */
internal object ArtistPages {
    /** `_artist_page_route`: a not-found song looked up on its artist's UG page; true when it was found and accepted
     * there ([SongRun.song] then its match). Neutral: not found, no request and nothing written, as Python's list
     * cut short leaves it. */
    fun route(run: SongRun): Boolean = false

    /**
     * `_artist_page_versions`: a matched song's entries in its artist's UG lists of [kinds] read as its versions,
     * [own] its index tabs to learn the page from; false when this run's page cap cut a list short. Neutral: no list
     * is read, so the answer is Python's for a list cut short: the song marked dirty first (`update_song(ug_dirty=True)`,
     * as Python marks it before it reads), then false, so that [SongFetch.processSong] stops before `_finish` and
     * nothing says UG was asked (no `ug_checked_at`, no `ug:artist_page_checked:`); the computer's nightly run, which
     * the sync tells it is owed, reads the lists.
     */
    fun versions(run: SongRun, kinds: List<String>, own: List<IndexTab> = emptyList()): Boolean {
        Versions.updateSong(run.db, run.song.id, mapOf("ug_dirty" to true), now = run.stamp)
        return false
    }

    /** `artist_keys`: the UG artist keys a song may be listed under: `[alias]` first, then each artist's own keys
     * (`Normalize.nameForms`), each once, in order, none empty. */
    fun artistKeys(song: SongRow, overrides: Overrides): List<String> {
        val keys = ArrayList<String>()
        for (name in song.artists.ifEmpty { listOf(song.artist) }) {
            keys += overrides.alias[Normalize.slugKey(name)].orEmpty()
            keys += Normalize.nameForms(name)
        }
        return keys.distinct().filter { it.isNotEmpty() }
    }

    /** `artist_is_known`: whether the song's artist page can be found: pasted in `[artist_url]` (a tab page there
     * counts until reading it shows it leads to no artist page), learned, or in the index. */
    fun artistIsKnown(db: Db, song: SongRow, overrides: Overrides): Boolean {
        val keys = artistKeys(song, overrides)
        if (overrides.artistUrlEntry(keys) != null && failedPaste(db, keys, overrides) == null) return true
        return keys.any { !UgLookup.learnedArtistUrl(db, it).isNullOrEmpty() || UgLookup.artistKnown(db, it) }
    }

    /** `_pasted_key`. */
    private fun pastedKey(tabId: Long): String = "ug:pasted_tab:$tabId"

    /** `_pasted_record`: what reading the tab page at an `[artist_url]` address found, once it was read (its
     * `artist_url`, or its `problem`); null for an artist page, or a tab page not read yet. */
    private fun pastedRecord(db: Db, url: String): JsonObject? {
        val tabId = OverrideUrls.pastedTabId(url) ?: return null
        return db.kvGetJson(pastedKey(tabId)) as? JsonObject
    }

    /** `_failed_paste`: your `[artist_url]` address for an artist with these keys and what is wrong with it, when it
     * is a tab page that reading showed leads to no artist page. */
    private fun failedPaste(db: Db, keys: List<String>, overrides: Overrides): Pair<String, String>? {
        val entry = overrides.artistUrlEntry(keys) ?: return null
        val problem = (pastedRecord(db, entry.second)?.get("problem") as? JsonPrimitive)?.takeIf { it.isString }?.content
        return if (problem.isNullOrEmpty()) null else entry.second to problem
    }
}
