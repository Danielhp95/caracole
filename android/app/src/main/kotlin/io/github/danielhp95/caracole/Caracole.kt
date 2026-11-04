package io.github.danielhp95.caracole

import android.content.Context
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.http.RealTransport
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.mirror.Http
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.mirror.Progress
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.PhoneDeps
import io.github.danielhp95.caracole.server.files.FileTypes
import io.github.danielhp95.caracole.server.http.Security
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import java.io.File
import java.security.SecureRandom
import java.util.Locale

/**
 * What the app's parts share in its process: the one [Mirror], the phone's caracole ([phone]: its database, its job
 * queue and its server on 127.0.0.1), what keeps its queue's work going ([working]), the launch's secret, and where
 * the mirror's sync stands ([status]).
 *
 * The app's files (the plan's §5.4): `caracole.sqlite` (caracole's schema and the phone's tables: the indexes
 * imported, the songs taken or added), `library/` (the phone's kept files), `state/` (`backups/`, and `cache/`, the
 * index files fetched or picked until they are merged), and the mirror's `blobs/` and `manifest.json`.
 */
object Caracole {
    /** The port the server asks for first: a fixed origin keeps the viewers' localStorage across launches. */
    const val PORT = 8738
    private const val DATABASE = "caracole.sqlite"

    private val random = SecureRandom()

    /**
     * The launch's secret, 32 random bytes in hex: the cookie the WebView carries ([cookie]) and the server checks on
     * every request, so no other app on the phone can use the server on 127.0.0.1.
     */
    val secret: String = hex(32)

    /** The served pages' form token, made at each launch as caracole serve makes its own. */
    private val csrf: String = hex(32)

    /**
     * The transport a site's request goes through, read on every request: [RealTransport], unless an instrumentation
     * runner set [sitesForTests] (CaracoleTestRunner: a transport that refuses every site, or a test's
     * RoutedTransport to the fake sites server).
     */
    fun transport(): Transport = sitesForTests ?: RealTransport

    /** A test's sites: set by CaracoleTestRunner before Application.onCreate, so the app under test reaches none. */
    @Volatile var sitesForTests: Transport? = null

    /** False under CaracoleTestRunner: `/api/search`'s `lacuerda_search` null, so no page sends LaCuerda a search. */
    @Volatile var searchesLacuerdaForTests: Boolean = true

    /** The phone's alerts (lane alerts-backups' Android notifications; none until then). */
    var alerts: Alerts = Alerts.NONE

    /** The process's own work: the phone's job queue, and what a screen starts that must outlive it. */
    val background = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    @Volatile private var mirror: Mirror? = null
    @Volatile private var phone: Phone? = null
    @Volatile private var working: Working? = null

    /** The copy of the library, in the app's files folder: `blobs/` and `manifest.json`. */
    fun mirror(context: Context): Mirror = mirror ?: synchronized(this) {
        mirror ?: Mirror(context.applicationContext.filesDir).also { mirror = it }
    }

    /**
     * The phone's caracole, its server listening: made once a process, by the first caller, on its own thread (never
     * the main one: it opens the database, migrating and seeding it on the first start, and binds the port).
     */
    fun phone(context: Context): Phone = phone ?: synchronized(this) {
        phone ?: start(context.applicationContext).also { phone = it }
    }

    /** The phone's caracole once it has started, else null. */
    fun started(): Phone? = phone

    /** What keeps the phone's caracole working while its queue works ([SyncService]), once it has started. */
    internal fun working(): Working? = working

    private fun start(context: Context): Phone {
        val files = context.filesDir
        val database = openDatabase(File(files, DATABASE))
        try {
            val library = File(files, "library").apply { mkdirs() }
            val state = File(files, "state").apply { mkdirs() }
            cacheDir(context).mkdirs()
            val phone = Phone(PhoneDeps(
                database = database, libraryDir = library, stateDir = state, mirror = mirror(context), scope = background,
                settings = SavedAddress(Settings(context)), secret = secret, csrf = csrf,
                transport = { _ -> transport() }, version = BuildConfig.VERSION_NAME, alerts = alerts,
                searchesLacuerda = searchesLacuerdaForTests,
            ))
            // A job the queue gets (a sync from the Sync tab, an add, a removal) keeps the process going in the
            // foreground until none waits or runs: the queue tells, the service follows.
            val working = Working(phone.queue::snapshot, background, start = { SyncService.start(context) })
            phone.queue.onBusy = working::busy
            phone.server.start(PORT)
            this.working = working
            return phone
        } catch (e: Throwable) {
            database.close()
            throw e
        }
    }

    /**
     * The phone's database at [file], made whole on the first start ([PhoneDatabase]): migrated, seeded with the kv
     * records a fresh computer's database holds (IndexTransfer.seedFresh), and its WAL checkpointed into the file and
     * truncated, so a close that leaves its WAL behind (a connection's close failing) leaves an empty one, never a
     * database the next start can't name.
     */
    internal fun openDatabase(file: File): Database = PhoneDatabase.open(file, { Database(it) }) { fresh ->
        fresh.writeBlocking { db ->
            IndexTransfer.seedFresh(db)
            db.query("PRAGMA wal_checkpoint(TRUNCATE)") { }
        }
    }

    /** The launch's cookie, for the server's origin alone (the WebView loads no other: Links). */
    fun cookie(): String = "${Security.SECRET_COOKIE}=$secret; Path=/; HttpOnly; SameSite=Lax"

    /** Where an index waits to be merged: `files/state/cache/`. */
    fun cacheDir(context: Context): File = File(context.applicationContext.filesDir, "state/cache")

    /**
     * Whether [path] of the library ("Estopa/Tu calorro/sheet.pdf") is a file another app opens rather than a page the
     * WebView shows: one the copy lists that is no page, or of a kind the phone's own folder serves (FileTypes).
     */
    fun isFile(context: Context, path: String): Boolean {
        val listed = mirror(context).lookup(path)
        if (listed != null) return !listed.entry.isPage
        return FileTypes.suffix(path).lowercase(Locale.ROOT) in FileTypes.TYPES
    }

    fun http() = Http(userAgent = "caracole-android/${BuildConfig.VERSION_NAME}")

    /** Where the sync stands, for the screens that show it. */
    val status = MutableStateFlow<SyncState>(SyncState.Idle)

    /** [bytes] random bytes in lowercase hex, each digit written by hand (no locale's formatting). */
    private fun hex(bytes: Int): String = buildString {
        for (b in ByteArray(bytes).also { random.nextBytes(it) }) append(HEX[(b.toInt() shr 4) and 15]).append(HEX[b.toInt() and 15])
    }

    private const val HEX = "0123456789abcdef"
}

/** Where a sync stands. */
sealed interface SyncState {
    data object Idle : SyncState

    /** Running: [progress] is null while it asks caracole for the list. */
    data class Running(val progress: Progress?) : SyncState

    /** Over, with its [outcome]. */
    data class Ended(val outcome: Outcome) : SyncState
}

/** How a sync ended, [at] a time: [ok], and what it did ([text]: "12 files new, 2 removed") or why it failed. */
data class Outcome(val at: Long, val ok: Boolean, val text: String)
