package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.PoliteClient
import io.github.danielhp95.caracole.core.http.Transport
import java.io.File

/** A lookup's clients, `make_client(..., interactive=True)` on the phone: each at the lookup pace, its requests
 * logged under [runId], its first one paced after the last request this side sent. */
class Clients(val cfg: PhoneConfig, val cacheDir: File, val transport: (provider: String) -> Transport,
              val pacing: Pacing) {
    fun interactive(db: Db, provider: String, runId: String, policy: ProviderPolicy? = null): PoliteClient =
        TODO("lane health-pace")
}
