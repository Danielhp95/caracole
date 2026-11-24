package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.catalogues.Names
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive
import java.time.format.DateTimeFormatter

/**
 * The catalogue files' names (vectors/catalogues/names.jsonl, tests/test_conformance_catalogues.py): each
 * `{"name", "schema", "at"}` record read by [Names.read], null for null, the schema and the minute equal (`at` as
 * stamps.stamp writes it, UTC to the second). The Keep-rule records (`{"kept", "out"}`) are passed over on purpose:
 * the phone only downloads the newest catalogue and never prunes a release's files, so it has no Keep rule to hold.
 */
object CataloguesReplay : AreaReplay {
    override val area = "catalogues"

    private val STAMP = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'").withZone(java.time.ZoneOffset.UTC)

    override fun replay(misses: Misses) {
        var names = 0
        for (line in Corpus.lines("catalogues/names.jsonl")) {
            if (line["header"]?.jsonPrimitive?.content == "true") continue
            if ("kept" in line) continue // the Keep rule: not the phone's, passed over
            names++
            val name = line.getValue("name").jsonPrimitive.content
            val schema = line.getValue("schema")
            val at = line.getValue("at")
            val got = Names.read(name)
            if (schema is JsonNull) {
                misses.check(got == null) { "read_name(${'"'}$name${'"'}): Python none, the phone $got" }
            } else if (got == null) {
                misses.check(false) { "read_name(${'"'}$name${'"'}): Python $schema $at, the phone none" }
            } else {
                misses.check(got.schema == schema.jsonPrimitive.int && STAMP.format(got.at) == at.jsonPrimitive.contentOrNull) {
                    "read_name(${'"'}$name${'"'}): Python $schema $at, the phone ${got.schema} ${STAMP.format(got.at)}"
                }
            }
        }
        misses.check(names > 0) { "catalogues/names.jsonl holds no name record" }
    }
}
