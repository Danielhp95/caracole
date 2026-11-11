package io.github.danielhp95.caracole.core.backup.internal

import androidx.sqlite.SQLiteConnection
import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.sqlite.execSQL
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.db.PhoneSchema
import java.io.File

/**
 * A backup's database: a whole, openable one (caracole's migrations and the phone's tables run on a new file) holding
 * the library's tables alone ([TABLES]: the index tables stay empty, since neither a take nor a restore changes them
 * and a whole copy is about 430 MB), copied in one savepoint, and SQLite's quick check of it. [restore] puts those
 * tables' rows back, exactly.
 */
internal object BackupTables {
    /** The library's tables, parents first. */
    val TABLES = listOf("songs", "versions", "files", "removed", "kv", "phone_overrides", "phone_songbooks")

    private const val ALIAS = "backup_copy"

    /** The library's tables of [db] copied into the new database [part] ([fresh]'s), in one savepoint. */
    fun copyInto(db: Db, part: File) {
        db.attach(part, ALIAS)
        try {
            db.savepoint("backup_make") { copy(db, from = "main", to = ALIAS) }
        } finally {
            db.detach(ALIAS)
        }
    }

    /** [backup]'s library tables back into [db], exactly, in one savepoint, [within] which the copy is made (what it
     * does before and after the copy is in the same savepoint); a file that is no backup of this caracole's is refused
     * and nothing changes (IllegalArgumentException for none there, one of another schema or without those tables;
     * SQLite's error for one that is no database). */
    fun restore(db: Db, backup: File, within: (copy: () -> Unit) -> Unit = { it() }) {
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
            db.savepoint("backup_restore") { within { copy(db, from = ALIAS, to = "main") } }
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
    fun fresh(file: File) {
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
    fun payload(db: Db): Long = TABLES.sumOf { table ->
        val cells = db.query("SELECT name FROM pragma_table_info(?)", table) { it.text(0)!! }
            .joinToString(" + ") { "IFNULL(LENGTH(CAST(\"$it\" AS BLOB)), 0)" }
        db.one("SELECT IFNULL(SUM($cells), 0) FROM $table") { it.long(0) } ?: 0L
    }

    /** SQLite's quick check of the copy at [file], which must say "ok" (IllegalStateException otherwise). */
    fun quickCheck(file: File) {
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

    /** The kept files the backup attached by [restore] names, each's path and SHA-256 in path order: for its
     * `within`, before the copy. */
    fun keptInCopy(db: Db): List<Pair<String, String>> =
        db.query("SELECT path, sha256 FROM $ALIAS.files ORDER BY path") { it.text(0)!! to it.text(1)!! }

    /** The kept files the backup at [file] names, each's path and SHA-256 in path order (SQLite's error for a copy
     * that can't be read; IllegalArgumentException for none there, never made one). */
    fun keptOf(file: File): List<Pair<String, String>> {
        require(file.isFile) { "no backup at $file" }
        val connection = BundledSQLiteDriver().open(file.path)
        try {
            return connection.prepare("SELECT path, sha256 FROM files ORDER BY path").use { st ->
                buildList { while (st.step()) add(st.getText(0) to st.getText(1)) }
            }
        } finally {
            connection.close()
        }
    }

    /** The SHA-256s a backup's `files` names; none for a copy that can't be read. */
    fun shasOf(file: File): Set<String> = try {
        keptOf(file).mapTo(HashSet()) { it.second }
    } catch (e: Exception) {
        emptySet()
    }
}
