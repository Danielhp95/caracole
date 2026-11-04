package io.github.danielhp95.caracole

import android.os.Bundle
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.server.testing.ColdSearch
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * The first search after an import and a start, under Android's runtime and storage (lane prep-db; ColdSearchBench is
 * the JVM's): a phone imports 300,000 ug_index rows (BigIndex, made in the test) as Settings' Import does, is killed
 * with its database open, starts again, warms up as Phone does at start, and answers /api/search (ColdSearch). The
 * import leaves a WAL of at most the journal size limit, and the first search answers within 3 s, or within twice a
 * warm search's time, whichever is larger. Its numbers go to the instrumentation's output and the log (ColdSearchTest),
 * for android/README.md's Performance notes.
 *
 *     android/scripts/device-test.sh ColdSearchTest
 */
@RunWith(AndroidJUnit4::class)
class ColdSearchTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private lateinit var dir: File

    @Before
    fun aFolderOfItsOwn() {
        Corpus.open = { name -> runCatching { instrumentation.context.assets.open("conformance/$name") }.getOrNull() }
        dir = File(instrumentation.targetContext.cacheDir, "cold-search-test").apply { deleteRecursively(); mkdirs() }
    }

    @After
    fun gone() {
        dir.deleteRecursively()
    }

    @Test
    fun theFirstSearchAfterAStartAnswersAsAWarmOneDoes() {
        val result = ColdSearch(dir, ROWS).run()
        said("ColdSearchTest: $result")
        assertTrue("the WAL the import left: ${result.wal} bytes, over ${Database.JOURNAL_SIZE_LIMIT}",
                   result.wal <= Database.JOURNAL_SIZE_LIMIT)
        val within = maxOf(3_000L, 2 * result.warm)
        assertTrue("the first search took ${result.first} ms, a warm one ${result.warm} ms: over $within ms",
                   result.first <= within)
    }

    private fun said(text: String) {
        Log.i(TAG, text)
        instrumentation.sendStatus(0, Bundle().apply { putString("stream", "$text\n") })
    }

    companion object {
        const val ROWS = 300_000
        const val TAG = "ColdSearchTest"
    }
}
