package io.github.danielhp95.caracole.server.files

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.stub
import io.github.danielhp95.caracole.mirror.Gate
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.mirror.UnitGate
import io.github.danielhp95.caracole.server.http.Response
import java.io.File

/** song/<key>: removed on the phone → REMOVED; Units.digestOf differs from the entry's → CHANGED; else SERVE
 * (lane server-shell). */
class PhoneGate(val database: Database) : UnitGate {
    override fun check(unit: String, digest: String?): Gate = TODO("lane server-shell")
}

/** A library file: the phone's folder first, then the mirror through [gate] (lane server-shell; until then, none). */
class LibraryFiles(val libraryDir: File, val mirror: Mirror?, val gate: UnitGate, val database: Database) {
    fun serve(path: String): Response? = stub("lane server-shell") { null }
}
