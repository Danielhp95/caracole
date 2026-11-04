package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.http.LibraryName
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonPrimitive

/** How a page names the library it shows (vectors/web/library_name.jsonl, tests/test_conformance_library_name.py):
 * every record's title, markup and icon answered by server.http.LibraryName as library_name.LibraryName answered it,
 * on the JVM (LibraryNameTest) and on the device (CorpusOnDeviceTest). */
object LibraryNameReplay : AreaReplay {
    override val area = "library-name"

    private const val FN = "caracole.library_name.LibraryName."

    override fun replay(misses: Misses) {
        val records = Corpus.records("web/library_name.jsonl")
        check(records.size >= 200) { "web/library_name.jsonl holds ${records.size} records" }
        for (r in records) {
            val name = r.args[0].jsonPrimitive.content
            val badge = r.args[1].takeIf { it !is JsonNull }?.jsonPrimitive?.content
            val shown = LibraryName(name, badge)
            when (r.fn) {
                FN + "title" -> misses.expect(r) { shown.title(r.args[2].jsonPrimitive.content) }
                FN + "markup" -> misses.expect(r) { shown.markup(r.args[2].jsonPrimitive.content) }
                FN + "icon" -> misses.expect(r) { shown.icon() }
                else -> misses.check(false) { "an unknown record: ${r.fn}" }
            }
        }
    }
}
