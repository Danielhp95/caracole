package io.github.danielhp95.caracole.ml

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** [Mixdown] as numpy's float32 mean over the channels: summed in their order in float32, then divided. */
class MixdownTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun theMeanOfTheChannelsInFloat32InTheirOrder() {
        assertArrayEquals(floatArrayOf(0.125f), Mixdown.mono(floatArrayOf(0.5f, -0.25f), 2), 0f)
        // 1e8 + 1 - 1e8 in float32, in order: 1e8 + 1 rounds to 1e8, so the sum is 0, never 1.
        assertArrayEquals(floatArrayOf(0f, 1f), Mixdown.mono(floatArrayOf(1e8f, 1f, -1e8f, 1f, 1f, 1f), 3), 0f)
        assertArrayEquals(floatArrayOf(0.25f, -1f), Mixdown.mono(floatArrayOf(0.25f, -1f), 1), 0f)
    }

    @Test fun aFileIsMixedDownABlockAtATimeAsTheArrayIs() {
        val pcm = FloatArray(2 * 20_001) { (it % 97) / 97f - 0.5f + if (it % 2 == 0) 0.1f else 0f }
        val source = tmp.newFile("in.f32").apply {
            writeBytes(ByteBuffer.allocate(4 * pcm.size).order(ByteOrder.LITTLE_ENDIAN).also { b ->
                pcm.forEach { b.putFloat(it) }
            }.array())
        }
        val out = tmp.newFile("out.f32")
        assertEquals(20_001L, Mixdown.mono(source, 2, out))
        val got = ByteBuffer.wrap(out.readBytes()).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
        assertArrayEquals(Mixdown.mono(pcm, 2), FloatArray(got.remaining()).also { got.get(it) }, 0f)
    }
}
