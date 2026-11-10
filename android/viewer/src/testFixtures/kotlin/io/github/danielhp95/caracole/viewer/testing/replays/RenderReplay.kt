package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.viewer.render.InfoJson
import io.github.danielhp95.caracole.viewer.render.OwnVersions
import io.github.danielhp95.caracole.viewer.render.PhoneRender
import io.github.danielhp95.caracole.viewer.render.PlainLyrics
import io.github.danielhp95.caracole.viewer.render.RenderNames
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.nio.file.Files

/**
 * The phone's own pages (vectors/viewer/render.jsonl, tests/test_conformance_viewer_render.py's docstring its
 * records' shapes), each answered by :viewer's viewer.render as tests/helpers/phone_render.py answered it:
 *
 * - [constants]: RenderNames is render.py's names;
 * - [facts]: each fixture library's first pass as far as no page is built: the lyrics put on its auto sheets
 *   (PlainLyrics), the own versions as they play now (OwnVersions), then each song's info.json (InfoJson) and unit's
 *   digest as Python had them after that pass;
 * - [passes]: every step of each record, its fixture loaded into a fresh database and library folder, each render
 *   PhoneRender.render of its songs (every song for null; the record's build, `corpus-build`): the failures, every
 *   file of the songs' folders by its SHA-256 and size, the render's kv records, each song's unit's digest and each
 *   info.json, as Python's after that step.
 *
 * PhoneRenderTest runs it on the JVM, CorpusOnDeviceTest on the device.
 */
object RenderReplay : AreaReplay {
    override val area = "render"

    const val VECTOR = "viewer/render.jsonl"

    /** The build each record's pages were made by (helpers/phone_render.py BUILD). */
    const val BUILD = "corpus-build"

    override fun replay(misses: Misses) {
        constants(misses)
        facts(misses)
        passes(misses)
    }

    private fun records(fn: String): List<Record> = Corpus.records(VECTOR).filter { it.fn == fn }

    // --- the names ------------------------------------------------------------------------------------------------

    fun constants(misses: Misses) {
        val want = records("constants").single().out!!.jsonObject
        val got = linkedMapOf<String, Any>(
            "FILES_KEY" to RenderNames.FILES_KEY, "OWN_VERSIONS_KEY" to RenderNames.OWN_VERSIONS_KEY,
            "STATUS_KEY" to RenderNames.STATUS_KEY, "PHONE_KV" to RenderNames.PHONE_KV,
            "HUMAN_SHEET" to RenderNames.HUMAN_SHEET, "AUTO_SHEET" to RenderNames.AUTO_SHEET,
            "SHEET_OUTPUTS" to RenderNames.SHEET_OUTPUTS, "TRADITIONAL_PDFS" to RenderNames.TRADITIONAL_PDFS,
            "SHEET_DOC" to RenderNames.SHEET_DOC, "AUTO_MARKER" to RenderNames.AUTO_MARKER, "LETTER" to RenderNames.LETTER,
            "HARMONICA_KIND" to RenderNames.HARMONICA_KIND, "HARMONICA_FILE" to RenderNames.HARMONICA_FILE,
            "HARMONICA_PAGE" to RenderNames.HARMONICA_PAGE, "LYRICS_PAGES" to RenderNames.LYRICS_PAGES,
            "YOUTUBE" to RenderNames.YOUTUBE, "IGNORED" to RenderNames.IGNORED,
        )
        misses.check(want.keys == got.keys) { "constants: names ${got.keys}, Python's ${want.keys}" }
        for ((name, value) in got) {
            misses.check(json(value) == want[name]) { "constants.$name = ${json(value)}, Python's ${want[name]}" }
        }
    }

    // --- a pass's facts, no page built ------------------------------------------------------------------------------

    fun facts(misses: Misses) {
        for (record in records("phone_render")) {
            val case = record.extra.getValue("case").jsonPrimitive.content
            val (fixture, steps) = record.args
            val first = steps.jsonArray.first().jsonObject.getValue("render")
            val out = record.out!!.jsonArray.first().jsonObject
            world(fixture) { database, library ->
                database.writeBlocking { db ->
                    LibraryStore(library).ensureCurrentKeys(db)
                    PlainLyrics.onto(db, library, Overrides.read(db), only = ids(db, first))
                    OwnVersions.upgraded(db, library, Overrides.read(db))
                    for ((path, text) in out.getValue("info").jsonObject) {
                        val song = Songs.list(db).firstOrNull { infoOf(library, it) == path }
                        misses.check(song != null) { "$case: no song of $path" }
                        song ?: continue
                        val got = InfoJson.bytes(db, library, song).toString(Charsets.UTF_8)
                        misses.check(got == text.jsonPrimitive.content) { "$case: $path is\n$got\nPython's\n${text.jsonPrimitive.content}" }
                    }
                    checkUnits(db, case, out, misses)
                }
            }
        }
    }

    /** The song's info.json, by its path in the library. */
    private fun infoOf(library: File, song: SongRow): String =
        LibraryStore(library).folderOf(song).relativeTo(library).invariantSeparatorsPath + "/info.json"

    // --- every step -----------------------------------------------------------------------------------------------

    fun passes(misses: Misses) {
        for (record in records("phone_render")) {
            val case = record.extra.getValue("case").jsonPrimitive.content
            val (fixture, steps) = record.args
            val outs = record.out!!.jsonArray.iterator()
            world(fixture) { database, library ->
                val render = object : PhoneRender(database, library, null, "corpus") {
                    override fun build(): String = BUILD
                }
                for ((n, step) in steps.jsonArray.map { it.jsonObject }.withIndex()) {
                    when {
                        "render" in step -> {
                            val out = outs.next().jsonObject
                            val failed = database.writeBlocking { db ->
                                render.render(db, ids(db, step.getValue("render")).sortedBy { it }, null).failed.keys
                                    .map { id -> Songs.byId(db, id)!!.display }
                            }
                            check(misses, "$case step $n", database, library, failed, out)
                        }
                        "drop" in step -> database.writeBlocking { db ->
                            val (id, name) = step.getValue("drop").jsonArray
                            Kept.dropFile(db, LibraryStore(library), Songs.byId(db, id.jsonPrimitive.long)!!,
                                          name.jsonPrimitive.content)
                        }
                        else -> Files.delete(File(library, step.getValue("delete").jsonPrimitive.content).toPath())
                    }
                }
            }
        }
    }

    private fun check(misses: Misses, case: String, database: Database, library: File, failed: List<String>,
                      out: JsonObject) {
        val want = out.getValue("failed").jsonArray.map { it.jsonPrimitive.content }
        misses.check(failed.sorted() == want.sorted()) { "$case: failed $failed, Python's $want" }
        val files = filesOf(library)
        val wantFiles = out.getValue("files").jsonArray
            .map { it.jsonArray.let { (p, s, n) -> Triple(p.jsonPrimitive.content, s.jsonPrimitive.content, n.jsonPrimitive.long) } }
            .sortedWith { a, b -> Py.CODE_POINT_ORDER.compare(a.first, b.first) } // Python sorted them as paths
        misses.check(files.map { it.first } == wantFiles.map { it.first }) {
            "$case: files ${files.map { it.first }}, Python's ${wantFiles.map { it.first }}"
        }
        val byPath = files.associateBy { it.first }
        for (f in wantFiles) {
            val mine = byPath[f.first] ?: continue
            misses.check(mine == f) { "$case: ${f.first} is ${mine.second} (${mine.third} bytes), Python's ${f.second} (${f.third})" }
        }
        database.read { db ->
            val kv = db.query("SELECT key, value FROM kv ORDER BY key") { it.text(0)!! to it.text(1)!! }
                .filter { (key, _) -> RECORDED.matches(key) }.toMap()
            val wantKv = out.getValue("kv").jsonObject.mapValues { it.value.jsonPrimitive.content }
            misses.check(kv.keys == wantKv.keys) { "$case: kv ${kv.keys}, Python's ${wantKv.keys}" }
            for ((key, text) in wantKv) {
                val mine = kv[key] ?: continue
                misses.check(mine == text) { "$case: kv $key is\n$mine\nPython's\n$text" }
            }
            checkUnits(db, case, out, misses)
            for ((path, text) in out.getValue("info").jsonObject) {
                val mine = File(library, path).takeIf { it.isFile }?.readText()
                misses.check(mine == text.jsonPrimitive.content) { "$case: $path is\n$mine\nPython's\n${text.jsonPrimitive.content}" }
            }
        }
    }

    private fun checkUnits(db: Db, case: String, out: JsonObject, misses: Misses) {
        val want = out.getValue("units").jsonObject
        val got = Songs.list(db).associate { RenderNames.unitOf(it.key) to Units.digestOf(db, RenderNames.unitOf(it.key)) }
        misses.check(got.keys == want.keys) { "$case: units ${got.keys}, Python's ${want.keys}" }
        for ((unit, digest) in want) {
            misses.check(got[unit] == digest.jsonPrimitive.content) { "$case: $unit is ${got[unit]}, Python's $digest" }
        }
    }

    /** render.py's records and the phone's, as the generator lists them. */
    private val RECORDED = Regex("""render:(files:\d+|progressions:\d+|\d+:phone)|keys:own_versions""")

    /** Every file of the songs' folders (none of the library's own), by path: its SHA-256 and size. */
    private fun filesOf(library: File): List<Triple<String, String, Long>> =
        library.walkTopDown().filter { it.isFile && !Files.isSymbolicLink(it.toPath()) && it.parentFile != library }
            .map { f -> val bytes = f.readBytes(); Triple(f.relativeTo(library).invariantSeparatorsPath, Canonical.sha256Hex(bytes), bytes.size.toLong()) }
            .sortedWith { a, b -> Py.CODE_POINT_ORDER.compare(a.first, b.first) }
            .toList()

    /** A step's songs: those it names, or every song for null. */
    private fun ids(db: Db, named: JsonElement): Set<Long> =
        if (named is JsonNull) Songs.list(db).map { it.id }.toSet() else named.jsonArray.map { it.jsonPrimitive.long }.toSet()

    /** The record's fixture in a fresh database and library folder of its own, gone after [block]. */
    private fun world(fixture: JsonElement, block: (Database, File) -> Unit) {
        val dir = Files.createTempDirectory("caracole-render").toFile()
        try {
            val library = File(dir, "library").apply { mkdirs() }
            TestDb.fresh(dir).use { database ->
                database.writeBlocking { db -> Fixtures.loadRecords(db, fixture.jsonArray.map { it.jsonObject }, library) }
                block(database, library)
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    private fun json(value: Any): JsonElement = when (value) {
        is String -> JsonPrimitive(value)
        is List<*> -> JsonArray(value.map { json(it!!) })
        is Map<*, *> -> JsonObject(value.entries.associate { (k, v) -> k as String to json(v!!) })
        else -> throw IllegalArgumentException("no JSON for $value")
    }
}
