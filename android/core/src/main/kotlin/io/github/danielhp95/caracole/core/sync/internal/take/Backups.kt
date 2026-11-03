package io.github.danielhp95.caracole.core.sync.internal.take

import androidx.sqlite.SQLiteConnection
import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.sqlite.execSQL
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.db.PhoneSchema
import io.github.danielhp95.caracole.core.library.internal.Stamps
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.SecureRandom

/**
 * The phone's copy of its library before a sync takes anything (the plan's §1 and §5.4): a whole, openable
 * database (caracole's migrations and the phone's tables run on a new file), holding the library's tables alone
 * ([TABLES]: the index tables stay empty, since a take never changes them and a whole copy is about 430 MB), as
 * `state/backups/before-sync-<UTC time>.sqlite`, the newest [KEEP] kept. None is made without free space of twice
 * what the copy needs. [restore] puts those tables' rows back, and nothing on disk (Take.restore says what that
 * leaves).
 */
internal object Backups {
    const val KEEP = 3
    const val FOLDER = "backups"
    private const val PREFIX = "before-sync-"
    private const val SUFFIX = ".sqlite"
    private const val ALIAS = "sync_backup"

    /** The library's tables, parents first. */
    val TABLES = listOf("songs", "versions", "files", "removed", "kv", "phone_overrides", "phone_songbooks")

    /** The bytes free where a copy goes (a test gives less). */
    @Volatile
    var freeSpace: (File) -> Long = { it.usableSpace }

    private val random = SecureRandom()

    fun make(db: Db, stateDir: File, now: String): File? {
        val stamp = Stamps.stampOf(now)
        val folder = File(stateDir, FOLDER)
        folder.mkdirs()
        folder.listFiles()?.filter { it.name.startsWith(PREFIX) && it.name.endsWith(".part") }?.forEach { it.delete() }
        val target = File(folder, PREFIX + stamp.replace(":", "") + SUFFIX)
        val part = File(folder, "${target.name}.${hex(6)}.part")
        try {
            fresh(part)
            if (freeSpace(folder) < 2 * (part.length() + payload(db))) return null
            db.attach(part, ALIAS)
            try {
                db.savepoint("sync_backup") { copy(db, from = "main", to = ALIAS) }
            } finally {
                db.detach(ALIAS)
            }
            quickCheck(part)
            Files.move(part.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
        } finally {
            part.delete()
        }
        rotate(folder, target)
        return target
    }

    fun restore(db: Db, backup: File) {
        require(backup.isFile) { "no backup at $backup" }
        db.attach(backup, ALIAS)
        try {
            val version = db.one("PRAGMA $ALIAS.user_version") { it.long(0) }
            require(version == Database.SCHEMA_VERSION.toLong()) {
                "$backup is no backup of this caracole's (schema $version, not ${Database.SCHEMA_VERSION})"
            }
            val missing = TABLES.filter {
                db.one("SELECT 1 FROM $ALIAS.sqlite_master WHERE type = 'table' AND name = ?", it) { true } == null
            }
            require(missing.isEmpty()) { "$backup holds no ${missing.joinToString()}" }
            db.savepoint("sync_restore") { copy(db, from = ALIAS, to = "main") }
        } finally {
            db.detach(ALIAS)
        }
    }

    /** The library's tables of [to] made [from]'s: emptied, children first, then filled, parents first. */
    private fun copy(db: Db, from: String, to: String) {
        for (table in TABLES.asReversed()) db.execute("DELETE FROM $to.$table")
        for (table in TABLES) {
            val columns = db.query("SELECT name FROM pragma_table_info(?, ?)", table, to) { it.text(0)!! }
                .joinToString(", ") { "\"$it\"" }
            db.execute("INSERT INTO $to.$table ($columns) SELECT $columns FROM $from.$table")
        }
    }

    /** A new database at [file]: caracole's migrations (migrations.json), then the phone's tables (phone.sql). */
    private fun fresh(file: File) {
        val connection = BundledSQLiteDriver().open(file.path)
        try {
            for ((version, statements) in Database.migrations) {
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
            PhoneSchema.migrate(Db(connection))
        } finally {
            connection.close()
        }
    }

    /** What the library's rows take, their cells' bytes. */
    private fun payload(db: Db): Long = TABLES.sumOf { table ->
        val cells = db.query("SELECT name FROM pragma_table_info(?)", table) { it.text(0)!! }
            .joinToString(" + ") { "IFNULL(LENGTH(CAST(\"$it\" AS BLOB)), 0)" }
        db.one("SELECT IFNULL(SUM($cells), 0) FROM $table") { it.long(0) } ?: 0L
    }

    /** SQLite's quick check of the copy, which must say "ok". */
    private fun quickCheck(file: File) {
        val connection: SQLiteConnection = BundledSQLiteDriver().open(file.path)
        try {
            val said = connection.prepare("PRAGMA quick_check").use { st ->
                buildList { while (st.step()) add(st.getText(0)) }
            }
            check(said == listOf("ok")) { "the copy failed its check: ${said.joinToString("\n")}" }
        } finally {
            connection.close()
        }
    }

    /** The copies beyond the newest [KEEP] deleted, never [made]. */
    private fun rotate(folder: File, made: File) {
        val copies = folder.listFiles()?.filter { it.isFile && it.name.startsWith(PREFIX) && it.name.endsWith(SUFFIX) }
            ?.sortedBy { it.name } ?: return
        copies.filter { it != made }.take(maxOf(0, copies.size - KEEP)).forEach { it.delete() }
    }

    private fun hex(n: Int): String {
        val bytes = ByteArray(n).also { random.nextBytes(it) }
        val digits = "0123456789abcdef"
        return buildString { for (b in bytes) append(digits[(b.toInt() shr 4) and 15]).append(digits[b.toInt() and 15]) }
    }
}
