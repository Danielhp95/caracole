package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.http.Client

/** get.py's `_Lookup._ask` on the phone: a provider turned off, cooling, blocked or spent, said as an [Asked], each
 * client made once a lookup through [Clients.interactive]. */
class InteractiveAsk(val clients: Clients) : Asking {
    override fun <T> ask(provider: String, policy: ProviderPolicy?, work: (Client) -> T): Asked<T> = TODO("lane lookup")
    override val requests: Map<String, Int> get() = TODO("lane lookup")
}
