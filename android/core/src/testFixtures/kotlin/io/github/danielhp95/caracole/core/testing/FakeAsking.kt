package io.github.danielhp95.caracole.core.testing

import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.health.ProviderState
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.Asking

/**
 * A lookup's asking with the clients a test made: each error turned into its [Asked] as the envelope does, with no
 * words and no cooldown recorded, so a site lane tests its stage before lane lookup's InteractiveAsk lands. A
 * provider with no client is [Asked.Off].
 */
class FakeAsking(private val clients: Map<String, Client>) : Asking {
    override fun <T> ask(provider: String, policy: ProviderPolicy?, work: (Client) -> T): Asked<T> {
        val client = clients[provider] ?: return Asked.Off("no client for $provider")
        if (policy != null) client.policy = policy
        return try {
            Asked.Done(work(client))
        } catch (e: BudgetExhausted) {
            Asked.Spent(hour = false, keptForSheets = false)
        } catch (e: ProviderBlocked) {
            Asked.Blocked(e, ProviderState(provider))
        } catch (e: ProviderError) {
            Asked.Failed(e)
        }
    }

    override val requests: Map<String, Int> get() = clients.mapValues { it.value.requestsMade }
}
