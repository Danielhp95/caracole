package io.github.danielhp95.caracole.core.testing

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.PoliteClient
import kotlinx.serialization.json.JsonObject
import java.io.File

/** What a scenario record is replayed in: its fixture's database, a library folder, a cache seeded from the record,
 * a [FakeTransport] serving its answers and a [PoliteClient] per client of the record. */
class ScenarioWorld(val db: Db, val library: File, val cacheDir: File, val transport: FakeTransport,
                    val clients: Map<String, PoliteClient>)

/**
 * Scenario records (docs/superpowers/specs/2026-11-03-conformance-corpus.md, "Scenario records"; Python's
 * tests/helpers/scenario.py): [replay] builds the record's world, runs [pass] in it, and compares the requests, the
 * rows, the kv records, the files and the events with the record's (lane http-client).
 */
object Scenarios {
    fun replay(record: JsonObject, pass: (ScenarioWorld) -> Any?): Unit = TODO("lane http-client")
}
