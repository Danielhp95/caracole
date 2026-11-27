package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.CommandContext
import io.github.danielhp95.caracole.core.lookup.InteractiveAsk
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.lookup.sites.LyricsSearchCommands
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive
import java.time.Instant

/**
 * `caracole lyrics --song X --as "A - T"` replayed from the computer's records (vectors/lookup/lyrics_search.jsonl,
 * written by tests/test_conformance_lyrics_search.py, whose docstring says what each holds), each in
 * LookupScenariosReplay's world (its fixture, cache, fake sites, settings and clocks): [SEARCH], the song found by its
 * key, the name typed read as the command reads it, then [LyricsSearchCommands.search] through an InteractiveAsk at
 * the lookup's run, and its lines. Compared as every whole lookup is: the lines, the requests, events, pauses, the rows
 * (`phone_overrides`' `[lyrics]`, a song asked anew), the kv (`lyrics-search:<id>`, the misses forgotten, the sites'
 * health) and the files.
 */
object LyricsSearchReplay : AreaReplay {
    override val area = "lyrics-search"

    const val SEARCHES = "lookup/lyrics_search.jsonl"

    override fun replay(misses: Misses) {
        LookupScenariosReplay.replay(SEARCHES, misses, SEARCH)
    }

    /** The command a record's `kw` names (`song`, `as`), run as LyricsRunner runs it, its lines its result. */
    val SEARCH = LookupScenariosReplay.Run { w ->
        if (w.fn != "caracole.commands.lyrics._lyrics_as") throw AssertionError("SEARCH runs no ${w.fn}")
        val display = w.kw.getValue("song").jsonPrimitive.content
        val typed = w.kw.getValue("as").jsonPrimitive.content
        val lines = ArrayList<String>()
        w.database.writeBlocking { db ->
            val name = LyricsSearchCommands.typedName(db, typed, Songs.list(db)) ?: throw AssertionError("no name: $typed")
            val song = Songs.byKey(db, OverrideUrls.overrideKey(display)) ?: throw AssertionError("no song $display")
            val ask = InteractiveAsk(w.clients(), db, Pace.lookupRunId(w.now), w.now, Alerts.NONE, w.config)
            try {
                val found = LyricsSearchCommands.search(context(db, ask, w.now, lines), song, name, w.config)
                lines += LyricsSearchCommands.lines(song, name, found)
            } finally {
                ask.close()
            }
        }
        LookupScenariosReplay.Ran(JsonObject(mapOf("lines" to JsonArray(lines.map(::JsonPrimitive)))))
    }

    fun context(db: Db, ask: InteractiveAsk, now: Instant, lines: MutableList<String>): CommandContext =
        object : CommandContext {
            override val db: Db = db
            override val asking = ask
            override val now: Instant = now
            override fun say(line: String) {
                lines += line
            }
        }
}
