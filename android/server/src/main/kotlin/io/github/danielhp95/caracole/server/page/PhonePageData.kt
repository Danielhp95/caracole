package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.mirror.Gate
import io.github.danielhp95.caracole.mirror.Looked
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.mirror.UnitGate
import io.github.danielhp95.caracole.mirror.pageFor
import io.github.danielhp95.caracole.server.files.PhoneGate
import io.github.danielhp95.caracole.server.page.internal.cards.Cards
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import java.time.Instant
import java.time.temporal.ChronoUnit

/**
 * The library page's data and cards from the phone's own library (library_page.song_cards; lane library-cards): every
 * song's card made by the phone as the computer makes it of the same library (internal/cards' [Cards]), in place of
 * the mirror's cards re-identified and the minimal ones; its icons, its sites, its catalogue, its fold table, its
 * generated time and its songbooks still the mirror's ([MirrorPageData.mirrored]), and the mirror's cards of songs
 * the phone hasn't got (their negative ids) after the phone's. With no mirror, the page's data is
 * library_page.build_library_page's of the same library but its `sites` (vectors/web/cards_full.jsonl's).
 *
 * A song's folder holds what the phone keeps and the pages it made; beside them a card links the files of its folder
 * the mirror serves now, as LibraryFiles serves them: those `Mirror.pageFor` answers with a page under the phone's
 * gate (PhoneGate's rule, read through the caller's [Db]): the computer's, at the digest the phone holds the unit at,
 * else a `.caracole` file's layer's. A song the computer's library page has a card of and whose unit the computer
 * listed a file of at that digest is held as the computer holds it, so what no sync carries is said as the computer's
 * card says it (Cards' docstring).
 *
 * [config] is read through the caller's [Db] (PhoneConfig.read on the phone), never a read of its own: every caller
 * builds its cards inside a read or a write it holds. [clock] is the buy list's time for [cards] (fetch_due's ages),
 * as /jobs.json's card is made now.
 */
class PhonePageData(val mirror: MirrorPageData, val store: LibraryStore,
                    val config: (Db) -> PhoneConfig = { db -> PhoneConfig.read(db) },
                    val clock: () -> Instant = { Instant.now() }) : PageData, SongCards {
    override fun data(db: Db, now: String): JsonObject {
        val base = mirror.mirrored(db, now)
        val at = runCatching { Instant.parse(now) }.getOrElse { clock() }.truncatedTo(ChronoUnit.SECONDS)
        val mine = made(db, now = at).cards(Songs.list(db), only = false)
        val theirs = (base["songs"] as? JsonArray).orEmpty()
        return JsonObject(base.mapValues { (name, value) -> if (name == "songs") JsonArray(mine + theirs) else value })
    }

    override fun cards(db: Db, songs: List<SongRow>): Map<Long, JsonObject> {
        val made = made(db, now = clock().truncatedTo(ChronoUnit.SECONDS)).cards(songs, only = true)
        return songs.zip(made).associate { (song, card) -> song.id to card }
    }

    /** library_page.result_cards of [songs], /api/search's rows' (Cards.results). */
    override fun results(db: Db, songs: List<SongRow>): Map<Long, JsonObject> =
        made(db, now = clock().truncatedTo(ChronoUnit.SECONDS)).results(songs)

    private fun made(db: Db, now: Instant): Cards {
        val served = Served(db, mirror.mirror)
        val computers = mirror.computerCards()
        return Cards(db, store.libraryDir, config(db), Overrides.read(db), now,
                     names = { song -> Cards.folderNames(store.libraryDir, song) + served.names(song) },
                     computers = { song -> computers[song.key]?.takeIf { served.asListed(song) } })
    }

    /**
     * What the mirror serves of each song's folder, read once for a build through [db]: the paths its lists name in
     * the folder (the computer's and each layer's), each counted as LibraryFiles counts it ([Mirror.pageFor] under the
     * phone's gate, each unit's answer asked once).
     */
    private class Served(private val db: Db, private val mirror: Mirror?) {
        private val answers = HashMap<Pair<String, String?>, Gate>()
        private val gate = UnitGate { unit, digest -> answers.getOrPut(unit to digest) { PhoneGate.check(db, unit, digest) } }

        /** Each folder's paths in the lists, the computer's first, each once. */
        private val byFolder: Map<String, Set<String>> by lazy {
            val found = HashMap<String, LinkedHashSet<String>>()
            val mirror = mirror ?: return@lazy found
            val lists = listOfNotNull(mirror.manifest()) + mirror.layers().mapNotNull { it.manifest() }
            for (list in lists) for (entry in list.entries) {
                val cut = entry.path.lastIndexOf('/')
                if (cut > 0) found.getOrPut(entry.path.substring(0, cut)) { LinkedHashSet() }.add(entry.path)
            }
            found
        }

        /** The computer's list's digests of each song unit it names, by unit. */
        private val listed: Map<String, Set<String>> by lazy {
            val found = HashMap<String, MutableSet<String>>()
            for (entry in mirror?.manifest()?.entries.orEmpty()) {
                val unit = entry.unit ?: continue
                found.getOrPut(unit) { HashSet() }.add(entry.digest ?: continue)
            }
            found
        }

        /** The names of the song's folder's files the mirror serves now. */
        fun names(song: SongRow): Set<String> {
            val mirror = mirror ?: return emptySet()
            val paths = byFolder[folderOf(song)] ?: return emptySet()
            return paths.filter { mirror.pageFor(it, gate) is Looked.Page }.mapTo(HashSet()) { it.substringAfterLast('/') }
        }

        /** Whether the computer listed a file of the song's unit at the digest the phone holds it at now, so that its
         * library page's card of it is of the song as the phone holds it. */
        fun asListed(song: SongRow): Boolean {
            val unit = SONG + song.key
            return listed[unit].orEmpty().any { gate.check(unit, it) == Gate.SERVE }
        }

        private fun folderOf(song: SongRow): String {
            val (artist, title) = SafeName.songFolder(song.artist, song.title)
            return "$artist/$title"
        }
    }

    private companion object {
        const val SONG = "song/"
    }
}
