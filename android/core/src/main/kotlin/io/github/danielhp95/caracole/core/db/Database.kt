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
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.SecureRandom
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/**
 * caracole's database on the phone: db.py's schema in the bundled SQLite (3.50.1, FTS5), migrated as db.py migrates
 * it, then the phone's own tables ([PhoneSchema]).
 *
 * Threads (the plan's §5.5): one writer connection, used under [writes] alone ([write], [writeBlocking]), and a pool
 * of [readers] connections, each lent to one block at a time ([read]); the bundled SQLite is THREADSAFE=2, so a
 * connection is never used by two threads at once. Every connection sets foreign_keys, WAL, synchronous=NORMAL and
 * [BUSY_TIMEOUT_MS]. [write] is not reentrant: a block never writes again inside itself.
 *
 * Opening migrates once per path, under an in-process lock, from caracole/schema/migrations.json: a database at
 * 0 < user_version < [SCHEMA_VERSION] is first copied to `<path>.v<N>.bak` (VACUUM INTO under a name of its own, then
 * renamed); each version runs in BEGIN IMMEDIATE … PRAGMA user_version = N … COMMIT, a statement at a time (the
 * bundled driver runs the first statement of a text and drops the rest); a newer database is [DatabaseTooNew].
 * (The skeleton's first version; lane core-db hardens it.)
 */
class Database(val path: File, driver: SQLiteDriver = BundledSQLiteDriver(), readers: Int = 4) : AutoCloseable {
    companion object {
        const val SCHEMA_VERSION = 15
        const val SQLITE_SOURCE_ID = "2025-06-06 14:52:32 b77dc5e0f596d2140d9ac682b2893ff65d3a4140aa86067a3efebe29dc914c95"
        const val BUSY_TIMEOUT_MS = 10_000

        private val migrating = ConcurrentHashMap<String, ReentrantLock>()
        private val random = SecureRandom()

        /** db.py's migrations, statement by statement: version → statements, in version order. */
        internal val migrations: Map<Int, List<String>> by lazy {
            val text = resource("caracole/schema/migrations.json")
            val root = Json.parseToJsonElement(text).jsonObject
            val schema = root.getValue("schema").jsonPrimitive.intOrNull
            check(schema == SCHEMA_VERSION) { "migrations.json is schema $schema, this build $SCHEMA_VERSION" }
            root.getValue("statements").jsonObject.entries
                .map { (version, list) -> version.toInt() to list.jsonArray.map { it.jsonPrimitive.content } }
                .sortedBy { it.first }
                .toMap(LinkedHashMap())
        }

        internal fun resource(name: String): String {
            val stream = Database::class.java.classLoader?.getResourceAsStream(name)
                ?: Database::class.java.getResourceAsStream("/$name")
                ?: throw IllegalStateException("the resource $name is missing")
            return stream.use { it.readBytes().toString(Charsets.UTF_8) }
        }

        private fun token(): String = ByteArray(6).also { random.nextBytes(it) }.joinToString("") { "%02x".format(it) }
    }

    val writes: Mutex = Mutex()

    private val writer: SQLiteConnection
    private val pool: ArrayBlockingQueue<SQLiteConnection>
    private val all = ArrayList<SQLiteConnection>()

    init {
        require(readers >= 1) { "a database needs a reader at least" }
        path.absoluteFile.parentFile?.mkdirs()
        writer = open(driver)
        try {
            val lock = migrating.computeIfAbsent(path.canonicalPath) { ReentrantLock() }
            lock.withLock { migrate(writer) }
            PhoneSchema.migrate(Db(writer))
            pool = ArrayBlockingQueue(readers)
            repeat(readers) { pool.add(open(driver)) }
        } catch (e: Throwable) {
            all.forEach { runCatching { it.close() } }
            throw e
        }
    }

    private fun open(driver: SQLiteDriver): SQLiteConnection {
        val connection = driver.open(path.path)
        all.add(connection)
        connection.execSQL("PRAGMA foreign_keys = ON")
        connection.prepare("PRAGMA journal_mode = WAL").use { it.step() }
        connection.execSQL("PRAGMA synchronous = NORMAL")
        connection.execSQL("PRAGMA busy_timeout = $BUSY_TIMEOUT_MS")
        return connection
    }

    private fun migrate(connection: SQLiteConnection) {
        val current = connection.prepare("PRAGMA user_version").use { it.step(); it.getLong(0).toInt() }
        if (current > SCHEMA_VERSION) {
            throw DatabaseTooNew(
                "$path is at schema version $current, but this caracole knows up to $SCHEMA_VERSION: " +
                    "a newer caracole migrated it.",
            )
        }
        val pending = migrations.filterKeys { it > current }
        if (pending.isEmpty()) return
        if (current > 0) {
            val backup = File(path.path + ".v$current.bak")
            val partial = File(backup.path + "." + token() + ".part")
            try {
                connection.prepare("VACUUM INTO ?").use { it.bindText(1, partial.path); it.step() }
                Files.move(partial.toPath(), backup.toPath(), StandardCopyOption.REPLACE_EXISTING)
            } finally {
                partial.delete()
            }
        }
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

    /** A pooled connection for [block] alone, which never writes and never suspends. */
    fun <T> read(block: (Db) -> T): T {
        val connection = pool.take()
        try {
            return block(Db(connection))
        } finally {
            pool.put(connection)
        }
    }

    /** The one writer connection, under [writes]. */
    suspend fun <T> write(block: (Db) -> T): T = writes.withLock { block(Db(writer)) }

    /** [write], for a caller that is not a coroutine (a test, a worker waiting on its job). */
    fun <T> writeBlocking(block: (Db) -> T): T = runBlocking { write(block) }

    /** A whole copy of the database at [target]: VACUUM INTO a name of its own beside it, then a rename. */
    fun backupTo(target: File) {
        target.absoluteFile.parentFile?.mkdirs()
        val partial = File(target.path + "." + token() + ".part")
        try {
            read { db -> db.raw.prepare("VACUUM INTO ?").use { it.bindText(1, partial.path); it.step() } }
            Files.move(partial.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING)
        } finally {
            partial.delete()
        }
    }

    override fun close() {
        all.forEach { runCatching { it.close() } }
        all.clear()
    }
}

/** One connection, lent for a block: queries, kv, savepoints. */
class Db internal constructor(val raw: SQLiteConnection) {
    fun <T> query(sql: String, vararg args: Any?, row: (Row) -> T): List<T> = raw.prepare(sql).use { st ->
        bind(st, args)
        val reading = StatementRow(st)
        val out = ArrayList<T>()
        while (st.step()) out.add(row(reading))
        out
    }

    fun <T> one(sql: String, vararg args: Any?, row: (Row) -> T): T? = raw.prepare(sql).use { st ->
        bind(st, args)
        if (st.step()) row(StatementRow(st)) else null
    }

    /** Runs one statement; the rows it changed (changes()). */
    fun execute(sql: String, vararg args: Any?): Int {
        raw.prepare(sql).use { st ->
            bind(st, args)
            while (st.step()) Unit
        }
        return raw.prepare("SELECT changes()").use { it.step(); it.getLong(0).toInt() }
    }

    fun lastRowid(): Long = raw.prepare("SELECT last_insert_rowid()").use { it.step(); it.getLong(0) }

    /** [block]'s writes, all or none: a transaction of its own, or one nested in the caller's. */
    fun <T> savepoint(name: String, block: () -> T): T {
        val id = identifier(name)
        raw.execSQL("SAVEPOINT $id")
        val result = try {
            block()
        } catch (e: Throwable) {
            raw.execSQL("ROLLBACK TO $id")
            raw.execSQL("RELEASE $id")
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
        require(Regex("[A-Za-z_][A-Za-z0-9_]*").matches(name)) { "not a plain identifier: $name" }
        return name
    }

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

class DatabaseTooNew(message: String) : Exception(message)

/**
 * The phone's own tables, from caracole/schema/phone.sql (its comments dropped, split at semicolons), and kv
 * phone:schema, in one BEGIN IMMEDIATE; nothing when phone:schema already says [VERSION].
 */
object PhoneSchema {
    const val VERSION = 1

    fun migrate(db: Db) {
        val raw = db.raw
        val has = db.one("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'kv'") { true } ?: false
        check(has) { "the phone's schema goes on caracole's" }
        val current = db.kvGet("phone:schema")?.toIntOrNull() ?: 0
        if (current > VERSION) throw DatabaseTooNew("the phone's tables are at version $current, this build knows $VERSION")
        if (current == VERSION) return
        val sql = Database.resource("caracole/schema/phone.sql").lines().joinToString("\n") { it.substringBefore("--") }
        raw.execSQL("BEGIN IMMEDIATE")
        try {
            for (statement in sql.split(';').map { it.trim() }.filter { it.isNotEmpty() }) {
                raw.prepare(statement).use { while (it.step()) Unit }
            }
            db.kvSet("phone:schema", VERSION.toString())
            raw.execSQL("COMMIT")
        } catch (e: Throwable) {
            if (raw.inTransaction()) raw.execSQL("ROLLBACK")
            throw e
        }
    }
}
