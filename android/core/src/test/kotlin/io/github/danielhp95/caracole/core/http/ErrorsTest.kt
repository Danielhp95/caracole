package io.github.danielhp95.caracole.core.http

import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** http.py's errors say what Python's say, and RealTransport sends a test nothing. */
class ErrorsTest {
    @Test fun anErrorSaysItsProviderStatusUrlAndWordsAsPythonsStr() {
        assertEquals("ug: 503: https://u/1: busy", ProviderError("ug", "https://u/1", 503, "busy").message)
        assertEquals("ug", ProviderError("ug").message)
        assertEquals("lacuerda: https://l/x: no table", LaCuerdaParseError("no table", url = "https://l/x").message)
        assertEquals("lrclib: request budget for this run is spent", BudgetExhausted("lrclib").message)
    }

    @Test fun underTheTestsRealTransportRefusesEverySiteButLoopback() {
        assertEquals("loopback", System.getProperty(RealTransport.NETWORK))
        val refused = assertFailsWith<TransportError> {
            RealTransport.send(HttpRequest("GET", "https://tabs.ultimate-guitar.com/tab/1", emptyList()))
        }
        assertEquals("refused", refused.kind)
        RealTransport.refuseUnderTests("http://127.0.0.1:8738/")
        RealTransport.refuseUnderTests("http://10.0.2.2:5000/x")
        RealTransport.refuseUnderTests("http://[::1]:80/")
    }
}
