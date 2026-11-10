package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.lacuerda.LaCuerda
import io.github.danielhp95.caracole.core.library.OverridesStore
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.server.page.SongCards
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import java.time.DateTimeException
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneOffset
import java.util.WeakHashMap

/**
 * status.py's SongFacts: what the library knows of a job's song now. [sheet] is the link to its sheet (its card's
 * main file), [review] says its match needs review, [notFound] that the offline index has it nowhere, [checkedNow]
 * that a fetch looked it up since the job started (or that Ultimate Guitar can't be asked about it at all),
 * [ignored] that the phone's overrides ignore it, [picker] the link to its picker while its review has candidates,
 * [lacuerda] that the sheet picked on LaCuerda is still to be asked for, [elsewhere] what the local indexes have of
 * a song a fetch left without a sheet (a source and its page), [askedUg] that the fetch asked Ultimate Guitar, and
 * [sheetFrom] where its sheet came from (the site's tag, "UG", "LaCuerda"; "" without one).
 */
data class SongFacts(val sheet: String? = null, val review: Boolean = false, val notFound: Boolean = false,
                     val checkedNow: Boolean = false, val ignored: Boolean = false, val picker: String? = null,
                     val lacuerda: Boolean = false, val elsewhere: Pair<String, String>? = null,
                     val askedUg: Boolean = false, val sheetFrom: String = "") {
    /**
     * jobs_routes' `app._ended` on the phone: what each job over came to ([songOf]'s answer, its song's id and
     * facts), worked out once, since a job over doesn't change, and kept while the queue remembers the job
     * ([forget]). One a queue ([ended]), shared by every route that says a job's line: /jobs.json's views
     * (JobsRoutes) and the Requests tab's feed, so a finished request never ends "Not fetched yet" on the song's line
     * and "Not on the sites" in the tab once a later fetch checked its song, as Python's one cache keeps them alike.
     */
    class Ended internal constructor() {
        private val kept = HashMap<Int, Pair<Long?, SongFacts?>>()

        /** [SongFacts.songOf], from what was kept for a job over, else worked out (and kept, the job over). */
        fun songOf(db: Db, job: Job, cards: SongCards, now: Instant): Pair<Long?, SongFacts?> {
            val over = !job.active
            if (over) synchronized(kept) { kept[job.id] }?.let { return it }
            val answer = SongFacts.songOf(db, job, cards, now)
            if (over) return synchronized(kept) { kept.getOrPut(job.id) { answer } }
            return answer
        }

        /** Let go of the jobs the queue no longer remembers ([jobs], its whole snapshot). */
        fun forget(jobs: List<Job>) {
            val ids = jobs.mapTo(HashSet()) { it.id }
            synchronized(kept) { kept.keys.retainAll(ids) }
        }
    }

    companion object {
        private val ENDED = WeakHashMap<JobQueue, Ended>()

        /** The [Ended] answers of [queue]'s jobs, the same for every route that asks. */
        fun ended(queue: JobQueue): Ended = synchronized(ENDED) { ENDED.getOrPut(queue) { Ended() } }

        /** Facts as the vectors write them (status.SongFacts's fields as data), or null. */
        fun of(data: JsonElement?): SongFacts? {
            val o = data as? JsonObject ?: return null
            fun text(name: String) = (o[name] as? JsonPrimitive)?.takeIf { it.isString }?.content
            fun yes(name: String) = (o[name] as? JsonPrimitive)?.booleanOrNull == true
            val where = (o["elsewhere"] as? JsonArray)?.map { (it as JsonPrimitive).content }
            return SongFacts(text("sheet"), yes("review"), yes("not_found"), yes("checked_now"), yes("ignored"),
                             text("picker"), yes("lacuerda"), where?.let { it[0] to it[1] }, yes("asked_ug"),
                             text("sheet_from") ?: "")
        }

        /**
         * jobs_routes.song_of on the phone: the id of the job's song as the library has it now, and what its line
         * needs to know of it (null while the library has no such song). A sync's, a take's or a pull's job is no
         * song's; Make this my version and a harmonica tab's reading are their song's by its id, and none of its
         * requests (no id); a removal's song is the one it removed once it is gone. [cards] give the song's sheet
         * link (its card's main file, as the page opens it); [now], for what the indexes have elsewhere.
         *
         * A job of the phone's own that names no song by its key (an index import, PhoneKinds') has none.
         */
        fun songOf(db: Db, job: Job, cards: SongCards, now: Instant): Pair<Long?, SongFacts?> {
            val shape = Shape(job)
            if (shape.peer != null) return null to null
            if (shape.own && job.spec.kind != "add" && job.spec.kind != "remove") return null to null
            val over = !job.active
            val key = job.key
            val removal = key.startsWith(JobCommands.REMOVING)
            val export = key.startsWith(JobCommands.EXPORTING) || key.startsWith(JobCommands.READING)
            val song = if (export) job.songId?.let { Songs.byId(db, it) } else Songs.byKey(db, JobCommands.songKeyOf(key))
            var facts: SongFacts? = null
            if (song != null) {
                val entries = OverridesStore.songEntries(db, song.key)
                val ignored = song.status == "ignored" || "ignore" in entries
                val sheet = sheetHref(db, cards, song)
                var checkedNow = false
                var askedUg = false
                val started = job.startedAt
                if (over && job.fetching && sheet == null && started != null) {
                    askedUg = checkedSince(db, song, started)
                    checkedNow = askedUg || (shape.stages.isNotEmpty() && nothingToAsk(db, song))
                }
                val picker = if (song.review && !ignored && hasCandidates(song)) "review?song=${song.id}" else null
                val picked = "lacuerda" in entries && song.lacuerdaCheckedAt == null
                val sheetFrom = if (sheet != null && shape.stages.isNotEmpty()) sheetFrom(db, song) else ""
                val elsewhere = if (over && job.fetching && sheet == null && !song.review && !ignored) {
                    elsewhere(db, song, shape, now)
                } else null
                facts = SongFacts(sheet, song.review, song.matchDecision == "not_found", checkedNow, ignored, picker,
                                  picked, elsewhere, askedUg, sheetFrom)
            }
            val id = if (export) null else song?.id ?: if (removal) job.songId else null
            return id to facts
        }

        /** library_page.sheet_href: the link to the song's sheet, its card's main file, or null without one. */
        private fun sheetHref(db: Db, cards: SongCards, song: SongRow): String? {
            val files = cards.cards(db, listOf(song))[song.id]?.get("files") as? JsonArray ?: return null
            return files.filterIsInstance<JsonObject>().firstOrNull { (it["primary"] as? JsonPrimitive)?.booleanOrNull == true }
                ?.let { (it["href"] as? JsonPrimitive)?.content }
        }

        /** review.candidates_of(song) has one: a stored candidate that names a UG song (the Requests tab's picks
         * too, RequestsRoutes). */
        internal fun hasCandidates(song: SongRow): Boolean {
            val stored = try {
                Json.parseToJsonElement(song.matchCandidates.ifEmpty { "[]" })
            } catch (e: IllegalArgumentException) {
                return false
            }
            return (stored as? JsonArray).orEmpty().filterIsInstance<JsonObject>().any { c ->
                listOf("artist_key", "song_key").all { name -> truthy(c[name]) }
            }
        }

        /** Python's truth of a JSON value: none of null, false, 0, "", [] or {}. */
        private fun truthy(value: JsonElement?): Boolean = when (value) {
            null, JsonNull -> false
            is JsonPrimitive -> if (value.isString) value.content.isNotEmpty()
                                else value.content != "false" && value.content.toDoubleOrNull() != 0.0
            is JsonArray -> value.isNotEmpty()
            is JsonObject -> value.isNotEmpty()
        }

        // --- what the fetch did: ug/fetch.py's reads ----------------------------------------------------------

        /** ug.fetch.checked_since: whether a fetch settled the song at [since] or after (its `ug_checked_at`, an
         * unreadable one passed over, else, for a song with no match yet, its artist's UG page read for it: kv
         * `ug:artist_page_checked:<id>`, which, unreadable, is Python's ValueError, an [IllegalArgumentException]),
         * both written to the second. */
        private fun checkedSince(db: Db, song: SongRow, since: Instant): Boolean {
            val cutoff = since.epochSecond
            song.ugCheckedAt?.takeIf { it.isNotEmpty() }?.let(::strptime)?.let { if (it.epochSecond >= cutoff) return true }
            if (song.matchDecision == "accept" || song.matchDecision == "pinned") return false
            val value = db.kvGet("ug:artist_page_checked:${song.id}") ?: return false
            val checked = strptime(value)
                ?: throw IllegalArgumentException("time data ${value} does not match format '%Y-%m-%dT%H:%M:%SZ'")
            return checked.epochSecond >= cutoff
        }

        /**
         * `datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")` made UTC (ug.fetch._parse_iso), null where Python raises
         * ValueError: _strptime's own pattern for that format (IGNORECASE, Python's `\d`, one digit where it allows
         * one, a space before a day or an hour), re.match then the whole text read, each field read by int(), and a
         * date and time datetime takes (year 1 on, the month's days, no second 60 or 61).
         */
        internal fun strptime(value: String): Instant? {
            val m = STRPTIME.toPattern().matcher(value)
            if (!m.lookingAt() || m.end() != value.length) return null
            val f = (1..6).map { PyInt.parse(m.group(it))!!.toInt() }
            if (f[0] < 1) return null
            return try {
                LocalDateTime.of(f[0], f[1], f[2], f[3], f[4], f[5]).toInstant(ZoneOffset.UTC)
            } catch (e: DateTimeException) {
                null
            }
        }

        private val STRPTIME = PyRegex.compile(
            """(?i)(\d\d\d\d)-(1[0-2]|0[1-9]|[1-9])-(3[0-1]|[1-2]\d|0[1-9]|[1-9]| [1-9])""" +
                """T(2[0-3]|[0-1]\d|\d| \d):([0-5]\d|\d):(6[0-1]|[0-5]\d|\d)Z""",
        )

        /** jobs_routes._nothing_to_ask: the offline index doesn't have the song, and its artist's UG page isn't
         * known (ug.fetch.artist_is_known). */
        private fun nothingToAsk(db: Db, song: SongRow): Boolean =
            song.matchDecision == "not_found" && !artistIsKnown(db, song)

        /** ug.fetch.artist_is_known: the song's artist page pasted in `[artist_url]` (a tab page there counts until
         * reading it shows it leads to no artist page), learned (kv `ug:artist_url:<key>`), or in the index. */
        private fun artistIsKnown(db: Db, song: SongRow): Boolean {
            val keys = artistKeys(db, song)
            val entry = artistUrlEntry(db, keys)
            if (entry != null && pasteProblem(db, entry.second) == null) return true
            return keys.any { key ->
                db.kvGet("ug:artist_url:$key") != null ||
                    db.one("SELECT 1 FROM ug_index WHERE artist_key = ? LIMIT 1", key) { true } == true
            }
        }

        /** ug.fetch.artist_keys: `[alias]` first, then each artist's own name forms. */
        private fun artistKeys(db: Db, song: SongRow): List<String> {
            val keys = LinkedHashSet<String>()
            for (name in song.artists.ifEmpty { listOf(song.artist) }) {
                OverridesStore.alias(db, Normalize.slugKey(name))?.forEach { slug ->
                    (slug as? JsonPrimitive)?.takeIf { it.isString }?.let { keys.add(Normalize.ugSlugKey(it.content)) }
                }
                keys.addAll(Normalize.nameForms(name))
            }
            return keys.filter { it.isNotEmpty() }
        }

        /** overrides.artist_url_entry: the `[artist_url]` entry under one of [keys], else one whose name shares a
         * form with them, hyphens aside; (its key, its page). */
        private fun artistUrlEntry(db: Db, keys: List<String>): Pair<String, String>? {
            val entries = db.query("SELECT key, written, value FROM phone_overrides WHERE tbl = 'artist_url' ORDER BY rowid") {
                Triple(it.text(0)!!, it.text(1)!!, it.text(2)!!)
            }.mapNotNull { (key, written, value) ->
                val page = (Json.parseToJsonElement(value) as? JsonPrimitive)?.takeIf { it.isString }?.content
                page?.let { Triple(key, written, it) }
            }
            for (key in keys) entries.firstOrNull { it.first == key }?.let { return it.first to it.third }
            val wanted = keys.map(Normalize::compact).toSet()
            return entries.firstOrNull { (_, written, _) -> Normalize.nameForms(written).any { Normalize.compact(it) in wanted } }
                ?.let { it.first to it.third }
        }

        /** ug.fetch._failed_paste's problem: what reading the tab page an `[artist_url]` page is found wrong with it
         * (kv `ug:pasted_tab:<tab id>`'s `problem`); null for an artist page, or a tab page with none. */
        private fun pasteProblem(db: Db, page: String): String? {
            if (!page.startsWith("$TAB_HOST/tab/")) return null
            val path = page.substring(TAB_HOST.length).substringBefore('?').substringBefore('#').trimEnd('/')
            val tab = TAB_PATH.matchEntire(path)?.groupValues?.get(1) ?: return null
            val record = db.kvGet("ug:pasted_tab:${tab.toBigInteger()}")?.let {
                try {
                    Json.parseToJsonElement(it)
                } catch (e: IllegalArgumentException) {
                    null
                }
            } as? JsonObject ?: return null
            return (record["problem"] as? JsonPrimitive)?.takeIf { it.isString && it.content.isNotEmpty() }?.content
        }

        private const val TAB_HOST = "https://tabs.ultimate-guitar.com"
        private val TAB_PATH = PyRegex.compile("""/tab/(?:[^/]+/)?(?:[^/]*-)?(\d+)""")

        // --- where its sheet came from ------------------------------------------------------------------------

        /** jobs_routes._sheet_from: its kept sheet's (the human one, else the auto one) version's site's tag. */
        private fun sheetFrom(db: Db, song: SongRow): String {
            for (name in SHEETS) {
                val provider = db.one("SELECT v.provider FROM files f JOIN versions v ON v.id = f.version_id " +
                                      "WHERE f.song_id = ? AND f.name = ?", song.id, name) { it.text(0) }
                if (provider != null) return TAGS[provider] ?: provider
            }
            return ""
        }

        private val SHEETS = listOf("sheet.txt", "sheet (auto).txt")  // songs.SHEET_FILE_NAMES

        /** icons.tag: each source's tag on the command line. */
        private val TAGS = mapOf(
            "ug" to "UG", "lacuerda" to "LaCuerda", "lrclib" to "LRCLIB", "megalobiz" to "Megalobiz",
            "azlyrics" to "AZLyrics", "gtptabs" to "gtptabs", "musescore" to "MuseScore", "harptabs" to "harptabs",
            "gametabs" to "gametabs", "youtube" to "YouTube", "auto" to "auto", "inbox" to "inbox",
        )

        // --- what the local indexes have elsewhere: outcome.elsewhere ----------------------------------------

        /**
         * outcome.elsewhere: for a song a fetch left without a sheet, a sheet LaCuerda's index holds of it
         * (`("lacuerda", its page)`), else a gtptabs.com page its index lists for a song with no Guitar Pro file
         * (`("gtptabs", the page)`); null for neither. A site a new lookup would skip again is none: one the job's
         * lookup asked already, one that cools down after a block now, one its stage skipped for a block, a cooldown
         * or a spent budget, and LaCuerda once asked about the song this month, as gtptabs.com. It reads the local
         * tables alone.
         */
        internal fun elsewhere(db: Db, song: SongRow, job: Shape, now: Instant): Pair<String, String>? {
            if (song.status == "ignored") return null
            val byName = job.stages.associateBy { it.name }
            fun mayAsk(provider: String): Boolean {
                val stage = byName[provider]
                if (stage != null && (stage.state == Job.DONE || stage.detail.startsWith("asked already") ||
                        (stage.state == Job.SKIPPED && Outcomes.waited(stage.detail)))) return false
                return !Health.isCooling(db, provider, now)
            }
            if (mayAsk("lacuerda") && !askedLately(song.lacuerdaCheckedAt, now)) {
                laCuerdaSheet(db, song.artists.ifEmpty { listOf(song.artist) }, song.title)?.let { return "lacuerda" to it }
            }
            if (PhoneConfig.read(db).provider("gtptabs").enabled && mayAsk("gtptabs")) {
                gtpTabsPage(db, song, now)?.let { return "gtptabs" to it }
            }
            return null
        }

        private const val MONTH_US = 30L * 86_400_000_000L  // RECHECK_AFTER, 30 days

        private fun micros(now: Instant): Long = Stamps.parse("1970-01-01T00:00:00Z")!! +
            now.epochSecond * 1_000_000L + now.nano / 1_000

        /** lacuerda_fetch.asked_lately: LaCuerda asked about the song in the last 30 days (stamps.before). */
        private fun askedLately(checkedAt: String?, now: Instant): Boolean = !before(checkedAt, micros(now) - MONTH_US)

        /** stamps.before: a stored time older than [cutoff]; a missing or unreadable one is. */
        private fun before(value: String?, cutoff: Long): Boolean {
            val at = try {
                Stamps.parse(value)
            } catch (e: ArithmeticException) {
                null
            }
            return at == null || at < cutoff
        }

        /** lacuerda_index.sheet_page: the page of the best Letra y Acordes version the index holds of the song, by its
         * artists' names (each of their forms) and its title, compared by their keys. */
        private fun laCuerdaSheet(db: Db, artists: List<String>, title: String): String? {
            val keys = artists.flatMap { name -> (listOf(name) + Normalize.nameForms(name)).map(LaCuerda::nameKey) }
                .filter { it.isNotEmpty() }.distinct()
            val song = LaCuerda.titleKey(title)
            if (keys.isEmpty() || song.isEmpty()) return null
            val marks = keys.joinToString(", ") { "?" }
            return db.one("SELECT artist_slug, path, acordes FROM lacuerda_index WHERE artist_key IN ($marks) " +
                          "AND title_key = ? AND acordes > 0 ORDER BY popular IS NULL, popular, path LIMIT 1",
                          *keys.toTypedArray(), song) { row ->
                val n = row.long(2)!!
                "$LACUERDA/${row.text(0)!!}/${row.text(1)!!.substringAfter('/', "")}${if (n == 1L) "" else "-$n"}.shtml"
            }
        }

        private const val LACUERDA = "https://acordes.lacuerda.net"

        /** gtptabs_fetch.title_page: the gtptabs.com page whose sitemaps list the song's title under one of its
         * artists, for a song a pass would look up there now (no Guitar Pro or Power Tab file, not looked up there in
         * 30 days). */
        private fun gtpTabsPage(db: Db, song: SongRow, now: Instant): String? {
            val kept = db.one("SELECT 1 FROM files f JOIN versions v ON v.id = f.version_id WHERE f.song_id = ? " +
                              "AND v.kind IN ('guitar-pro', 'power') LIMIT 1", song.id) { true }
            if (kept == true) return null
            if (!before(db.kvGet("gtptabs:checked:${song.id}"), micros(now) - MONTH_US)) return null
            val keys = song.artists.ifEmpty { listOf(song.artist) }.flatMap(::gtpTabsArtistKeys).distinct()
            val title = Normalize.slugKey(Normalize.cleanTitle(song.title))
            if (keys.isEmpty() || title.isEmpty()) return null
            val marks = keys.joinToString(",") { "?" }
            return db.one("SELECT path FROM gtptabs_index WHERE artist_key IN ($marks) AND (title_key = ? OR base_key = ?) " +
                          "ORDER BY title_key != base_key, path LIMIT 1", *keys.toTypedArray(), title, title) {
                "https://gtptabs.com/${it.text(0)!!}"
            }
        }

        /** gtptabs.artist_keys: the name's own key and, for two words or more, the same with its last word first. */
        private fun gtpTabsArtistKeys(name: String): List<String> {
            val own = Normalize.slugKey(name)
            if (own.isEmpty()) return emptyList()
            val words = own.split("-")
            val rotated = if (words.size > 1) (listOf(words.last()) + words.dropLast(1)).joinToString("-") else own
            return listOf(own, rotated).distinct()
        }
    }
}
