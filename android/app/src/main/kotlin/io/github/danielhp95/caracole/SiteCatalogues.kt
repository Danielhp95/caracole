package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.core.catalogues.Catalogues
import io.github.danielhp95.caracole.core.catalogues.Named
import io.github.danielhp95.caracole.core.catalogues.Names
import io.github.danielhp95.caracole.core.catalogues.date
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import io.github.danielhp95.caracole.server.jobs.QueueFull
import io.github.danielhp95.caracole.server.lookups.CataloguesRunner
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull
import java.time.Duration
import java.time.Instant

/**
 * What the app says and decides of the site catalogues (CataloguesRunner's job, Settings' row and the first start's
 * card), apart from Android, so that a JVM test holds it: the date Settings shows ([fresh], [day], [age]), whether the
 * first start offers them ([firstStart]), and the question a metered network leaves ([asking], [question]). Its
 * words are the app's strings.xml; the ones it makes here are the job's ([size]) and core.catalogues' ([day]).
 */
object SiteCatalogues {
    /** kv: when the first start offered the catalogues (or found a site's index there already), so it decides once. */
    const val OFFERED = "catalogues:offered"

    /** kv: the computer's indexes' stamps as the phone merged them last, a record a computer (SyncEngine.INDEX_KEY). */
    const val COMPUTERS = "sync:index:"

    /** Where the indexes Settings dates came from: the site catalogues imported, or a computer's, by a sync. */
    enum class Source { CATALOGUES, COMPUTER }

    data class Fresh(val source: Source, val at: Instant)

    /**
     * How fresh the phone's site indexes are, as Settings says it: the catalogues imported last ([imported], kv
     * `catalogues:imported`, the file's name, which names its minute: core.catalogues' Names), or the computer's
     * indexes as a sync merged them ([computers], each kv [COMPUTERS] record, `{site: stamp}`), the newer of the two
     * (the catalogues on a tie); none when neither was ever taken. Never the phone's own reads (a lookup's UG artist
     * page, an artist's Songs on harptabs.com), which say nothing of how old the rest is.
     */
    fun fresh(imported: String?, computers: List<String?>): Fresh? {
        val catalogues = imported?.let(Names::read)?.let { Fresh(Source.CATALOGUES, it.at) }
        val computer = newest(computers.flatMap(::stampsOf))?.let { Fresh(Source.COMPUTER, it) }
        return listOfNotNull(catalogues, computer).maxByOrNull { it.at }  // the first of the newest: the catalogues
    }

    /** [fresh] as the phone's database [db] has it: kv `catalogues:imported` and each kv [COMPUTERS] record. */
    fun read(db: Db): Fresh? = fresh(db.kvGet(Catalogues.IMPORTED),
                                     db.query("SELECT value FROM kv WHERE key >= ? AND key < ?", COMPUTERS,
                                              COMPUTERS.dropLast(1) + ";") { it.text(0) })

    /** A kv [COMPUTERS] record's stamps; none of a record that isn't a JSON object of texts. */
    private fun stampsOf(text: String?): List<String> {
        val doc = try {
            text?.let(PyJson::loads)
        } catch (e: Exception) {
            null
        } as? JsonObject ?: return emptyList()
        return doc.values.mapNotNull { (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content }
    }

    /** The newest of [stamps], none for none; a time Stamps can't read is none. */
    private fun newest(stamps: List<String>): Instant? = stamps.mapNotNull { stamp ->
        try {
            Stamps.parse(stamp)?.let(Stamps::instant)
        } catch (e: ArithmeticException) {
            null
        }
    }.maxOrNull()

    /** [at]'s day in UTC as "3 Nov 2026", English months from core.catalogues' table. */
    fun day(at: Instant): String = date(Named(0, at))

    /** How old a time is, as Settings says it: today, then days to 13, weeks to 8, months (of 30 days) to 11, years. */
    enum class Unit { TODAY, DAYS, WEEKS, MONTHS, YEARS }

    data class Age(val unit: Unit, val count: Int)

    /** How old [at] is at [now], in whole days (a time after [now], a laptop's clock ahead, is today's). */
    fun age(at: Instant, now: Instant): Age {
        val days = Duration.between(at, now).toDays()
        return when {
            days < 1 -> Age(Unit.TODAY, 0)
            days < 14 -> Age(Unit.DAYS, days.toInt())
            days < 60 -> Age(Unit.WEEKS, (days / 7).toInt())
            days < 365 -> Age(Unit.MONTHS, minOf(days / 30, 11L).toInt())  // 360 to 364 days: 11, not 12
            else -> Age(Unit.YEARS, (days / 365).toInt())
        }
    }

    /** What a start does of the offer: [OFFER] it (recorded once answered), record it [DECIDED] (a site's index is
     * there already: no later start need look again), or [NOTHING]. */
    enum class FirstStart { OFFER, DECIDED, NOTHING }

    /**
     * Whether the start offers the catalogues: no computer set ([server] blank), never offered nor decided before
     * ([offered], kv [OFFERED]), and no site's index holding a tab ([holdsIndex]), which is asked only once both
     * cheaper checks leave the offer open, so a start with a computer set, or after the offer, counts no table.
     */
    fun firstStart(server: String, offered: String?, holdsIndex: () -> Boolean): FirstStart = when {
        server.isNotBlank() || offered != null -> FirstStart.NOTHING
        holdsIndex() -> FirstStart.DECIDED
        else -> FirstStart.OFFER
    }

    /** The file a metered network left waiting for the owner's go-ahead (kv `catalogues:asking`). */
    data class Asking(val name: String, val bytes: Long)

    /** kv `catalogues:asking`'s text read: `{"name": text, "bytes": number}`, none else. */
    fun asking(text: String?): Asking? {
        val doc = try {
            text?.let(PyJson::loads)
        } catch (e: Exception) {
            null
        } as? JsonObject ?: return null
        val name = (doc["name"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return null
        val bytes = (doc["bytes"] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull ?: return null
        return Asking(name, bytes)
    }

    /**
     * The question to ask after the newest catalogues job, [job] by its key ([keyOf]), ended [state] with its line's
     * [tone]: the file waiting, when the job stopped for a metered network (done, its line a wait: the kind's
     * otherwise) and [asking] names it, whoever queued it (Settings' Download, the first start's, the Journal's Try
     * again), until it is [answered] (Settings.cataloguesAnswered, the last job's key answered); none else.
     */
    fun question(state: String, tone: String, asking: Asking?, job: String, answered: String?): Asking? =
        if (state == Job.DONE && tone == WAITING && job != answered) asking else null

    /** A job's key for its question: its id and the second it was queued, as the Journal's history keeps them. */
    fun keyOf(id: Int, queuedAt: Instant): String = "$id@${queuedAt.epochSecond}"

    /** Whether a job in [state] is over: done, failed, cancelled, or cut short by the app's end. */
    fun over(state: String): Boolean = state in OVER

    /** The catalogues' job queued ([meteredOk]: the owner's go-ahead on a metered network), as BackupsActivity queues
     * a backup; the job waiting or running answers a second tap (CataloguesRunner.spec); null when the queue is full. */
    fun queue(phone: Phone, meteredOk: Boolean): Job? = try {
        phone.queue.submit(phone.catalogues.spec(meteredOk)).first
    } catch (_: QueueFull) {
        null
    }

    /** The newest of [jobs] that is a catalogues job, none for none. */
    fun newestOf(jobs: List<Job>): Job? = jobs.filter { it.spec.kind == PhoneKinds.CATALOGUES.kind }.maxByOrNull { it.id }

    /** A size as the job says one ("52 MB"). */
    fun size(bytes: Long): String = CataloguesRunner.size(bytes)

    private const val WAITING = "waiting"
    private val OVER = setOf(Job.DONE, Job.FAILED, Job.CANCELLED, Job.INTERRUPTED)
}
