package io.github.danielhp95.caracole.core.sites.internal.gametabs

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.GameTabsParseError
import io.github.danielhp95.caracole.core.http.HttpRules
import io.github.danielhp95.caracole.core.http.RobotsClosed
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.GameTabsPick
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Numbering
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.Passes
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.sites.GameTab
import io.github.danielhp95.caracole.core.sites.GameTabs
import io.github.danielhp95.caracole.core.sites.GameTabsFetch
import io.github.danielhp95.caracole.core.sites.GameTabsPages
import io.github.danielhp95.caracole.core.sites.GameTabsStats
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant

/** gametabs_fetch.py for a lookup's song, its helpers' names kept (GameTabsFetch's docstring says what it does). */
internal object Lookups {
    private const val PROVIDER = GameTabsPages.PROVIDER
    private const val KEPT = "kept"
    private const val MISSING = "missing"
    private val ACCEPT = setOf(200, 404)  // a 404 is an answer: the tab is gone

    /** What follows a game's name in a wanted.txt line that names its music: "Hollow Knight OST", "Celeste (Original
     * Soundtrack)", "Chrono Trigger Original Game Soundtrack". */
    private val SOUNDTRACK by lazy {
        PyRegex.compile("""(?i)[\s(\[-]+(?:original\s+)?(?:game\s+|video\s+game\s+)?(?:ost|soundtrack)[)\]]?\s*$""")
    }

    fun gametabsTabs(db: Db, client: Client, lib: LibraryStore, now: Instant, overrides: Overrides,
                     only: Set<Long>): GameTabsStats {
        val stats = GameTabsStats()
        GameTabsFetch.ensureCurrentKeys(db)
        val wanting = songsWantingATab(db, now, overrides, only)
        if (wanting.isEmpty()) return stats
        val index = Index(db)
        val run = Pass(db, client, lib, now)
        // Each song is checked just before its turn, as Python's generator checks it.
        val songs = wanting.asSequence()
            .filter { (pick(overrides, it) != null || index.candidates(it).isNotEmpty()) && wants(db, it, overrides) }
        for ((_, outcome) in Passes.eachSong(songs, stats, "gametabs.net") { song ->
            lookUp(run, song, index, pick(overrides, song))
        }) {
            if (outcome == KEPT) stats.kept++
            if (outcome == MISSING) stats.missing++
        }
        return stats
    }

    // --- the forms names are compared by -----------------------------------------------------------------------

    fun gameForms(name: String): List<String> {
        val names = LinkedHashSet(listOf(name, PyRe.sub(SOUNDTRACK, name) { "" }))
        return names.filter { Py.strip(it).isNotEmpty() }.flatMap { n -> Normalize.nameForms(n).filter { it.isNotEmpty() } }
    }

    fun songForms(song: SongRow): Set<String> = named(song.artists.ifEmpty { listOf(song.artist) })

    /** `_named`: the keys some names are compared by, hyphens aside. */
    private fun named(names: Iterable<String>): Set<String> =
        names.flatMapTo(LinkedHashSet()) { name -> gameForms(name).map { Normalize.compact(it) } }

    /** `_listed`: a JSON array of names, as gametabs_game_tabs keeps them. */
    private fun listed(text: String?): List<String> {
        val names = PageText.loads(text?.ifEmpty { null } ?: "[]") as? JsonArray ?: return emptyList()
        return names.mapNotNull { (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content }
    }

    fun fits(song: SongRow, tab: GameTab): Boolean {
        val key = GameTabsPages.titleKey(tab.title)
        if (key.isEmpty() || key != GameTabsPages.titleKey(song.title)) return false
        val theirs = named(listOf(tab.game) + tab.composers).toMutableSet()
        if (tab.gameSlug.isNotEmpty()) theirs += Normalize.compact(Normalize.ugSlugKey(tab.gameSlug.replace("_", "-")))
        return songForms(song).any { it in theirs }
    }

    // --- the index ---------------------------------------------------------------------------------------------

    /** `_Index`: gametabs_index and the game pages read, as a pass reads them: each game by the keys of its slug and
     * of its name once its page was read, hyphens aside, loaded once. */
    private class Index(private val db: Db) {
        private val games = HashMap<String, MutableSet<String>>()

        init {
            db.query("SELECT DISTINCT game, key FROM gametabs_index WHERE kind = ?", GAME) { it.text(0)!! to it.text(1)!! }
                .forEach { (game, key) -> games.getOrPut(Normalize.compact(key)) { HashSet() }.add(game) }
            db.query("SELECT DISTINCT game, name FROM gametabs_games WHERE name != ''") { it.text(0)!! to it.text(1)!! }
                .forEach { (game, name) -> for (form in named(listOf(name))) games.getOrPut(form) { HashSet() }.add(game) }
        }

        /** The paths of the tabs titled as the song is, at most CANDIDATES, the most viewed first (then by path): those
         * of a game one of the song's artists names, and those whose composer one of them is. */
        fun candidates(song: SongRow): List<String> {
            val key = GameTabsPages.titleKey(song.title)
            if (key.isEmpty()) return emptyList()
            val forms = songForms(song)
            val games = forms.flatMapTo(HashSet()) { this.games[it].orEmpty() }.sortedWith(Py.CODE_POINT_ORDER)
            val found = LinkedHashMap<String, Long>()
            if (games.isNotEmpty()) {
                val marks = games.joinToString(", ") { "?" }
                db.query("SELECT i.path, MAX(COALESCE(t.views, 0)) FROM gametabs_index i LEFT JOIN gametabs_game_tabs t " +
                             "ON t.path = i.path WHERE i.kind = ? AND i.game IN ($marks) AND (i.key = ? OR i.slug_key = ?) " +
                             "GROUP BY i.path", TAB, *games.toTypedArray(), key, key) { it.text(0)!! to (it.long(1) ?: 0L) }
                    .forEach { (path, views) -> found[path] = maxOf(found[path] ?: 0L, views) }
            }
            db.query("SELECT path, game, composers, views FROM gametabs_game_tabs WHERE title_key = ?", key) {
                listOf(it.text(0)!!, it.text(1)!!, it.text(2), it.long(3) ?: 0L)
            }.forEach { (path, game, composers, views) ->
                if (game in games || named(listed(composers as String?)).any { it in forms }) {
                    found[path as String] = maxOf(found[path] ?: 0L, views as Long)
                }
            }
            return found.entries.sortedWith(compareBy<Map.Entry<String, Long>> { -it.value }
                                                 .thenComparing({ it.key }, Py.CODE_POINT_ORDER))
                .take(GameTabsFetch.CANDIDATES).map { it.key }
        }
    }

    // --- which songs -------------------------------------------------------------------------------------------

    /** `_songs_wanting_a_tab`, of the songs [only] names: newest first, not ignored, with no tab from gametabs.net
     * (or not the one you picked), and not looked up there in the last 30 days (or with a pick not asked for yet).
     * Python filters `only` after; the predicate only reads, so the songs are read by their id first, in list_songs'
     * order (`added_at DESC, id DESC`, SQLite's text order a code point's), and no other song's kv is read. */
    private fun songsWantingATab(db: Db, now: Instant, overrides: Overrides, only: Set<Long>): List<SongRow> {
        val songs = only.mapNotNull { Songs.byId(db, it) }.sortedWith { a, b ->
            Py.CODE_POINT_ORDER.compare(b.addedAt, a.addedAt).takeIf { it != 0 } ?: b.id.compareTo(a.id)
        }
        if (songs.isEmpty()) return emptyList()
        val withTab = songsWithAGametab(db)
        val cutoff = Stamps.micros(now.minus(GameTabsFetch.RECHECK_AFTER))
        return songs.filter { song ->
            song.status != "ignored" && song.key !in overrides.ignore &&
                (if (pick(overrides, song) == null) song.id !in withTab else wants(db, song, overrides)) &&
                (before(db.kvGet("${GameTabsFetch.CHECKED_PREFIX}${song.id}"), cutoff) || newlyPicked(db, song, overrides))
        }
    }

    /** stamps.before: whether a stored time is older than [cutoff]; a missing or unreadable one is. */
    private fun before(value: String?, cutoff: Long): Boolean {
        val at = Stamps.parse(value)
        return at == null || at < cutoff
    }

    private fun newlyPicked(db: Db, song: SongRow, overrides: Overrides): Boolean {
        val pick = pick(overrides, song) ?: return false
        return db.kvGet("${GameTabsFetch.CHECKED_PREFIX}${song.id}${GameTabsFetch.PICKED}") != pick.path
    }

    private fun pick(overrides: Overrides, song: SongRow): GameTabsPick? = overrides.gametabs[song.key]

    /** `_wants`: the one you picked, while it hasn't kept it; else any, while it has none. */
    private fun wants(db: Db, song: SongRow, overrides: Overrides): Boolean {
        val pick = pick(overrides, song) ?: return song.id !in songsWithAGametab(db)
        return db.one("SELECT 1 FROM files f JOIN versions v ON v.id = f.version_id WHERE f.song_id = ? AND " +
                          "v.provider = ? AND v.kind = ? AND v.tab_id = ? LIMIT 1",
                      song.id, PROVIDER, GameTabsFetch.KIND, pick.path) { true } == null
    }

    /** songs_with_a_gametab: the songs the files table holds a tab from gametabs.net for. */
    private fun songsWithAGametab(db: Db): Set<Long> =
        db.query("SELECT DISTINCT f.song_id FROM files f JOIN versions v ON v.id = f.version_id WHERE v.kind = ?",
                 GameTabsFetch.KIND) { it.long(0)!! }.toSet()

    // --- one song ----------------------------------------------------------------------------------------------

    private class Pass(val db: Db, val client: Client, val lib: LibraryStore, val now: Instant) {
        val fetched = HashSet<String>()  // pages fetched from the site in this pass
        val stamp: String = Stamps.of(now)
    }

    /** `_look_up`: the song's candidates read, the most viewed that is the song's kept: KEPT; MISSING when none is.
     * With a pick, that tab alone, kept whatever its page names: MISSING when the site no longer has it. */
    private fun lookUp(run: Pass, song: SongRow, index: Index, pick: GameTabsPick?): String {
        val checked = "${GameTabsFetch.CHECKED_PREFIX}${song.id}"
        if (pick != null) {
            val tab = tab(run, pick.url)
            if (tab != null) keep(run, song, pick.path, tab)
            run.db.kvSet(checked, run.stamp)
            run.db.kvSet("$checked${GameTabsFetch.PICKED}", pick.path)
            return if (tab != null) KEPT else MISSING
        }
        val found = ArrayList<Pair<String, GameTab>>()
        for (path in index.candidates(song)) {
            val tab = tab(run, GameTabsPages.pageUrl(path))
            if (tab != null && fits(song, tab)) found += path to tab
        }
        if (found.isNotEmpty()) {
            // min(found, key=lambda f: (-f[1].views, -(f[1].rating or 0.0), f[0])): floats compared as Python's
            // are, 0.0 and -0.0 one.
            val rated = Comparator<Pair<String, GameTab>> { a, b ->
                val x = -(a.second.rating ?: 0.0)
                val y = -(b.second.rating ?: 0.0)
                if (x < y) -1 else if (x > y) 1 else 0
            }
            val (path, tab) = found.minWithOrNull(compareBy<Pair<String, GameTab>> { it.second.views.negate() }
                .then(rated).thenComparing({ it.first }, Py.CODE_POINT_ORDER))!!
            keep(run, song, path, tab)
        }
        run.db.kvSet(checked, run.stamp)
        return if (found.isNotEmpty()) KEPT else MISSING
    }

    /** `_tab`: a tab page, read; null when the site no longer has it (404), or sends it where robots.txt closes. A
     * cached page that won't parse is asked for once more before it is an error. */
    private fun tab(run: Pass, url: String): GameTab? {
        val resp = try {
            run.client.get(url, accept = ACCEPT)
        } catch (e: RobotsClosed) {
            return null
        }
        return HttpRules.readOnceMore(run.client, resp, url, { it is GameTabsParseError }, fetched = run.fetched,
                                      accept = ACCEPT) { r -> if (r.status == 404) null else TabPages.parse(r.content, r.url) }
    }

    /** `_keep`: the tab as the song's next `gametab-N.txt`, with its version; its name. The version's votes are its
     * views, Python's int, which SQLite holds to a signed 64-bit integer (sqlite3's OverflowError past it, before
     * anything is written). */
    private fun keep(run: Pass, song: SongRow, path: String, tab: GameTab): String {
        if (tab.views.bitLength() > 63) throw OverflowError("Python int too large to convert to SQLite INTEGER")
        val votes = tab.views.toLong()
        val versionId = Versions.upsert(
            run.db, provider = PROVIDER, tabId = path, songId = song.id, slot = "guitar", kind = GameTabsFetch.KIND,
            rating = tab.rating?.takeIf { it != 0.0 } ?: 0.0, votes = votes.coerceAtMost(Int.MAX_VALUE.toLong()).toInt(), version = 1,
            label = null, url = GameTabsPages.pageUrl(path), raw = tab.raw(), now = run.stamp,
        )
        if (votes > Int.MAX_VALUE) run.db.execute("UPDATE versions SET votes = ? WHERE id = ?", votes, versionId)
        val number = Numbering.gametab(run.db, run.lib, song)
        val name = "gametab-$number.txt"
        Kept.keepFile(run.db, run.lib, song, versionId, name, tab.body.toByteArray(Charsets.UTF_8), number, run.stamp)
        return name
    }

    private const val TAB = GameTabs.TAB
    private const val GAME = GameTabs.GAME
}
