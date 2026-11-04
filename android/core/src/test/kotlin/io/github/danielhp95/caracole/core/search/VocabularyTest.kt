package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.random.Random
import kotlin.test.assertEquals

/** The words a process keeps of UG's keys (search.py `_Vocabulary`): many words added since a letter was read (an
 * import) read that letter again, in one query, rather than one word at a time, and its answers are the same. */
class VocabularyTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun manyWordsAddedSinceALetterWasReadAreReadAgainAsOneAndAnswerAlike() {
        val random = Random(3)
        val words = List(Vocabulary.REREAD * 3) { n ->
            "b" + List(2 + random.nextInt(6)) { ('a' + random.nextInt(26)) }.joinToString("") + n % 7
        }.distinct()
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db ->
                db.execute("INSERT INTO ug_key_words(term) VALUES ('beatles')")
                val kept = Vocabulary.of(db)
                assertEquals(listOf("beatles"), kept.among(db, "beatls"))
                // More than REREAD words since: the letter is read again, as a new process would read it.
                db.savepoint("words") {
                    for (w in words.shuffled(random)) {
                        db.execute("INSERT OR IGNORE INTO ug_key_words(term) VALUES (?)", w)
                    }
                }
                for (probe in listOf("beatls", "bxyz", "bqwertyu", "bab")) {
                    assertEquals(Vocabulary().among(db, probe), kept.among(db, probe), probe)
                }
                val n = Py.len("beatls")
                val all = (words + "beatles").filter { Py.len(it) in n - 2..n + 2 }
                assertEquals(all.sortedWith { a, b -> Py.CODE_POINT_ORDER.compare(a, b) }.sortedBy { Py.len(it) },
                             kept.among(db, "beatls"))
                // A few more since: one at a time, in order, as before.
                db.execute("INSERT INTO ug_key_words(term) VALUES ('beatlez')")
                assertEquals(Vocabulary().among(db, "beatls"), kept.among(db, "beatls"))
            }
        }
    }
}
