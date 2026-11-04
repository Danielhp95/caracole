package io.github.danielhp95.caracole.server.files

import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals

/** web/files.py's kinds of file, as vectors/web/downloads.jsonl has them. */
class FileTypesTest {
    private val records = Corpus.records("web/downloads.jsonl")

    @Test fun theKindsOfFileAreFilesPys() {
        val types = records.single { it.fn == "caracole.web.files.TYPES" }.out!!.jsonArray.map { pair ->
            pair.jsonArray.let { it[0].jsonPrimitive.content to it[1].jsonPrimitive.content }
        }
        assertEquals(types, FileTypes.TYPES.toList(), "files.py's, in its order")
        assertEquals(records.single { it.fn == "caracole.web.files.DOWNLOADS" }.out!!.jsonArray.map { it.jsonPrimitive.content },
                     FileTypes.DOWNLOADS.sorted())
        assertEquals(records.single { it.fn == "caracole.web.files.MAX_BYTES" }.out!!.jsonPrimitive.int.toLong(),
                     FileTypes.MAX_BYTES)
    }
}
