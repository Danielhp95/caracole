package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.mirror.Entry
import io.github.danielhp95.caracole.server.page.internal.cards.Cards
import io.github.danielhp95.caracole.server.page.internal.cards.Producers
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull
import java.time.Instant
import java.time.temporal.ChronoUnit

/**
 * The library page's data and cards from the phone's own library (library_page.song_cards; lane library-cards): every
 * song's card made by the phone as the computer makes it of the same library (internal/cards' [Cards]), in place of
 * the mirror's cards re-identified and the minimal ones; its icons, its sites, its catalogue, its fold table, its
 * generated time and its songbooks still the mirror's ([mirror]'s data, MirrorPageData), and the mirror's cards of
 * songs the phone hasn't got (their negative ids) after the phone's.
 *
 * A song's folder holds what the phone keeps and the pages it made; the pages the computer made of a song the phone
 * holds as the computer did are the mirror's ([mirrorNames]: a file of the song's folder the mirror lists at the
 * unit's digest the phone's render last saw, else at its digest now), which the card links as its own, and which
 * LibraryFiles answers from the mirror. With no mirror, the page's data is library_page.build_library_page's of the
 * same library but its `sites` (vectors/web/cards_full.jsonl's).
 *
 * [clock] is the buy list's time for [cards] (fetch_due's ages), as /jobs.json's card is made now.
 */
class PhonePageData(val mirror: MirrorPageData, val store: LibraryStore, val config: () -> PhoneConfig,
                    val clock: () -> Instant = { Instant.now() }) : PageData, SongCards {
    override fun data(db: Db, now: String): JsonObject {
        val base = mirror.data(db, now)
        val at = runCatching { Instant.parse(now) }.getOrElse { clock() }.truncatedTo(ChronoUnit.SECONDS)
        val mine = made(db, Songs.list(db), only = false, now = at)
        val theirs = (base["songs"] as? JsonArray).orEmpty().filter { card ->
            ((card as? JsonObject)?.get("id") as? JsonPrimitive)?.longOrNull?.let { it < 0 } == true
        }
        return JsonObject(base.mapValues { (name, value) -> if (name == "songs") JsonArray(mine + theirs) else value })
    }

    override fun cards(db: Db, songs: List<SongRow>): Map<Long, JsonObject> {
        val made = made(db, songs, only = true, now = clock().truncatedTo(ChronoUnit.SECONDS))
        return songs.zip(made).associate { (song, card) -> song.id to card }
    }

    private fun made(db: Db, songs: List<SongRow>, only: Boolean, now: Instant): List<JsonObject> {
        val served = mirrorNames(db)
        return Cards(db, store.libraryDir, config(), Overrides.read(db), now) { song ->
            val own = Cards.folderNames(store.libraryDir, song)
            served(song)?.let { own + it } ?: own
        }.cards(songs, only)
    }

    /**
     * The files of each song's folder the mirror serves (a file of no unit; else its unit the song's, listed at the
     * digest the phone holds it at: its render record's, else Units.digestOf now), by the song; null for a song the
     * mirror has none of, or no mirror. Its entries are read once for the page.
     */
    private fun mirrorNames(db: Db): (SongRow) -> Set<String>? {
        val manifest = mirror.mirror?.manifest() ?: return { null }
        val byFolder = HashMap<String, MutableList<Entry>>()
        for (entry in manifest.entries) {
            val cut = entry.path.lastIndexOf('/')
            if (cut <= 0) continue
            byFolder.getOrPut(entry.path.substring(0, cut)) { ArrayList() }.add(entry)
        }
        return { song ->
            val (artist, title) = SafeName.songFolder(song.artist, song.title)
            byFolder["$artist/$title"]?.let { entries ->
                val unit = "song/${song.key}"
                val digest by lazy { Producers.rendered(db, song.id)?.first ?: Units.digestOf(db, unit) }
                entries.filter { e -> e.unit == null || (e.unit == unit && e.digest != null && e.digest == digest) }
                    .mapTo(HashSet()) { it.name }
            }
        }
    }
}
