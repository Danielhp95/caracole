package io.github.danielhp95.caracole

import java.io.File
import java.io.IOException

/**
 * The phone's database file ([file]), made whole once: a fresh database is opened (migrated) under a name of its own,
 * `<file>.new`, seeded ([seed]: the kv records a fresh computer's database holds, so the first index import re-keys
 * nothing), closed, and only then given its name. A start cut short while seeding leaves no database, and the next
 * makes it again; once it has its name, it is opened as it is.
 */
internal object PhoneDatabase {
    private val LEFT = listOf("", "-wal", "-shm", "-journal")

    fun <D : AutoCloseable> open(file: File, open: (File) -> D, seed: (D) -> Unit): D {
        if (!file.exists()) {
            val fresh = File(file.path + ".new")
            for (suffix in LEFT) File(fresh.path + suffix).delete()
            open(fresh).use(seed)
            // Closed, SQLite checkpoints its WAL into the file and deletes it: a WAL left holds what the file lacks.
            if (File(fresh.path + "-wal").let { it.exists() && it.length() > 0 }) {
                throw IOException("the new database ${fresh.name} wasn't closed whole")
            }
            File(fresh.path + "-shm").delete()
            if (!fresh.renameTo(file)) throw IOException("can't name the new database ${file.name}")
        }
        return open(file)
    }
}
