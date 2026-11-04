package io.github.danielhp95.caracole

import android.app.Activity
import android.os.Bundle

/**
 * Files shared to caracole (lane inbox-share): ACTION_SEND and SEND_MULTIPLE of the stream types the manifest names
 * alone (a Guitar Pro file, MusicXML, a PDF, MIDI, MuseScore; never VIEW, text/plain or any type), each read from its
 * EXTRA_STREAM and queued as the inbox runner's job (PhoneKinds' inbox kind), then a toast of the outcome.
 *
 * Until its lane lands it finishes at once.
 */
class ShareActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        finish()
    }
}
