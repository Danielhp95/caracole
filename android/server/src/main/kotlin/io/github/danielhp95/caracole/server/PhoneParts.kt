package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.page.SongCards
import java.io.File

/**
 * What every route module and command runner of the phone is built from (Assembly's): the database, the library,
 * the settings now ([config], read again for each use), the one queue, the cards, a lookup's clients (made for each lookup, at the settings then), the seams of
 * the pages a lookup makes ([pages], [songbooks]: NONE until milestones 5 and 6), the alerts and the pace, and
 * [searchesLacuerda] (false: `/api/search`'s `lacuerda_search` null, as `WebApp(searches_lacuerda=False)`).
 */
class PhoneParts(val database: Database, val store: LibraryStore, val stateDir: File, val config: () -> PhoneConfig,
                 val queue: JobQueue, val cards: SongCards, val clients: () -> Clients, val pages: SongPages,
                 val songbooks: SongbookPages, val alerts: Alerts, val pacing: Pacing, val searchesLacuerda: Boolean)
