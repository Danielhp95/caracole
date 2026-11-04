package io.github.danielhp95.caracole.core.db

import androidx.sqlite.SQLiteConnection
import androidx.sqlite.SQLiteDriver
import androidx.sqlite.SQLiteStatement
import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.sqlite.execSQL
import io.github.danielhp95.caracole.core.json.PyJson
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.SecureRandom
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/**
 * caracole's database on the phone: db.py's schema in the bundled SQLite (3.50.1, FTS5), migrated as db.py migrates
 * it, then the phone's own tables ([PhoneSchema]). Its schema is Python's to the byte: DatabaseTest holds
 * `sqlite_master` and every table's columns to vectors/schema/ (tests/test_conformance_schema.py).
 *
 * Threads (the plan's §5.5): one writer connection, used under [writes] alone ([write], [writeBlocking]), and a pool
 * of [readers] connections, each lent to one block at a time ([read]); the bundled SQLite is THREADSAFE=2 (one
 * connection, one thread at a time), so a connection is never used by two threads at once. A read sees the last
 * commit (WAL): never a write's open transaction, its own thread's included. Every connection sets [BUSY_TIMEOUT_MS]
 * first, then db.py's foreign_keys, WAL and synchronous=NORMAL, and [journalSizeLimit]. [write] is not reentrant: a
 * write asked for inside a write's block, on its thread, is refused rather than waiting for itself. A connection goes
 * back in no transaction: one a block began with a bare BEGIN and left open is rolled back (and refused, for a write
 * that returned).
 *
 * The WAL (the plan's prep-db): a big write (an index import, a sync's merge) grows it past [journalSizeLimit] while
 * it runs, and SQLite's own checkpoints copy it back but keep the file; [checkpoint] gives it back whole, as the
 * import and the sync's index stage ask after their merge, and so does opening a database whose WAL a phone killed
 * with it open left over the limit. [warmUp] reads ahead what the first search reads (Warmup).
 *
 * Opening migrates once per path (every [Database] of this process on one file waits for the one opening it), from
 * caracole/schema/migrations.json, as db.py's `_migrate_locked`: the version read under the lock; a database at
 * 0 < user_version < [SCHEMA_VERSION] first copied to `<path>.v<N>.bak` (VACUUM INTO under a name of its own, then put
 * in the older copy's place); each version in BEGIN IMMEDIATE … PRAGMA user_version = N … COMMIT, a statement at a
 * time (the bundled driver runs the first statement of a text and drops the rest), a failure rolling it back whole; a
 * newer database is [DatabaseTooNew], left as it is. Then [PhoneSchema], under the same lock.
 */
class Database(val path: File, driver: SQLiteDriver = BundledSQLiteDriver(), readers: Int = 4,
               val journalSizeLimit: Long = JOURNAL_SIZE_LIMIT) : AutoCloseable {
    companion object {
        const val SCHEMA_VERSION = 15
        const val SQLITE_SOURCE_ID = "2025-06-06 14:52:32 b77dc5e0f596d2140d9ac682b2893ff65d3a4140aa86067a3efebe29dc914c95"
        const val BUSY_TIMEOUT_MS = 10_000

        /** The most a WAL file keeps on disk once a checkpoint has copied it back (PRAGMA journal_size_limit, every
         * connection's): 16 MiB. A big write grows it past that while it runs; its checkpoint gives the rest back. */
        const val JOURNAL_SIZE_LIMIT: Long = 16L * 1024 * 1024

        private val migrating = ConcurrentHashMap<String, ReentrantLock>()
        private val random = SecureRandom()

        /** db.py's migrations, statement by statement: version → statements, versions 1 to [SCHEMA_VERSION] in order. */
        internal val migrations: Map<Int, List<String>> by lazy {
            val text = resource("caracole/schema/migrations.json")
            val root = Json.parseToJsonElement(text).jsonObject
            val schema = root.getValue("schema").jsonPrimitive.intOrNull
            check(schema == SCHEMA_VERSION) { "migrations.json is schema $schema, this build $SCHEMA_VERSION" }
            val versions = root.getValue("statements").jsonObject.entries
                .map { (version, list) -> version.toInt() to list.jsonArray.map { it.jsonPrimitive.content } }
                .sortedBy { it.first }
            check(versions.map { it.first } == (1..SCHEMA_VERSION).toList()) {
                "migrations.json holds versions ${versions.map { it.first }}, not 1 to $SCHEMA_VERSION"
            }
            versions.toMap(LinkedHashMap())
        }

        internal fun resource(name: String): String {
            val stream = Database::class.java.classLoader?.getResourceAsStream(name)
                ?: Database::class.java.getResourceAsStream("/$name")
                ?: throw IllegalStateException("the resource $name is missing")
            return stream.use { it.readBytes().toString(Charsets.UTF_8) }
        }

        /** secrets.token_hex(6), its digits written by hand (no locale's formatting). */
        internal fun token(): String {
            val bytes = ByteArray(6).also { random.nextBytes(it) }
            return buildString { for (b in bytes) append(HEX[(b.toInt() shr 4) and 15]).append(HEX[b.toInt() and 15]) }
        }

        private const val HEX = "0123456789abcdef"

        /** os.replace: [from] in [to]'s place, in one rename. */
        internal fun replace(from: File, to: File) {
            try {
                Files.move(from.toPath(), to.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
            } catch (e: AtomicMoveNotSupportedException) {
                Files.move(from.toPath(), to.toPath(), StandardCopyOption.REPLACE_EXISTING)
            }
        }

        /** VACUUM INTO a name of its own beside [target], then that copy in [target]'s place: VACUUM INTO overwrites
         * nothing, and a copy cut short is never taken for a whole one. */
        internal fun vacuumInto(connection: SQLiteConnection, target: File) {
            val partial = File(target.path + "." + token() + ".part")
            try {
                connection.prepare("VACUUM INTO ?").use { it.bindText(1, partial.path); it.step() }
                replace(partial, target)
            } finally {
                partial.delete()
            }
        }
    }

    /** caracole's lock on the phone: the writer connection is used under it alone. */
    val writes: Mutex = Mutex()

    private val writer: SQLiteConnection
    private val pool: ArrayBlockingQueue<SQLiteConnection>
    private val readerCount = readers
    private val all = ArrayList<SQLiteConnection>()
    private val writing = ThreadLocal.withInitial { false }
    private val reading = ThreadLocal.withInitial { 0 }

    init {
        require(readers >= 1) { "a database needs a reader at least" }
        path.absoluteFile.parentFile?.mkdirs()
        try {
            // The writer opens under the lock too: SQLite answers a first switch to WAL beside another connection's
            // transaction with SQLITE_BUSY at once, never waiting its busy timeout.
            val lock = migrating.computeIfAbsent(path.canonicalPath) { ReentrantLock() }
            writer = lock.withLock {
                open(driver).also { connection ->
                    migrate(connection)
                    PhoneSchema.migrate(Db(connection))
                    // What a phone killed with the database open left of a big write: given back before any read.
                    if (File(path.path + "-wal").length() > journalSizeLimit) checkpointOn(connection, truncate = true)
                }
            }
            pool = ArrayBlockingQueue(readers)
            repeat(readers) { pool.add(open(driver)) }
        } catch (e: Throwable) {
            all.forEach { runCatching { it.close() } }
            all.clear()
            throw e
        }
    }

    private fun open(driver: SQLiteDriver): SQLiteConnection {
        val connection = driver.open(path.path)
        all.add(connection)
        // The busy timeout first: changing the journal mode waits for another connection's transaction too.
        connection.execSQL("PRAGMA busy_timeout = $BUSY_TIMEOUT_MS")
        connection.execSQL("PRAGMA foreign_keys = ON")
        connection.prepare("PRAGMA journal_mode = WAL").use { it.step() }
        // No fsync on each commit, as db.py: a crash may lose the last commits, never the database (WAL).
        connection.execSQL("PRAGMA synchronous = NORMAL")
        connection.prepare("PRAGMA journal_size_limit = $journalSizeLimit").use { it.step() }
        return connection
    }

    private fun version(connection: SQLiteConnection): Int {
        val current = connection.prepare("PRAGMA user_version").use { it.step(); it.getLong(0).toInt() }
        if (current > SCHEMA_VERSION) {
            val backup = File(path.path + ".v$SCHEMA_VERSION.bak")
            val restore = if (backup.exists()) ", or restore ${backup.name}, the copy saved before it was migrated" else ""
            throw DatabaseTooNew(
                "$path is at schema version $current, but this caracole knows up to $SCHEMA_VERSION: " +
                    "a newer caracole migrated it. Run that caracole$restore.",
            )
        }
        return current
    }

    /** db.py's `_migrate_locked`, under the path's lock. */
    private fun migrate(connection: SQLiteConnection) {
        val current = version(connection)
        val pending = migrations.filterKeys { it > current }
        if (current > 0 && pending.isNotEmpty()) vacuumInto(connection, File(path.path + ".v$current.bak"))
        for ((version, statements) in pending) {
            connection.execSQL("BEGIN IMMEDIATE")
            try {
                for (statement in statements) connection.prepare(statement).use { while (it.step()) Unit }
                connection.execSQL("PRAGMA user_version = $version")
                connection.execSQL("COMMIT")
            } catch (e: Throwable) {
                if (connection.inTransaction()) connection.execSQL("ROLLBACK")
                throw e
            }
        }
    }

    /** A pooled connection for [block] alone, which never writes and never suspends; it waits for one to be free. A
     * transaction the block began and left open is rolled back before the connection goes back, so it pins no old
     * snapshot for the next block. */
    fun <T> read(block: (Db) -> T): T {
        val connection = pool.take()
        reading.set(reading.get() + 1)
        try {
            return block(Db(connection))
        } finally {
            reading.set(reading.get() - 1)
            try {
                if (connection.inTransaction()) connection.execSQL("ROLLBACK")
            } finally {
                pool.put(connection)
            }
        }
    }

    /** The one writer connection, under [writes]. */
    suspend fun <T> write(block: (Db) -> T): T {
        check(!writing.get()) { "a write inside a write's block would wait for itself" }
        return writes.withLock { writing(block) }
    }

    /** [write], for a caller that is not a coroutine (a test, a worker waiting on its job). */
    fun <T> writeBlocking(block: (Db) -> T): T {
        check(!writing.get()) { "a write inside a write's block would wait for itself" }
        return runBlocking { writes.withLock { writing(block) } }
    }

    /** [block] on the writer, which it leaves in no transaction: one it began and left open (a bare BEGIN, never
     * a [Db.savepoint], which ends its own) is rolled back, and a block that returned with one open is an
     * IllegalStateException, since every later write's savepoint would nest in it and never commit. */
    private fun <T> writing(block: (Db) -> T): T {
        writing.set(true)
        try {
            val result = try {
                block(Db(writer))
            } catch (e: Throwable) {
                if (writer.inTransaction()) {
                    try {
                        writer.execSQL("ROLLBACK")
                    } catch (undoing: Throwable) {
                        e.addSuppressed(undoing)
                    }
                }
                throw e
            }
            if (writer.inTransaction()) {
                writer.execSQL("ROLLBACK")
                throw IllegalStateException("a write's block left a transaction open: its writes are undone")
            }
            return result
        } finally {
            writing.set(false)
        }
    }

    /** A whole copy of the database at [target], as it was at the last commit: VACUUM INTO a name of its own beside
     * it, then a rename in its place. */
    fun backupTo(target: File) {
        target.absoluteFile.parentFile?.mkdirs()
        read { db -> vacuumInto(db.raw, target) }
    }

    /**
     * A WAL checkpoint after a big write (an index import, a sync's merge): every frame copied back into the
     * database, then the WAL file truncated to nothing ([truncate], `PRAGMA wal_checkpoint(TRUNCATE)`), or left for
     * the next write to restart and cut to [journalSizeLimit] (PASSIVE). It runs on the writer, under [writes], with
     * every reader of the pool taken first, so that none holds a snapshot that would keep the WAL (a read that runs
     * ends first: Database.read rolls each block back, so the pool holds none between reads). Reads wait for it; a
     * checkpoint asked for inside a read's or a write's block, which would wait for itself, is an
     * IllegalStateException.
     */
    fun checkpoint(truncate: Boolean = true): Checkpointed {
        check(!writing.get()) { "a checkpoint inside a write's block would wait for itself" }
        check(reading.get() == 0) { "a checkpoint inside a read's block would wait for its own reader" }
        return runBlocking {
            writes.withLock {
                val taken = ArrayList<SQLiteConnection>(readerCount)
                try {
                    repeat(readerCount) { taken.add(pool.take()) }
                    Timings.time("checkpoint") { checkpointOn(writer, truncate) }
                } finally {
                    taken.forEach { pool.put(it) }
                }
            }
        }
    }

    private fun checkpointOn(connection: SQLiteConnection, truncate: Boolean): Checkpointed =
        connection.prepare("PRAGMA wal_checkpoint(${if (truncate) "TRUNCATE" else "PASSIVE"})").use {
            it.step()
            Checkpointed(busy = it.getLong(0) != 0L, log = it.getLong(1), checkpointed = it.getLong(2))
        }

    /** What the first search after a start reads, read ahead through the reader pool ([Warmup]: the app's start
     * launches it on Dispatchers.IO, and it never holds the search's lock); a search that comes meanwhile runs beside
     * it. A database that can't be read is no warm-up's to report: the search says so. */
    fun warmUp() = Warmup.run(this)

    override fun close() {
        all.forEach { runCatching { it.close() } }
        all.clear()
    }
}

/** One connection, lent for a block: queries, kv, savepoints.
 *
 * [query], [one] and [execute] take one statement a call, as Python's sqlite3 `execute` does: a text holding a second
 * statement after the first's `;` is an IllegalArgumentException before anything runs ([Statements], SQLite's own
 * `sqlite3_complete` reading, so a trigger's body is one), where the bundled driver would run the first and drop the
 * rest. Several statements are a list, run one at a time, as migrations.json holds them. */
class Db internal constructor(val raw: SQLiteConnection) {
    companion object {
        /** The bundled SQLite's SQLITE_MAX_VARIABLE_NUMBER: a statement binds no more values than this. */
        const val MAX_VARIABLES = 32_766

        /** [values] in lists of [size] at most, each one statement's: an `IN (…)` of any length. */
        fun <T> chunks(values: List<T>, size: Int = MAX_VARIABLES): List<List<T>> {
            require(size in 1..MAX_VARIABLES) { "a chunk of $size values: 1 to $MAX_VARIABLES" }
            return values.chunked(size)
        }
    }

    fun <T> query(sql: String, vararg args: Any?, row: (Row) -> T): List<T> = prepare(sql, args).use { st ->
        bind(st, args)
        val reading = StatementRow(st)
        val out = ArrayList<T>()
        while (st.step()) out.add(row(reading))
        out
    }

    fun <T> one(sql: String, vararg args: Any?, row: (Row) -> T): T? = prepare(sql, args).use { st ->
        bind(st, args)
        if (st.step()) row(StatementRow(st)) else null
    }

    /** Runs one statement; the rows it changed (changes()). */
    fun execute(sql: String, vararg args: Any?): Int {
        prepare(sql, args).use { st ->
            bind(st, args)
            while (st.step()) Unit
        }
        return raw.prepare("SELECT changes()").use { it.step(); it.getLong(0).toInt() }
    }

    fun lastRowid(): Long = raw.prepare("SELECT last_insert_rowid()").use { it.step(); it.getLong(0) }

    /** db.savepoint: [block]'s writes, all or none, a transaction of its own or one nested in the caller's (a name
     * met again nests too). Any exception undoes the block and goes on up, so a caller's savepoint can still undo it. */
    fun <T> savepoint(name: String, block: () -> T): T {
        val id = identifier(name)
        raw.execSQL("SAVEPOINT $id")
        val result = try {
            block()
        } catch (e: Throwable) {
            try {
                raw.execSQL("ROLLBACK TO $id")
                raw.execSQL("RELEASE $id")
            } catch (undoing: Throwable) {
                e.addSuppressed(undoing)
            }
            throw e
        }
        raw.execSQL("RELEASE $id")
        return result
    }

    fun kvGet(key: String): String? = one("SELECT value FROM kv WHERE key = ?", key) { it.text(0) }

    fun kvSet(key: String, value: String) {
        execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", key, value)
    }

    fun kvDelete(key: String) {
        execute("DELETE FROM kv WHERE key = ?", key)
    }

    fun kvGetJson(key: String): JsonElement? = kvGet(key)?.let { Json.parseToJsonElement(it) }

    /** db.kv_set_json's bytes: json.dumps(value, ensure_ascii=False). */
    fun kvSetJson(key: String, value: JsonElement) = kvSet(key, PyJson.dumps(value))

    fun attach(file: File, alias: String) {
        raw.prepare("ATTACH DATABASE ? AS ${identifier(alias)}").use { it.bindText(1, file.path); it.step() }
    }

    fun detach(alias: String) {
        raw.execSQL("DETACH DATABASE ${identifier(alias)}")
    }

    private fun identifier(name: String): String {
        val plain = name.isNotEmpty() && name.withIndex().all { (i, c) ->
            c == '_' || c in 'A'..'Z' || c in 'a'..'z' || (i > 0 && c in '0'..'9')
        }
        require(plain) { "not a plain identifier: $name" }
        return name
    }

    private fun prepare(sql: String, args: Array<out Any?>): SQLiteStatement {
        require(args.size <= MAX_VARIABLES) { "${args.size} values for one statement: SQLite binds $MAX_VARIABLES at most (Db.chunks)" }
        Statements.one(sql)
        return raw.prepare(sql)
    }

    /** Long, Int, Double, String, ByteArray, Boolean (1 or 0) and null, as Python's sqlite3 binds them. */
    private fun bind(st: SQLiteStatement, args: Array<out Any?>) {
        args.forEachIndexed { i, arg ->
            val at = i + 1
            when (arg) {
                null -> st.bindNull(at)
                is Long -> st.bindLong(at, arg)
                is Int -> st.bindLong(at, arg.toLong())
                is Double -> st.bindDouble(at, arg)
                is String -> st.bindText(at, arg)
                is ByteArray -> st.bindBlob(at, arg)
                is Boolean -> st.bindLong(at, if (arg) 1L else 0L)
                else -> throw IllegalArgumentException("can't bind a ${arg::class.simpleName}")
            }
        }
    }
}

/** The row a query is on. */
interface Row {
    fun text(i: Int): String?
    fun long(i: Int): Long?
    fun double(i: Int): Double?
    fun isNull(i: Int): Boolean
    fun text(name: String): String?
    fun long(name: String): Long?
    fun double(name: String): Double?
    val columns: List<String>
}

private class StatementRow(private val st: SQLiteStatement) : Row {
    override val columns: List<String> = (0 until st.getColumnCount()).map { st.getColumnName(it) }
    private fun at(name: String): Int = columns.indexOf(name).also { require(it >= 0) { "no column $name" } }

    override fun isNull(i: Int): Boolean = st.isNull(i)
    override fun text(i: Int): String? = if (st.isNull(i)) null else st.getText(i)
    override fun long(i: Int): Long? = if (st.isNull(i)) null else st.getLong(i)
    override fun double(i: Int): Double? = if (st.isNull(i)) null else st.getDouble(i)
    override fun text(name: String): String? = text(at(name))
    override fun long(name: String): Long? = long(at(name))
    override fun double(name: String): Double? = double(at(name))
}

/** What a WAL checkpoint did (PRAGMA wal_checkpoint's row): whether a reader or a writer kept it from finishing
 * ([busy]), the WAL's frames ([log]) and those copied back ([checkpointed]); -1 for no WAL. */
data class Checkpointed(val busy: Boolean, val log: Long, val checkpointed: Long)

/** db.DatabaseTooNew: the database was migrated by a newer caracole than this one. */
class DatabaseTooNew(message: String) : Exception(message)

/**
 * The phone's own tables, from caracole/schema/phone.sql (its comments dropped, split at semicolons, as
 * helpers.corpus.phone_schema reads it), and kv phone:schema, in one BEGIN IMMEDIATE: all of them or none. The version
 * is read again inside the transaction, so a second connection finds the tables made and makes nothing; tables newer
 * than [VERSION] are [DatabaseTooNew]. It runs on the writer, when a [Database] opens.
 */
object PhoneSchema {
    const val VERSION = 1

    fun migrate(db: Db) {
        val raw = db.raw
        val has = db.one("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'kv'") { true } ?: false
        check(has) { "the phone's schema goes on caracole's" }
        if (current(db) == VERSION) return
        val sql = Database.resource("caracole/schema/phone.sql").lines().joinToString("\n") { it.substringBefore("--") }
        raw.execSQL("BEGIN IMMEDIATE")
        try {
            if (current(db) < VERSION) {
                for (statement in sql.split(';').map { it.trim(' ', '\t', '\n', '\r') }.filter { it.isNotEmpty() }) {
                    raw.prepare(statement).use { while (it.step()) Unit }
                }
                db.kvSet("phone:schema", VERSION.toString())
            }
            raw.execSQL("COMMIT")
        } catch (e: Throwable) {
            if (raw.inTransaction()) raw.execSQL("ROLLBACK")
            throw e
        }
    }

    private fun current(db: Db): Int {
        val current = db.kvGet("phone:schema")?.toIntOrNull() ?: 0
        if (current > VERSION) throw DatabaseTooNew("the phone's tables are at version $current, this build knows $VERSION")
        return current
    }
}
