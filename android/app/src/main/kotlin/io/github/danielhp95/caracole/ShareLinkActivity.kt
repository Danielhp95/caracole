package io.github.danielhp95.caracole

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.util.Log

/**
 * A song's link shared to caracole from a music app (Spotify, Deezer, Apple Music, TIDAL, a Navidrome client,
 * Audile…): ACTION_SEND of text/plain alone, as the manifest names it, never a file (those are ShareActivity's). What
 * the app sent (EXTRA_TEXT, else the share's ClipData text; EXTRA_SUBJECT, EXTRA_TITLE, and the sender's package when
 * Android gives it, the referrer) is logged under [SharedLink.TAG], then shown on the library screen as the page of
 * the phone's server that reads the song it names, searches for it and offers Get it ([SharedLink.page], ShareRoutes'
 * `/share`). Nothing is sent to any site, nor to the music app, before the owner taps Get it there.
 */
class ShareLinkActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val intent = intent
        if (intent?.action == Intent.ACTION_SEND) {
            val text = intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()
                ?: intent.clipData?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.text?.toString()
            val subject = intent.getCharSequenceExtra(Intent.EXTRA_SUBJECT)?.toString()
            val title = intent.getCharSequenceExtra(Intent.EXTRA_TITLE)?.toString()
            val from = sender()
            Log.i(SharedLink.TAG, SharedLink.said(text, subject, title, from, intent.type))
            startActivity(Intent(this, MainActivity::class.java)
                              .putExtra(SharedLink.PAGE, SharedLink.page(text, subject, title, from)))
        }
        finish()
    }

    /** The app that shared, as Android says it: the referrer (`android-app://com.spotify.music`), else the caller. */
    private fun sender(): String? {
        val referrer = referrer
        if (referrer != null && referrer.scheme == "android-app" && !referrer.host.isNullOrEmpty()) return referrer.host
        return callingPackage
    }
}
