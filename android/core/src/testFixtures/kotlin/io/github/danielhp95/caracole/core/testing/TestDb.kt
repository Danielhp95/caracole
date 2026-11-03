package io.github.danielhp95.caracole.core.testing

import io.github.danielhp95.caracole.core.db.Database
import java.io.File

/** A freshly migrated database for a test: caracole's schema and the phone's, in [dir]. */
object TestDb {
    fun fresh(dir: File): Database = Database(File(dir, "caracole.sqlite"))
}
