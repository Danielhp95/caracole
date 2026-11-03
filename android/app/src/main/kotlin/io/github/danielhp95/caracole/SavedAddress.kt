package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.server.routes.SyncSettings

/**
 * The computer's address the Sync tab offers ([address]: GET /api/sync's, put in its field) and remembers once it
 * compares with one ([remember]): the one Settings keeps for the mirror's sync, so the two syncs are with one computer,
 * and an address typed in either place is the other's too.
 */
internal class SavedAddress(private val settings: Settings) : SyncSettings {
    /** As typed (the Sync tab and the computer read it as caracole's peer_address does), none while blank. */
    override val address: String? get() = settings.server.trim().ifEmpty { null }

    override fun remember(address: String) {
        settings.server = address
    }
}
