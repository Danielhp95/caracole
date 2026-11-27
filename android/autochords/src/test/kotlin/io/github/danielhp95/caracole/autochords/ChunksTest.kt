package io.github.danielhp95.caracole.autochords

import io.github.danielhp95.caracole.autochords.testing.ChunksRecords
import io.github.danielhp95.caracole.core.testing.Misses
import kotlin.test.Test
import kotlin.test.assertEquals

/** [Chunks] against beat_this's split_piece and aggregate_prediction (vectors/autochords/chunks.jsonl). */
class ChunksTest {
    @Test
    fun `every length from 0 to 4,000 frames is cut and put together as beat_this does`() {
        val misses = Misses("autochords/chunks.jsonl")
        ChunksRecords.replay(misses)
        misses.assertNone()
    }

    @Test
    fun `a piece past one chunk ends with a chunk moved back to its end, and the earlier chunk's frames are kept`() {
        val chunks = Chunks.split(3000)
        assertEquals(listOf(-6, 1482, 1506), chunks.map { it.start })
        assertEquals(listOf(1500, 1500, 1500), chunks.map { it.length })
        val (_, runs) = ChunksRecords.runs(3000, 1500, 6, 2048)
        assertEquals(listOf(listOf(0, 1488, 0, 6), listOf(1488, 2976, 1, 6), listOf(2976, 3000, 2, 1470)), runs)
        val short = Chunks.split(10).single()
        assertEquals(listOf(-6, 0, 10, 6, 6, 22), listOf(short.start, short.from, short.to, short.left, short.right,
                                                         short.length))
    }
}
